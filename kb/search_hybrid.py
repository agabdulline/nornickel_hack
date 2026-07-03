# -*- coding: utf-8 -*-
"""Гибридный поиск по kb_yandex_v2: dense (Yandex v2) + BM25Plus, слияние RRF.

Закрывает слабость чистого dense-256 на лексически-точных запросах
(«шламы», «контрольная флотация», «насадки») — см. eval/kb_manual_check.md.
Та же схема, что в KB основного приложения (backend/app/kb).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Plus

ROOT = Path(__file__).resolve().parents[1]
CHUNKS_JSONL = ROOT / "data" / "kb" / "chunks.jsonl"
COLLECTION = "kb_yandex_v2"

RRF_K = 60
CAND = 30  # кандидатов с каждой ветки


def tokenize(text: str) -> list[str]:
    """Грубый стемминг [:6] — компенсирует русскую морфологию."""
    return [t[:6] for t in re.findall(r"[а-яёa-z0-9]+", text.lower())]


@lru_cache(maxsize=1)
def _load():
    chunks = [json.loads(l) for l in CHUNKS_JSONL.read_text(encoding="utf-8").splitlines()
              if l.strip()]
    toks = [tokenize(c["text"]) for c in chunks]
    bm25 = BM25Plus(toks)
    token_sets = [set(t) for t in toks]
    by_id = {c["chunk_id"]: c for c in chunks}
    import chromadb
    col = chromadb.PersistentClient(path=str(ROOT / "chroma")).get_collection(COLLECTION)
    return chunks, bm25, token_sets, by_id, col


# dense-ветка точнее на «смысловых» запросах; вес калиброван перебором
# (1.0/1.3/1.5/2.0) по 6 контрольным запросам eval/kb_manual_check.md: при 2.0
# все отслеживаемые цитаты в top-5, лексические попадания BM25 не теряются
DENSE_WEIGHT = 2.0


def search(query: str, k: int = 5, embedder=None, dense_only: bool = False,
           dense_weight: float = DENSE_WEIGHT,
           exclude_types: frozenset[str] | set[str] = frozenset()) -> list[dict]:
    """Взвешенное RRF-слияние BM25 и dense. embedder — из kb.embedder_base.get_embedder().

    exclude_types — доменный фильтр по метаданному type чанка: для Cu-Ni-контекста
    передавайте {"book_gold"}, иначе золотая книга Лодейщикова шумит в выдаче.
    """
    chunks, bm25, token_sets, by_id, col = _load()
    ranks: dict[str, float] = {}
    bm_score: dict[str, float] = {}
    dense_dist: dict[str, float] = {}

    def allowed(cid: str) -> bool:
        return by_id[cid].get("type", "") not in exclude_types

    if not dense_only:
        q_tokens = set(tokenize(query))
        scores = bm25.get_scores(tokenize(query))
        cand = [i for i in range(len(chunks))
                if token_sets[i] & q_tokens and allowed(chunks[i]["chunk_id"])]
        for rank, i in enumerate(sorted(cand, key=lambda i: -scores[i])[:CAND]):
            cid = chunks[i]["chunk_id"]
            ranks[cid] = ranks.get(cid, 0) + 1.0 / (RRF_K + rank + 1)
            bm_score[cid] = float(scores[i])

    if embedder is None:
        from .embedder_base import get_embedder
        embedder = get_embedder("yandex")
    where = {"type": {"$nin": sorted(exclude_types)}} if exclude_types else None
    got = col.query(query_embeddings=[embedder.embed_query(query)],
                    n_results=min(CAND, col.count()), include=["distances"], where=where)
    for rank, (cid, dist) in enumerate(zip(got["ids"][0], got["distances"][0])):
        if cid in by_id:  # индекс и chunks.jsonl могли разъехаться
            ranks[cid] = ranks.get(cid, 0) + dense_weight / (RRF_K + rank + 1)
            dense_dist[cid] = float(dist)

    out = []
    for cid, score in sorted(ranks.items(), key=lambda kv: -kv[1])[:k]:
        c = by_id[cid]
        out.append({
            "chunk_id": cid, "text": c["text"], "source_file": c["source_file"],
            "author": c.get("author", ""), "year": c.get("year", ""),
            "title": c.get("title", ""), "page": c.get("page"),
            "rrf": round(score, 5),
            "bm25": round(bm_score.get(cid, 0.0), 2),
            "dense_dist": round(dense_dist[cid], 3) if cid in dense_dist else None,
        })
    return out
