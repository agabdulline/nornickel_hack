# -*- coding: utf-8 -*-
"""Пре-перевод всех нерусских источников БЗ на русский (наполнение кэша).

Разовый прогон после пополнения корпуса: все en/zh чанки переводятся
FAST-моделью и запоминаются в storage/kb/translations.json — читалка
и цитаты дальше открываются мгновенно и без токенов.

Запуск: python scripts/pretranslate_kb.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("--log", default="", help="писать вывод в файл (для docker exec -d, "
                                          "где shell-редирект ненадёжен)")
args = ap.parse_args()
if args.log:
    sys.stdout = sys.stderr = open(args.log, "a", buffering=1, encoding="utf-8")

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
    left = 0
    for doc_id, meta in foreign:
        t0 = time.time()
        try:
            n = pretranslate_document(doc_id, kb, client)
        except Exception as e:  # noqa: BLE001 — добираем остальные документы
            print(f"  {meta['source'][:60]}: ОШИБКА {type(e).__name__} — пропущен")
            left += meta.get("chunks", 0)
            continue
        print(f"  {meta['source'][:60]}: {n}/{meta.get('chunks')} фрагментов "
              f"({time.time()-t0:.0f}с)")
        left += meta.get("chunks", 0) - n
    print("готово" + (f" (не переведено {left} — повторный запуск доберёт)" if left else ""))


if __name__ == "__main__":
    main()
