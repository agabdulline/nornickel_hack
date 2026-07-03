# -*- coding: utf-8 -*-
"""Дополнительное покрытие: пропагация восстановления, детали ТОФ, границы Ганта."""
from datetime import date, timedelta

import pytest

from backend.app.hypotheses.roadmap import build_roadmap, move_item
from backend.app.models import Effect, Hypothesis, LossCell, SizeClassRow, Step, TailingsReport
from backend.app.parser.recover import recover_math
from backend.app.parser.xlsx import parse_workbook
from backend.tests.conftest import find_case_file, requires_data


def _cell(size, form, el, tonnes, share, recoverable=True):
    return LossCell(axes={"size_class": size, "mineral_form": form}, element=el,
                    tonnes=tonnes, share_pct=share, recoverable=recoverable)


def test_recover_chain_propagation():
    """Двухшаговая цепочка: I5 восстанавливает тонны класса, затем I3 — ячейку."""
    r = TailingsReport(
        plant="Т", losses_tonnes={"Ni": 200.0},
        size_classes=[
            SizeClassRow(label="+125", share_pct=50.0,
                         element_share_pct={"Ni": 75.0}, element_tonnes={"Ni": None}),  # битые
            SizeClassRow(label="-10", share_pct=50.0,
                         element_share_pct={"Ni": 25.0}, element_tonnes={"Ni": 50.0}),
        ],
        cells=[
            _cell("+125", "Раскрытый Pnt/Cp", "Ni", None, 40.0),   # ждёт тонны класса
            _cell("+125", "Закрытый Pnt/Cp", "Ni", None, 60.0),
            _cell("-10", "Раскрытый Pnt/Cp", "Ni", 50.0, 100.0),
        ])
    n = recover_math(r)
    assert n >= 3
    # I5: 75% × 200 = 150 т; затем I3: 40% × 150 и 60% × 150
    assert r.size_classes[0].element_tonnes["Ni"] == pytest.approx(150.0)
    assert r.cell("+125", "Раскрытый Pnt/Cp", "Ni").tonnes == pytest.approx(60.0)
    assert r.cell("+125", "Закрытый Pnt/Cp", "Ni").tonnes == pytest.approx(90.0)
    assert all(c.provenance == "recovered_math" for c in r.cells if c.axes["size_class"] == "+125")


def test_recover_clamps_negative_residual():
    """I1 с отрицательным остатком (несходимость) не даёт отрицательных тонн."""
    r = TailingsReport(
        plant="Т", losses_tonnes={"Ni": 100.0},
        size_classes=[SizeClassRow(label="+125", share_pct=100.0,
                                   element_share_pct={"Ni": 100.0},
                                   element_tonnes={"Ni": 100.0})],
        cells=[
            _cell("+125", "Раскрытый Pnt/Cp", "Ni", 80.0, 80.0),
            _cell("+125", "Закрытый Pnt/Cp", "Ni", 30.0, 30.0),
            _cell("+125", "Пирит", "Ni", None, None, recoverable=False),
        ])
    recover_math(r)
    c = r.cell("+125", "Пирит", "Ni")
    assert c.tonnes == 0.0  # max(100 - 110, 0)


@requires_data
def test_tof_pyrrhotite_mineralogy_normalized():
    """ТОФ пирротиновые: заголовок блока «+71 мкм» слился с классом «-125+71»."""
    res = parse_workbook(find_case_file(r"Пример 4/Хвосты.*\.xlsx$"))
    pyrr = next(r for r in res.reports if r.tail_type == "пирротиновые")
    c = pyrr.cell("-125+71", "Закрытый Pnt/Cp", "Ni")
    assert c is not None and c.tonnes == pytest.approx(309.978, abs=0.01)
    # контрольные строки блока сохранены для R5
    assert "-125+71" in pyrr.control_totals["class_totals"]
    # у ТОФ «Пирит» и «Миллерит» отдельными строками -> обе формы есть
    forms = {x.axes["mineral_form"] for x in pyrr.cells}
    assert {"Пирит", "Миллерит"} <= forms


@requires_data
def test_tof_general_section_grand_check():
    res = parse_workbook(find_case_file(r"Пример 4/Хвосты.*\.xlsx$"))
    common = next(r for r in res.reports if "общие" in r.tail_type)
    assert common.losses_tonnes["Ni"] == pytest.approx(22414.7, abs=0.1)
    assert common.recoverable_total["Ni"] == pytest.approx(8351.24, abs=0.01)


def _h(hid, htype, score):
    return Hypothesis(id=hid, title=hid, process_area="x", hypothesis_type=htype, score=score,
                      status="accepted", effect=Effect(money_usd=1),
                      verification_plan=[Step(n=1, action="а", success_criterion="к")])


def test_move_before_dependency_rejected():
    """Сдвиг pilot раньше конца lab -> отказ (нарушение depends_on)."""
    items = build_roadmap([_h("hyp-x", "liner", 0.9)], start=date(2026, 7, 6))
    lab = next(i for i in items if i.stage == "lab")
    pilot = next(i for i in items if i.stage == "pilot")
    ok, reason = move_item(items, pilot.id, date.fromisoformat(lab.start))
    assert ok is False
    assert "раньше завершения" in reason


def test_move_item_unknown_id():
    items = build_roadmap([_h("hyp-x", "liner", 0.9)], start=date(2026, 7, 6))
    ok, reason = move_item(items, "нет-такой:lab", date(2026, 8, 1))
    assert ok is False and "не найдена" in reason


def test_roadmap_deterministic():
    """Планировщик детерминирован: два вызова дают одинаковое расписание."""
    hyps = [_h("a", "liner", 0.9), _h("b", "liner", 0.7), _h("c", "reagent", 0.8)]
    i1 = build_roadmap(hyps, start=date(2026, 7, 6))
    i2 = build_roadmap([h.model_copy(deep=True) for h in hyps], start=date(2026, 7, 6))
    assert [(x.id, x.start, x.end, x.resource) for x in i1] == \
           [(x.id, x.start, x.end, x.resource) for x in i2]
