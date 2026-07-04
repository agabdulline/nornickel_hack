# -*- coding: utf-8 -*-
"""Инжест PDF: текст (pymupdf) -> нормализация -> чанки -> индекс.

Детектор скана (раздел 3 CLAUDE.md): 5 проб по страницам, <200 символов/стр
в среднем -> скан без текстового слоя, НЕ OCR-им: status="scan_no_text",
UI показывает бейдж «требуется OCR».
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path

import fitz  # pymupdf

from ..config import ROOT
from .index import KBIndex, default_index
from .textnorm import chunk_pages, normalize_page_text

log = logging.getLogger("kb.ingest")

SCAN_CHARS_PER_PAGE = 200
SCAN_SAMPLE_PAGES = 5

# готовые OCR-результаты (Vision OCR прогонялся заранее): <имя книги>.pages.jsonl
OCR_SIDECAR_DIR = ROOT / "data" / "kb" / "ocr"


def load_ocr_sidecar(filename: str, sidecar_dir: Path | None = None) -> list[tuple[int, str]] | None:
    """Ищет рядом сохранённый OCR-результат для скана: jsonl со строками
    {"page": N, "text": "..."} — чтобы не гонять Vision OCR повторно
    (в т.ч. на сервере, где OCR-ключа может не быть).
    Писатель (scripts/ocr_scan_book.py) параллельный и возобновляемый —
    страницы в файле НЕ по порядку, сортируем. Битый файл -> None (деградация
    к обычному scan_no_text/OCR-пути, не 500)."""
    stem = Path(filename).stem
    if not stem:
        return None
    p = (sidecar_dir or OCR_SIDECAR_DIR) / (stem + ".pages.jsonl")
    if not p.exists():
        return None
    try:
        pages: list[tuple[int, str]] = []
        # utf-8-sig: файл мог быть пересохранён на Windows с BOM
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                row = json.loads(line)
                pages.append((int(row["page"]), row.get("text", "")))
    except (ValueError, KeyError, UnicodeDecodeError) as e:
        log.warning("OCR-sidecar %s повреждён (%s) — игнорируем", p.name, e)
        return None
    pages.sort(key=lambda pg: pg[0])
    return pages or None


def detect_scan(doc: "fitz.Document") -> bool:
    """5 равномерно распределённых страниц; в среднем <200 симв./стр -> скан."""
    n = doc.page_count
    if n == 0:
        return True
    idxs = sorted({min(n - 1, round(i * (n - 1) / max(SCAN_SAMPLE_PAGES - 1, 1)))
                   for i in range(min(SCAN_SAMPLE_PAGES, n))})
    total = sum(len(doc[i].get_text("text") or "") for i in idxs)
    return total / len(idxs) < SCAN_CHARS_PER_PAGE


def ingest_pdf(source, filename: str = "", index: KBIndex | None = None,
               ocr_dir: Path | None = None) -> dict:
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
        doc.close()
        sidecar = load_ocr_sidecar(filename, ocr_dir)
        # sidecar должен покрывать PDF: частичный/чужой результат не индексируем
        if sidecar and len(sidecar) >= 0.9 * n_pages:
            log.info("%s: скан, но найден готовый OCR-результат (%d стр.) — индексируем его",
                     filename, len(sidecar))
            return ingest_ocr_pages(doc_id, filename, sidecar, index=index)
        if sidecar:
            log.warning("%s: OCR-sidecar покрывает %d из %d стр. — неполный, игнорируем",
                        filename, len(sidecar), n_pages)
        log.warning("%s: скан без текстового слоя (%d стр.) — не индексируем, нужен OCR",
                    filename, n_pages)
        index.add_document(doc_id, filename, [(0, "")], [], status="scan_no_text")
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


def ingest_text(source, filename: str = "",
                index: KBIndex | None = None) -> dict:
    """Индексация plain-text источника (.txt: патенты, распознанные статьи).
    source: путь | bytes. Кодировка: utf-8 с фоллбэком на cp1251 (типична
    для русских патентов из внешних источников)."""
    index = index or default_index()
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
        filename = filename or Path(source).name
    else:
        data = source
    if not filename:
        raise ValueError("ingest_text: для bytes-источника нужен filename")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1251")
    doc_id = hashlib.sha1(filename.encode("utf-8")).hexdigest()[:12]
    pages = [(1, normalize_page_text(text))]
    chunks = chunk_pages(pages)
    index.add_document(doc_id, filename, pages, chunks, status="indexed")
    log.info("%s (txt): %d чанков", filename, len(chunks))
    return {"status": "indexed", "pages": 1, "chunks": len(chunks), "doc_id": doc_id}
