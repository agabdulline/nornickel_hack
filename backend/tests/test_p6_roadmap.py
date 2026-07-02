# -*- coding: utf-8 -*-
"""P6: планировщик Ганта (обязательный тест из 8.2): конфликт ресурса
разводится последовательно по score, независимый передел параллелен,
PATCH со сдвигом в конфликт -> 409/отказ."""
from datetime import date, timedelta

import pytest

from backend.app.hypotheses.roadmap import build_roadmap, move_item, validate_schedule
from backend.app.models import Effect, EquipmentRef, Hypothesis, Step


def _h(hid, title, htype, score, positions=None):
    return Hypothesis(
        id=hid, title=title, process_area="измельчение", hypothesis_type=htype,
        score=score, status="accepted",
        effect=Effect(tonnes_max=100, tonnes_expected=30, money_usd=1000),
        equipment=[EquipmentRef(name="МШЦ 4,5×6,0", positions=positions or [],
                                present_on_plant=True)] if positions is not None else [],
        verification_plan=[
            Step(n=1, action="лаба", duration="2 нед", success_criterion="+5 п.п. раскрытия"),
            Step(n=2, action="ОПИ", duration="6 нед", success_criterion="−0.005 п.п. Ni в хвостах"),
            Step(n=3, action="тираж", duration="3 нед", success_criterion="эффект на балансе"),
        ])


@pytest.fixture()
def three_hypotheses():
    # две конфликтующие по мельнице 5-3 (liner) и одна флотационная (параллельная)
    h1 = _h("hyp-a", "Футеровка А", "liner", score=0.9, positions=["5-3"])
    h2 = _h("hyp-b", "Футеровка Б (шары)", "liner", score=0.7, positions=["5-3"])
    h3 = _h("hyp-c", "Фронт флотации", "flotation_time", score=0.8)
    return [h1, h2, h3]


def test_conflict_resolved_sequentially_by_score(three_hypotheses):
    items = build_roadmap(three_hypotheses, start=date(2026, 7, 6))
    assert validate_schedule(items) == []

    def stage(hid, st):
        return next(i for i in items if i.hypothesis_id == hid and i.stage == st)

    a_pilot, b_pilot = stage("hyp-a", "pilot"), stage("hyp-b", "pilot")
    assert a_pilot.resource == b_pilot.resource == "мельница 5-3"
    # приоритет по score: A раньше, B ждёт ресурс
    assert date.fromisoformat(b_pilot.start) >= date.fromisoformat(a_pilot.end) or \
           date.fromisoformat(b_pilot.start) >= date.fromisoformat(stage("hyp-a", "rollout").end)
    shifted = [i for i in items if i.hypothesis_id == "hyp-b" and i.shifted_reason]
    assert any("мельница 5-3" in i.shifted_reason for i in shifted), \
        "у B должен быть сдвиг с причиной «ждёт мельницу 5-3»"

    # флотационная гипотеза идёт параллельно мельничным (ресурсы независимы)
    c_pilot = stage("hyp-c", "pilot")
    assert c_pilot.resource == "секция флотации"
    a_s, a_e = date.fromisoformat(a_pilot.start), date.fromisoformat(a_pilot.end)
    c_s, c_e = date.fromisoformat(c_pilot.start), date.fromisoformat(c_pilot.end)
    assert c_s < a_e and a_s < c_e, "независимые переделы должны пересекаться по времени"


def test_stages_and_gates(three_hypotheses):
    items = build_roadmap(three_hypotheses, start=date(2026, 7, 6))
    a = [i for i in items if i.hypothesis_id == "hyp-a"]
    assert [i.stage for i in a] == ["lab", "pilot", "rollout"]
    assert a[1].depends_on == [a[0].id]
    assert a[0].gate_criterion == "+5 п.п. раскрытия"
    assert a[1].gate_criterion == "−0.005 п.п. Ni в хвостах"
    # ёмкость лаборатории = 2: первые две лабы (по score: A и C) параллельны,
    # третья (B) ждёт освобождения слота
    labs = sorted([i for i in items if i.stage == "lab"],
                  key=lambda i: (i.start, i.hypothesis_id))
    assert len(labs) == 3
    starts = {i.hypothesis_id: date.fromisoformat(i.start) for i in labs}
    assert starts["hyp-a"] == starts["hyp-c"] == date(2026, 7, 6)
    assert starts["hyp-b"] > date(2026, 7, 6)


def test_move_into_conflict_rejected(three_hypotheses):
    items = build_roadmap(three_hypotheses, start=date(2026, 7, 6))
    a_pilot = next(i for i in items if i.hypothesis_id == "hyp-a" and i.stage == "pilot")
    b_pilot = next(i for i in items if i.hypothesis_id == "hyp-b" and i.stage == "pilot")
    old_b = (b_pilot.start, b_pilot.end)

    ok, reason = move_item(items, b_pilot.id, date.fromisoformat(a_pilot.start))
    assert ok is False
    assert "конфликт" in reason or "мельница" in reason
    assert (b_pilot.start, b_pilot.end) == old_b, "неудачный сдвиг не должен менять расписание"


def test_move_valid_shift(three_hypotheses):
    items = build_roadmap(three_hypotheses, start=date(2026, 7, 6))
    c_pilot = next(i for i in items if i.hypothesis_id == "hyp-c" and i.stage == "pilot")
    new_start = date.fromisoformat(c_pilot.start) + timedelta(weeks=30)
    ok, reason = move_item(items, c_pilot.id, new_start)
    assert ok is True, reason
    assert c_pilot.start == new_start.isoformat()
    # rollout сдвинулся вслед
    c_roll = next(i for i in items if i.hypothesis_id == "hyp-c" and i.stage == "rollout")
    assert date.fromisoformat(c_roll.start) >= new_start


def test_skip_lab_profile():
    # classification: skip_lab=true -> стадии без лабы
    h = _h("hyp-d", "Насадки ГЦ", "classification", score=0.5)
    items = build_roadmap([h], start=date(2026, 7, 6))
    assert [i.stage for i in items] == ["pilot", "rollout"]
