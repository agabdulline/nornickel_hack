# -*- coding: utf-8 -*-
"""Оцифрованные схемы фабрик (flowsheets) и их подключение к пайплайну."""
import pytest

from backend.app.diagnostics import run_diagnostics
from backend.app.domain import pack
from backend.app.flowsheet import (detect_factory, get_flowsheet, nodes_for_rule,
                                   summarize_for_prompt, zero_reagent_hints)
from backend.app.parser.recover import recover
from backend.app.parser.xlsx import parse_workbook
from backend.tests.conftest import find_case_file, requires_data


def test_flowsheets_yaml_loads():
    fs = pack().get("flowsheets")
    assert fs and "НОФ" in fs and "ТОФ" in fs
    for factory, sheet in fs.items():
        ids = [n["id"] for n in sheet["nodes"]]
        assert len(ids) == len(set(ids)), f"{factory}: дубликаты id узлов"
        for s in sheet["streams"]:
            assert s["kind"] in ("feed", "concentrate", "tails", "sands", "overflow", "middlings")
        # обязательные по ТЗ: хвостовые потоки оцифрованы
        assert [s for s in sheet["streams"] if s["kind"] == "tails"], \
            f"{factory}: нет хвостовых потоков"


def test_tof_has_dmdk_zero_flotation_node():
    """Кейс подсказки генератору: ДМДК предусмотрен режимом ТОФ, но расход 0."""
    tof = get_flowsheet("ТОФ")
    dmdk_zero = [n for n in tof["nodes"]
                 if n["type"] == "flotation" and (n.get("reagents") or {}).get("ДМДК") == 0]
    assert dmdk_zero, "у ТОФ должен быть flotation-узел с reagents['ДМДК'] == 0"


def test_detect_factory_all_4_xlsx():
    cases = {
        "Хвосты КГМК.xlsx": "КГМК",
        "Хвосты НОФ Вкр.xlsx": "НОФ",
        "Хвосты НОФ мед.xlsx": "НОФ",
        "Хвосты ТОФ_2.xlsx": "ТОФ",
    }
    for name, expected in cases.items():
        assert detect_factory(name) == expected, name
    assert detect_factory("что-то неизвестное.xlsx") is None


@requires_data
def test_example4_diagnoses_have_node_refs():
    res = parse_workbook(find_case_file(r"Пример 4/Хвосты.*\.xlsx$"))
    r = res.reports[0]
    recover(r, llm=None)
    diag = run_diagnostics(r, flowsheet=get_flowsheet("ТОФ"))
    assert diag.diagnoses
    for d in diag.diagnoses:
        assert d.node_refs, f"{d.rule_id}: нет привязки к узлам ТОФ"
        assert all(ref.startswith("tof_") for ref in d.node_refs)
        assert d.regime_line and d.regime_line.startswith("по регламенту:")
        assert "по регламенту:" in d.text


@requires_data
def test_example2_diagnoses_reference_nof_nodes():
    res = parse_workbook(find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$"))
    r = res.reports[0]
    recover(r, llm=None)
    diag = run_diagnostics(r, flowsheet=get_flowsheet("НОФ"))
    r1 = next(d for d in diag.diagnoses if d.rule_id == "R1")
    assert all(ref.startswith("nof_") for ref in r1.node_refs)
    # R1 -> узлы grinding/classification/crushing
    nof = get_flowsheet("НОФ")
    by_id = {n["id"]: n for n in nof["nodes"]}
    assert all(by_id[ref]["type"] in ("grinding", "classification", "crushing")
               for ref in r1.node_refs)
    # R2 -> флотация, контрольные в приоритете невозможен (нет «контрольной» у НОФ),
    # но тип узлов обязан быть flotation/classification
    r2 = next(d for d in diag.diagnoses if d.rule_id == "R2")
    assert all(by_id[ref]["type"] in ("flotation", "classification") for ref in r2.node_refs)


def test_nodes_for_rule_control_priority():
    tof = get_flowsheet("ТОФ")
    nodes = nodes_for_rule("R2", tof)
    assert nodes, "R2 должен находить flotation-узлы"
    # у ТОФ «2 основная Cu-флотация (контрольная)» должна встать первой
    assert "контрольн" in nodes[0]["name"].lower()


def test_summarize_for_prompt():
    s = summarize_for_prompt("ТОФ")
    assert s["фабрика"] == "ТОФ"
    assert any("ДМДК" in str(n.get("реагенты_г_т", {})) for n in s["узлы"])
    assert s["хвостовые_потоки"], "хвостовые потоки — мишени диагнозов"
    assert any(t.get("eps_ni") == 28.0 for t in s["хвостовые_потоки"])
    assert summarize_for_prompt("КГМК") is None  # схемы нет — мягкая деградация
    assert summarize_for_prompt(None) is None


def test_zero_reagent_hints_with_kb():
    class FakeKB:
        def search(self, q, k=2):
            return [{"chunk_id": "m1:0", "source": "Манцевич-2008.pdf", "page": 4,
                     "text": "Наибольший эффект подавления пирротина получен с реагентом ДМДК"}]

    hints = zero_reagent_hints("ТОФ", kb_index=FakeKB())
    assert hints, "ДМДК=0 + источник в KB -> подсказка"
    assert hints[0]["реагент"] == "ДМДК"
    assert hints[0]["источники"][0]["source"] == "Манцевич-2008.pdf"
    # без KB-подтверждения подсказки нет
    class EmptyKB:
        def search(self, q, k=2):
            return []
    assert zero_reagent_hints("ТОФ", kb_index=EmptyKB()) == []
    assert zero_reagent_hints("КГМК", kb_index=FakeKB()) == []