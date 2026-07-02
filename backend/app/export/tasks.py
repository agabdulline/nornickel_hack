# -*- coding: utf-8 -*-
"""Экспорт задач (CSV) и полного проекта (JSON)."""
from __future__ import annotations

import csv
import io

from ..diagnostics import DiagnosticsResult
from ..models import Hypothesis, Project, RoadmapItem, TailingsReport

STAGE_LABELS = {"lab": "лаборатория", "pilot": "ОПИ", "rollout": "тираж"}


def to_tasks_csv(hypotheses: list[Hypothesis],
                 roadmap: list[RoadmapItem] | None = None) -> str:
    """Стадии дорожной карты; без карты — шаги планов проверки."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["hypothesis", "status", "stage", "start", "end", "resource",
                "criterion", "effect_tonnes", "effect_usd"])
    by_id = {h.id: h for h in hypotheses}
    if roadmap:
        for it in roadmap:
            h = by_id.get(it.hypothesis_id)
            w.writerow([it.hypothesis_title, h.status if h else "",
                        STAGE_LABELS.get(it.stage, it.stage), it.start, it.end,
                        it.resource or "", it.gate_criterion or "",
                        h.effect.tonnes_expected if h else "",
                        h.effect.money_usd if h else ""])
    else:
        for h in hypotheses:
            for s in h.verification_plan:
                w.writerow([h.title, h.status, f"шаг {s.n}: {s.action}", "", "",
                            s.resources, s.success_criterion,
                            h.effect.tonnes_expected, h.effect.money_usd])
    return "﻿" + buf.getvalue()  # BOM: Excel читает кириллицу


def to_project_json(project: Project, report: TailingsReport | None,
                    diag: DiagnosticsResult | None, hypotheses: list[Hypothesis],
                    roadmap: list[RoadmapItem] | None = None) -> dict:
    return {
        "project": project.model_dump(),
        "report": report.model_dump() if report else None,
        "diagnostics": diag.model_dump() if diag else None,
        "hypotheses": [h.model_dump() for h in hypotheses],
        "roadmap": [r.model_dump() for r in (roadmap or [])],
    }
