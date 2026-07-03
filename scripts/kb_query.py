# -*- coding: utf-8 -*-
"""Ручной запрос к индексу kb_yandex_v2 (для отладки качества поиска).

Использование: python scripts/kb_query.py "текст запроса" [N] [--dense]
По умолчанию — гибрид BM25+dense (RRF); --dense — чистый dense-поиск.
Вывод: top-N (default 5): source_file | author, year | page | скоры | 300 символов.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kb.search_hybrid import search  # noqa: E402


def query(text: str, k: int = 5, dense_only: bool = False) -> list[dict]:
    return search(text, k=k, dense_only=dense_only)


def main():
    args = [a for a in sys.argv[1:] if a != "--dense"]
    dense_only = "--dense" in sys.argv
    if not args:
        print(__doc__)
        return 1
    text = args[0]
    k = int(args[1]) if len(args) > 1 else 5
    print(f"ЗАПРОС ({'dense' if dense_only else 'гибрид'}): {text}\n")
    for h in query(text, k, dense_only):
        page = f"с. {h['page']}" if h.get("page") not in (-1, None) else "—"
        scores = f"rrf {h['rrf']}" + (f" | bm25 {h['bm25']}" if h["bm25"] else "") + \
                 (f" | dist {h['dense_dist']}" if h["dense_dist"] is not None else "")
        print(f"{h['source_file']} | {h.get('author', '')}, {h.get('year', '')} | {page} | {scores}")
        print(f"  [{h['chunk_id']}] {' '.join(h['text'].split())[:300]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
