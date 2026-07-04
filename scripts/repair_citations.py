# -*- coding: utf-8 -*-
"""Ремонт цитат сохранённых гипотез проекта: смысловое пере-заземление.

Аудит показал: часть цитат тематически-соседние (та же тема, но само
вмешательство не обосновано) — артефакт старого пере-заземления «первые 35 слов
топ-чанка» и генерации до пополнения корпуса. Скрипт пере-оценивает цитаты всех
гипотез проекта по актуальному корпусу: FAST-модель выбирает дословный
обосновывающий фрагмент из свежих кандидатов поиска (включая текущие чанки);
если обосновывающего нет — цитата гипотезы не трогается.

Запуск: python scripts/repair_citations.py --project <id> [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.hypotheses.generate import (_fill_quote_translations,  # noqa: E402
                                              _reground_citations)
from backend.app.hypotheses.verify import verify_citations  # noqa: E402
from backend.app.kb.index import default_index  # noqa: E402
from backend.app.llm import client  # noqa: E402
from backend.app.store import default_store  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not getattr(client, "enabled", False):
        sys.exit("нужен живой LLM-ключ (.env) — смысловая пере-оценка без него невозможна")

    store = default_store()
    kb = default_index()
    hyps = store.get_hypotheses(args.project)
    if not hyps:
        sys.exit(f"у проекта {args.project} нет гипотез")

    before = {h.id: [(c.chunk_id, (c.quote or "")[:60]) for c in h.rationale] for h in hyps}
    _reground_citations(hyps, kb, llm=client, recheck_all=True)
    _fill_quote_translations(hyps, client)
    verify_citations(hyps, kb)

    changed = 0
    for h in hyps:
        after = [(c.chunk_id, (c.quote or "")[:60]) for c in h.rationale]
        if after != before[h.id]:
            changed += 1
            print(f"~ {h.title[:70]}")
            for c in h.rationale:
                print(f"    -> [{c.source}, с. {c.page}] «{(c.quote or '')[:90]}…»")
        else:
            print(f"= {h.title[:70]} (без изменений)")
        if not args.dry_run:
            store.update_hypothesis(h)

    print(f"\nобновлено карточек: {changed}/{len(hyps)}"
          + (" (dry-run, не сохранено)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
