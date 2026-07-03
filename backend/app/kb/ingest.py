# -*- coding: utf-8 -*-
"""Инжест PDF: текст (pymupdf) -> нормализация -> чанки -> индекс.

Детектор скана (раздел 3 CLAUDE.md): 5 проб по страницам, <200 символов/стр
в среднем -> скан без текстового слоя, НЕ OCR-им: status="scan_no_text",
UI показывает бейдж «требуется OCR».
"""
from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

import fitz  # pymupdf

from .index import KBIndex, default_index
from .textnorm import chunk_pages, normalize_page_text

log = logging.getLogger("kb.ingest")

SCAN_CHARS_PER_PAGE = 200
SCAN_SAMPLE_PAGES = 5


def detect_scan(doc: "fitz.Document") -> bool:
    """5 равномерно распределённых страниц; в среднем <200 симв./стр -> скан."""
    n = doc.page_count
    if n == 0:
        return True
    idxs = sorted({min(n - 1, round(i * (n - 1) / max(SCAN_SAMPLE_PAGES - 1, 1)))
                   for i in range(min(SCAN_SAMPLE_PAGES, n))})
    total = sum(len(doc[i].get_text("text") or "") for i in idxs)
    return total / len(idxs) < SCAN_CHARS_PER_PAGE


def ingest_pdf(source, filename: str = "", index: KBIndex | None = None) -> dict:
    """source: путь | bytes. -> {"status", "pages", "chunks", "doc_id"}."""
    index = index or default_index()
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
        filename = filename or Path(source).name
    else:
        data = source
    doc_id = hashlib.sha1(filename.encode("utf-8") if filename else data[:65536]).hexdigest()[:12]

    doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
    n_pages = doc.page_count

    if detect_scan(doc):
        log.warning("%s: скан без текстового слоя (%d стр.) — не индексируем, нужен OCR",
                    filename, n_pages)
        info = index.add_document(doc_id, filename, [(0, "")], [], status="scan_no_text")
        doc.close()
        return {"status": "scan_no_text", "pages": n_pages, "chunks": 0, "doc_id": doc_id}

    pages = []
    for i in range(n_pages):
        raw = doc[i].get_text("text") or ""
        pages.append((i + 1, normalize_page_text(raw)))
    doc.close()

    chunks = chunk_pages(pages)
    index.add_document(doc_id, filename, pages, chunks, status="indexed")
    log.info("%s: %d стр. -> %d чанков", filename, n_pages, len(chunks))
    return {"status": "indexed", "pages": n_pages, "chunks": len(chunks), "doc_id": doc_id}


def ingest_ocr_pages(doc_id: str, filename: str, ocr_pages: list[tuple[int, str]],
                     index: KBIndex | None = None) -> dict:
    """Индексация распознанных OCR страниц (скан после Vision)."""
    index = index or default_index()
    pages = [(no, normalize_page_text(text)) for no, text in ocr_pages]
    chunks = chunk_pages(pages)
    index.add_document(doc_id, filename, pages, chunks, status="indexed_ocr")
    log.info("%s (OCR): %d стр. -> %d чанков", filename, len(pages), len(chunks))
    return {"status": "indexed_ocr", "pages": len(pages), "chunks": len(chunks),
            "doc_id": doc_id}
