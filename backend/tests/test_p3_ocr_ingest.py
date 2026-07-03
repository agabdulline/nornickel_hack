# -*- coding: utf-8 -*-
"""Инжест OCR-страниц в KB приложения (без Vision — страницы подложены)."""
from backend.app.kb.index import KBIndex
from backend.app.kb.ingest import ingest_ocr_pages


def test_ingest_ocr_pages(tmp_path):
    idx = KBIndex(root=tmp_path, use_dense=False)
    pages = [(10, "Автоклавное выщелачивание упорных золотых руд ведут при повышенном "
                  "давлении кислорода, что вскрывает сульфидную матрицу. " * 4),
             (11, "Бактериальное окисление арсенопирита — альтернатива обжигу. " * 6)]
    res = ingest_ocr_pages("doc42", "скан_книги.pdf", pages, index=idx)
    assert res["status"] == "indexed_ocr"
    assert res["pages"] == 2 and res["chunks"] >= 1

    docs = idx.documents()
    assert docs[0]["status"] == "indexed_ocr"

    hits = idx.search("автоклавное выщелачивание золотых руд", k=2)
    assert hits and hits[0]["source"] == "скан_книги.pdf"
    assert hits[0]["page"] == 10  # страница сохраняется для цитат

    # прогресс-мета обновляется
    idx.set_doc_meta("doc42", status="ocr_processing", ocr_done=5, pages=100)
    d = [x for x in idx.documents() if x["doc_id"] == "doc42"][0]
    assert d["ocr_done"] == 5 and d["status"] == "ocr_processing"
