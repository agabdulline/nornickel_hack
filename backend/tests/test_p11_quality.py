# -*- coding: utf-8 -*-
"""Качество генерации: best-of-N дедуп, few-shot чужих фабрик, пере-заземление цитат."""
import pytest

from backend.app.hypotheses.generate import _dedup_hypotheses, _reground_citations
from backend.app.kb.index import KBIndex
from backend.app.kb.textnorm import chunk_pages
from backend.app.models import Citation, Effect, Hypothesis, Step
from backend.app.parser.docx import cross_plant_examples, expert_titles_for_plant
from backend.tests.conftest import requires_data


def _h(hid, title, n_cit=0, n_steps=0, tonnes=100.0, element="Ni"):
    return Hypothesis(
        id=hid, title=title, process_area="измельчение", element=element,
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
