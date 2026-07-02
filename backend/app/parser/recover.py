# -*- coding: utf-8 -*-
"""Восстановление битых данных (раздел 7.1 CLAUDE.md). Два яруса строго по порядку:

Ярус 1 — детерминированный решатель по балансовым инвариантам (без LLM):
  I1: сумма тонн форм класса = тонны класса;
  I2: сумма долей форм класса = 100%;
  I3: тонны формы = доля формы / 100 × тонны класса;
  I4: сумма тонн классов = потери элемента в хвостах;
  I5: тонны класса = доля класса в потерях / 100 × потери элемента;
  I6: тонны класса = 0 -> тонны всех форм = 0 (неотрицательность).
Итеративная пропагация до неподвижной точки: восстанавливаем там, где ровно
одно неизвестное. provenance="recovered_math", формула — в recovery_note.

Ярус 2 — LLM-оценка (FAST) только для ячеек, не закрытых ярусом 1, в классах
с ненулевым тоннажем. В промпт: соседние блоки этого отчёта + типовые
диапазоны из domain_packs/flotation.yaml. provenance="recovered_llm".

Восстановленные значения НИКОГДА не участвуют в контрольных суммах как
истинные — валидатор R5 сверяет только measured.
"""
from __future__ import annotations

import json
import logging

from ..domain import pack
from ..llm import LLMClient, LLMUnavailable, client as default_client, extract_json
from ..models import DataIssue, LossCell, TailingsReport

log = logging.getLogger("recover")

EPS = 1e-9


def _mark(cell: LossCell, field: str, value: float, note: str, report: TailingsReport):
    setattr(cell, field, round(value, 6))
    cell.provenance = "recovered_math"
    cell.recovery_note = (cell.recovery_note + "; " if cell.recovery_note else "") + note
    report.issues.append(DataIssue(
        severity="info", rule="recover", cell=cell.key,
        message=f"Восстановлено (ярус 1): {cell.key} {field} = {value:.4g} — {note}"))


def recover_math(report: TailingsReport) -> int:
    """Ярус 1. Возвращает число восстановленных значений."""
    recovered = 0
    by_class: dict[str, dict[str, list[LossCell]]] = {}
    for c in report.cells:
        by_class.setdefault(c.axes["size_class"], {}).setdefault(c.element, []).append(c)

    size_by_label = {sc.label: sc for sc in report.size_classes}

    changed = True
    guard = 0
    while changed and guard < 50:
        changed = False
        guard += 1

        # --- уровень классов: I4/I5 ---
        for el in ("Ni", "Cu"):
            losses = report.losses_tonnes.get(el)
            rows = [sc for sc in report.size_classes]
            unknown_t = [sc for sc in rows if sc.element_tonnes.get(el) is None]
            if losses is not None:
                for sc in rows:
                    t, sh = sc.element_tonnes.get(el), sc.element_share_pct.get(el)
                    if t is None and sh is not None:
                        sc.element_tonnes[el] = round(sh / 100.0 * losses, 6)
                        report.issues.append(DataIssue(
                            severity="info", rule="recover", cell=f"{sc.label}/{el}",
                            message=f"Восстановлено (ярус 1): тонны класса {sc.label} ({el}) = "
                                    f"{sh:.4g}% × {losses:.4g} т (I5)"))
                        recovered += 1
                        changed = True
                    elif sh is None and t is not None and losses > EPS:
                        sc.element_share_pct[el] = round(t / losses * 100.0, 6)
                        recovered += 1
                        changed = True
                if len(unknown_t) == 1:
                    sc = unknown_t[0]
                    if sc.element_tonnes.get(el) is None:
                        known = sum(x.element_tonnes[el] for x in rows
                                    if x is not sc and x.element_tonnes.get(el) is not None)
                        if all(x.element_tonnes.get(el) is not None for x in rows if x is not sc):
                            val = max(losses - known, 0.0)
                            sc.element_tonnes[el] = round(val, 6)
                            report.issues.append(DataIssue(
                                severity="info", rule="recover", cell=f"{sc.label}/{el}",
                                message=f"Восстановлено (ярус 1): тонны класса {sc.label} ({el}) = "
                                        f"{losses:.4g} − {known:.4g} (I4)"))
                            recovered += 1
                            changed = True

        # --- уровень ячеек минералогии ---
        for label, per_el in by_class.items():
            sc = size_by_label.get(label)
            for el, cells in per_el.items():
                ct = sc.element_tonnes.get(el) if sc else None

                # I6: пустой класс -> все тонны форм нули
                if ct is not None and abs(ct) < EPS:
                    for c in cells:
                        if c.tonnes is None:
                            _mark(c, "tonnes", 0.0,
                                  f"класс {label} пуст ({el}: 0 т), все формы = 0 (I6)", report)
                            recovered += 1
                            changed = True
                    continue

                if ct is not None:
                    # I3: тонны из доли
                    for c in cells:
                        if c.tonnes is None and c.share_pct is not None:
                            _mark(c, "tonnes", c.share_pct / 100.0 * ct,
                                  f"{c.share_pct:.4g}% × {ct:.4g} т класса (I3)", report)
                            recovered += 1
                            changed = True
                        elif c.share_pct is None and c.tonnes is not None and ct > EPS:
                            _mark(c, "share_pct", c.tonnes / ct * 100.0,
                                  f"{c.tonnes:.4g} т / {ct:.4g} т класса (I3)", report)
                            recovered += 1
                            changed = True
                    # I1: ровно одно неизвестное по тоннам
                    unknown = [c for c in cells if c.tonnes is None]
                    if len(unknown) == 1:
                        known_sum = sum(c.tonnes for c in cells if c.tonnes is not None)
                        val = max(ct - known_sum, 0.0)
                        _mark(unknown[0], "tonnes", val,
                              f"{ct:.4g} − {known_sum:.4g} = {val:.4g} т (I1)", report)
                        recovered += 1
                        changed = True

                # I2: ровно одно неизвестное по долям
                unknown_sh = [c for c in cells if c.share_pct is None]
                if len(unknown_sh) == 1:
                    known_sum = sum(c.share_pct for c in cells if c.share_pct is not None)
                    val = max(100.0 - known_sum, 0.0)
                    _mark(unknown_sh[0], "share_pct", val,
                          f"100% − {known_sum:.4g}% = {val:.4g}% (I2)", report)
                    recovered += 1
                    changed = True

    return recovered


def unresolved_cells(report: TailingsReport) -> list[LossCell]:
    """Ячейки, оставшиеся битыми после яруса 1, в непустых классах."""
    size_by_label = {sc.label: sc for sc in report.size_classes}
    out = []
    for c in report.cells:
        sc = size_by_label.get(c.axes["size_class"])
        ct = sc.element_tonnes.get(c.element) if sc else None
        empty_class = ct is not None and abs(ct) < EPS
        if (c.tonnes is None or (c.share_pct is None and not empty_class)) and not empty_class:
            out.append(c)
    return out


def recover_llm(report: TailingsReport, llm: LLMClient | None = None) -> int:
    """Ярус 2: LLM-оценка оставшихся ячеек. Без ключа — issue и 0."""
    cells = unresolved_cells(report)
    if not cells:
        return 0
    llm = llm or default_client
    size_by_label = {sc.label: sc for sc in report.size_classes}

    context_blocks = {}
    for sc in report.size_classes:
        block = {}
        for c in report.cells:
            if c.axes["size_class"] == sc.label and c.provenance == "measured" and c.share_pct is not None:
                block[f"{c.axes['mineral_form']}/{c.element}"] = c.share_pct
        if block:
            context_blocks[sc.label] = block

    typical = pack().get("typical_distribution", {})
    ask = [{"size_class": c.axes["size_class"], "mineral_form": c.axes["mineral_form"],
            "element": c.element} for c in cells]

    prompt = (
        "Ты — главный обогатитель НИИ. В отчёте по хвостам флотации битые ячейки "
        "минералогии. Оцени долю каждой формы в потерях её класса (в %), опираясь на "
        "аналогичные блоки этого же отчёта и типовые диапазоны.\n\n"
        f"Измеренные блоки отчёта (доля формы в потерях класса, %):\n{json.dumps(context_blocks, ensure_ascii=False)}\n\n"
        f"Типовые диапазоны по классам:\n{json.dumps(typical, ensure_ascii=False)}\n\n"
        f"Оцени ячейки:\n{json.dumps(ask, ensure_ascii=False)}\n\n"
        'Ответ строго JSON: {"cells": [{"size_class": "...", "mineral_form": "...", '
        '"element": "Ni|Cu", "share_pct": число, "confidence": 0..1, "explanation": "кратко"}]}'
    )
    try:
        resp = llm.chat([{"role": "user", "content": prompt}], strong=False, json_mode=True)
        data = extract_json(resp["content"])
    except (LLMUnavailable, ValueError) as e:
        report.issues.append(DataIssue(
            severity="warning", rule="recover",
            message=f"Ярус 2 (LLM) недоступен: {e}. {len(cells)} ячеек не восстановлены — проверьте вручную"))
        return 0

    est = {(x.get("size_class"), x.get("mineral_form"), x.get("element")): x
           for x in data.get("cells", [])}
    recovered = 0
    for c in cells:
        x = est.get((c.axes["size_class"], c.axes["mineral_form"], c.element))
        if not x or not isinstance(x.get("share_pct"), (int, float)):
            continue
        share = float(x["share_pct"])
        c.share_pct = share
        sc = size_by_label.get(c.axes["size_class"])
        ct = sc.element_tonnes.get(c.element) if sc else None
        if c.tonnes is None and ct is not None:
            c.tonnes = round(share / 100.0 * ct, 6)
        c.provenance = "recovered_llm"
        c.confidence = float(x.get("confidence", 0.5))
        c.recovery_note = f"LLM-оценка: {x.get('explanation', '')} (confidence={c.confidence:.2f})"
        report.issues.append(DataIssue(
            severity="warning", rule="recover", cell=c.key,
            message=f"Восстановлено (ярус 2, LLM): {c.key} ≈ {share:.2f}% "
                    f"(confidence {c.confidence:.2f}) — проверьте вручную"))
        recovered += 1
    return recovered


def recover(report: TailingsReport, llm: LLMClient | None = None) -> dict:
    """Полный конвейер 7.1: ярус 1, затем ярус 2. -> статистика."""
    n_math = recover_math(report)
    n_llm = recover_llm(report, llm) if unresolved_cells(report) else 0
    left = unresolved_cells(report)
    return {"recovered_math": n_math, "recovered_llm": n_llm, "unresolved": len(left)}
