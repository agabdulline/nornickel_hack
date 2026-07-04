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


def find_resource_conflicts(items: list[RoadmapItem], lab_capacity: int | None = None,
                            ) -> list[tuple[RoadmapItem, RoadmapItem, str]]:
    """Пары стадий, РЕАЛЬНО превышающих ёмкость общего ресурса (для форс-сдвига и
    подсветки). Превышение = в какой-то момент одновременно активны > cap стадий.
    Пик занятости всегда приходится на старт какой-то стадии, поэтому проверяем
    ровно эти моменты (иначе попарный счёт ложно ловит длинную стадию, накрывающую
    две непересекающиеся короткие на ресурсе ёмкостью > 1)."""
    cfg = pack().get("roadmap", {})
    lab_capacity = lab_capacity or int(cfg.get("lab_capacity", 2))
    by_res: dict[str, list[RoadmapItem]] = {}
    for it in items:
        by_res.setdefault(it.resource or "", []).append(it)
    pairs: list[tuple[RoadmapItem, RoadmapItem, str]] = []
    seen: set[tuple[str, str]] = set()
    for res, lst in by_res.items():
        cap = lab_capacity if res == "лаборатория" else 1
        over_ids: set[str] = set()
        for x in lst:
            xs = date.fromisoformat(x.start)
            active = [y for y in lst
                      if date.fromisoformat(y.start) <= xs < date.fromisoformat(y.end)]
            if len(active) > cap:
                over_ids.update(y.id for y in active)
        over = [x for x in lst if x.id in over_ids]
        for i, a in enumerate(over):
            a_s, a_e = date.fromisoformat(a.start), date.fromisoformat(a.end)
            for b in over[i + 1:]:
                if _overlaps(a_s, a_e, date.fromisoformat(b.start), date.fromisoformat(b.end)):
                    key = tuple(sorted((a.id, b.id)))
                    if key not in seen:
                        seen.add(key)
                        pairs.append((a, b, res))
    return pairs


def find_order_violations(items: list[RoadmapItem]) -> list[str]:
    """Стадия начинается раньше завершения предшественника (жёсткое ограничение)."""
    by_id = {it.id: it for it in items}
    errs: list[str] = []
    for it in items:
        for dep in it.depends_on:
            d = by_id.get(dep)
            if d and date.fromisoformat(it.start) < date.fromisoformat(d.end):
                errs.append(f"«{STAGE_LABELS.get(it.stage, it.stage)}» начинается раньше "
                            f"завершения «{STAGE_LABELS.get(d.stage, d.stage)}»")
    return errs


def validate_schedule(items: list[RoadmapItem], lab_capacity: int | None = None) -> list[str]:
    """Все нарушения расписания (ресурсы + порядок стадий) — для тестов/диагностики."""
    errs = [f"конфликт ресурса «{res}»: {a.id} пересекается с {b.id}"
            for a, b, res in find_resource_conflicts(items, lab_capacity)]
    errs += find_order_violations(items)
    return errs


def _it_label(it: RoadmapItem) -> str:
    return f"{it.hypothesis_title} · {STAGE_LABELS.get(it.stage, it.stage)}"


def _apply_conflict_flags(items: list[RoadmapItem],
                          pairs: list[tuple[RoadmapItem, RoadmapItem, str]]) -> None:
    """Проставляет manual_conflict/conflict_with по актуальным пересечениям ресурсов."""
    for it in items:
        it.manual_conflict = False
        it.conflict_with = []
    for a, b, _res in pairs:
        for x, y in ((a, b), (b, a)):
            x.manual_conflict = True
            if _it_label(y) not in x.conflict_with:
                x.conflict_with.append(_it_label(y))


def move_item(items: list[RoadmapItem], item_id: str, new_start: date,
              force: bool = False) -> tuple[bool, str, str]:
    """Ручной сдвиг стадии (PATCH): двигает стадию и все последующие стадии той же
    гипотезы. Возвращает (ok, kind, message), kind ∈ ""|"resource"|"order"|"past"|"notfound".

    Ресурсный конфликт можно ПРИНЯТЬ (force=True): сдвиг применяется, а пересекающиеся
    стадии помечаются manual_conflict. Нарушение порядка стадий и планирование раньше
    сегодня — жёсткие, force не помогает. Ранее принятые конфликты не блокируют новые
    (в т.ч. непересекающиеся) сдвиги."""
    by_id = {it.id: it for it in items}
    target = by_id.get(item_id)
    if not target:
        return False, "notfound", "стадия не найдена"

    prior = {tuple(sorted((a.id, b.id))) for a, b, _ in find_resource_conflicts(items)}
    old = [(it.start, it.end) for it in items]
    delta = new_start - date.fromisoformat(target.start)

    chain = sorted((it for it in items if it.hypothesis_id == target.hypothesis_id),
                   key=lambda it: it.start)
    started, moved = False, []
    for it in chain:
        if it.id == item_id:
            started = True
        if started:
            it.start = (date.fromisoformat(it.start) + delta).isoformat()
            it.end = (date.fromisoformat(it.end) + delta).isoformat()
            moved.append(it)

    def revert() -> None:
        for it, (s, e) in zip(items, old):
            it.start, it.end = s, e

    if any(date.fromisoformat(it.start) < date.today() for it in moved):
        revert()
        return False, "past", "нельзя планировать стадию раньше сегодня"

    order = find_order_violations(items)
    if order:
        revert()
        return False, "order", order[0]

    pairs = find_resource_conflicts(items)
    introduced = [p for p in pairs if tuple(sorted((p[0].id, p[1].id))) not in prior]
    if introduced and not force:
        a, b, res = introduced[0]
        revert()
        return False, "resource", f"конфликт ресурса «{res}»: «{_it_label(a)}» пересекается с «{_it_label(b)}»"

    _apply_conflict_flags(items, pairs)
    return True, ("resource" if pairs else ""), ""
