# -*- coding: utf-8 -*-
"""P2: правила диагностики на Примере 2 (обязательные проверки из правила 3 CLAUDE.md)."""
import pytest

from backend.app.diagnostics import run_diagnostics
from backend.app.parser.recover import recover
from backend.app.parser.xlsx import parse_workbook
from backend.tests.conftest import find_case_file, requires_data

TOL = 0.01


@pytest.fixture(scope="module")
def example2():
    res = parse_workbook(find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$"))
    r = res.reports[0]
    recover(r, llm=None)
    return run_diagnostics(r), r


@requires_data
def test_r1_fires_on_example2(example2):
    diag, report = example2
    r1 = [d for d in diag.diagnoses if d.rule_id == "R1" and d.element == "Ni"]
    assert len(r1) == 1
    d = r1[0]
    assert d.zone == "измельчение/классификация"
    assert "+125/Закрытый Pnt/Cp/Ni" in d.cell_keys
    # закрытый Pnt/Cp в +125 = 845.73 т — входит в целевые ячейки
    cell = report.cell("+125", "Закрытый Pnt/Cp", "Ni")
    assert cell.tonnes == pytest.approx(845.73, abs=TOL)
    assert d.inputs["закрытый_т"] == pytest.approx(845.73 + 260.64, abs=0.1)
    assert d.uncertain is False
    assert d.inputs["порог_процента"] == 25.0  # интерпретируемость: порог хранится


@requires_data
def test_r2_fires_on_example2(example2):
    diag, report = example2
    r2 = [d for d in diag.diagnoses if d.rule_id == "R2" and d.element == "Ni"]
    assert len(r2) == 1
    d = r2[0]
    assert "переизмельчение" in d.text or d.inputs.get("причина") == "переизмельчение"
    assert "-10/Раскрытый Pnt/Cp/Ni" in d.cell_keys
    assert d.tonnes_recoverable == pytest.approx(836.87, abs=TOL)


@requires_data
def test_r5_catches_cu_pyrite_anomaly(example2):
    diag, _ = example2
    hits = [i for i in diag.issues
            if i.rule == "R5v" and "Пирит" in (i.cell or "") and "-10" in (i.cell or "")
            and "Cu" in (i.cell or "")]
    assert hits, "аномалия: 56.39% потерь Cu класса -10 в пирите — должна ловиться R5в"
    assert "56.4" in hits[0].message


@requires_data
def test_r4_why_not_proposed(example2):
    diag, report = example2
    ni_silicate = [x for x in diag.not_proposed
                   if x["element"] == "Ni" and x["form"] == "Силикатная форма"]
    assert len(ni_silicate) == 1
    expected = sum(c.tonnes for c in report.cells
                   if c.element == "Ni" and c.axes["mineral_form"] == "Силикатная форма")
    assert ni_silicate[0]["tonnes"] == pytest.approx(expected, abs=0.1)
    assert "не флотируется" in ni_silicate[0]["reason"]
    forms_ni = {x["form"] for x in diag.not_proposed if x["element"] == "Ni"}
    assert "Примесь в пирротине" in forms_ni
    assert "Миллерит" not in forms_ni  # для Ni миллерит извлекаем


@requires_data
def test_r3_does_not_fire_on_example2(example2):
    diag, _ = example2
    assert not [d for d in diag.diagnoses if d.rule_id == "R3"], \
        "раскрытый в средних классах Примера 2 ~4.5% < 15% — R3 не должен срабатывать"


@requires_data
def test_example1_diagnostics_no_nan():
    """После восстановления Примера 1 диагностика работает без NaN."""
    res = parse_workbook(find_case_file(r"Пример 1/Хвосты.*\.xlsx$"))
    r = res.reports[0]
    recover(r, llm=None)
    diag = run_diagnostics(r)
    assert diag.diagnoses, "на КГМК должны быть диагнозы"
    for d in diag.diagnoses:
        assert d.tonnes_recoverable == d.tonnes_recoverable  # not NaN
        assert all(isinstance(v, (int, float, str)) for v in d.inputs.values())
    # R5b отмечает восстановленные ячейки
    assert [i for i in diag.issues if i.rule == "R5b"]


@requires_data
def test_r5_fact_calc_divergence_tof():
    """ТОФ: итоги Факт (замер) и Расчёт (по минералогии) расходятся — R5г
    выносит это явным флагом качества «проверьте пробу/баланс»."""
    res = parse_workbook(find_case_file(r"Пример 4/Хвосты.*\.xlsx$"))
    diag = run_diagnostics(res.reports[0], meta=res.meta)
    r5g = [i for i in diag.issues if i.rule == "R5g"]
    assert r5g, "ТОФ: расхождение итогов Факт/Расчёт должно ловиться R5г"
    ni = [i for i in r5g if "Ni" in (i.cell or "")]
    assert ni, "должен быть флаг по Ni"
    assert "проверьте пробу/баланс" in ni[0].message
    assert "на 5.6%" in ni[0].message   # Факт 23756.4 vs Расчёт 22414.7
    assert ni[0].severity == "warning"


@requires_data
def test_r5_fact_calc_silent_on_nof():
    """Пример 2 (НОФ) — блока «Расчёт» нет: R5г молчит даже с переданным meta
    (нет ложных срабатываний вне ТОФ)."""
    res = parse_workbook(find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$"))
    diag = run_diagnostics(res.reports[0], meta=res.meta)
    assert not [i for i in diag.issues if i.rule == "R5g"]


@requires_data
def test_loss_map_structure(example2):
    diag, _ = example2
    assert "+125" in diag.loss_map["Ni"]
    cell = diag.loss_map["Ni"]["+125"]["Закрытый Pnt/Cp"]
    assert cell["tonnes"] == pytest.approx(845.73, abs=TOL)
    assert cell["recoverable"] is True
    assert diag.loss_map["Ni"]["+125"]["Силикатная форма"]["recoverable"] is False
