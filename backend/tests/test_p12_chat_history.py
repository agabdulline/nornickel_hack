# -*- coding: utf-8 -*-
"""P12: ассистент — диалоги с серверной историей (store + API), графики
в ответах и обогащённый контекст (roadmap, ранги гипотез, формула score)."""
import json

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


# ---------- store: диалоги ----------
def test_store_chats_roundtrip(tmp_path):
    store = Store(tmp_path / "s.db")
    c1 = store.create_chat("p1", "Про диагноз")
    c2 = store.create_chat("p1")
    store.add_chat_message("p1", "user", "вопрос-1", chat_id=c1["id"])
    store.add_chat_message("p1", "assistant", "ответ-1",
                           refs=[{"type": "rule", "id": "R1"}],
                           charts=[{"type": "bar", "title": "t", "unit": "т",
                                    "data": [{"label": "+125", "value": 1.0}]}],
                           chat_id=c1["id"])
    store.add_chat_message("p1", "user", "вопрос-2", chat_id=c2["id"])

    # сообщения не перемешиваются между диалогами
    m1 = store.get_chat_messages("p1", chat_id=c1["id"])
    assert [m["content"] for m in m1] == ["вопрос-1", "ответ-1"]
    assert m1[1]["references"] == [{"type": "rule", "id": "R1"}]
    assert m1[1]["charts"][0]["title"] == "t"
    assert len(store.get_chat_messages("p1", chat_id=c2["id"])) == 1
    assert len(store.get_chat_messages("p1")) == 3  # весь проект

    # свежий диалог первым, счётчики сообщений
    chats = store.list_chats("p1")
    assert chats[0]["id"] == c2["id"] and chats[0]["messages"] == 1
    assert chats[1]["messages"] == 2

    store.rename_chat(c1["id"], "Новое имя")
    assert store.get_chat(c1["id"])["title"] == "Новое имя"

    assert store.delete_chat(c2["id"])
    assert store.get_chat_messages("p1", chat_id=c2["id"]) == []
    assert store.clear_chat("p1") == 2
    assert store.list_chats("p1") == []


def test_store_migrates_orphan_messages(tmp_path):
    """Сообщения, записанные до появления диалогов, собираются в «Диалог»."""
    path = tmp_path / "s.db"
    store = Store(path)
    store.add_chat_message("p1", "user", "старое сообщение")   # без chat_id
    reopened = Store(path)
    chats = reopened.list_chats("p1")
    assert len(chats) == 1 and chats[0]["title"] == "Диалог"
    assert [m["content"] for m in
            reopened.get_chat_messages("p1", chat_id=chats[0]["id"])] == ["старое сообщение"]


def test_delete_project_drops_chats(tmp_path):
    store = Store(tmp_path / "s.db")
    p = store.create_project("НОФ · вкрапленные руды")
    c = store.create_chat(p.id)
    store.add_chat_message(p.id, "user", "вопрос", chat_id=c["id"])
    store.delete_project(p.id)
    assert store.get_chat_messages(p.id) == []
    assert store.list_chats(p.id) == []


# ---------- API: диалоги ----------
def test_chats_crud_endpoints(client):
    c, _store = client
    pid = c.post("/api/projects", json={"plant": "НОФ"}).json()["id"]

    assert c.get(f"/api/projects/{pid}/chats").json() == []
    assert c.get(f"/api/projects/{pid}/chat/history").json() == \
        {"chat_id": None, "messages": []}

    chat = c.post(f"/api/projects/{pid}/chats").json()
    assert chat["title"] == "Новый диалог"
    assert [x["id"] for x in c.get(f"/api/projects/{pid}/chats").json()] == [chat["id"]]

    # чужой/несуществующий диалог и проект — 404
    assert c.delete(f"/api/projects/{pid}/chats/nope").status_code == 404
    assert c.get("/api/projects/nope/chats").status_code == 404
    assert c.get(f"/api/projects/{pid}/chat/history?chat_id=nope").status_code == 404

    assert c.delete(f"/api/projects/{pid}/chats/{chat['id']}").json() == {"ok": True}
    assert c.get(f"/api/projects/{pid}/chats").json() == []


@requires_data
def test_chat_persists_history_per_dialog(client):
    c, _store = client
    pid = c.post("/api/projects", json={"plant": "НОФ"}).json()["id"]
    path = find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$")
    with open(path, "rb") as f:
        c.post(f"/api/projects/{pid}/report",
               files={"file": ("Хвосты НОФ Вкр.xlsx", f.read())})

    # без chat_id диалог создаётся сам и получает заголовок из вопроса
    r = c.post(f"/api/projects/{pid}/chat", json={"message": "объясни главный диагноз"})
    assert r.status_code == 200
    cid1 = r.json()["chat_id"]
    chats = c.get(f"/api/projects/{pid}/chats").json()
    assert chats[0]["id"] == cid1 and chats[0]["title"] == "объясни главный диагноз"

    # «переоткрытие панели»: история диалога с сервера
    h = c.get(f"/api/projects/{pid}/chat/history?chat_id={cid1}").json()
    assert [m["role"] for m in h["messages"]] == ["user", "assistant"]
    assert h["messages"][1]["references"][0]["type"] == "rule"

    # второй диалог живёт отдельно
    cid2 = c.post(f"/api/projects/{pid}/chats").json()["id"]
    c.post(f"/api/projects/{pid}/chat",
           json={"message": "что неизвлекаемо и почему?", "chat_id": cid2})
    assert len(c.get(f"/api/projects/{pid}/chat/history?chat_id={cid1}").json()["messages"]) == 2
    assert len(c.get(f"/api/projects/{pid}/chat/history?chat_id={cid2}").json()["messages"]) == 2

    # удаление одного диалога не трогает другой
    c.delete(f"/api/projects/{pid}/chats/{cid2}")
    assert len(c.get(f"/api/projects/{pid}/chat/history?chat_id={cid1}").json()["messages"]) == 2
    # полная очистка
    assert c.delete(f"/api/projects/{pid}/chat/history").json()["cleared"] == 2


# ---------- графики ----------
def test_parse_charts_validation():
    from backend.app.chat import _parse_charts
    raw = [
        {"type": "bar", "title": "Потери Ni", "unit": "т",
         "data": [{"label": "+125", "value": 1471.3}, {"label": "-10", "value": "1171.7"},
                  {"label": "-45 +20", "value": 500}, {"label": "битый", "value": "нет"}]},
        {"title": "мало точек", "data": [{"label": "a", "value": 1}]},
        "мусор",
        {"type": "bar", "title": "третий лишний",
         "data": [{"label": str(i), "value": i} for i in range(5)]},
    ]
    charts = _parse_charts(raw)
    assert len(charts) == 1  # второй отброшен (<3 точек), третий — мусор, кап 2
    assert charts[0].title == "Потери Ni"
    assert [p.value for p in charts[0].data] == [1471.3, 1171.7, 500.0]
    assert _parse_charts(None) == []


@requires_data
def test_chat_answer_with_charts(tmp_path):
    from backend.app.chat import answer
    from backend.app.diagnostics import run_diagnostics
    from backend.app.parser.recover import recover
    from backend.app.parser.xlsx import parse_workbook

    res = parse_workbook(find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$"))
    report = res.reports[0]
    recover(report, llm=None)
    diag = run_diagnostics(report)
    kb = KBIndex(root=tmp_path / "kb", use_dense=False)
    project = Project(id="p1", plant="НОФ (вкрапленные)")

    class ChartLLM:
        enabled = True

        def chat(self, messages, **kw):
            return {"content": json.dumps({
                "text": "Потери по классам [R1].",
                "references": [{"type": "rule", "id": "R1"}],
                "charts": [{"type": "bar", "title": "Потери Ni по классам", "unit": "т",
                            "data": [{"label": "+125", "value": 1471.3},
                                     {"label": "-125+71", "value": 300.0},
                                     {"label": "-10", "value": 1171.7}]}],
            }, ensure_ascii=False), "usage": {}}

    ans = answer("покажи график потерь", [], report, diag, [], project, kb, llm=ChartLLM())
    assert len(ans.charts) == 1 and ans.charts[0].unit == "т"
    assert ans.charts[0].data[0].label == "+125"

    # офлайн-фоллбэк тоже строит график по классам из отчёта
    ans_off = answer("покажи график потерь", [], report, diag, [], project, kb, llm=NoLLM())
    assert ans_off.charts and any("Ni" in ch.title for ch in ans_off.charts)
    assert all(len(ch.data) >= 3 for ch in ans_off.charts)


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
                        hyps, project, kb, roadmap=roadmap, page="hypotheses")
    # ассистент знает, какой экран открыт («здесь», «на этой странице»)
    assert "Гипотезы" in ctx["где_сейчас_пользователь"]
    assert ctx["гипотезы_кратко"][0]["№"] == 1
    assert ctx["гипотезы_кратко"][0]["цитат_подтверждено"] == 1
    assert "score" in ctx["формула_score"]
    assert ctx["дорожная_карта"][0]["стадия"] == "lab"
    # «первая гипотеза» разворачивается в полную карточку
    assert any(h["id"] == "h01-aaaaaa" for h in ctx["гипотезы_полные_упомянутые"])
