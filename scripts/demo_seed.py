# -*- coding: utf-8 -*-
"""Демо-сид (раздел 11 CLAUDE.md): создаёт проект «НОФ · вкрапленные руды · Q2 2026»,
загружает Пример 2, индексирует 4 текстовых PDF (+ помечает скан), генерирует
гипотезы, проставляет статусы для канбана и строит дорожную карту.

Работает и с ключом (живые вызовы), и без (мок-фикстура): python scripts/demo_seed.py [--mock]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402
from backend.app.diagnostics import run_diagnostics  # noqa: E402
from backend.app.hypotheses.generate import generate_hypotheses  # noqa: E402
from backend.app.hypotheses.rank import rank_hypotheses  # noqa: E402
from backend.app.hypotheses.roadmap import build_roadmap  # noqa: E402
from backend.app.hypotheses.verify import verify_citations  # noqa: E402
from backend.app.kb.index import default_index  # noqa: E402
from backend.app.kb.ingest import ingest_pdf  # noqa: E402
from backend.app.llm import client  # noqa: E402
from backend.app.parser.recover import recover  # noqa: E402
from backend.app.parser.xlsx import parse_workbook  # noqa: E402
from backend.app.store import default_store  # noqa: E402
from backend.app.api import expert_titles_for_plant  # noqa: E402


class _NoLLM:
    enabled = False


def find_file(pattern: str) -> Path:
    import os
    import re
    import unicodedata
    from backend.app.config import DATA_CASE
    rx = re.compile(pattern)
    for dirpath, _dirs, files in os.walk(DATA_CASE):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), DATA_CASE)
            if rx.search(unicodedata.normalize("NFC", rel.replace(os.sep, "/"))):
                return Path(dirpath) / f
    raise FileNotFoundError(pattern)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="без живых LLM-вызовов")
    args = ap.parse_args()
    live = not args.mock and settings.has_key
    llm = client if live else _NoLLM()
    print(f"=== demo_seed, режим {'live' if live else 'mock'}")

    store = default_store()
    kb = default_index()

    # 1. база знаний: 4 текстовых PDF + скан (бейдж «требуется OCR»)
    for pat in [r"flotacionnye.*\.pdf$", r"metallurgiya-blagorodnyh.*\.pdf$",
                r"tehnologiyaobogashcheniya.*\.pdf$",
                r"tehnologiya_izvlecheniya_zolota.*\.pdf$", r"lodeyshchikov.*\.pdf$"]:
        path = find_file(pat)
        doc_id_known = any(d["source"] == path.name for d in kb.documents())
        if doc_id_known:
            print(f"KB: {path.name} уже в индексе")
            continue
        t0 = time.time()
        res = ingest_pdf(path, index=kb)
        print(f"KB: {path.name} -> {res['status']}, {res['chunks']} чанков ({time.time()-t0:.0f}с)")

    # 2. проект + отчёт (Пример 2)
    project = store.create_project("НОФ · вкрапленные руды · Q2 2026",
                                   goal="Снижение потерь Ni и Cu в отвальных хвостах")
    xlsx = find_file(r"Пример 2/Хвосты.*Вкр\.xlsx$")
    parsed = parse_workbook(xlsx)
    report = parsed.reports[0]
    stats = recover(report, llm=llm if live else None)
    store.save_reports(project.id, xlsx.name, parsed.reports,
                       {"issues": [i.model_dump() for i in parsed.issues],
                        "parse_meta": parsed.meta})
    print(f"проект {project.id}: отчёт загружен, recover={stats}")

    # 3. диагностика + генерация + verify + rank
    diag = run_diagnostics(report)
    print("диагнозы:", [f"{d.rule_id}/{d.element}" for d in diag.diagnoses])
    t0 = time.time()
    hyps = generate_hypotheses(report, diag, kb_index=kb, llm=llm)
    verify_citations(hyps, kb)
    prior = expert_titles_for_plant(report.plant)
    rank_hypotheses(hyps, weights=project.weights, prior_titles=prior)
    store.save_hypotheses(project.id, hyps, replace=True)
    ver = sum(1 for h in hyps for c in h.rationale if c.verified)
    tot = sum(len(h.rationale) for h in hyps)
    print(f"гипотез: {len(hyps)} за {time.time()-t0:.0f}с, цитат verified {ver}/{tot}")

    # 4. статусы для канбана: принять 3 (две — с ОДНИМ ресурсом, чтобы Гант
    #    показал конфликт-сдвиг «ждёт …») + 1 в testing
    from backend.app.domain import verification_profile
    from backend.app.hypotheses.roadmap import _resource_label
    by_resource: dict[str, list] = {}
    for h in hyps:
        res = _resource_label(h, verification_profile(h.hypothesis_type))
        by_resource.setdefault(res, []).append(h)
    conflict_pair = next((v[:2] for v in by_resource.values() if len(v) >= 2), hyps[:2])
    flot = next((h for h in hyps if h.process_area == "флотация" and h not in conflict_pair),
                None)
    accepted = conflict_pair + ([flot] if flot else [])
    for h in accepted:
        h.status = "accepted"
        store.update_hypothesis(h)
        store.add_feedback(h.id, project.id, "accept", "")
    rest = [h for h in hyps if h not in accepted]
    if rest:
        rest[0].status = "testing"
        store.update_hypothesis(rest[0])
    print("статусы: accepted:", [f"{h.title[:40]} [{h.hypothesis_type}]" for h in accepted],
          "| testing:", rest[0].title[:40] if rest else "—")

    # 5. дорожная карта
    accepted = store.get_hypotheses(project.id, statuses=["accepted", "testing"])
    items = build_roadmap(accepted)
    store.save_roadmap(project.id, [it.model_dump() for it in items])
    shifted = [it for it in items if it.shifted_reason]
    print(f"дорожная карта: {len(items)} стадий, со сдвигом: "
          f"{[f'{it.id} ({it.shifted_reason})' for it in shifted] or 'нет'}")

    print(f"\nГОТОВО. Проект: {project.id} — откройте фронтенд и выберите его на главной.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
