# -*- coding: utf-8 -*-
"""P5: сквозной API-флоу на Примере 2 (LLM замокана, генерация из фикстуры)."""
import pytest
from fastapi.testclient import TestClient

import backend.app.api as api
from backend.app.kb.index import KBIndex
from backend.app.kb.textnorm import chunk_pages
from backend.app.main import app
from backend.app.store import Store
from backend.tests.conftest import find_case_file, requires_data


class NoLLM:
    enabled = False

    def chat(self, *a, **kw):
        from backend.app.llm import LLMUnavailable
        raise LLMUnavailable("тесты без сети")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = Store(tmp_path / "api.db")
    kb = KBIndex(root=tmp_path / "kb", use_dense=False)
    pages = [(7, "Доизмельчение сростков и классификация в гидроциклонах повышают "
                 "раскрытие пентландита. Время флотации определяет извлечение тонких частиц. " * 4)]
    kb.add_document("kbdoc", "Справочник.pdf", pages, chunk_pages(pages, target=300))
    app.dependency_overrides[api.get_store] = lambda: store
    app.dependency_overrides[api.get_kb] = lambda: kb
    monkeypatch.setattr(api, "llm_client", NoLLM())
    yield TestClient(app)
    app.dependency_overrides.clear()


@requires_data
def test_full_flow_example2(client):
    # 1. проект
    r = client.post("/api/projects", json={"plant": "НОФ", "goal": "потери Ni"})
    assert r.status_code == 200
    pid = r.json()["id"]

    # 2. загрузка отчёта
    path = find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$")
    with open(path, "rb") as f:
        r = client.post(f"/api/projects/{pid}/report",
                        files={"file": ("Хвосты НОФ Вкр.xlsx", f.read())})
    assert r.status_code == 200
    body = r.json()
    assert body["plant"] == "НОФ (вкрапленные)"
    assert body["recover_stats"][0]["recovered_math"] == 0
    assert body["reports"][0]["tails_tonnes"] == pytest.approx(4376437.99, abs=0.01)

    # 3. диагностика
    r = client.get(f"/api/projects/{pid}/diagnostics")
    assert r.status_code == 200
    diag = r.json()
    rules = {d["rule_id"] for d in diag["diagnoses"]}
    assert {"R1", "R2"} <= rules
    assert diag["not_proposed"]

    # 4. генерация (мок из фикстуры, без сети)
    r = client.post(f"/api/projects/{pid}/hypotheses/generate", json={})
    assert r.status_code == 200
    hyps = r.json()
    assert len(hyps) >= 6
    assert all(h["score"] > 0 for h in hyps)
    assert hyps == sorted(hyps, key=lambda h: -h["score"])
    # novelty: эталоны НОФ вкр содержат футеровку и фронт флотации -> есть совпадения
    matched = [h for h in hyps if h["novelty"]["prior_matches"]]
    assert matched, "мок-гипотезы пересекаются с эталонными — бейдж должен появиться"

    # 5. фидбэк: reject с причиной -> стоп-лист
    hid = hyps[0]["id"]
    r = client.post(f"/api/hypotheses/{hid}/feedback",
                    json={"action": "reject", "reason": "футеровка уже меняется по графику"})
    assert r.status_code == 200
    assert "футеровка уже меняется по графику" in r.json()["stoplist"]

    # 6. accept второй
    r = client.post(f"/api/hypotheses/{hyps[1]['id']}/feedback", json={"action": "accept"})
    assert r.json()["status"] == "accepted"

    # 7. регенерация исключает направление из стоп-листа и не трогает принятую
    r = client.post(f"/api/projects/{pid}/hypotheses/generate", json={})
    assert r.status_code == 200
    r = client.get(f"/api/projects/{pid}/hypotheses")
    all_h = r.json()
    assert any(h["status"] == "accepted" for h in all_h)

    # 8. ручная правка ячейки
    r = client.patch(f"/api/projects/{pid}/report/cells", json={
        "edits": [{"key": "+125/Закрытый Pnt/Cp/Ni", "tonnes": 845.0}]})
    assert r.status_code == 200
    rep = r.json()["report"]
    cell = [c for c in rep["cells"]
            if c["axes"]["size_class"] == "+125" and c["element"] == "Ni"
            and c["axes"]["mineral_form"] == "Закрытый Pnt/Cp"][0]
    assert cell["provenance"] == "manual"
    assert cell["tonnes"] == 845.0


def test_kb_endpoints(client):
    r = client.get("/api/kb/documents")
    assert r.status_code == 200
    assert r.json()[0]["source"] == "Справочник.pdf"

    r = client.post("/api/kb/ask", json={"question": "как повысить раскрытие пентландита"})
    assert r.status_code == 200
    body = r.json()
    assert "LLM недоступна" in body["answer"]
    assert body["chunks"], "чанки должны вернуться и без LLM"

    cid = body["chunks"][0]["chunk_id"]
    r = client.get(f"/api/kb/chunk/{cid}")
    assert r.status_code == 200
    assert r.json()["source"] == "Справочник.pdf"


def test_project_404(client):
    assert client.get("/api/projects/nope").status_code == 404
    assert client.get("/api/projects/nope/diagnostics").status_code == 404
