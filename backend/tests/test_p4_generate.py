# -*- coding: utf-8 -*-
"""P4: генерация гипотез (мок LLM), расчёт эффекта, verify цитат."""
import json

import pytest

from backend.app.diagnostics import run_diagnostics
from backend.app.hypotheses.generate import build_queries, generate_hypotheses
from backend.app.hypotheses.verify import verify_citations
from backend.app.kb.index import KBIndex
from backend.app.kb.textnorm import chunk_pages
from backend.app.parser.recover import recover
from backend.app.parser.xlsx import parse_workbook
from backend.tests.conftest import find_case_file, requires_data


@pytest.fixture(scope="module")
def example2_diag():
    res = parse_workbook(find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$"))
    r = res.reports[0]
    recover(r, llm=None)
    return r, run_diagnostics(r)


@pytest.fixture()
def kb(tmp_path):
    idx = KBIndex(root=tmp_path, use_dense=False)
    pages = [(42, "Для повышения извлечения никеля применяют доизмельчение сростков "
                  "пентландита: раскрытие минерала растёт с уменьшением крупности. "
                  "Футеровка мельниц и насадки гидроциклонов определяют гранулометрию слива. " * 3),
             (43, "Время флотации и фронт контрольных операций определяют извлечение "
                  "тонких раскрытых частиц; плотность пульпы влияет на кинетику. " * 3)]
    idx.add_document("doc1", "Глембоцкий.pdf", pages, chunk_pages(pages, target=300))
    return idx


class FakeLLM:
    """LLM, отвечающая заранее заданным JSON."""
    enabled = True

    def __init__(self, payload):
        self.payload = payload

    def chat(self, messages, **kw):
        return {"content": json.dumps(self.payload, ensure_ascii=False), "usage": {}}


@requires_data
def test_mock_generation_offline(example2_diag, kb):
    """Без ключа: гипотезы из фикстуры, цитаты заземлены на локальный индекс."""
    report, diag = example2_diag

    class NoLLM:
        enabled = False

    hyps = generate_hypotheses(report, diag, kb_index=kb, llm=NoLLM())
    assert len(hyps) >= 6
    for h in hyps:
        assert h.title and h.mechanism
        assert h.effect.tonnes_max > 0
        assert 0 < h.effect.tonnes_expected < h.effect.tonnes_max
        assert h.effect.money_usd > 0
        assert h.verification_plan, "план проверки обязателен"
        assert all(s.success_criterion for s in h.verification_plan)
        # только извлекаемые целевые ячейки
        assert h.target_cells
    # мок-цитаты заземлены и верифицируются
    stats = verify_citations(hyps, kb)
    assert stats["validity"] == 1.0


@requires_data
def test_llm_generation_with_fake(example2_diag, kb):
    report, diag = example2_diag
    payload = {"hypotheses": [{
        "title": "Тестовая гипотеза про насадки",
        "process_area": "классификация",
        "hypothesis_type": "classification",
        "element": "Ni",
        "diagnosis_rule": "R1",
        "target_cells": [{"key": "+125/Закрытый Pnt/Cp/Ni"}],
        "mechanism": "Меньше насадка — больше циркуляция.",
        "citations": [{"chunk_id": "doc1:0",
                       "quote": "доизмельчение сростков пентландита: раскрытие минерала растёт"}],
        "equipment": ["ГЦ-660", "Неведомый сепаратор X99"],
        "risks": ["забивка"],
        "feasibility": {"capex": "low"},
        "verification_plan": [{"n": 1, "action": "ОПИ", "duration": "4 нед",
                               "success_criterion": "-20% +71 в сливе",
                               "fail_criterion": "рост песков"}],
        "effect_assumptions": "тест"
    }]}
    hyps = generate_hypotheses(report, diag, kb_index=kb, llm=FakeLLM(payload))
    assert len(hyps) == 1
    h = hyps[0]
    # эффект: 845.73 т × capture_rate(classification)=0.25
    assert h.effect.tonnes_max == pytest.approx(845.7, abs=0.1)
    assert h.effect.tonnes_expected == pytest.approx(845.73 * 0.25, abs=0.5)
    assert h.effect.money_usd == pytest.approx(h.effect.tonnes_expected * 16500, rel=0.01)
    # неизвестное оборудование -> present_on_plant=false + capex high
    unknown = [e for e in h.equipment if not e.present_on_plant]
    assert unknown and h.feasibility["capex"] == "high"
    known = next(e for e in h.equipment if e.name == "ГЦ-660")
    assert known.positions == ["4-2", "5-3", "5-5"]
    # цитата верифицируется fuzzy-матчем
    stats = verify_citations(hyps, kb)
    assert h.rationale[0].verified is True
    assert h.rationale[0].page == 42
    assert stats["validity"] == 1.0


@requires_data
def test_nonrecoverable_hypotheses_dropped(example2_diag, kb):
    """Гипотезы по неизвлекаемым формам запрещены."""
    report, diag = example2_diag
    payload = {"hypotheses": [{
        "title": "Довыделение пирротина",
        "process_area": "флотация", "hypothesis_type": "other", "element": "Ni",
        "diagnosis_rule": "",
        "target_cells": [{"key": "+125/Примесь в пирротине/Ni"},
                         {"key": "-10/Силикатная форма/Ni"}],
        "mechanism": "х", "citations": [], "equipment": [], "risks": [],
        "feasibility": {}, "verification_plan": [], "effect_assumptions": ""
    }]}
    hyps = generate_hypotheses(report, diag, kb_index=kb, llm=FakeLLM(payload))
    assert hyps == []


@requires_data
def test_stoplist_and_excluded_areas(example2_diag, kb):
    report, diag = example2_diag

    class NoLLM:
        enabled = False

    all_h = generate_hypotheses(report, diag, kb_index=kb, llm=NoLLM())
    filtered = generate_hypotheses(report, diag, kb_index=kb, llm=NoLLM(),
                                   stoplist=["футеровки"], excluded_areas=["флотация"])
    assert len(filtered) < len(all_h)
    assert not [h for h in filtered if "футеровки" in h.title.lower()]
    assert not [h for h in filtered if h.process_area == "флотация"]


@requires_data
def test_build_queries(example2_diag):
    _, diag = example2_diag
    qs = build_queries(diag)
    assert any("сростк" in q for q in qs)      # R1
    assert any("шлам" in q for q in qs)        # R2
    assert len(qs) == len(set(qs))


def test_verify_rejects_fabricated_quote(tmp_path):
    from backend.app.models import Citation, Hypothesis
    idx = KBIndex(root=tmp_path, use_dense=False)
    pages = [(1, "Реальный текст книги про флотацию сульфидов и измельчение руды. " * 5)]
    idx.add_document("d1", "Книга.pdf", pages, chunk_pages(pages, target=200))
    cid = idx.chunks[0]["chunk_id"]
    h = Hypothesis(id="x", title="т", process_area="флотация", rationale=[
        Citation(quote="Реальный текст книги про флотацию сульфидов", chunk_id=cid),
        Citation(quote="Выдуманная модель квантовой сепарации бозонов", chunk_id=cid),
        Citation(quote="цитата в никуда", chunk_id="d1:999"),
    ])
    stats = verify_citations([h], idx)
    assert h.rationale[0].verified is True
    assert h.rationale[1].verified is False
    assert h.rationale[2].verified is False
    assert stats == {"total": 3, "verified": 1, "validity": round(1 / 3, 3)}
