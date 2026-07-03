# -*- coding: utf-8 -*-
"""Нормализация грязного текстового слоя PDF и чанкование.

Проблемы главной книги (Глембоцкий/Классен): переносы («повыше-\nния»)
и разреженные буквы («Д л я»). Правила нормализации — из раздела 3 CLAUDE.md.
"""
from __future__ import annotations

import re

# перенос: буква + дефис/мягкий перенос + \n + буква -> склеить
_HYPHEN_RE = re.compile(r"([а-яёa-z])[\-­]\s*\n\s*([а-яёa-z])", re.IGNORECASE)
# разреженные буквы: 3+ одиночных букв через пробел («Д л я», «ф л о т а ц и я»)
_SPACED_RE = re.compile(r"\b(?:[А-Яа-яЁёA-Za-z][ \t]+){2,}[А-Яа-яЁёA-Za-z]\b")
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")
_LAT1SUP_RE = re.compile(r"[À-ÿ]")
_CYR_RE = re.compile(r"[а-яА-ЯёЁ]")


def fix_mojibake(text: str) -> str:
    """Битый текстовый слой PDF: cp1251, показанная как latin-1 («Áîëîáîâ»→«Болобов»).
    Типовая болячка PDF из ГИАБ."""
    if not text:
        return text
    lat1 = len(_LAT1SUP_RE.findall(text))
    if lat1 <= max(len(_CYR_RE.findall(text)), 20):
        return text
    for enc in ("cp1252", "latin-1"):
        try:
            return text.encode(enc, errors="replace").decode("cp1251", errors="replace")
        except (UnicodeError, LookupError):
            continue
    return text


def normalize_page_text(text: str) -> str:
    if not text:
        return ""
    text = fix_mojibake(text)
    text = _HYPHEN_RE.sub(r"\1\2", text)
    text = _SPACED_RE.sub(lambda m: re.sub(r"[ \t]+", "", m.group(0)), text)
    text = _MULTISPACE_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_pages(pages: list[tuple[int, str]], target: int = 1200,
                overlap: int = 200) -> list[dict]:
    """pages: [(номер страницы 1-based, текст)] -> чанки с диапазоном страниц.

    Чанк ~target символов, собирается из абзацев, перекрытие ~overlap символов
    (последние абзацы предыдущего чанка).
    """
    paras: list[tuple[str, int]] = []
    for page_no, text in pages:
        for p in re.split(r"\n\s*\n", text or ""):
            p = p.strip()
            if len(p) > 1:
                paras.append((p, page_no))

    chunks: list[dict] = []
    buf: list[tuple[str, int]] = []
    size = 0

    def flush():
        nonlocal buf, size
        if not buf:
            return
        text = "\n".join(p for p, _ in buf).strip()
        if len(text) < 50:  # мусорные обрезки не индексируем
            buf, size = [], 0
            return
        chunks.append({
            "text": text,
            "page_start": buf[0][1],
            "page_end": buf[-1][1],
        })
        # перекрытие: хвостовые абзацы до overlap символов
        tail: list[tuple[str, int]] = []
        acc = 0
        for p in reversed(buf):
            if acc + len(p[0]) > overlap:
                break
            tail.insert(0, p)
            acc += len(p[0])
        buf = tail
        size = acc

    for para, page_no in paras:
        if len(para) > target * 2:  # гигантский абзац режем жёстко
            for i in range(0, len(para), target):
                buf.append((para[i:i + target], page_no))
                size += min(target, len(para) - i)
                if size >= target:
                    flush()
            continue
        buf.append((para, page_no))
        size += len(para)
        if size >= target:
            flush()
    flush()
    return chunks


def tokenize(text: str) -> list[str]:
    """Токенизация для BM25 с грубым стеммингом (первые 6 символов) —
    компенсирует русскую морфологию без внешних библиотек."""
    return [t[:6] for t in re.findall(r"[а-яёa-z0-9]+", text.lower())]
