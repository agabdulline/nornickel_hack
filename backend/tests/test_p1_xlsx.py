# -*- coding: utf-8 -*-
"""P1: парсинг всех 4 xlsx, контрольные числа раздела 3 CLAUDE.md (допуск 0.01)."""
import pytest

from backend.app.parser.labels import normalize_form_label, normalize_size_label
from backend.app.parser.xlsx import parse_workbook
from backend.tests.conftest import find_case_file, requires_data

TOL = 0.01


def test_normalize_size_labels():
    assert normalize_size_label("+125") == "+125"
    assert normalize_size_label("+125 мкм") == "+125"
    assert normalize_size_label("-125 +71") == "-125+71"
    assert normalize_size_label(" -125 +71 мкм") == "-125+71"
    assert normalize_size_label("+71") == "-125+71"      # метка «гуляет» в Примере 1 и ТОФ
    assert normalize_size_label(" -20 + 10") == "-20+10"  # ведущий пробел
    assert normalize_size_label("-71 + 45") == "-71+45"
    assert normalize_size_label("-45 +20") == "-45+20"
    assert normalize_size_label("-10") == "-10"
    assert normalize_size_label("Итого (проверка)") is None


def test_normalize_form_labels():
    assert normalize_form_label("Пирит/Другие Элемент 29 сульфиды") == "Пирит"
    assert normalize_form_label("Пирит") == "Пирит"
    assert normalize_form_label("Силикатная форма/Валлериит") == "Силикатная форма"
    assert normalize_form_label("Раскрытый Pnt/Cp") == "Раскрытый Pnt/Cp"
    assert normalize_form_label("Закрытый Pnt/Cp") == "Закрытый Pnt/Cp"
    assert normalize_form_label("Примесь в пирротине ") == "Примесь в пирротине"
    assert normalize_form_label("Миллерит") == "Миллерит"
    assert normalize_form_label("Потери (расписать)") == "__потери_расписать__"
    assert normalize_form_label("Свободный слот") == "__свободный_слот__"


@requires_data
def test_example2_control_numbers():
    path = find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$")
    res = parse_workbook(path)
    assert res.plant == "НОФ (вкрапленные)"
    assert len(res.reports) == 1
    r = res.reports[0]
    assert r.tail_type == "породные"

    assert r.tails_tonnes == pytest.approx(4376437.99, abs=TOL)
    assert r.grade["Ni"] == pytest.approx(0.100367, abs=1e-4)
    assert r.losses_tonnes["Ni"] == pytest.approx(4392.49, abs=TOL)
    assert r.losses_tonnes["Cu"] == pytest.approx(1506.28, abs=TOL)

    sc = {s.label: s for s in r.size_classes}
    assert set(sc) == {"+125", "-125+71", "-71+45", "-45+20", "-20+10", "-10"}
    assert sc["+125"].share_pct == pytest.approx(35.765, abs=TOL)
    assert sc["+125"].element_share_pct["Ni"] == pytest.approx(33.496, abs=TOL)
    assert sc["+125"].element_tonnes["Ni"] == pytest.approx(1471.30, abs=TOL)
    assert sc["-10"].element_share_pct["Ni"] == pytest.approx(26.675, abs=TOL)
    assert sc["-10"].element_tonnes["Ni"] == pytest.approx(1171.70, abs=TOL)

    closed = r.cell("+125", "Закрытый Pnt/Cp", "Ni")
    assert closed is not None and closed.tonnes == pytest.approx(845.73, abs=TOL)
    assert closed.recoverable is True
    silicate = r.cell("+125", "Силикатная форма", "Ni")
    assert silicate.tonnes == pytest.approx(544.50, abs=TOL)
    assert silicate.recoverable is False

    assert r.recoverable_pct["Ni"] == pytest.approx(60.062, abs=TOL)
    assert r.recoverable_total["Ni"] == pytest.approx(2638.24, abs=TOL)
    assert r.recoverable_pct["Cu"] == pytest.approx(75.417, abs=TOL)

    # эталонно чистый файл: ни одной error-issue и ни одной битой ячейки
    assert not [i for i in res.all_issues if i.severity == "error"]
    assert all(c.tonnes is not None and c.provenance == "measured" for c in r.cells)
    # 6 классов × 6 форм × 2 элемента
    assert len(r.cells) == 72


@requires_data
def test_example1_broken_refs_do_not_crash():
    path = find_case_file(r"Пример 1/Хвосты.*\.xlsx$")
    res = parse_workbook(path)
    assert res.plant == "КГМК"
    assert len(res.reports) == 1
    r = res.reports[0]
    errors = [i for i in r.issues if i.severity == "error"]
    assert errors, "в Примере 1 есть #REF! — парсер обязан вернуть issues"
    assert any("+125" in (i.cell or "") for i in errors)
    # битые ячейки -> None, но парсер не упал и остальные блоки целы
    broken = [c for c in r.cells if c.tonnes is None or c.share_pct is None]
    assert broken
    ok = r.cell("-125+71", "Закрытый Pnt/Cp", "Ni")   # метка «+71» нормализована
    assert ok.tonnes == pytest.approx(2088.28, abs=TOL)


@requires_data
def test_example3_parses():
    path = find_case_file(r"Пример 3/Хвосты.*\.xlsx$")
    res = parse_workbook(path)
    r = res.reports[0]
    assert r.tails_tonnes == pytest.approx(3749560, abs=10)
    assert r.losses_tonnes["Ni"] == pytest.approx(5721.45, abs=TOL)
    assert len(r.cells) == 72


@requires_data
def test_example4_tof_both_tail_types():
    path = find_case_file(r"Пример 4/Хвосты.*\.xlsx$")
    res = parse_workbook(path)
    types = [r.tail_type for r in res.reports]
    assert "породные" in types and "пирротиновые" in types
    rock = next(r for r in res.reports if r.tail_type == "породные")
    pyrr = next(r for r in res.reports if r.tail_type == "пирротиновые")
    assert rock.losses_tonnes["Ni"] == pytest.approx(4676.92, abs=TOL)
    assert pyrr.losses_tonnes["Ni"] == pytest.approx(17739.5, abs=0.1)
    # у пирротиновых нет +125: классов 5
    assert len(pyrr.size_classes) == 5
    assert len(rock.size_classes) == 6
    # Факт/Расчёт распознаны
    assert "отвальные_Факт" in res.meta and "отвальные_Расчёт" in res.meta
    assert res.meta["отвальные_Факт"]["Ni_t"] == pytest.approx(23756.4, abs=0.1)
