# -*- coding: utf-8 -*-
"""Ручной запрос к индексу kb_yandex_v2 (для отладки качества поиска).

Использование: python scripts/kb_query.py "текст запроса" [N]
Вывод: top-N (default 5): source_file | author, year | page | dist | первые 300 символов.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402

from kb.embedder_base import get_embedder  # noqa: E402


def query(text: str, k: int = 5) -> list[dict]:
    embedder = get_embedder("yandex")
    col = chromadb.PersistentClient(path=str(ROOT / "chroma")).get_collection("kb_yandex_v2")
    got = col.query(query_embeddings=[embedder.embed_query(text)], n_results=k,
                    include=["metadatas", "documents", "distances"])
    out = []
    for cid, meta, doc, dist in zip(got["ids"][0], got["metadatas"][0],
                                    got["documents"][0], got["distances"][0]):
        out.append({"chunk_id": cid, "dist": dist, "text": doc, **meta})
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    text = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    print(f"ЗАПРОС: {text}\n")
    for h in query(text, k):
        page = f"с. {h['page']}" if h.get("page", -1) not in (-1, None) else "—"
        head = f"{h['source_file']} | {h.get('author', '')}, {h.get('year', '')} | {page} | dist {h['dist']:.3f}"
        print(head)
        print(f"  [{h['chunk_id']}] {' '.join(h['text'].split())[:300]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
