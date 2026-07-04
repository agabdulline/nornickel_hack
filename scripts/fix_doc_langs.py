# -*- coding: utf-8 -*-
"""Пересчёт языка документов БЗ новым детектором (доли алфавитов по всему
документу вместо голосования чанков — китайские статьи с английскими
аннотациями детектировались как en). Идемпотентно.

Запуск: python scripts/fix_doc_langs.py [--log FILE]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("--log", default="")
args = ap.parse_args()
if args.log:
    sys.stdout = sys.stderr = open(args.log, "a", buffering=1, encoding="utf-8")

from backend.app.kb.index import default_index, doc_lang  # noqa: E402


def main():
    kb = default_index()
    texts_by_doc: dict[str, list[str]] = defaultdict(list)
    for c in kb.chunks:
        texts_by_doc[c["doc_id"]].append(c["text"])

    changed = []
    for doc_id, meta in kb.docs.items():
        texts = texts_by_doc.get(doc_id) or []
        new = doc_lang(texts)
        old = meta.get("lang", "ru")
        if new != old:
            meta["lang"] = new
            changed.append((meta.get("source", doc_id), old, new))
    if changed:
        with kb._lock:
            kb._save_meta()
    print(f"документов: {len(kb.docs)}, исправлено языков: {len(changed)}")
    for src, old, new in changed[:40]:
        print(f"  {old}->{new}: {src[:75]}")
    if len(changed) > 40:
        print(f"  … и ещё {len(changed) - 40}")
    from collections import Counter
    print("итог:", Counter(m.get("lang") for m in kb.docs.values()))


if __name__ == "__main__":
    main()
