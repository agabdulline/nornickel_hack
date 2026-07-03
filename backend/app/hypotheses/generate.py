# -*- coding: utf-8 -*-
"""Генерация гипотез (раздел 8 CLAUDE.md).

Пайплайн: диагнозы R1–R3 + топ-K чанков KB + онтология оборудования +
ограничения/стоп-лист/история -> один вызов STRONG-модели (JSON) ->
валидация -> расчёт эффекта детерминированным кодом.

Без LLM-ключа возвращается мок из tests/fixtures/generate_mock.json,
цитаты мока заземляются на реальные чанки локального индекса.
"""
from __future__ import annotations

import json
import logging
import time
import uuid

from ..config import METAL_PRICE_USD, ROOT
from ..diagnostics import DiagnosticsResult
from ..domain import capture_rate, equipment_list, pack
from ..llm import LLMClient, LLMUnavailable, client as default_client, extract_json
from ..kb.index import KBIndex, default_index
from ..kb.search import search_multi
from ..models import (Citation, Effect, EquipmentRef, Hypothesis, Step,
                      TailingsReport)
from .prompts import KB_QUERIES, SYSTEM_GENERATE, build_user_prompt

log = logging.getLogger("hypotheses.generate")

MOCK_FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "generate_mock.json"


def build_queries(diag: DiagnosticsResult) -> list[str]:
    queries: list[str] = []
    for d in diag.diagnoses:
        queries.extend(KB_QUERIES.get(d.rule_id, []))
    seen = set()
    out = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def report_summary(report: TailingsReport) -> dict:
    return {
        "фабрика": report.plant,
        "тип_хвостов": report.tail_type,
        "хвосты_СМТ": report.tails_tonnes,
        "содержание_%": report.grade,
        "потери_т": report.losses_tonnes,
        "извлекаемо_т": report.recoverable_total,
        "извлекаемо_%": report.recoverable_pct,
        "классы": [{
            "класс": sc.label, "доля_%": sc.share_pct,
            "Ni_т": sc.element_tonnes.get("Ni"), "Cu_т": sc.element_tonnes.get("Cu"),
        } for sc in report.size_classes],
    }


def generate_hypotheses(report: TailingsReport, diag: DiagnosticsResult, *,
                        kb_index: KBIndex | None = None,
                        llm: LLMClient | None = None,
                        constraints: str = "",
                        stoplist: list[str] | None = None,
                        history_titles: list[str] | None = None,
                        excluded_areas: list[str] | None = None,
                        flowsheet_summary: dict | None = None,
                        reagent_hints: list[dict] | None = None) -> list[Hypothesis]:
    kb_index = kb_index if kb_index is not None else default_index()
    llm = llm if llm is not None else default_client
    stoplist = stoplist or []
    history_titles = history_titles or []
    excluded_areas = excluded_areas or []

    queries = build_queries(diag)
    log.info("Генерация гипотез: фабрика «%s», диагнозов R1–R3=%d, стоп-лист=%d, "
             "исключённых направлений=%d, история=%d",
             report.plant, len(diag.diagnoses), len(stoplist),
             len(excluded_areas), len(history_titles))
    chunks = search_multi(queries, k_total=10, index=kb_index) if diag.diagnoses else []
    log.info("KB-контекст: %d запрос(ов) → %d релевантных чанков", len(queries), len(chunks))

    raw = None
    if getattr(llm, "enabled", False):
        model_name = getattr(getattr(llm, "s", None), "llm_model_strong", "STRONG")
        diagnoses_payload = [{
            "rule_id": d.rule_id, "element": d.element, "zone": d.zone, "text": d.text,
            "inputs": d.inputs, "target_cells": d.cell_keys,
            "tonnes_recoverable": d.tonnes_recoverable, "uncertain": d.uncertain,
        } for d in diag.diagnoses]
        prompt = build_user_prompt(report_summary(report), diagnoses_payload, chunks,
                                   equipment_list(), constraints, stoplist,
                                   history_titles, excluded_areas,
                                   intervention_menu=pack().get("intervention_menu"),
                                   flowsheet_summary=flowsheet_summary,
                                   reagent_hints=reagent_hints)
        log.info("Вызов STRONG-модели «%s» (json_mode, промпт %d симв.) — может занять минуты…",
                 model_name, len(prompt))
        t0 = time.perf_counter()
        try:
            resp = llm.chat([{"role": "system", "content": SYSTEM_GENERATE},
                             {"role": "user", "content": prompt}],
                            strong=True, json_mode=True)
            dt = time.perf_counter() - t0
            usage = resp.get("usage") or {}
            log.info("Ответ STRONG-модели за %.1fс: %d симв., токены prompt=%s completion=%s total=%s",
                     dt, len(resp.get("content", "")), usage.get("prompt_tokens"),
                     usage.get("completion_tokens"), usage.get("total_tokens"))
            raw = extract_json(resp["content"])
        except (LLMUnavailable, ValueError) as e:
            log.warning("Генерация LLM недоступна за %.1fс (%s) — мок из фикстуры",
                        time.perf_counter() - t0, e)

    grounded_mock = False
    if raw is None:
        raw = json.loads(MOCK_FIXTURE.read_text(encoding="utf-8"))
        grounded_mock = True
        log.info("Генерация в МОК-режиме — фикстура %s (цитаты заземляются на локальный индекс)",
                 MOCK_FIXTURE.name)

    n_raw = len(raw.get("hypotheses", []))
    hyps = _postprocess(raw, report, diag, stoplist, excluded_areas)
    if grounded_mock:
        _ground_mock_citations(hyps, kb_index)
    log.info("Генерация завершена: %d гипотез после валидации (сырых от модели: %d)",
             len(hyps), n_raw)
    return hyps


def _postprocess(raw: dict, report: TailingsReport, diag: DiagnosticsResult,
                 stoplist: list[str], excluded_areas: list[str]) -> list[Hypothesis]:
    """Валидация ответа модели + детерминированный расчёт эффекта (раздел 6)."""
    known_types = set(pack()["hypothesis_types"].keys())
    ontology = {e["name"]: e for e in equipment_list()}
    cells_by_key = {c.key: c for c in report.cells}
    diag_by_rule: dict[str, list[str]] = {}
    for d in diag.diagnoses:
        diag_by_rule.setdefault(d.rule_id, []).extend(d.cell_keys)

    out: list[Hypothesis] = []
    for n, h in enumerate(raw.get("hypotheses", [])):
        title = (h.get("title") or "").strip()
        if not title:
            continue
        low_title = title.lower()
        if any(s.lower() in low_title for s in stoplist):
            continue
        area = h.get("process_area", "прочее")
        if area in excluded_areas:
            continue
        htype = h.get("hypothesis_type", "other")
        if htype not in known_types:
            htype = "other"
        element = h.get("element") if h.get("element") in ("Ni", "Cu") else "Ni"

        # целевые ячейки: только существующие и ИЗВЛЕКАЕМЫЕ
        target = []
        for tc in h.get("target_cells", []):
            key = tc.get("key") if isinstance(tc, dict) else str(tc)
            cell = cells_by_key.get(key)
            if cell and cell.recoverable:
                target.append(cell)
        if not target:  # fallback: ячейки диагноза
            for key in diag_by_rule.get(h.get("diagnosis_rule", ""), []):
                cell = cells_by_key.get(key)
                if cell and cell.recoverable and cell.element == element:
                    target.append(cell)
        if not target:
            log.info("Гипотеза «%s» без извлекаемых целевых ячеек — отброшена", title)
            continue

        tonnes_max = sum(c.tonnes or 0.0 for c in target)
        rate = capture_rate(htype)
        tonnes_expected = round(tonnes_max * rate, 1)
        money = round(tonnes_expected * METAL_PRICE_USD[element])
        recovered_based = any(c.provenance != "measured" for c in target)
        uncertain = any(c.provenance == "recovered_llm" for c in target)

        assumptions = (h.get("effect_assumptions") or "").strip()
        assumptions = (f"capture_rate={rate:.2f} по типу «{htype}» (domain_pack); "
                       + assumptions).strip("; ")
        if recovered_based:
            assumptions += "; оценка на восстановленных данных"

        equipment = []
        for name in h.get("equipment", []) or []:
            name = str(name).strip()
            ont = ontology.get(name)
            matched = ont
            if not matched:  # частичное совпадение имени
                for oname, o in ontology.items():
                    if oname.lower() in name.lower() or name.lower() in oname.lower():
                        matched = o
                        name = oname
                        break
            equipment.append(EquipmentRef(
                name=name,
                positions=(matched or {}).get("positions", []),
                present_on_plant=matched is not None))
        feas = h.get("feasibility") or {}
        if any(not e.present_on_plant for e in equipment):
            feas["capex"] = "high"

        plan = []
        for s in h.get("verification_plan", []) or []:
            try:
                plan.append(Step(
                    n=int(s.get("n", len(plan) + 1)), action=s.get("action", ""),
                    resources=s.get("resources", ""), duration=s.get("duration", ""),
                    success_criterion=s.get("success_criterion", ""),
                    fail_criterion=s.get("fail_criterion", "")))
            except (TypeError, ValueError):
                continue

        citations = [Citation(quote=(c.get("quote") or "")[:400],
                              source=c.get("source", ""),
                              chunk_id=c.get("chunk_id"))
                     for c in (h.get("citations") or []) if c.get("quote")]

        out.append(Hypothesis(
            id=f"h{n + 1:02d}-{uuid.uuid4().hex[:6]}",
            title=title, process_area=area, element=element, hypothesis_type=htype,
            target_cells=[{"key": c.key, "tonnes": c.tonnes} for c in target],
            mechanism=(h.get("mechanism") or "").strip(),
            rationale=citations,
            equipment=equipment,
            effect=Effect(tonnes_max=round(tonnes_max, 1), tonnes_expected=tonnes_expected,
                          money_usd=money, assumptions=assumptions),
            risks=[str(r) for r in (h.get("risks") or [])],
            feasibility=feas,
            verification_plan=plan,
            diagnosis_rule=h.get("diagnosis_rule"),
            uncertain=uncertain,
        ))
    return out


def _ground_mock_citations(hyps: list[Hypothesis], kb_index: KBIndex):
    """Мок-цитаты заземляются на реальные чанки локального индекса,
    чтобы verify и демо работали без LLM."""
    if not kb_index.chunks:
        for h in hyps:
            h.rationale = []
        return
    for h in hyps:
        hits = kb_index.search(f"{h.title} {h.mechanism}", k=1)
        if not hits:
            h.rationale = []
            continue
        hit = hits[0]
        quote = " ".join(hit["text"].split()[:35])
        h.rationale = [Citation(quote=quote, source=hit["source"],
                                page=hit["page"], chunk_id=hit["chunk_id"])]
