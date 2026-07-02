# -*- coding: utf-8 -*-
"""Парсер docx с эталонными гипотезами экспертов (ground truth для eval).

Формат файлов кейса: заголовок-абзац + таблица в одну колонку,
каждая строка — «N. Текст гипотезы». Парсим и таблицы, и абзацы.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import docx

_ITEM_RE = re.compile(r"^\s*(\d+)\s*[.)]\s*(.+)", re.DOTALL)


def parse_expert_hypotheses(source, source_name: str = "") -> list[dict]:
    """-> [{"n": 1, "title": "...", "text": "..."}] в порядке нумерации."""
    if isinstance(source, (str, Path)):
        document = docx.Document(str(source))
    elif isinstance(source, bytes):
        document = docx.Document(io.BytesIO(source))
    else:
        document = docx.Document(source)

    texts: list[str] = []
    for table in document.tables:
        for row in table.rows:
            seen_ids = set()
            for cell in row.cells:  # merged-ячейки повторяются — дедуп по id
                if id(cell._tc) in seen_ids:
                    continue
                seen_ids.add(id(cell._tc))
                if cell.text.strip():
                    texts.append(cell.text.strip())
    for p in document.paragraphs:
        if p.text.strip():
            texts.append(p.text.strip())

    items: list[dict] = []
    seen_n = set()
    for t in texts:
        m = _ITEM_RE.match(t)
        if not m:
            continue
        n = int(m.group(1))
        if n in seen_n or n > 50:
            continue
        seen_n.add(n)
        body = m.group(2).strip()
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        items.append({
            "n": n,
            "title": lines[0] if lines else body,
            "text": body,
        })
    items.sort(key=lambda x: x["n"])
    return items
