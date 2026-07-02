# -*- coding: utf-8 -*-
"""Верификация цитат: fuzzy-матч цитаты по тексту её chunk_id (раздел 8).

rapidfuzz.partial_ratio > 75 -> verified=true; иначе false, в UI бейдж
«требует проверки». Гипотезы без единой verified-цитаты понижаются в score
(rank.py).
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..kb.index import KBIndex, default_index
from ..models import Hypothesis

THRESHOLD = 75.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def verify_citations(hypotheses: list[Hypothesis],
                     kb_index: KBIndex | None = None) -> dict:
    """Мутирует verified/source/page у цитат. -> статистика."""
    kb_index = kb_index if kb_index is not None else default_index()
    total = verified = 0
    for h in hypotheses:
        for cit in h.rationale:
            total += 1
            chunk = kb_index.get_chunk(cit.chunk_id) if cit.chunk_id else None
            if chunk is None:
                cit.verified = False
                continue
            score = fuzz.partial_ratio(_norm(cit.quote), _norm(chunk["text"]))
            cit.verified = score > THRESHOLD
            if cit.verified:
                cit.source = cit.source or chunk["source"]
                cit.page = cit.page or chunk["page_start"]
                verified += 1
    return {"total": total, "verified": verified,
            "validity": round(verified / total, 3) if total else None}
