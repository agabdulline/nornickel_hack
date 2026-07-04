# -*- coding: utf-8 -*-
"""Правила диагностики R1–R5 (раздел 7 CLAUDE.md). Детерминированный код, БЕЗ LLM.

Каждый диагноз хранит правило-ID, входные числа и русский текст —
это и есть интерпретируемость: правило показывается в UI по клику.
Все вычисления ведутся от ТОНН ячеек (доли пересчитываются из тонн),
чтобы восстановленные ячейки без share_pct не давали NaN.
Диагноз, опирающийся на recovered_llm-ячейки, получает uncertain=true.
Контрольные суммы R5a сверяют только measured-значения.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .models import (RECOVERABLE, DataIssue, Diagnosis, LossCell,
                     MineralForm, TailingsReport)

# пороги правил (проценты)
R1_COARSE_LOSS_PCT = 25.0      # потери извлекаемого в крупных классах, % всех потерь
R1_CLOSED_SHARE_PCT = 40.0     # доля закрытого Pnt/Cp в потерях крупных классов
R2_FINES_LOSS_PCT = 20.0       # потери в классе -10, % всех потерь
R2_OPEN_SHARE_PCT = 40.0       # доля раскрытого Pnt/Cp в -10
R3_MID_OPEN_PCT = 15.0         # раскрытый в средних классах, % всех потерь
R5_SHARE_TOL = 0.5             # допуск сумм долей, п.п.
R5_TONNES_TOL = 0.01           # допуск сумм тонн, доля (1%)
R5_UNEXPECTED_SHARE = 50.0     # неожиданная форма забирает > 50% потерь класса
R5_FACT_CALC_TOL = 3.0         # расхождение итогов Факт/Расчёт, % (выше — data-quality warning; только ТОФ)

COARSE = ["+125", "-125+71"]
MIDDLE = ["-71+45", "-45+20", "-20+10"]
FINES = "-10"

OPEN = MineralForm.OPEN_PNT_CP.value
CLOSED = MineralForm.CLOSED_PNT_CP.value

NOT_RECOVERABLE_REASONS = {
    MineralForm.PYRRHOTITE_IMPURITY.value:
        "металл находится в кристаллической решётке пирротина — флотацией не извлекается, "
        "нужен металлургический передел",
    MineralForm.SILICATE.value:
        "силикатная форма/валлериит не флотируется стандартными сульфидными собирателями",
    MineralForm.PYRITE.value:
        "пирит — не носитель целевого металла; его отделяют, а не извлекают",
    MineralForm.MILLERITE.value:
        "миллерит — никелевый минерал, меди практически не содержит",
}


class DiagnosticsResult(BaseModel):
    diagnoses: list[Diagnosis] = Field(default_factory=list)          # R1-R3
    not_proposed: list[dict] = Field(default_factory=list)            # R4
    issues: list[DataIssue] = Field(default_factory=list)             # R5
    loss_map: dict = Field(default_factory=dict)                      # классы×формы, т (для UI)


def _t(c: LossCell) -> float:
    return c.tonnes if c.tonnes is not None else 0.0


def _cells(report: TailingsReport, el: str, classes: list[str] | None = None,
           form: str | None = None) -> list[LossCell]:
    out = []
    for c in report.cells:
        if c.element != el:
            continue
        if classes is not None and c.axes["size_class"] not in classes:
            continue
        if form is not None and c.axes["mineral_form"] != form:
            continue
        out.append(c)
    return out


def _uncertain(cells: list[LossCell]) -> bool:
    return any(c.provenance == "recovered_llm" for c in cells)


def _has_recovered(cells: list[LossCell]) -> bool:
    return any(c.provenance != "measured" for c in cells)


def run_diagnostics(report: TailingsReport, flowsheet: dict | None = None,
                    meta: dict | None = None) -> DiagnosticsResult:
    res = DiagnosticsResult()
    for el in ("Ni", "Cu"):
        total = report.losses_tonnes.get(el) or sum(_t(c) for c in _cells(report, el))
        if not total:
            continue
        _r1(report, el, total, res)
        _r2(report, el, total, res)
        _r3(report, el, total, res)
        _r4(report, el, res)
    _r5(report, res)
    res.issues.extend(_r5_fact_calc(meta))   # R5г: сверка итогов Факт/Расчёт (файл-уровень, ТОФ)
    res.loss_map = _loss_map(report)
    if flowsheet:
        _attach_flowsheet(res, flowsheet)
    return res


def _r5_fact_calc(meta: dict | None) -> list[DataIssue]:
    """R5г: сверка измеренного (Факт) и расчётного (Расчёт) итогов хвостов.

    Блок «Расчёт» есть только в ТОФ — в остальных файлах проверка молчит.
    Итог «Факт» — прямой замер металла в хвостах; «Расчёт» — сумма по формам
    минералогии. Их расхождение это не ошибка парсинга, а свойство источника
    (несходимость пробы/баланса) — но именно его жюри просит выносить явным
    флагом качества, поэтому поднимаем warning в семействе R5."""
    parse_meta = meta or {}
    fact = parse_meta.get("отвальные_Факт") or {}
    calc = parse_meta.get("отвальные_Расчёт") or {}
    if not fact or not calc:
        return []
    out: list[DataIssue] = []
    for el in ("Ni", "Cu"):
        f, c = fact.get(f"{el}_t"), calc.get(f"{el}_t")
        if not f or not c or f <= 0:
            continue
        diff = abs(f - c) / f * 100.0
        if diff > R5_FACT_CALC_TOL:
            f_s = f"{f:,.0f}".replace(",", " ")
            c_s = f"{c:,.0f}".replace(",", " ")
            out.append(DataIssue(
                severity="warning", rule="R5g", cell=f"итог/{el}",
                message=(f"Факт и Расчёт по {el} расходятся на {diff:.1f}% "
                         f"(замер {f_s} т vs расчёт {c_s} т) — свойство источника, "
                         f"проверьте пробу/баланс")))
    return out


def _attach_flowsheet(res: DiagnosticsResult, flowsheet: dict):
    """Привязка диагнозов к узлам оцифрованной схемы фабрики (раздел flowsheets)."""
    from .flowsheet import node_regime_line, nodes_for_rule
    for d in res.diagnoses:
        nodes = nodes_for_rule(d.rule_id, flowsheet)
        if not nodes:
            continue
        d.node_refs = [n["id"] for n in nodes[:4]]
        d.regime_line = node_regime_line(nodes[0])
        d.text += " " + d.regime_line + "."


def _r1(report: TailingsReport, el: str, total: float, res: DiagnosticsResult):
    """Недораскрытие: крупные классы + закрытый минерал -> недоизмельчение."""
    coarse_cells = _cells(report, el, COARSE)
    recov = sum(_t(c) for c in coarse_cells if c.recoverable)
    coarse_total = sum(_t(c) for c in coarse_cells)
    closed_cells = [c for c in coarse_cells if c.axes["mineral_form"] == CLOSED]
    closed_t = sum(_t(c) for c in closed_cells)
    recov_pct = recov / total * 100.0
    closed_share = closed_t / coarse_total * 100.0 if coarse_total else 0.0
    if recov_pct > R1_COARSE_LOSS_PCT and closed_share > R1_CLOSED_SHARE_PCT:
        for c in closed_cells:
            c.process_area = "измельчение/классификация"
        res.diagnoses.append(Diagnosis(
            rule_id="R1", zone="измельчение/классификация", element=el,
            title=f"Недоизмельчение: закрытый Pnt/Cp в крупных классах ({el})",
            text=(f"Потери извлекаемого {el} в крупных классах (+125, −125+71) — "
                  f"{recov:.1f} т ({recov_pct:.1f}% всех потерь {el}, порог {R1_COARSE_LOSS_PCT}%). "
                  f"Доля закрытого Pnt/Cp в потерях этих классов — {closed_share:.1f}% "
                  f"(порог {R1_CLOSED_SHARE_PCT}%). Минерал в сростках не раскрыт — пузырёк не видит "
                  f"его поверхность. Лечится в переделах измельчения/классификации: футеровка и шары "
                  f"мельниц, насадки гидроциклонов, тонкое грохочение, контроль гранулометрии."),
            inputs={"потери_извлекаемого_в_крупных_т": round(recov, 2),
                    "процент_всех_потерь": round(recov_pct, 2),
                    "порог_процента": R1_COARSE_LOSS_PCT,
                    "доля_закрытого_в_крупных_%": round(closed_share, 2),
                    "порог_доли_закрытого": R1_CLOSED_SHARE_PCT,
                    "закрытый_т": round(closed_t, 2)},
            cell_keys=[c.key for c in closed_cells],
            tonnes_recoverable=round(closed_t, 2),
            uncertain=_uncertain(closed_cells),
        ))


def _r2(report: TailingsReport, el: str, total: float, res: DiagnosticsResult):
    """Шламы: класс -10 + раскрытый минерал -> переизмельчение."""
    fines_cells = _cells(report, el, [FINES])
    fines_total = sum(_t(c) for c in fines_cells)
    open_cells = [c for c in fines_cells if c.axes["mineral_form"] == OPEN]
    open_t = sum(_t(c) for c in open_cells)
    fines_pct = fines_total / total * 100.0
    open_share = open_t / fines_total * 100.0 if fines_total else 0.0
    if fines_pct > R2_FINES_LOSS_PCT and open_share > R2_OPEN_SHARE_PCT:
        for c in open_cells:
            c.process_area = "флотация+классификация"
        res.diagnoses.append(Diagnosis(
            rule_id="R2", zone="флотация+классификация", element=el,
            title=f"Переизмельчение: раскрытый Pnt/Cp в шламах −10 мкм ({el})",
            text=(f"Класс −10 мкм несёт {fines_total:.1f} т ({fines_pct:.1f}% всех потерь {el}, "
                  f"порог {R2_FINES_LOSS_PCT}%), из них {open_share:.1f}% — уже РАСКРЫТЫЙ Pnt/Cp "
                  f"({open_t:.1f} т, порог {R2_OPEN_SHARE_PCT}%). Готовый минерал перемололи в шлам — "
                  f"пузырёк его не удерживает. Причина: переизмельчение. Лечится флотацией (время, "
                  f"фронт, плотность пульпы, реагенты, контактные чаны) и классификацией "
                  f"(не перемалывать готовое)."),
            inputs={"потери_в_-10_т": round(fines_total, 2),
                    "процент_всех_потерь": round(fines_pct, 2),
                    "порог_процента": R2_FINES_LOSS_PCT,
                    "доля_раскрытого_%": round(open_share, 2),
                    "порог_доли_раскрытого": R2_OPEN_SHARE_PCT,
                    "раскрытый_т": round(open_t, 2),
                    "причина": "переизмельчение"},
            cell_keys=[c.key for c in open_cells],
            tonnes_recoverable=round(open_t, 2),
            uncertain=_uncertain(open_cells),
        ))


def _r3(report: TailingsReport, el: str, total: float, res: DiagnosticsResult):
    """Недоработка флотации: раскрытый минерал в средних классах."""
    open_cells = [c for c in _cells(report, el, MIDDLE) if c.axes["mineral_form"] == OPEN]
    open_t = sum(_t(c) for c in open_cells)
    open_pct = open_t / total * 100.0
    if open_pct > R3_MID_OPEN_PCT:
        for c in open_cells:
            c.process_area = "флотация"
        res.diagnoses.append(Diagnosis(
            rule_id="R3", zone="флотация: время/реагенты/плотность", element=el,
            title=f"Недоработка флотации: раскрытый Pnt/Cp в средних классах ({el})",
            text=(f"Раскрытый Pnt/Cp в средних классах (−71+45, −45+20, −20+10) — {open_t:.1f} т "
                  f"({open_pct:.1f}% всех потерь {el}, порог {R3_MID_OPEN_PCT}%). Это рабочее окно "
                  f"флотации: минерал раскрыт и по крупности флотируем, но не извлечён — недоработка "
                  f"самой флотации. Проверить: время/фронт флотации, реагентный режим, плотность пульпы."),
            inputs={"раскрытый_в_средних_т": round(open_t, 2),
                    "процент_всех_потерь": round(open_pct, 2),
                    "порог": R3_MID_OPEN_PCT},
            cell_keys=[c.key for c in open_cells],
            tonnes_recoverable=round(open_t, 2),
            uncertain=_uncertain(open_cells),
        ))


def _r4(report: TailingsReport, el: str, res: DiagnosticsResult):
    """Потолок: неизвлекаемое по формам -> «Почему не предложено»."""
    forms = [f for f in NOT_RECOVERABLE_REASONS
             if MineralForm(f) not in RECOVERABLE[el]]
    for form in forms:
        cells = _cells(report, el, form=form)
        tonnes = sum(_t(c) for c in cells)
        if tonnes < 0.5:  # незначимо
            continue
        res.not_proposed.append({
            "rule_id": "R4", "element": el, "form": form,
            "tonnes": round(tonnes, 2),
            "reason": NOT_RECOVERABLE_REASONS[form],
            "uncertain": _uncertain(cells),
        })


def _r5(report: TailingsReport, res: DiagnosticsResult):
    """Аномалии данных. Сверяются ТОЛЬКО measured-значения."""
    # (а) контрольные суммы
    for el in ("Ni", "Cu"):
        losses = report.losses_tonnes.get(el)
        rows = report.size_classes
        if rows and all(sc.element_tonnes.get(el) is not None for sc in rows):
            # только если вся таблица measured (у SizeClassRow provenance нет — битые были None)
            s = sum(sc.element_tonnes[el] for sc in rows)
            if losses and abs(s - losses) / losses > R5_TONNES_TOL:
                res.issues.append(DataIssue(
                    severity="warning", rule="R5a", cell=f"таблица крупности/{el}",
                    message=f"Сумма тонн по классам ({s:.1f} т {el}) не бьётся с потерями в хвостах "
                            f"({losses:.1f} т) более чем на 1% — проверьте пробу/анализ"))
        shares = [sc.share_pct for sc in rows if sc.share_pct is not None]
        if len(shares) == len(rows) and rows:
            if abs(sum(shares) - 100.0) > R5_SHARE_TOL:
                res.issues.append(DataIssue(
                    severity="warning", rule="R5a", cell="таблица крупности",
                    message=f"Сумма долей классов {sum(shares):.2f}% ≠ 100% (допуск {R5_SHARE_TOL} п.п.)"))

    by_class: dict[tuple, list[LossCell]] = {}
    for c in report.cells:
        by_class.setdefault((c.axes["size_class"], c.element), []).append(c)
    size_by_label = {sc.label: sc for sc in report.size_classes}

    for (label, el), cells in by_class.items():
        sc = size_by_label.get(label)
        ct = sc.element_tonnes.get(el) if sc else None
        measured = [c for c in cells if c.provenance == "measured"]
        # суммы только для полностью измеренных блоков
        if len(measured) == len(cells) and ct:
            s_t = sum(_t(c) for c in measured)
            if abs(s_t - ct) / ct > R5_TONNES_TOL:
                res.issues.append(DataIssue(
                    severity="warning", rule="R5a", cell=f"{label}/{el}",
                    message=f"Минералогия класса {label}: сумма тонн форм {s_t:.1f} т {el} "
                            f"не бьётся с тоннами класса {ct:.1f} т (>1%) — проверьте пробу/анализ"))
            shares = [c.share_pct for c in measured if c.share_pct is not None]
            if len(shares) == len(measured) and abs(sum(shares) - 100.0) > R5_SHARE_TOL:
                res.issues.append(DataIssue(
                    severity="warning", rule="R5a", cell=f"{label}/{el}",
                    message=f"Минералогия класса {label} ({el}): сумма долей {sum(shares):.2f}% ≠ 100%"))

        # (б) битые/восстановленные ячейки
        broken = [c for c in cells if c.provenance != "measured" or c.tonnes is None]
        for c in broken:
            sev = "error" if c.tonnes is None else "info"
            res.issues.append(DataIssue(
                severity=sev, rule="R5b", cell=c.key,
                message=(f"Ячейка {c.key}: " + (
                    "не заполнена — исключена из диагностики" if c.tonnes is None else
                    "значение введено вручную" if c.provenance == "manual" else
                    "значение подставлено автоматически — проверьте и впишите вручную"))))

        # (в) неожиданная форма забирает >50% потерь класса
        if ct and ct > 0:
            for c in cells:
                form = c.axes["mineral_form"]
                if form in (OPEN, CLOSED):
                    continue  # ожидаемые носители
                share = _t(c) / ct * 100.0
                if share > R5_UNEXPECTED_SHARE:
                    res.issues.append(DataIssue(
                        severity="warning", rule="R5v", cell=c.key,
                        message=f"Аномалия: {share:.1f}% потерь {el} класса {label} — в форме "
                                f"«{form}» ({_t(c):.1f} т). Нетипично — проверьте пробу/анализ"))


def _loss_map(report: TailingsReport) -> dict:
    """Матрица классы×формы для тепловой карты UI."""
    out: dict = {"Ni": {}, "Cu": {}}
    for c in report.cells:
        el_map = out[c.element]
        row = el_map.setdefault(c.axes["size_class"], {})
        row[c.axes["mineral_form"]] = {
            "tonnes": _t(c), "share_pct": c.share_pct, "recoverable": c.recoverable,
            "provenance": c.provenance, "process_area": c.process_area,
        }
    return out
