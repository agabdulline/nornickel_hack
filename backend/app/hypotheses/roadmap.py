# -*- coding: utf-8 -*-
"""Дорожная карта проверки гипотез (раздел 8.2 CLAUDE.md).

Уровень гипотезы: verification_plan -> стадии lab -> pilot (ОПИ) -> rollout
с воротами (числовой критерий из плана). Дешёвые обратимые вмешательства
пропускают лабу (skip_lab в профиле).

Уровень портфеля: детерминированный планировщик.
- Конфликт ресурсов: две гипотезы с одним occupied_resource не пересекаются —
  вторая сдвигается (иначе эффекты не разделить), приоритет по score.
- Ёмкость лаборатории: max 2 одновременные лабораторные программы.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from ..domain import pack, verification_profile
from ..models import Hypothesis, RoadmapItem

log = logging.getLogger("roadmap")

STAGE_LABELS = {"lab": "лабораторные испытания", "pilot": "ОПИ", "rollout": "тираж"}


def _resource_label(h: Hypothesis, profile: dict) -> str:
    base = profile.get("occupied_resource", "лаборатория")
    for eq in h.equipment:
        if eq.present_on_plant and eq.positions:
            return f"{base} {eq.positions[0]}"
    return base


def _gate(h: Hypothesis, stage_idx: int) -> str:
    plan = h.verification_plan
    if stage_idx < len(plan) and plan[stage_idx].success_criterion:
        return plan[stage_idx].success_criterion
    return "числовой критерий из плана проверки"


def _overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start < b_end and b_start < a_end


def _earliest_slot(busy: list[tuple[date, date]], t: date, dur: timedelta,
                   capacity: int = 1) -> date:
    """Ранний start >= t, чтобы на всём интервале занятость < capacity."""
    candidates = sorted({t} | {e for _s, e in busy if e > t})
    for cand in candidates:
        end = cand + dur
        concurrent = sum(1 for s, e in busy if _overlaps(cand, end, s, e))
        if concurrent < capacity:
            return cand
    return max(e for _s, e in busy) if busy else t  # теоретически недостижимо


def build_roadmap(hypotheses: list[Hypothesis], start: date | None = None,
                  lab_capacity: int | None = None) -> list[RoadmapItem]:
    """Планирует принятые гипотезы. Вход уже отфильтрован по status=accepted."""
    cfg = pack().get("roadmap", {})
    lab_capacity = lab_capacity or int(cfg.get("lab_capacity", 2))
    t0 = start or date.today()

    items: list[RoadmapItem] = []
    lab_busy: list[tuple[date, date]] = []
    res_busy: dict[str, list[tuple[date, date]]] = {}

    for h in sorted(hypotheses, key=lambda x: -x.score):
        profile = verification_profile(h.hypothesis_type)
        resource = _resource_label(h, profile)
        t = t0
        prev_id: str | None = None
        stage_idx = 0

        stages: list[tuple[str, timedelta, str, int]] = []
        if not profile.get("skip_lab", False):
            stages.append(("lab", timedelta(weeks=int(profile.get("lab_weeks", 3))),
                           "лаборатория", lab_capacity))
        stages.append(("pilot", timedelta(weeks=int(profile.get("pilot_weeks", 6))),
                       resource, 1))
        stages.append(("rollout", timedelta(weeks=int(profile.get("rollout_weeks", 3))),
                       resource, 1))

        for stage, dur, res, cap in stages:
            busy = lab_busy if res == "лаборатория" else res_busy.setdefault(res, [])
            slot = _earliest_slot(busy, t, dur, capacity=cap)
            shifted = slot > t
            end = slot + dur
            busy.append((slot, end))
            item = RoadmapItem(
                id=f"{h.id}:{stage}",
                hypothesis_id=h.id,
                hypothesis_title=h.title,
                stage=stage,
                start=slot.isoformat(),
                end=end.isoformat(),
                resource=res,
                gate_criterion=_gate(h, stage_idx),
                depends_on=[prev_id] if prev_id else [],
                shifted_reason=f"ждёт {res}" if shifted and res != "лаборатория" else (
                    "ждёт лабораторию" if shifted else None),
            )
            items.append(item)
            prev_id = item.id
            t = end
            stage_idx += 1
    return items


def validate_schedule(items: list[RoadmapItem], lab_capacity: int | None = None) -> list[str]:
    """Конфликты расписания: пересечения ресурсов и нарушение порядка стадий."""
    cfg = pack().get("roadmap", {})
    lab_capacity = lab_capacity or int(cfg.get("lab_capacity", 2))
    errors: list[str] = []

    by_res: dict[str, list[RoadmapItem]] = {}
    for it in items:
        by_res.setdefault(it.resource or "", []).append(it)

    for res, lst in by_res.items():
        cap = lab_capacity if res == "лаборатория" else 1
        for i, a in enumerate(lst):
            a_s, a_e = date.fromisoformat(a.start), date.fromisoformat(a.end)
            concurrent = [b for b in lst if b is not a and _overlaps(
                a_s, a_e, date.fromisoformat(b.start), date.fromisoformat(b.end))]
            if len(concurrent) + 1 > cap:
                other = concurrent[0]
                errors.append(f"конфликт ресурса «{res}»: {a.id} пересекается с {other.id}")

    by_id = {it.id: it for it in items}
    for it in items:
        for dep in it.depends_on:
            d = by_id.get(dep)
            if d and date.fromisoformat(it.start) < date.fromisoformat(d.end):
                errors.append(f"стадия {it.id} начинается раньше завершения {dep}")
    # дубли не нужны
    seen = set()
    out = []
    for e in errors:
        key = "".join(sorted(e))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def move_item(items: list[RoadmapItem], item_id: str, new_start: date) -> tuple[bool, str]:
    """Ручной сдвиг стадии (PATCH). Сдвигает стадию и все последующие стадии
    той же гипотезы; при конфликте — (False, причина), список не меняется."""
    by_id = {it.id: it for it in items}
    target = by_id.get(item_id)
    if not target:
        return False, "стадия не найдена"

    old = [(it.start, it.end) for it in items]
    delta = new_start - date.fromisoformat(target.start)

    chain = [it for it in items if it.hypothesis_id == target.hypothesis_id]
    chain.sort(key=lambda it: it.start)
    started = False
    for it in chain:
        if it.id == item_id:
            started = True
        if started:
            it.start = (date.fromisoformat(it.start) + delta).isoformat()
            it.end = (date.fromisoformat(it.end) + delta).isoformat()

    errors = validate_schedule(items)
    if errors:
        for it, (s, e) in zip(items, old):
            it.start, it.end = s, e
        return False, "; ".join(errors[:3])
    return True, ""
