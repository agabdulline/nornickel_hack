# -*- coding: utf-8 -*-
"""P5: ранжирование (веса, novelty, штраф за цитаты) и SQLite-store."""
import pytest

from backend.app.hypotheses.rank import rank_hypotheses
from backend.app.models import Citation, Effect, Hypothesis
from backend.app.store import Store


def _h(hid, money, capex="low", risks=None, title="Гипотеза", verified=True):
    return Hypothesis(
        id=hid, title=title, process_area="флотация",
        effect=Effect(tonnes_max=100, tonnes_expected=20, money_usd=money),
        feasibility={"capex": capex, "complexity": "low"},
        risks=risks or [],
        rationale=[Citation(quote="ц", chunk_id="x", verified=verified)],
    )


def test_rank_orders_by_money_when_rest_equal():
    hyps = [_h("a", 1_000_000), _h("b", 5_000_000), _h("c", 3_000_000)]
    ranked = rank_hypotheses(hyps, use_embeddings=False)
    assert [h.id for h in ranked] == ["b", "c", "a"]
    assert ranked[0].score > ranked[-1].score


def test_rank_capex_and_weights():
    cheap = _h("cheap", 1_000_000, capex="low")
    rich_expensive = _h("rich", 1_200_000, capex="high", risks=["р1", "р2", "р3", "р4"])
    ranked = rank_hypotheses([cheap, rich_expensive],
                             weights={"money": 0.1, "capex": 0.5, "risk": 0.25, "novelty": 0.15},
                             use_embeddings=False)
    assert ranked[0].id == "cheap"


def test_rank_unverified_penalty():
    ok = _h("ok", 1_000_000, verified=True)
    bad = _h("bad", 1_000_000, verified=False)
    ranked = rank_hypotheses([ok, bad], use_embeddings=False)
    assert ranked[0].id == "ok"
    assert ranked[1].score == pytest.approx(ranked[0].score * 0.75, rel=1e-6)


def test_rank_novelty_prior_match_fuzzy():
    novel = _h("novel", 1_000_000, title="Магнитная сепарация промпродукта")
    known = _h("known", 1_000_000, title="Изменение геометрии футеровки мельниц 3,3 м")
    priors = ["Изменение геометрии футеровки мельниц 3,3м и 6м."]
    ranked = rank_hypotheses([novel, known], prior_titles=priors, use_embeddings=False)
    assert ranked[0].id == "novel"
    assert known.novelty["score"] == 0.2
    assert known.novelty["prior_matches"] == priors
    assert novel.novelty["score"] == 1.0


def test_store_roundtrip(tmp_path):
    s = Store(tmp_path / "t.db")
    p = s.create_project("НОФ", goal="снизить потери Ni")
    assert s.get_project(p.id).plant == "НОФ"

    hyps = [_h("h1", 500), _h("h2", 900)]
    rank_hypotheses(hyps, use_embeddings=False)
    s.save_hypotheses(p.id, hyps)
    got = s.get_hypotheses(p.id)
    assert [h.id for h in got] == ["h2", "h1"]  # по score

    h, pid = s.get_hypothesis("h1")
    assert pid == p.id
    h.status = "accepted"
    s.update_hypothesis(h)
    assert s.get_hypotheses(p.id, statuses=["accepted"])[0].id == "h1"

    s.add_feedback("h1", p.id, "accept", "")
    s.add_feedback("h2", p.id, "reject", "не трогать реагентику")
    fb = s.get_feedback(p.id)
    assert len(fb) == 2 and fb[1]["reason"] == "не трогать реагентику"

    p.stoplist.append("реагентика")
    s.update_project(p)
    assert s.get_project(p.id).stoplist == ["реагентика"]

    # replace=True не трогает принятые
    s.save_hypotheses(p.id, [_h("h3", 100)], replace=True)
    left = {h.id for h in s.get_hypotheses(p.id)}
    assert left == {"h1", "h3"}  # h2 (proposed) заменена, h1 (accepted) жива


def test_delete_project_cascades_but_keeps_master_data(tmp_path):
    from backend.app.models import TailingsReport
    s = Store(tmp_path / "t.db")

    # мастер-данные линии (общие, не проект-скоуп) — должны пережить удаление
    line = s.create_line("НОФ · вкрапленные руды")
    s.add_equipment(line.id, "Гидроциклон ГЦ-660", position="5-3")

    p = s.create_project(line.id, goal="снизить потери")
    s.save_reports(p.id, "х.xlsx", [TailingsReport(plant="НОФ")], {"parse_meta": {}})
    hyps = [_h("h1", 500)]
    rank_hypotheses(hyps, use_embeddings=False)
    s.save_hypotheses(p.id, hyps)
    s.add_feedback("h1", p.id, "accept", "")
    s.save_roadmap(p.id, [{"id": "it1", "hypothesis_id": "h1", "stage": "lab"}])

    assert s.delete_project(p.id) is True
    # всё проект-скоуп вычищено
    assert s.get_project(p.id) is None
    assert s.get_reports(p.id) is None
    assert s.get_hypotheses(p.id) == []
    assert s.get_feedback(p.id) == []
    assert s.get_roadmap(p.id) == []
    assert s.get_hypothesis("h1") is None
    # мастер-данные линии не тронуты
    assert s.get_line(line.id) is not None
    assert len(s.list_equipment(line.id)) == 1
    # повторное удаление / несуществующий id -> False
    assert s.delete_project(p.id) is False
    assert s.delete_project("нет-такого") is False
