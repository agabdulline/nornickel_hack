# -*- coding: utf-8 -*-
"""Досев демо-проектов на РАЗНЫХ этапах пайплайна — чтобы страница «Проекты»
показывала проекты на шагах 1..4 (Данные / Диагностика / Гипотезы / Отчёт).

Переиспользует уже построенный индекс KB (НЕ переиндексирует). Гипотезы доп-проектов —
мок (быстро; цитаты заземляются на локальный индекс). Идемпотентно: проект с таким
же именем повторно не создаётся. Запускать ПОСЛЕ demo_seed, с выключенным бэкендом
(как one-off контейнер), чтобы не конфликтовать по chroma/sqlite.

    python scripts/seed_stages.py
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import DATA_CASE  # noqa: E402
from backend.app.diagnostics import run_diagnostics  # noqa: E402
from backend.app.hypotheses.generate import generate_hypotheses  # noqa: E402
from backend.app.hypotheses.rank import rank_hypotheses  # noqa: E402
from backend.app.hypotheses.roadmap import build_roadmap  # noqa: E402
from backend.app.hypotheses.verify import verify_citations  # noqa: E402
from backend.app.kb.index import default_index  # noqa: E402
from backend.app.parser.recover import recover  # noqa: E402
from backend.app.parser.xlsx import parse_workbook  # noqa: E402
from backend.app.store import default_store  # noqa: E402


class _NoLLM:
    enabled = False


def find_file(pattern: str) -> Path | None:
    rx = re.compile(pattern)
    for dp, _dirs, files in os.walk(DATA_CASE):
        for f in files:
            rel = os.path.relpath(os.path.join(dp, f), DATA_CASE)
            if rx.search(unicodedata.normalize("NFC", rel.replace(os.sep, "/"))):
                return Path(dp) / f
    return None


def _backdate(store, pid: str, days: int):
    d = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with store._lock:
        store._conn.execute("UPDATE projects SET created_at=? WHERE id=?", (d, pid))
        store._conn.commit()


def main() -> int:
    store = default_store()
    kb = default_index()
    existing = {p.name or p.plant for p in store.list_projects()}

    # (имя, цель, дней_назад, xlsx-паттерн|None, генерировать_гипотезы, принять+гант)
    specs = [
        ("ОФ «Заполярная» · пилот", "Снизить шламовые потери в контрольной флотации",
         12, None, False, False),
        ("НОФ · линия 1 · Cu-порфир", "Извлечение Cu на +0.8 п.п.",
         8, r"Пример 3/.*\.xlsx$", False, False),
        ("ТОФ · пирротиновые хвосты", "Снизить потери Ni на 1.2 п.п.",
         5, r"Пример 4/.*\.xlsx$", True, False),
        ("КГМК · вкрапленные руды", "Снижение потерь Ni и Cu в отвальных хвостах",
         3, r"Пример 1/.*\.xlsx$", True, True),
    ]

    for name, goal, days, pat, gen, accept_roadmap in specs:
        if name in existing:
            print(f"skip (уже есть): {name}")
            continue
        p = store.create_project(plant=name, goal=goal, name=name)
        _backdate(store, p.id, days)
        step = 1

        if pat:
            xlsx = find_file(pat)
            if not xlsx:
                print(f"  {name}: xlsx по «{pat}» не найден — оставляю на этапе 1")
            else:
                parsed = parse_workbook(xlsx)
                report = parsed.reports[0]
                recover(report, llm=None)
                store.save_reports(p.id, xlsx.name, parsed.reports,
                                   {"issues": [i.model_dump() for i in parsed.issues],
                                    "parse_meta": parsed.meta})
                step = 2

                if gen:
                    diag = run_diagnostics(report)
                    hyps = generate_hypotheses(report, diag, kb_index=kb, llm=_NoLLM())
                    verify_citations(hyps, kb)
                    rank_hypotheses(hyps, weights=p.weights)
                    store.save_hypotheses(p.id, hyps, replace=True)
                    if hyps:
                        step = 3
                    if accept_roadmap and hyps:
                        for h in hyps[:3]:
                            h.status = "accepted"
                            store.update_hypothesis(h)
                            store.add_feedback(h.id, p.id, "accept", "")
                        accepted = store.get_hypotheses(p.id, statuses=["accepted"])
                        items = build_roadmap(accepted)
                        store.save_roadmap(p.id, [it.model_dump() for it in items])
                        step = 4

        print(f"проект {p.id}: {name} — этап {step}/4")

    print("ГОТОВО seed_stages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
