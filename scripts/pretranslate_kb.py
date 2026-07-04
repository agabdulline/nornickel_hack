# -*- coding: utf-8 -*-
"""Пре-перевод всех нерусских источников БЗ на русский (наполнение кэша).

Разовый прогон после пополнения корпуса: все en/zh чанки переводятся
FAST-моделью и запоминаются в storage/kb/translations.json — читалка
и цитаты дальше открываются мгновенно и без токенов.

Запуск: python scripts/pretranslate_kb.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.kb.index import default_index  # noqa: E402
from backend.app.kb.translate import pretranslate_document  # noqa: E402
from backend.app.llm import client  # noqa: E402


def main():
    if not getattr(client, "enabled", False):
        sys.exit("нужен живой LLM-ключ (.env)")
    kb = default_index()
    foreign = [(d, m) for d, m in kb.docs.items() if m.get("lang", "ru") != "ru"]
    total_chunks = sum(m.get("chunks", 0) for _d, m in foreign)
    print(f"нерусских источников: {len(foreign)} ({total_chunks} фрагментов)")
    for doc_id, meta in foreign:
        t0 = time.time()
        n = pretranslate_document(doc_id, kb, client)
        print(f"  {meta['source'][:60]}: {n}/{meta.get('chunks')} фрагментов "
              f"({time.time()-t0:.0f}с)")
    print("готово")


if __name__ == "__main__":
    main()
