# -*- coding: utf-8 -*-
"""Ручной запрос к индексу kb_yandex_v2 (для отладки качества поиска).

Использование: python scripts/kb_query.py "текст запроса" [N] [--dense] [--with-gold]
По умолчанию — гибрид BM25+dense (RRF) c исключением book_gold (книга Лодейщикова
про золото шумит в Cu-Ni запросах); --with-gold — искать по всему корпусу;
--dense — чистый dense-поиск.
Вывод: top-N (default 5): source_file | author, year | page | скоры | 300 символов.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kb.search_hybrid import search  # noqa: E402


def query(text: str, k: int = 5, dense_only: bool = False,
          with_gold: bool = False) -> list[dict]:
    return search(text, k=k, dense_only=dense_only,
                  exclude_types=frozenset() if with_gold else frozenset({"book_gold"}))


def main():
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dense_only = "--dense" in flags
    with_gold = "--with-gold" in flags
    if not args:
        print(__doc__)
        return 1
    text = args[0]
    k = int(args[1]) if len(args) > 1 else 5
    mode = ("dense" if dense_only else "гибрид") + ("" if with_gold else ", без book_gold")
    print(f"ЗАПРОС ({mode}): {text}\n")
    for h in query(text, k, dense_only, with_gold):
        page = f"с. {h['page']}" if h.get("page") not in (-1, None) else "—"
        scores = f"rrf {h['rrf']}" + (f" | bm25 {h['bm25']}" if h["bm25"] else "") + \
                 (f" | dist {h['dense_dist']}" if h["dense_dist"] is not None else "")
        print(f"{h['source_file']} | {h.get('author', '')}, {h.get('year', '')} | {page} | {scores}")
        print(f"  [{h['chunk_id']}] {' '.join(h['text'].split())[:300]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
