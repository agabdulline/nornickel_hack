# -*- coding: utf-8 -*-
"""Поиск по базе знаний и вопрос-ответ с цитатами (для /kb/ask и генерации)."""
from __future__ import annotations

import json
import logging

from ..llm import LLMClient, LLMUnavailable, client as default_client, extract_json
from .index import KBIndex, default_index

log = logging.getLogger("kb.search")


def search(query: str, k: int = 5, index: KBIndex | None = None) -> list[dict]:
    return (index or default_index()).search(query, k=k)


def search_multi(queries: list[str], k_each: int = 4,
                 k_total: int = 10, index: KBIndex | None = None) -> list[dict]:
    """Несколько запросов -> объединённый топ без дублей (для генерации гипотез)."""
    index = index or default_index()
    seen: dict[str, dict] = {}
    for q in queries:
        for hit in index.search(q, k=k_each):
            prev = seen.get(hit["chunk_id"])
            if prev is None or hit["score"] > prev["score"]:
                seen[hit["chunk_id"]] = hit
    return sorted(seen.values(), key=lambda h: -h["score"])[:k_total]


def ask(question: str, k: int = 5, index: KBIndex | None = None,
        llm: LLMClient | None = None) -> dict:
    """Ответ на вопрос по KB с цитатами (страница + источник).

    Без LLM-ключа возвращает найденные чанки и честное сообщение.
    """
    llm = llm or default_client
    hits = search(question, k=k, index=index)
    if not hits:
        return {"answer": "В базе знаний ничего не найдено по этому вопросу.",
                "citations": [], "chunks": []}

    context = "\n\n".join(
        f"[{h['chunk_id']}] {h['source']}, с. {h['page']}:\n{h['text'][:1500]}" for h in hits)
    prompt = (
        "Ответь на вопрос инженера-обогатителя ТОЛЬКО по приведённым фрагментам "
        "литературы. На каждое утверждение — ссылка вида [chunk_id]. Если ответа "
        "в фрагментах нет — скажи прямо.\n\n"
        f"Фрагменты:\n{context}\n\nВопрос: {question}\n\n"
        'Ответ строго JSON: {"answer": "текст с [chunk_id]-ссылками", '
        '"used_chunk_ids": ["..."]}'
    )
    try:
        resp = llm.chat([{"role": "user", "content": prompt}], strong=False, json_mode=True)
        data = extract_json(resp["content"])
        used = set(data.get("used_chunk_ids", []))
    except (LLMUnavailable, ValueError) as e:
        log.warning("kb.ask: LLM недоступна (%s) — отдаю только фрагменты", e)
        return {"answer": "LLM недоступна — вот наиболее релевантные фрагменты литературы.",
                "citations": [_cite(h) for h in hits], "chunks": hits}

    citations = [_cite(h) for h in hits if h["chunk_id"] in used] or [_cite(h) for h in hits[:2]]
    return {"answer": data.get("answer", ""), "citations": citations, "chunks": hits}


def _cite(h: dict) -> dict:
    return {"chunk_id": h["chunk_id"], "source": h["source"], "page": h["page"],
            "quote": h["text"][:240]}
