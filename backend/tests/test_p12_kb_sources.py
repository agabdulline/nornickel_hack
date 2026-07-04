# -*- coding: utf-8 -*-
"""Управление источниками БЗ: язык (ru/en/zh), вкл/выкл в поиске, удаление,
подхват готового OCR-результата (sidecar) при инжесте скана."""
import json

import pytest

from backend.app.kb.index import KBIndex, detect_lang
from backend.app.kb.ingest import ingest_pdf, ingest_text
from backend.app.kb.textnorm import chunk_pages
from backend.tests.conftest import requires_data


RU = ("Флотация сульфидных минералов: пентландит и халькопирит поднимаются "
      "воздушными пузырьками в пенный слой, порода тонет в камере. " * 6)
EN = ("Froth flotation of sulphide minerals: pentlandite and chalcopyrite "
      "particles attach to air bubbles and report to the concentrate. " * 6)
ZH = "硫化矿浮选：五元石和黄铜矿颗粒附着在气泡上进入精矿，脉石沉入尾矿。选矿厂通过磨矿和分级控制粒度。" * 6


def _add(idx: KBIndex, doc_id: str, name: str, text: str):
    pages = [(1, text)]
    return idx.add_document(doc_id, name, pages, chunk_pages(pages, target=200))


def test_detect_lang():
    assert detect_lang(RU) == "ru"
    assert detect_lang(EN) == "en"
    assert detect_lang(ZH) == "zh"
    assert detect_lang("") == "ru", "пустой текст — дефолт ru"


def test_add_document_sets_lang_and_enabled(tmp_path):
    idx = KBIndex(root=tmp_path, use_dense=False)
    _add(idx, "d_ru", "флотация.pdf", RU)
    _add(idx, "d_en", "flotation.pdf", EN)
    _add(idx, "d_zh", "fuxuan.pdf", ZH)
    langs = {d["doc_id"]: d["lang"] for d in idx.documents()}
    assert langs == {"d_ru": "ru", "d_en": "en", "d_zh": "zh"}
    assert all(d["enabled"] for d in idx.documents())


def test_disabled_source_excluded_from_search(tmp_path):
    idx = KBIndex(root=tmp_path, use_dense=False)
    _add(idx, "d1", "флотация.pdf", RU)
    _add(idx, "d2", "измельчение.pdf",
         "Измельчение руды в шаровых мельницах и классификация в гидроциклонах. " * 8)

    hits = idx.search("флотация пентландит пузырьки", k=5)
    assert any(h["source"] == "флотация.pdf" for h in hits)

    idx.set_doc_meta("d1", enabled=False)
    hits_off = idx.search("флотация пентландит пузырьки", k=5)
    assert not any(h["source"] == "флотация.pdf" for h in hits_off), \
        "выключенный источник не должен попадать в выдачу"

    idx.set_doc_meta("d1", enabled=True)
    hits_on = idx.search("флотация пентландит пузырьки", k=5)
    assert any(h["source"] == "флотация.pdf" for h in hits_on)


def test_delete_document(tmp_path):
    idx = KBIndex(root=tmp_path, use_dense=False)
    _add(idx, "d1", "флотация.pdf", RU)
    _add(idx, "d2", "измельчение.pdf", "Измельчение руды в мельницах. " * 8)
    assert idx.delete_document("d1") is True
    assert idx.delete_document("d1") is False, "повторное удаление — False"
    assert all(c["doc_id"] != "d1" for c in idx.chunks)
    assert "d1" not in idx.docs
    assert not any(h["source"] == "флотация.pdf"
                   for h in idx.search("флотация пентландит", k=5))
    # персистентность: перечитанный индекс тоже без документа
    idx2 = KBIndex(root=tmp_path, use_dense=False)
    assert "d1" not in idx2.docs


def test_load_migrates_legacy_docs(tmp_path):
    idx = KBIndex(root=tmp_path, use_dense=False)
    _add(idx, "d1", "флотация.pdf", RU)
    # имитируем старый индекс: убираем новые поля из meta.json
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    for d in meta["docs"].values():
        d.pop("lang", None)
        d.pop("enabled", None)
    (tmp_path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False),
                                        encoding="utf-8")
    idx2 = KBIndex(root=tmp_path, use_dense=False)
    doc = idx2.docs["d1"]
    assert doc["enabled"] is True and doc["lang"] == "ru"


def _scan_pdf_bytes() -> bytes:
    """PDF без текстового слоя (3 пустые страницы) — детектор считает сканом."""
    import fitz
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def test_ingest_scan_uses_ocr_sidecar(tmp_path):
    idx = KBIndex(root=tmp_path / "kb", use_dense=False)
    data = _scan_pdf_bytes()

    # без sidecar — скан не индексируется
    res = ingest_pdf(data, filename="скан-книга.pdf", index=idx, ocr_dir=tmp_path / "нет")
    assert res["status"] == "scan_no_text" and res["chunks"] == 0

    # с sidecar — индексируется как OCR
    side = tmp_path / "ocr"
    side.mkdir()
    rows = [{"page": i + 1, "text": RU} for i in range(3)]
    (side / "скан-книга.pages.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    res2 = ingest_pdf(data, filename="скан-книга.pdf", index=idx, ocr_dir=side)
    assert res2["status"] == "indexed_ocr"
    assert res2["chunks"] > 0
    doc = idx.docs[res2["doc_id"]]
    assert doc["status"] == "indexed_ocr" and doc["lang"] == "ru"
    assert idx.search("флотация пентландит", k=3), "OCR-текст ищется"


def test_ingest_text_txt_source(tmp_path):
    p = tmp_path / "патент.txt"
    p.write_text(RU, encoding="utf-8")
    idx = KBIndex(root=tmp_path / "kb", use_dense=False)
    res = ingest_text(p, index=idx)
    assert res["status"] == "indexed" and res["chunks"] > 0
    assert idx.docs[res["doc_id"]]["source"] == "патент.txt"


def test_ingest_text_cp1251_fallback(tmp_path):
    """Русские .txt из внешних источников бывают в cp1251 — не падаем."""
    p = tmp_path / "патент1251.txt"
    p.write_bytes(RU.encode("cp1251"))
    idx = KBIndex(root=tmp_path / "kb", use_dense=False)
    res = ingest_text(p, index=idx)
    assert res["chunks"] > 0
    assert "флотация" in idx.chunks[0]["text"].lower()


def test_sidecar_pages_sorted_and_robust(tmp_path):
    """Sidecar пишется параллельным OCR — страницы вразнобой; читатель обязан
    сортировать. Битый jsonl/BOM/пустое имя не роняют инжест."""
    from backend.app.kb.ingest import load_ocr_sidecar
    side = tmp_path / "ocr"
    side.mkdir()
    rows = [{"page": p, "text": f"страница {p} " + RU[:120]} for p in (3, 1, 2)]
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    (side / "книга.pages.jsonl").write_text("﻿" + body, encoding="utf-8")

    pages = load_ocr_sidecar("книга.pdf", side)
    assert [p for p, _ in pages] == [1, 2, 3], "страницы отсортированы, BOM переварен"

    (side / "битый.pages.jsonl").write_text('{"page": 1, "text": "ок"}\n{оборванный',
                                            encoding="utf-8")
    assert load_ocr_sidecar("битый.pdf", side) is None, "битый jsonl -> None, не исключение"
    assert load_ocr_sidecar("", side) is None, "пустое имя не матчится на .pages.jsonl"


def test_partial_sidecar_rejected(tmp_path):
    """OCR-результат, покрывающий <90% страниц PDF, не выдаётся за полный."""
    from backend.app.kb.ingest import ingest_pdf
    idx = KBIndex(root=tmp_path / "kb", use_dense=False)
    data = _scan_pdf_bytes()  # 3 страницы
    side = tmp_path / "ocr"
    side.mkdir()
    (side / "скан.pages.jsonl").write_text(
        json.dumps({"page": 1, "text": RU}, ensure_ascii=False), encoding="utf-8")
    res = ingest_pdf(data, filename="скан.pdf", index=idx, ocr_dir=side)
    assert res["status"] == "scan_no_text", "1 из 3 страниц — неполный sidecar игнорируется"


def test_set_doc_meta_does_not_resurrect(tmp_path):
    """Прогресс фонового OCR не должен пересоздавать удалённый документ."""
    idx = KBIndex(root=tmp_path, use_dense=False)
    _add(idx, "d1", "скан.pdf", RU)
    assert idx.set_doc_meta("d1", status="ocr_processing") is True
    idx.delete_document("d1")
    assert idx.set_doc_meta("d1", status="ocr_processing", ocr_done=5) is False
    assert "d1" not in idx.docs, "запись-призрак не создана"


def test_doc_topic_classification(tmp_path):
    """Тема источника: детерминированная классификация + миграция + PATCH."""
    from backend.app.kb.index import doc_topic
    assert doc_topic([RU]) == "флотация"
    assert doc_topic(["Износ футеровки шаровых мельниц и классификация в "
                      "гидроциклонах при измельчении руды. " * 5]) == "измельчение и классификация"
    assert doc_topic(["Извлечение золота и серебра из упорных руд "
                      "цианированием. " * 5]) == "металлургия благородных металлов"
    assert doc_topic(["Общий текст без ключевых слов."]) == "прочее"

    idx = KBIndex(root=tmp_path, use_dense=False)
    _add(idx, "d1", "флотация.pdf", RU)
    assert idx.docs["d1"]["topic"] == "флотация"
    # ручной оверрайд через set_doc_meta (PATCH)
    idx.set_doc_meta("d1", topic="прочее")
    assert KBIndex(root=tmp_path, use_dense=False).docs["d1"]["topic"] == "прочее"


def test_kb_translate_endpoint(tmp_path, monkeypatch):
    """Перевод en-фрагмента: батч-вызов FAST, дисковый кэш, 503 без ключа."""
    import json as _json

    from fastapi.testclient import TestClient

    import backend.app.api as api
    import backend.app.config as config
    import backend.app.kb.translate as tr
    from backend.app.main import app

    monkeypatch.setattr(config, "STORAGE", tmp_path / "st")
    monkeypatch.setattr(tr, "STORAGE", tmp_path / "st")
    monkeypatch.setattr(tr, "_CACHE", None)

    idx = KBIndex(root=tmp_path / "kb", use_dense=False)
    pages = [(1, EN)]
    idx.add_document("d1", "flotation.pdf", pages, chunk_pages(pages, target=200))
    cid = idx.chunks[0]["chunk_id"]

    class FakeLLM:
        enabled = True
        calls = 0

        def chat(self, messages, strong=False, json_mode=False):
            FakeLLM.calls += 1
            return {"content": _json.dumps(
                {"translations": [{"n": 0, "text": "Пенная флотация сульфидных минералов."}]},
                ensure_ascii=False)}

    app.dependency_overrides[api.get_kb] = lambda: idx
    monkeypatch.setattr(api, "llm_client", FakeLLM())
    try:
        client = TestClient(app)
        r = client.post("/api/kb/translate", json={"chunk_ids": [cid]})
        assert r.status_code == 200
        assert "флотация" in r.json()["translations"][cid].lower()
        # повторный запрос — из кэша, без нового вызова LLM
        client.post("/api/kb/translate", json={"chunk_ids": [cid]})
        assert FakeLLM.calls == 1

        class DeadLLM:
            enabled = False
        monkeypatch.setattr(api, "llm_client", DeadLLM())
        monkeypatch.setattr(tr, "_CACHE", {})
        r3 = client.post("/api/kb/translate", json={"chunk_ids": [cid]})
        assert r3.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_kb_translate_rejects_wrong_language(tmp_path, monkeypatch):
    """Модель перепутала целевой язык (реальный сбой flash: перевод на
    китайский) — не-русский результат отбрасывается и не кэшируется."""
    import json as _json

    import backend.app.kb.translate as tr
    from backend.app.llm import LLMClient  # noqa: F401

    monkeypatch.setattr(tr, "STORAGE", tmp_path / "st")
    monkeypatch.setattr(tr, "_CACHE", None)

    idx = KBIndex(root=tmp_path / "kb", use_dense=False)
    pages = [(1, EN)]
    idx.add_document("d1", "flotation.pdf", pages, chunk_pages(pages, target=200))
    cid = idx.chunks[0]["chunk_id"]

    class ZhLLM:  # всегда отвечает по-китайски, и на ретрае тоже
        enabled = True
        calls = 0

        def chat(self, messages, strong=False, json_mode=False):
            ZhLLM.calls += 1
            return {"content": _json.dumps(
                {"translations": [{"n": 0, "text": "硫化矿浮选性能预测模型研究"}]},
                ensure_ascii=False)}

    got = tr.translate_chunks([cid], idx, ZhLLM())
    assert cid not in got, "китайский «перевод» отброшен"
    assert ZhLLM.calls == 2, "основной вызов + один ретрай"
    # и в кэш не попал
    assert not any("硫" in v for v in (tr._CACHE or {}).values())


def test_doc_lang_tie_deterministic():
    from backend.app.kb.index import doc_lang
    assert doc_lang([RU, EN]) == "ru", "при ничьей приоритет ru"
    assert doc_lang([EN, ZH]) == "en", "затем en"


def test_kb_document_file_endpoint(tmp_path, monkeypatch):
    """Вкладка «Исходник»: отдача оригинала из storage/kb/files + has_file в превью."""
    from fastapi.testclient import TestClient

    import backend.app.api as api
    import backend.app.config as config
    from backend.app.main import app

    monkeypatch.setattr(config, "STORAGE", tmp_path / "st")
    idx = KBIndex(root=tmp_path / "kb", use_dense=False)
    pages = [(1, RU)]
    idx.add_document("d1", "патент.txt", pages, chunk_pages(pages, target=200))
    files_dir = tmp_path / "st" / "kb" / "files"
    files_dir.mkdir(parents=True)
    (files_dir / "d1.txt").write_text(RU, encoding="utf-8")

    app.dependency_overrides[api.get_kb] = lambda: idx
    try:
        client = TestClient(app)
        r = client.get("/api/kb/documents/d1/file")
        assert r.status_code == 200
        assert "флотация" in r.text.lower()
        assert client.get("/api/kb/documents/d1/preview").json()["has_file"] is True
        # чанк тоже сообщает о наличии исходника — для вкладки в модалке цитаты
        chunk_id = idx.chunks[0]["chunk_id"]
        cr = client.get(f"/api/kb/chunk/{chunk_id}").json()
        assert cr["has_file"] is True and cr["doc_id"] == "d1"
        assert client.get("/api/kb/documents/нет/file").status_code == 404
    finally:
        app.dependency_overrides.clear()


@requires_data
def test_flowsheet_image_endpoint():
    """Исходные изображения оцифрованной схемы отдаются по индексу source_files."""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    client = TestClient(app)
    r = client.get("/api/flowsheet-image/НОФ/0")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert len(r.content) > 10_000, "это реальный PNG, не заглушка"
    assert client.get("/api/flowsheet-image/НОФ/99").status_code == 404
    assert client.get("/api/flowsheet-image/НЕТ-ТАКОЙ/0").status_code == 404


def test_kb_document_preview_endpoint(tmp_path):
    """Превью источника: постраничный срез чанков через API."""
    from fastapi.testclient import TestClient

    import backend.app.api as api
    from backend.app.main import app

    idx = KBIndex(root=tmp_path, use_dense=False)
    pages = [(p, f"Страница {p}. " + RU) for p in range(1, 6)]
    idx.add_document("d1", "книга.pdf", pages, chunk_pages(pages, target=150))
    app.dependency_overrides[api.get_kb] = lambda: idx
    try:
        client = TestClient(app)
        r = client.get("/api/kb/documents/d1/preview?offset=0&limit=3")
        assert r.status_code == 200
        data = r.json()
        assert data["source"] == "книга.pdf"
        assert len(data["chunks"]) == 3
        assert data["total_chunks"] == len([c for c in idx.chunks if c["doc_id"] == "d1"])
        assert data["chunks"][0]["page_start"] == 1
        # вторая страница среза продолжает с offset
        r2 = client.get("/api/kb/documents/d1/preview?offset=3&limit=3")
        ids1 = {c["chunk_id"] for c in data["chunks"]}
        ids2 = {c["chunk_id"] for c in r2.json()["chunks"]}
        assert not ids1 & ids2, "срезы не пересекаются"
        assert client.get("/api/kb/documents/нет/preview").status_code == 404
    finally:
        app.dependency_overrides.clear()
