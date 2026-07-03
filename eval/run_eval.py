# -*- coding: utf-8 -*-
"""Эвал против эталонных гипотез экспертов (раздел 10 CLAUDE.md).

Для каждого из 4 примеров: парсинг xlsx -> диагностика -> генерация ->
сравнение с эталонным docx (judge = FAST-модель: «покрывает ли сгенерированная
гипотеза эталонную (same intervention)?»).

Метрики: coverage (цель >=60%), novel, citation_validity (цель >=90%), parse_ok.
Без LLM-ключа: генерация из мок-фикстуры, judge — fuzzy-фоллбэк (помечается).

Запуск: python eval/run_eval.py [--mock]
Результаты дописываются в eval/report.md, сырые JSON — в eval/out/.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rapidfuzz import fuzz  # noqa: E402

from backend.app.config import DATA_CASE, settings  # noqa: E402
from backend.app.diagnostics import run_diagnostics  # noqa: E402
from backend.app.hypotheses.generate import generate_hypotheses  # noqa: E402
from backend.app.hypotheses.verify import verify_citations  # noqa: E402
from backend.app.kb.index import default_index  # noqa: E402
from backend.app.llm import LLMClient, LLMUnavailable, client, extract_json  # noqa: E402
from backend.app.parser.docx import parse_expert_hypotheses  # noqa: E402
from backend.app.parser.recover import recover  # noqa: E402
from backend.app.parser.xlsx import parse_workbook  # noqa: E402

EXAMPLES = [
    ("Пример 1", r"Пример 1/Хвосты.*\.xlsx$", r"Пример 1/Гипотезы.*\.docx$"),
    ("Пример 2", r"Пример 2/Хвосты.*\.xlsx$", r"Пример 2/Гипотезы.*\.docx$"),
    ("Пример 3", r"Пример 3/Хвосты.*\.xlsx$", r"Пример 3/Гипотезы.*\.docx$"),
    ("Пример 4", r"Пример 4/Хвосты.*\.xlsx$", r"Пример 4/Гипотезы.*\.docx$"),
]

JUDGE_PROMPT = """Ты — эксперт-обогатитель, судья бенчмарка. Сравни сгенерированные системой
гипотезы с эталонными гипотезами экспертов фабрики.

Эталонная гипотеза считается ПОКРЫТОЙ, если среди сгенерированных есть гипотеза с тем же
ВМЕШАТЕЛЬСТВОМ (same intervention: тот же параметр/приём), даже если формулировка
и обоснование другие. Конкретная марка, типоразмер или позиция агрегата НЕ важны:
«футеровка мельниц 3,3м» и «футеровка мельниц МШЦ 4,5×6,0» — одно вмешательство.
Смежные, но РАЗНЫЕ приёмы (например «футеровка» и «шаровая загрузка») покрытием
НЕ считаются.

ЭТАЛОННЫЕ ГИПОТЕЗЫ:
{expert}

СГЕНЕРИРОВАННЫЕ ГИПОТЕЗЫ:
{generated}

Ответ строго JSON:
{{"coverage": [{{"expert_n": 1, "covered": true, "by_id": "id или null", "why": "кратко"}}]}}"""


def find_file(pattern: str) -> Path | None:
    import os
    import unicodedata
    rx = re.compile(pattern)
    for dirpath, _dirs, files in os.walk(DATA_CASE):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), DATA_CASE)
            if rx.search(unicodedata.normalize("NFC", rel.replace(os.sep, "/"))):
                return Path(dirpath) / f
    return None


def judge_coverage(expert: list[dict], generated, llm: LLMClient, use_llm: bool) -> tuple[list[dict], str]:
    """-> (coverage-список, режим судьи)."""
    if use_llm and llm.enabled:
        exp_txt = "\n".join(f"{x['n']}. {x['title']}" for x in expert)
        gen_txt = "\n".join(f"- id={h.id}: {h.title} (механизм: {h.mechanism[:160]})"
                            for h in generated)
        try:
            resp = llm.chat(
                [{"role": "user", "content": JUDGE_PROMPT.format(expert=exp_txt, generated=gen_txt)}],
                strong=False, json_mode=True)
            data = extract_json(resp["content"])
            cov = data.get("coverage", [])
            if cov:
                return cov, "llm"
        except (LLMUnavailable, ValueError) as e:
            print(f"    judge LLM недоступен ({e}) -> fuzzy")
    cov = []
    for x in expert:
        best, best_id = 0.0, None
        for h in generated:
            s = fuzz.token_set_ratio(x["title"].lower(), (h.title + " " + h.mechanism).lower())
            if s > best:
                best, best_id = s, h.id
        cov.append({"expert_n": x["n"], "covered": best >= 55, "by_id": best_id if best >= 55 else None,
                    "why": f"fuzzy {best:.0f}"})
    return cov, "fuzzy-fallback"


def eval_example(name: str, xlsx_re: str, docx_re: str, llm: LLMClient, live: bool) -> dict:
    t0 = time.time()
    out: dict = {"example": name}
    try:
        res = parse_workbook(find_file(xlsx_re))
        report = res.reports[0]
        recover(report, llm=llm if live else None)
        out["parse_ok"] = True
        out["tail_types"] = [r.tail_type for r in res.reports]
        out["parse_issues"] = len(res.all_issues)
    except Exception as e:  # noqa: BLE001
        out["parse_ok"] = False
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    diag = run_diagnostics(report)
    out["diagnoses"] = [f"{d.rule_id}/{d.element}" for d in diag.diagnoses]

    kb = default_index()
    from backend.app.flowsheet import detect_factory, summarize_for_prompt, zero_reagent_hints
    factory = detect_factory(name if isinstance(name, str) else "", report.plant)
    hyps = generate_hypotheses(report, diag, kb_index=kb,
                               llm=llm if live else _NoLLM(),
                               flowsheet_summary=summarize_for_prompt(factory),
                               reagent_hints=zero_reagent_hints(factory, kb_index=kb),
                               n_samples=2 if live else 1)
    vstats = verify_citations(hyps, kb)
    out["generated"] = len(hyps)
    out["citation_validity"] = vstats["validity"]

    expert = parse_expert_hypotheses(find_file(docx_re))
    out["expert_total"] = len(expert)

    cov, judge_mode = judge_coverage(expert, hyps, llm, use_llm=live)
    covered = [c for c in cov if c.get("covered")]
    out["judge"] = judge_mode
    out["covered"] = len(covered)
    out["coverage"] = round(len(covered) / len(expert), 3) if expert else None
    out["coverage_detail"] = cov

    matched_ids = {c.get("by_id") for c in covered}
    novel = [h for h in hyps
             if h.id not in matched_ids and any(c.verified for c in h.rationale)]
    out["novel"] = len(novel)
    out["novel_titles"] = [h.title for h in novel][:20]
    out["hypothesis_titles"] = [h.title for h in hyps]
    out["seconds"] = round(time.time() - t0, 1)
    return out


class _NoLLM:
    enabled = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true",
                    help="не делать живых вызовов (генерация из фикстуры, judge fuzzy)")
    ap.add_argument("--no-report", action="store_true",
                    help="не дописывать eval/report.md (для CI/pytest)")
    args = ap.parse_args()
    live = not args.mock and settings.has_key
    mode = "live" if live else "mock"
    print(f"=== eval, режим {mode}, модель {settings.llm_model_strong}")

    results = []
    for name, xlsx_re, docx_re in EXAMPLES:
        print(f"[{name}] ...")
        r = eval_example(name, xlsx_re, docx_re, client, live)
        cov_str = f"{r.get('covered', '?')}/{r.get('expert_total', '?')}"
        print(f"    parse_ok={r.get('parse_ok')} диагнозы={r.get('diagnoses')} "
              f"гипотез={r.get('generated')} coverage={cov_str} "
              f"cit_validity={r.get('citation_validity')} novel={r.get('novel')} "
              f"за {r.get('seconds')}с")
        results.append(r)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_dir = ROOT / "eval" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{mode}.json"
    raw_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    oks = [r for r in results if r.get("parse_ok")]
    covs = [r["coverage"] for r in oks if r.get("coverage") is not None]
    vals = [r["citation_validity"] for r in oks if r.get("citation_validity") is not None]
    agg = {
        "parse_ok": f"{len(oks)}/{len(results)}",
        "coverage_avg": round(sum(covs) / len(covs), 3) if covs else None,
        "citation_validity_avg": round(sum(vals) / len(vals), 3) if vals else None,
        "novel_total": sum(r.get("novel", 0) for r in oks),
    }

    if args.no_report:
        print(f"\nraw -> {raw_path} (report.md не трогаем: --no-report)")
        print("aggregate:", agg)
        return

    report_path = ROOT / "eval" / "report.md"
    lines = []
    if not report_path.exists():
        lines += ["# Eval — сравнение с эталонными гипотезами экспертов", "",
                  "Цели (раздел 10 CLAUDE.md): coverage ≥ 60%, citation_validity ≥ 90%, "
                  "parse_ok на всех 4 файлах.", ""]
    lines += [f"## Прогон {stamp} ({mode}, {settings.llm_model_strong})", "",
              "| Пример | parse_ok | диагнозы | гипотез | coverage | citation_validity | novel | judge | время |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        cov = f"{r.get('covered', '—')}/{r.get('expert_total', '—')}" \
              + (f" ({r['coverage']:.0%})" if r.get("coverage") is not None else "")
        cv = f"{r['citation_validity']:.0%}" if r.get("citation_validity") is not None else "—"
        lines.append(
            f"| {r['example']} | {'✓' if r.get('parse_ok') else '✗'} "
            f"| {', '.join(r.get('diagnoses', []))} | {r.get('generated', '—')} "
            f"| {cov} | {cv} | {r.get('novel', '—')} | {r.get('judge', '—')} "
            f"| {r.get('seconds', '—')}с |")
    lines += ["",
              f"**Итог:** parse_ok {agg['parse_ok']}, средний coverage "
              f"{agg['coverage_avg']:.0%}" if agg["coverage_avg"] is not None else
              f"**Итог:** parse_ok {agg['parse_ok']}, coverage —",
              ]
    if agg["coverage_avg"] is not None:
        lines[-1] += (f", средняя citation_validity {agg['citation_validity_avg']:.0%}, "
                      f"novel всего {agg['novel_total']}. Сырые данные: {raw_path.name}")
    lines += [""]
    with report_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nreport -> {report_path}\nraw -> {raw_path}")
    print("aggregate:", agg)


if __name__ == "__main__":
    main()
