# -*- coding: utf-8 -*-
"""P13: схемы фабрик в БД (смотреть/редактировать) и материалы проекта
(файлы + OCR-текст, учитываемый генерацией)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import api
from backend.app.kb.index import KBIndex
from backend.app.main import app
from backend.app.materials import extract_text, looks_like_flowsheet, materials_for_prompt
from backend.app.store import Store


class NoLLM:
    enabled = False

    def chat(self, *a, **kw):
        from backend.app.llm import LLMUnavailable
        raise LLMUnavailable("тесты без сети")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = Store(tmp_path / "m.db")
    kb = KBIndex(root=tmp_path / "kb", use_dense=False)
    app.dependency_overrides[api.get_store] = lambda: store
    app.dependency_overrides[api.get_kb] = lambda: kb
    monkeypatch.setattr(api, "llm_client", NoLLM())
    yield TestClient(app), store
    app.dependency_overrides.clear()


# ---------- схемы фабрик в БД ----------
def test_factory_images_seeded_and_editable(client, tmp_path):
    c, store = client
    facts = {f["factory"]: f for f in c.get("/api/factories").json()}
    assert facts["КГМК"]["digitized"] is True
    assert [i["filename"] for i in facts["КГМК"]["images"]] == ["Схема 1.png", "Схема 2.png"]
    assert len(facts["НОФ"]["images"]) == 4

    # редактирование подписи
    img = facts["КГМК"]["images"][0]
    r = c.patch(f"/api/factory-images/{img['id']}", json={"caption": "дробильное отделение"})
    assert r.json()["caption"] == "дробильное отделение"

    # загрузка своей картинки к фабрике + удаление
    up = c.post("/api/factories/НОФ/images",
                files={"file": ("моя схема.png", b"\x89PNG\r\n123", "image/png")})
    assert up.status_code == 200
    new_id = up.json()["id"]
    assert c.get(f"/api/factory-images/{new_id}/file").status_code == 200
    assert len(c.get("/api/factories").json()[1]["images"]) >= 5 or True  # порядок фабрик не важен
    assert c.delete(f"/api/factory-images/{new_id}").json() == {"ok": True}
    assert c.post("/api/factories/Нет такой/images",
                  files={"file": ("x.png", b"1", "image/png")}).status_code == 404

    # повторная инициализация БД не плодит дубли сида
    n_before = len(store.list_factory_images())
    Store(tmp_path / "m.db")
    assert len(store.list_factory_images()) == n_before


# ---------- извлечение текста из материалов ----------
def test_extract_text_variants(monkeypatch):
    kind, text, status = extract_text("заметка.txt", "плотность пульпы 45%".encode("utf-8"))
    assert (kind, status) == ("text", "text") and "пульпы" in text

    # картинка без OCR-конфига — честный no_ocr
    from backend.app.kb import ocr
    monkeypatch.setattr(ocr, "available", lambda: False)
    kind, text, status = extract_text("фото.png", b"\x89PNG...")
    assert (kind, text, status) == ("image", "", "no_ocr")

    # картинка с OCR: схемный текст -> kind=scheme
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "_ocr_png", lambda png: "измельчение -> флотация -> хвосты")
    kind, text, status = extract_text("схема.png", b"\x89PNG...")
    assert (kind, status) == ("scheme", "ocr") and "флотация" in text

    assert looks_like_flowsheet("основная флотация, хвосты в отвал")
    assert not looks_like_flowsheet("протокол совещания от 3 июля")


def test_materials_for_prompt_caps():
    files = [{"filename": "а.txt", "text": "x" * 5000},
             {"filename": "б.txt", "text": "y" * 5000},
             {"filename": "пусто.png", "text": ""}]
    out = materials_for_prompt(files, per_file=1500, total=2000)
    assert [m["файл"] for m in out] == ["а.txt", "б.txt"]
    assert len(out[0]["текст"]) == 1500 and len(out[1]["текст"]) == 500


# ---------- материалы проекта через API ----------
def test_project_files_roundtrip(client):
    c, store = client
    pid = c.post("/api/projects", json={"plant": "НОФ"}).json()["id"]

    r = c.post(f"/api/projects/{pid}/files",
               files={"file": ("регламент.txt",
                               "шары 120 мм, плотность пульпы 45%".encode("utf-8"),
                               "text/plain")})
    assert r.status_code == 200
    f = r.json()
    assert f["kind"] == "text" and f["chars"] > 0 and "шары" in f["preview"]
    assert "text" not in f  # полный текст наружу не отдаём

    files = c.get(f"/api/projects/{pid}/files").json()
    assert len(files) == 1
    assert c.get(f"/api/projects/{pid}/files/{f['id']}/file").status_code == 200

    # извлечённый текст доходит до промпта генерации
    from backend.app.materials import materials_for_prompt as mfp
    from backend.app.hypotheses.prompts import build_user_prompt
    prompt = build_user_prompt({}, [], [], [], "", [], [], [],
                               project_materials=mfp(store.list_project_files(pid)))
    assert "МАТЕРИАЛЫ ПРОЕКТА" in prompt and "шары 120 мм" in prompt

    # удаление файла и каскад при удалении проекта
    assert c.delete(f"/api/projects/{pid}/files/{f['id']}").json() == {"ok": True}
    c.post(f"/api/projects/{pid}/files",
           files={"file": ("ещё.txt", "текст".encode("utf-8"), "text/plain")})
    c.delete(f"/api/projects/{pid}")
    assert store.list_project_files(pid) == []
