# -*- coding: utf-8 -*-
"""Качество генерации: best-of-N дедуп, few-shot чужих фабрик, пере-заземление
цитат, кап с разнообразием направлений, добор непокрытых направлений."""
import json

import pytest

from backend.app.hypotheses.generate import (_cap_diverse, _dedup_hypotheses,
                                             _reground_citations)
from backend.app.kb.index import KBIndex
from backend.app.kb.textnorm import chunk_pages
from backend.app.models import Citation, Effect, Hypothesis, Step
from backend.app.parser.docx import cross_plant_examples, expert_titles_for_plant
from backend.tests.conftest import requires_data


def _h(hid, title, n_cit=0, n_steps=0, tonnes=100.0, element="Ni", htype="other"):
    return Hypothesis(
        id=hid, title=title, process_area="измельчение", element=element,
        hypothesis_type=htype,
        effect=Effect(tonnes_max=tonnes, tonnes_expected=20, money_usd=1000),
        rationale=[Citation(quote=f"ц{i}", chunk_id=f"c{i}") for i in range(n_cit)],
        verification_plan=[Step(n=i + 1, action="а") for i in range(n_steps)],
        mechanism="м" * 50)


def test_dedup_keeps_richer_card():
    a = _h("a", "Замена песковых насадок гидроциклонов ГЦ-660", n_cit=2, n_steps=3)
    b = _h("b", "Замена насадок песковых на гидроциклонах ГЦ-660", n_cit=0, n_steps=1)
    c = _h("c", "Тонкое грохочение после второй стадии", n_cit=1, n_steps=2)
    kept = _dedup_hypotheses([b, a, c])
    ids = {h.id for h in kept}
    assert ids == {"a", "c"}, "дубль насадок схлопнут, остался богатый вариант"


def test_dedup_same_title_different_element_kept():
    a = _h("a", "Доизмельчение промпродукта", element="Ni")
    b = _h("b", "Доизмельчение промпродукта", element="Cu")
    assert len(_dedup_hypotheses([a, b])) == 2


def test_dedup_same_type_paraphrase_collapsed():
    """Реальные пары из прогона eval: перефразированный один приём внутри
    одного hypothesis_type — дубль; разные приёмы одного типа — не дубль."""
    a = _h("a", "Внедрение тонкого грохочения Derrick (71 мкм) на сливе ГЦ-660 (II стадия)",
           n_cit=2, htype="screening")
    b = _h("b", "Внедрение тонкого грохочения после II стадии измельчения (сетка 100 мкм)",
           htype="screening")
    c = _h("c", "Замена спиральных классификаторов I стадии на гидроциклоны ГЦ-660",
           htype="classification")
    d = _h("d", "Уменьшение диаметра песковой насадки гидроциклонов ГЦ-660 с 80 мм до 65 мм",
           htype="classification")
    kept = {h.id for h in _dedup_hypotheses([a, b, c, d])}
    assert kept == {"a", "c", "d"}, "грохочение схлопнуто, классификация — два разных приёма"


def test_cap_diverse_keeps_unique_directions():
    """Близнецы одного направления не вытесняют уникальные: не более 2 на
    (тип, элемент), бедная карточка уникального типа выживает при капе."""
    rich_twins = [_h(f"t{i}", f"Футеровка вариант {i}", n_cit=3, n_steps=3,
                     htype="liner") for i in range(4)]
    poor_unique = _h("u", "Автоматизация подачи воды в мельницы", htype="automation")
    kept = _cap_diverse(rich_twins + [poor_unique], cap=3)
    ids = {h.id for h in kept}
    assert "u" in ids, "уникальное направление не вытеснено близнецами"
    assert sum(1 for h in kept if h.hypothesis_type == "liner") <= 2


class _FakeLLM:
    """Первый вызов — основной сэмпл, второй — добор непокрытых направлений."""
    enabled = True

    def __init__(self):
        self.calls = []

    def chat(self, messages, strong=False, json_mode=False):
        self.calls.append(messages[-1]["content"])
        base = {"process_area": "измельчение", "element": "Ni",
                "diagnosis_rule": "R1", "mechanism": "Физика процесса. " * 3}
        if len(self.calls) == 1:
            hyps = [dict(base, title="Замена футеровки мельниц МШЦ 4,5×6,0",
                         hypothesis_type="liner")]
        else:
            hyps = [dict(base, title="Автоматизация подачи воды в мельницы",
                         hypothesis_type="automation")]
        return {"content": json.dumps({"hypotheses": hyps}, ensure_ascii=False)}


@requires_data
def test_repair_pass_adds_missing_directions(tmp_path):
    """Добор: после основной генерации идёт второй вызов с уже сгенерированными
    заголовками, его гипотезы попадают в выдачу."""
    from backend.app.diagnostics import run_diagnostics
    from backend.app.hypotheses.generate import generate_hypotheses
    from backend.app.parser.xlsx import parse_workbook
    from backend.tests.conftest import find_case_file

    report = parse_workbook(find_case_file(r"Пример 2/Хвосты.*\.xlsx$")).reports[0]
    diag = run_diagnostics(report)
    fake = _FakeLLM()
    idx = KBIndex(root=tmp_path, use_dense=False)
    hyps = generate_hypotheses(report, diag, kb_index=idx, llm=fake, n_samples=1)

    assert len(fake.calls) == 2, "основной сэмпл + добирающий вызов"
    assert "ДОБОР НЕПОКРЫТЫХ НАПРАВЛЕНИЙ" in fake.calls[1]
    assert "Замена футеровки мельниц МШЦ 4,5×6,0" in fake.calls[1], \
        "в добор передаются уже сгенерированные заголовки"
    titles = {h.title for h in hyps}
    assert "Автоматизация подачи воды в мельницы" in titles, "гипотеза добора в выдаче"
    assert len(hyps) == 2


@requires_data
def test_cross_plant_examples_exclude_current():
    ex_nof = cross_plant_examples("НОФ (вкрапленные)")
    assert ex_nof, "образцы других фабрик должны найтись"
    own = set(expert_titles_for_plant("НОФ (вкрапленные)")) | \
        set(expert_titles_for_plant("НОФ (медистые)"))
    assert not (set(ex_nof) & own), "эталоны своей фабрики (обеих веток НОФ) — лик"
    ex_tof = cross_plant_examples("ТОФ")
    own_tof = set(expert_titles_for_plant("ТОФ"))
    assert not (set(ex_tof) & own_tof)


def test_reground_citations(tmp_path):
    idx = KBIndex(root=tmp_path, use_dense=False)
    pages = [(5, "Уменьшение диаметра песковой насадки гидроциклона повышает "
                 "циркулирующую нагрузку и снижает крупность слива. " * 4)]
    idx.add_document("d1", "Справочник.pdf", pages, chunk_pages(pages, target=250))

    ok_cit = Citation(quote="Уменьшение диаметра песковой насадки гидроциклона повышает",
                      chunk_id=idx.chunks[0]["chunk_id"])
    fake_cit = Citation(quote="Выдуманная фраза о квантовой флотации", chunk_id="нет:1")
    h1 = _h("h1", "Замена насадок гидроциклонов", n_cit=0)
    h1.rationale = [ok_cit, fake_cit]
    h2 = _h("h2", "Снижение крупности слива гидроциклонов", n_cit=0)  # вовсе без цитат

    _reground_citations([h1, h2], idx)

    # валидная цитата сохранена, фейковая заменена реальным чанком
    assert h1.rationale[0].quote.startswith("Уменьшение диаметра")
    assert all(idx.get_chunk(c.chunk_id) for c in h1.rationale)
    # безцитатная гипотеза получила дословную цитату со страницей
    assert h2.rationale and h2.rationale[0].page == 5
    from backend.app.hypotheses.verify import verify_citations
    stats = verify_citations([h1, h2], idx)
    assert stats["validity"] == 1.0, "после пере-заземления все цитаты верифицируемы"
