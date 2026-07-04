# -*- coding: utf-8 -*-
"""Материалы проекта: извлечение текста из загруженных файлов.

Картинки распознаются Yandex Vision OCR (если сконфигурирован), PDF — текстовым
слоем, txt/docx — напрямую. Извлечённый текст уходит в промпт генерации гипотез;
картинки, похожие на технологические схемы, показываются на экране диагностики.
"""
from __future__ import annotations

import io
import logging

log = logging.getLogger("materials")

IMAGE_EXTS = {"png", "jpg", "jpeg", "bmp", "webp"}

# картинка считается схемой, если OCR-текст содержит >=2 доменных маркера
_FLOWSHEET_MARKERS = ("флотац", "измельчен", "дроблен", "классифика", "мельниц",
                      "хвост", "концентрат", "грохо", "сгущен", "гидроциклон",
                      "перечист", "пульп")


def looks_like_flowsheet(text: str) -> bool:
    low = (text or "").lower()
    return sum(1 for m in _FLOWSHEET_MARKERS if m in low) >= 2


def extract_text(filename: str, data: bytes) -> tuple[str, str, str]:
    """-> (kind, text, status).

    kind: scheme | image | pdf | text | other
    status: ocr | text | no_ocr | scan_no_text | empty | error:<...>
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in IMAGE_EXTS:
        from .kb import ocr
        if not ocr.available():
            return "image", "", "no_ocr"
        try:
            png = _to_png(data, ext)
            text = ocr._ocr_png(png)
        except Exception as e:  # квоты/сеть — файл сохраняем, текста нет
            log.warning("OCR материала «%s» не удался: %s", filename, e)
            return "image", "", f"error:{e}"
        kind = "scheme" if looks_like_flowsheet(text) else "image"
        return kind, text, "ocr"

    if ext == "pdf":
        try:
            import fitz
            doc = fitz.open(stream=data, filetype="pdf")
            pages = [doc[i].get_text() for i in range(len(doc))]
            text = "\n".join(pages)
            if len(doc) and len(text) / max(len(doc), 1) < 200:
                return "pdf", text, "scan_no_text"
            return "pdf", text, "text"
        except Exception as e:
            return "pdf", "", f"error:{e}"

    if ext in ("txt", "md", "csv"):
        for enc in ("utf-8-sig", "cp1251"):
            try:
                return "text", data.decode(enc), "text"
            except UnicodeDecodeError:
                continue
        return "text", "", "error:кодировка не распознана"

    if ext == "docx":
        try:
            import docx as docxlib
            d = docxlib.Document(io.BytesIO(data))
            text = "\n".join(p.text for p in d.paragraphs if p.text.strip())
            return "text", text, "text"
        except Exception as e:
            return "text", "", f"error:{e}"

    return "other", "", "empty"


def _to_png(data: bytes, ext: str) -> bytes:
    """Yandex OCR принимает png/jpeg; прочие форматы конвертируем через PIL."""
    if ext in ("png", "jpg", "jpeg"):
        return data
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def materials_for_prompt(files: list[dict], per_file: int = 1500,
                         total: int = 6000) -> list[dict]:
    """Выдержки извлечённого текста для промпта генерации: обрезка по файлу
    и общий кап, чтобы не раздувать контекст."""
    out, used = [], 0
    for f in files:
        text = (f.get("text") or "").strip()
        if not text:
            continue
        excerpt = text[: min(per_file, total - used)]
        if not excerpt:
            break
        used += len(excerpt)
        out.append({"файл": f["filename"], "текст": excerpt})
    return out
