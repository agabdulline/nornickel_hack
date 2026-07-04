# -*- coding: utf-8 -*-
"""P12: персистентная история чата-ассистента (store + API) и обогащённый
контекст (roadmap, ранги гипотез, формула score)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import api
from backend.app.kb.index import KBIndex
from backend.app.main import app
from backend.app.models import Citation, Effect, Hypothesis, Project
from backend.app.store import Store
from backend.tests.conftest import find_case_file, requires_data


class NoLLM:
    enabled = False

    def chat(self, *a, **kw):
        from backend.app.llm import LLMUnavailable
        raise LLMUnavailable("тесты без сети")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = Store(tmp_path / "chat.db")
    kb = KBIndex(root=tmp_path / "kb", use_dense=False)
    app.dependency_overrides[api.get_store] = lambda: store
    app.dependency_overrides[api.get_kb] = lambda: kb
    monkeypatch.setattr(api, "llm_client", NoLLM())
    yield TestClient(app), store
    app.dependency_overrides.clear()


def test_store_chat_roundtrip(tmp_path):
    store = Store(tmp_path / "s.db")
    store.add_chat_message("p1", "user", "вопрос")
    store.add_chat_message("p1", "assistant", "ответ",
                           refs=[{"type": "rule", "id": "R1"}])
    store.add_chat_message("p2", "user", "чужой проект")

    msgs = store.get_chat_messages("p1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["references"] == [{"type": "rule", "id": "R1"}]
    # limit отдаёт ПОСЛЕДНИЕ сообщения в хронологическом порядке
    assert [m["content"] for m in store.get_chat_messages("p1", limit=1)] == ["ответ"]

    assert store.clear_chat("p1") == 2
    assert store.get_chat_messages("p1") == []
    assert len(store.get_chat_messages("p2")) == 1


def test_delete_project_drops_chat(tmp_path):
    store = Store(tmp_path / "s.db")
    p = store.create_project("НОФ · вкрапленные руды")
    store.add_chat_message(p.id, "user", "вопрос")
    store.delete_project(p.id)
    assert store.get_chat_messages(p.id) == []


def test_history_endpoints_without_report(client):
    """История доступна и пуста до загрузки отчёта; 404 на чужой проект."""
    c, _store = client
    pid = c.post("/api/projects", json={"plant": "НОФ"}).json()["id"]
    assert c.get(f"/api/projects/{pid}/chat/history").json() == {"messages": []}
    assert c.delete(f"/api/projects/{pid}/chat/history").json() == {"cleared": 0}
    assert c.get("/api/projects/nope/chat/history").status_code == 404


@requires_data
def test_chat_persists_history(client):
    c, store = client
    pid = c.post("/api/projects", json={"plant": "НОФ"}).json()["id"]
    path = find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$")
    with open(path, "rb") as f:
        c.post(f"/api/projects/{pid}/report",
               files={"file": ("Хвосты НОФ Вкр.xlsx", f.read())})

    r = c.post(f"/api/projects/{pid}/chat", json={"message": "объясни главный диагноз"})
    assert r.status_code == 200

    # «переоткрытие панели»: история пришла с сервера, вопрос + ответ со ссылками
    msgs = c.get(f"/api/projects/{pid}/chat/history").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "объясни главный диагноз"
    assert msgs[1]["references"] and msgs[1]["references"][0]["type"] == "rule"

    # второй вопрос наслаивается, очистка обнуляет
    c.post(f"/api/projects/{pid}/chat", json={"message": "что неизвлекаемо и почему?"})
    msgs = c.get(f"/api/projects/{pid}/chat/history").json()["messages"]
    assert len(msgs) == 4
    assert c.delete(f"/api/projects/{pid}/chat/history").json()["cleared"] == 4
    assert c.get(f"/api/projects/{pid}/chat/history").json() == {"messages": []}


@requires_data
def test_context_has_ranks_roadmap_and_formula(tmp_path):
    """Контекст чата объясняет ранжирование: №, формула score, дорожная карта."""
    from backend.app.chat import build_context
    from backend.app.diagnostics import run_diagnostics
    from backend.app.parser.recover import recover
    from backend.app.parser.xlsx import parse_workbook

    res = parse_workbook(find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$"))
    report = res.reports[0]
    recover(report, llm=None)
    diag = run_diagnostics(report)
    hyps = [Hypothesis(id="h01-aaaaaa", title="Замена насадок гидроциклонов", score=0.8,
                       process_area="классификация",
                       effect=Effect(tonnes_max=845.7, tonnes_expected=211.4,
                                     money_usd=3_488_000),
                       rationale=[Citation(quote="ц", chunk_id="x", verified=True)]),
            Hypothesis(id="h02-bbbbbb", title="Футеровка мельниц", score=0.6,
                       process_area="измельчение")]
    project = Project(id="p1", plant="НОФ (вкрапленные)")
    kb = KBIndex(root=tmp_path / "kb", use_dense=False)
    roadmap = [{"hypothesis_id": "h01-aaaaaa", "stage": "lab",
                "start": "2026-07-06", "end": "2026-08-03",
                "resource": "лаборатория", "shifted_reason": None}]

    ctx = build_context("почему первая гипотеза выше второй?", report, diag,
                        hyps, project, kb, roadmap=roadmap)
    assert ctx["гипотезы_кратко"][0]["№"] == 1
    assert ctx["гипотезы_кратко"][0]["цитат_подтверждено"] == 1
    assert "score" in ctx["формула_score"]
    assert ctx["дорожная_карта"][0]["стадия"] == "lab"
    # «первая гипотеза» разворачивается в полную карточку
    assert any(h["id"] == "h01-aaaaaa" for h in ctx["гипотезы_полные_упомянутые"])
