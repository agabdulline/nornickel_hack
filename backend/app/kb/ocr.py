# -*- coding: utf-8 -*-
"""Yandex Vision OCR для сканов без текстового слоя.

Используется при загрузке в базу знаний: скан -> постраничное распознавание ->
обычный конвейер чанкования/индексации. Квота Vision по умолчанию ~1 rps —
троттлимся и ретраимся; процесс идёт в фоновом потоке, прогресс виден в
GET /kb/documents (status="ocr_processing", ocr_done/pages).
"""
from __future__ import annotations

import base64
import io
import logging
import re
import threading
import time
from typing import Callable

import fitz
import httpx

from ..config import settings

log = logging.getLogger("kb.ocr")

URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
DPI = 200
RETRIES = 8
TIMEOUT = 60.0
MAX_RPS = 0.9

_rate_lock = threading.Lock()
_next_slot = 0.0


def available() -> bool:
    """OCR возможен, если есть ключ Yandex и folder в model URI."""
    return bool(settings.llm_api_key) and bool(_folder())


def _folder() -> str:
    m = re.search(r"(?:gpt|emb)://([^/]+)/", settings.llm_model_strong or "")
    return m.group(1) if m else ""


def _throttle():
    global _next_slot
    with _rate_lock:
        now = time.monotonic()
        wait = _next_slot - now
        _next_slot = max(now, _next_slot) + 1.0 / MAX_RPS
    if wait > 0:
        time.sleep(wait)


def _ocr_png(png: bytes) -> str:
    body = {"mimeType": "image/png", "languageCodes": ["ru"], "model": "page",
            "content": base64.b64encode(png).decode()}
    last = None
    for attempt in range(RETRIES):
        _throttle()
        try:
            r = httpx.post(URL, json=body, timeout=TIMEOUT,
                           headers={"Authorization": f"Api-Key {settings.llm_api_key}",
                                    "x-folder-id": _folder()})
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}",
                                            request=r.request, response=r)
            r.raise_for_status()
            return r.json()["result"]["textAnnotation"]["fullText"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            last = e
            time.sleep(min(2 ** attempt, 30))
    raise RuntimeError(f"Vision OCR не ответил после {RETRIES} попыток: {last}")


def ocr_image(data: bytes) -> str:
    """Одиночное изображение (png/jpg/webp/bmp) -> текст. Конвертация в PNG
    через fitz — Vision получает единый mime, вход не ограничен форматом."""
    doc = fitz.open(stream=io.BytesIO(data))
    try:
        png = doc[0].get_pixmap(dpi=DPI).tobytes("png")
    finally:
        doc.close()
    return _ocr_png(png)


def ocr_pdf(data: bytes, progress: Callable[[int, int], None] | None = None
            ) -> list[tuple[int, str]]:
    """Скан-PDF -> [(страница, текст)]. progress(done, total) — для статуса в UI."""
    doc = fitz.open(stream=io.BytesIO(data), filetype="pdf")
    total = doc.page_count
    pages: list[tuple[int, str]] = []
    for i in range(total):
        png = doc[i].get_pixmap(dpi=DPI).tobytes("png")
        pages.append((i + 1, _ocr_png(png)))
        if progress:
            progress(i + 1, total)
    doc.close()
    return pages
