# -*- coding: utf-8 -*-
"""P1: восстановление битых данных (7.1). Ярус 1 на Примере 1, ноль ложных
срабатываний на Примере 2, синтетика на инварианты, мок LLM для яруса 2."""
import pytest

from backend.app.models import LossCell, SizeClassRow, TailingsReport
from backend.app.parser.recover import recover, recover_llm, recover_math, unresolved_cells
from backend.app.parser.xlsx import parse_workbook
from backend.tests.conftest import find_case_file, requires_data

TOL = 0.01


def _cell(size, form, el, tonnes, share, recoverable=True):
    return LossCell(axes={"size_class": size, "mineral_form": form}, element=el,
                    tonnes=tonnes, share_pct=share, recoverable=recoverable)


def _synthetic_report():
    return TailingsReport(
        plant="Тест", losses_tonnes={"Ni": 100.0, "Cu": 0.0},
        size_classes=[SizeClassRow(label="+125", share_pct=100.0,
                                   element_share_pct={"Ni": 100.0},
                                   element_tonnes={"Ni": 100.0})],
        cells=[
            _cell("+125", "Раскрытый Pnt/Cp", "Ni", 60.0, 60.0),
            _cell("+125", "Закрытый Pnt/Cp", "Ni", None, None),      # битая
            _cell("+125", "Силикатная форма", "Ni", 10.0, 10.0, recoverable=False),
        ],
    )


def test_tier1_i1_i2_single_unknown():
    r = _synthetic_report()
    n = recover_math(r)
    assert n >= 2
    broken = r.cell("+125", "Закрытый Pnt/Cp", "Ni")
    assert broken.tonnes == pytest.approx(30.0, abs=1e-6)     # I1: 100 - 60 - 10
    assert broken.share_pct == pytest.approx(30.0, abs=1e-6)  # I2: 100 - 60 - 10
    assert broken.provenance == "recovered_math"
    assert "I1" in broken.recovery_note or "I2" in broken.recovery_note
    assert unresolved_cells(r) == []


def test_tier1_i3_from_share():
    r = _synthetic_report()
    c = r.cell("+125", "Закрытый Pnt/Cp", "Ni")
    c.share_pct = 25.0  # доля известна, тонны битые
    recover_math(r)
    assert c.tonnes == pytest.approx(25.0, abs=1e-6)  # I3: 25% × 100 т
    assert c.provenance == "recovered_math"


def test_tier2_llm_mock(monkeypatch):
    r = _synthetic_report()
    # ярус 1 не сможет: два неизвестных
    r.cells[0].tonnes = None
    r.cells[0].share_pct = None

    class FakeLLM:
        enabled = True
        def chat(self, messages, **kw):
            return {"content": '{"cells": [{"size_class": "+125", "mineral_form": "Раскрытый Pnt/Cp",'
                               '"element": "Ni", "share_pct": 55, "confidence": 0.7, "explanation": "по соседним классам"},'
                               '{"size_class": "+125", "mineral_form": "Закрытый Pnt/Cp",'
                               '"element": "Ni", "share_pct": 35, "confidence": 0.6, "explanation": "типовой диапазон"}]}',
                    "usage": {}}

    stats = recover(r, llm=FakeLLM())
    c0 = r.cell("+125", "Раскрытый Pnt/Cp", "Ni")
    assert c0.provenance == "recovered_llm"
    assert c0.tonnes == pytest.approx(55.0, abs=1e-6)
    assert c0.confidence == pytest.approx(0.7)
    assert stats["unresolved"] == 0


def test_tier2_no_llm_graceful():
    r = _synthetic_report()
    r.cells[0].tonnes = None
    r.cells[0].share_pct = None

    class DeadLLM:
        enabled = False
        def chat(self, messages, **kw):
            from backend.app.llm import LLMUnavailable
            raise LLMUnavailable("нет ключа")

    n = recover_llm(r, llm=DeadLLM())
    assert n == 0
    assert any("не восстановлены" in i.message for i in r.issues)


@requires_data
def test_example1_tier1_closes_all_refs():
    """#REF! Примера 1: класс +125 пуст (0 т) -> ярус 1 закрывает всё нулями."""
    res = parse_workbook(find_case_file(r"Пример 1/Хвосты.*\.xlsx$"))
    r = res.reports[0]
    stats = recover(r, llm=None)  # llm не понадобится
    assert stats["recovered_math"] > 0
    # ни одно #REF! не доходит до диагностики как NaN
    assert all(c.tonnes is not None for c in r.cells)
    assert stats["unresolved"] == 0
    recovered = [c for c in r.cells if c.provenance != "measured"]
    assert recovered
    assert all(c.provenance == "recovered_math" for c in recovered)
    assert all(abs(c.tonnes) < 1e-6 for c in recovered), "класс +125 пуст — нули"


@requires_data
def test_example2_zero_false_positives():
    """На целом Примере 2 решатель не «восстанавливает» ничего."""
    res = parse_workbook(find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$"))
    r = res.reports[0]
    stats = recover(r, llm=None)
    assert stats == {"recovered_math": 0, "recovered_llm": 0, "unresolved": 0}
    assert all(c.provenance == "measured" for c in r.cells)


@requires_data
def test_example4_no_recovery_needed():
    res = parse_workbook(find_case_file(r"Пример 4/Хвосты.*\.xlsx$"))
    for r in res.reports:
        stats = recover(r, llm=None)
        assert stats["unresolved"] == 0
