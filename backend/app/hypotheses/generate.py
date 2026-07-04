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
import os
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


def _line_equipment_ontology(project_equipment: list[dict]) -> list[dict]:
    """Схлопывает построчный снимок оборудования проекта (раздел «Ограничения»,
    несколько строк на одно имя — разные позиции) к виду онтологии домен-пака."""
    by_name: dict[str, dict] = {}
    for e in project_equipment:
        name = e.get("name", "")
        entry = by_name.setdefault(name, {"name": name, "type": e.get("category", ""), "positions": []})
        pos = (e.get("position") or "").strip()
        if pos and pos not in entry["positions"]:
            entry["positions"].append(pos)
    return list(by_name.values())


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
                        project_equipment: list[dict] | None = None,
                        flowsheet_summary: dict | None = None,
                        reagent_hints: list[dict] | None = None,
                        n_samples: int = 1) -> list[Hypothesis]:
    """n_samples > 1 — best-of-N: параллельные независимые генерации, объединение
    и смысловой дедуп (LLM недобирает направления в одиночном сэмпле)."""
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

    raws: list[dict] = []
    if getattr(llm, "enabled", False):
        model_name = getattr(getattr(llm, "s", None), "llm_model_strong", "STRONG")
        diagnoses_payload = [{
            "rule_id": d.rule_id, "element": d.element, "zone": d.zone, "text": d.text,
            "inputs": d.inputs, "target_cells": d.cell_keys,
            "tonnes_recoverable": d.tonnes_recoverable, "uncertain": d.uncertain,
        } for d in diag.diagnoses]
        from ..parser.docx import cross_plant_examples
        # GEN_NO_FEWSHOT=1 — абляционный выключатель для eval-экспериментов
        few_shot = [] if os.environ.get("GEN_NO_FEWSHOT") == "1" \
            else cross_plant_examples(report.plant)
        eq_for_prompt = _line_equipment_ontology(project_equipment) if project_equipment else equipment_list()
        prompt = build_user_prompt(report_summary(report), diagnoses_payload, chunks,
                                   eq_for_prompt, constraints, stoplist,
                                   history_titles, excluded_areas,
                                   intervention_menu=pack().get("intervention_menu"),
                                   flowsheet_summary=flowsheet_summary,
                                   reagent_hints=reagent_hints,
                                   few_shot=few_shot)
        log.info("Вызов STRONG-модели «%s» (json_mode, промпт %d симв., n_samples=%d, "
                 "few_shot=%d) — может занять минуты…",
                 model_name, len(prompt), n_samples, len(few_shot))

        def one_sample(_i: int) -> dict | None:
            t0 = time.perf_counter()
            try:
                resp = llm.chat([{"role": "system", "content": SYSTEM_GENERATE},
                                 {"role": "user", "content": prompt}],
                                strong=True, json_mode=True)
                dt = time.perf_counter() - t0
                usage = resp.get("usage") or {}
                log.info("Сэмпл #%d: ответ STRONG-модели за %.1fс: %d симв., "
                         "токены prompt=%s completion=%s total=%s",
                         _i, dt, len(resp.get("content", "")), usage.get("prompt_tokens"),
                         usage.get("completion_tokens"), usage.get("total_tokens"))
                data = extract_json(resp["content"])
                if isinstance(data, list):  # модель вернула голый массив гипотез
                    data = {"hypotheses": data}
                return data if isinstance(data, dict) else None
            except (LLMUnavailable, ValueError) as e:
                log.warning("Сэмпл #%d генерации не удался за %.1fс (%s)",
                            _i, time.perf_counter() - t0, e)
                return None

        if n_samples <= 1:
            raws = [r for r in [one_sample(0)] if r]
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=n_samples) as pool:
                raws = [r for r in pool.map(one_sample, range(n_samples)) if r]
        log.info("Best-of-N: получено %d/%d успешных сэмплов", len(raws), n_samples)

    grounded_mock = False
    if not raws:
        raws = [json.loads(MOCK_FIXTURE.read_text(encoding="utf-8"))]
        grounded_mock = True
        log.info("Генерация в МОК-режиме — фикстура %s (цитаты заземляются на локальный индекс)",
                 MOCK_FIXTURE.name)

    n_raw = sum(len(r.get("hypotheses", [])) for r in raws)
    hyps: list[Hypothesis] = []
    for raw in raws:
        hyps.extend(_postprocess(raw, report, diag, stoplist, excluded_areas,
                                 project_equipment))
    n_valid = len(hyps)
    hyps = _dedup_hypotheses(hyps)
    log.info("Постобработка: %d валидных гипотез из %d сырых, после дедупа=%d",
             n_valid, n_raw, len(hyps))

    if not grounded_mock and os.environ.get("GEN_NO_REPAIR") != "1":
        extra = _repair_missing_directions(llm, prompt, hyps, report, diag,
                                           stoplist, excluded_areas,
                                           project_equipment)
        if extra:
            hyps = _dedup_hypotheses(hyps + extra)
    hyps = _cap_diverse(hyps, cap=15)

    if grounded_mock:
        _ground_mock_citations(hyps, kb_index)
    else:
        _reground_citations(hyps, kb_index)
    log.info("Генерация завершена: %d гипотез после дедупа/добора/капа (сырых от модели: %d)",
             len(hyps), n_raw)
    return hyps


def _richness(h: Hypothesis) -> tuple:
    return (len(h.rationale), len(h.verification_plan), h.effect.tonnes_max,
            len(h.mechanism))


def _dedup_hypotheses(hyps: list[Hypothesis]) -> list[Hypothesis]:
    """Смысловой дедуп после best-of-N: похожие заголовки (fuzzy) = одно
    вмешательство; остаётся более проработанная карточка. Внутри одного
    hypothesis_type порог ниже: перефразированные варианты одного приёма
    («грохочение Derrick 71 мкм» / «грохочение сетка 100 мкм») — дубли."""
    from rapidfuzz import fuzz

    kept: list[Hypothesis] = []
    for h in sorted(hyps, key=_richness, reverse=True):
        dup = False
        for k in kept:
            if h.element != k.element:
                continue
            s = fuzz.token_set_ratio(h.title.lower(), k.title.lower())
            if s > 78 or (s > 65 and h.hypothesis_type == k.hypothesis_type != "other"):
                dup = True
                break
        if not dup:
            kept.append(h)
    return kept


def _cap_diverse(hyps: list[Hypothesis], cap: int = 15) -> list[Hypothesis]:
    """Кап выдачи с сохранением разнообразия направлений: не более 2 гипотез на
    (тип, элемент), чтобы близнецы одного приёма не вытесняли уникальные
    направления; остаток слотов добирается по богатству карточки."""
    kept: list[Hypothesis] = []
    skipped: list[Hypothesis] = []
    per_group: dict[tuple, int] = {}
    for h in sorted(hyps, key=_richness, reverse=True):
        g = (h.hypothesis_type, h.element)
        if per_group.get(g, 0) >= 2:
            skipped.append(h)
            continue
        kept.append(h)
        per_group[g] = per_group.get(g, 0) + 1
    for h in skipped:
        if len(kept) >= cap:
            break
        kept.append(h)
    return kept[:cap]


REPAIR_SUFFIX = """

ДОБОР НЕПОКРЫТЫХ НАПРАВЛЕНИЙ. Уже сгенерированы гипотезы:
{titles}

Пройди по разделу «НАПРАВЛЕНИЯ ВМЕШАТЕЛЬСТВ» ещё раз. Для каждого направления,
по которому в списке выше НЕТ гипотезы, добери ровно одну гипотезу, следуя
направлению ДОСЛОВНО. Направление считается покрытым, только если совпадает
КОНКРЕТНАЯ операция и агрегат:
- гипотеза про основную флотацию НЕ покрывает направление про контрольную;
- ручная настройка НЕ покрывает авторегулирование;
- доизмельчение в мельнице НЕ покрывает додрабливание в дробилке;
- если направление содержит несколько приёмов — проверь каждый.
Направление неприменимо к этим данным — пропусти. Уже покрытые НЕ дублируй.
Ответ в той же JSON-схеме; если добирать нечего — {{"hypotheses": []}}."""


def _repair_missing_directions(llm: LLMClient, base_prompt: str,
                               hyps: list[Hypothesis], report: TailingsReport,
                               diag: DiagnosticsResult, stoplist: list[str],
                               excluded_areas: list[str],
                               project_equipment: list[dict] | None = None) -> list[Hypothesis]:
    """Гарантия обхода intervention_menu: один добирающий вызов по направлениям,
    не закрытым основной генерацией (fuzzy их не разделяет — матчит модель)."""
    titles = "\n".join(f"- {h.title} [{h.element}]" for h in hyps)
    try:
        resp = llm.chat([{"role": "system", "content": SYSTEM_GENERATE},
                         {"role": "user",
                          "content": base_prompt + REPAIR_SUFFIX.format(titles=titles)}],
                        strong=True, json_mode=True)
        data = extract_json(resp["content"])
        if isinstance(data, list):
            data = {"hypotheses": data}
        if isinstance(data, dict):
            extra = _postprocess(data, report, diag, stoplist, excluded_areas,
                                 project_equipment)
            log.info("Добор непокрытых направлений: +%d гипотез", len(extra))
            return extra
    except (LLMUnavailable, ValueError) as e:
        log.warning("Добор направлений не удался (%s)", e)
    return []


def _reground_citations(hyps: list[Hypothesis], kb_index: KBIndex):
    """Пере-заземление цитат живой генерации: цитата, которая не пройдёт verify
    (нет чанка / текст не совпадает), заменяется дословным фрагментом лучшего
    чанка ПОД ЭТУ гипотезу. Гипотеза без цитат получает одну."""
    import re as _re
    from rapidfuzz import fuzz

    def norm(s: str) -> str:
        return _re.sub(r"\s+", " ", (s or "").lower()).strip()

    for h in hyps:
        good = []
        for cit in h.rationale:
            chunk = kb_index.get_chunk(cit.chunk_id) if cit.chunk_id else None
            if chunk and fuzz.partial_ratio(norm(cit.quote), norm(chunk["text"])) > 75 \
                    and kb_index.doc_enabled(chunk["doc_id"]):
                good.append(cit)  # выключенный источник не проходит в новые цитаты
        target = min(max(len(h.rationale), 1), 2)
        if len(good) >= target:
            h.rationale = good
            continue  # валидных цитат достаточно — не трогаем
        for hit in kb_index.search(f"{h.title} {h.mechanism}", k=3):
            if len(good) >= target:
                break
            if any(c.chunk_id == hit["chunk_id"] for c in good):
                continue
            quote = " ".join(hit["text"].split()[:35])
            good.append(Citation(quote=quote, source=hit["source"],
                                 page=hit["page"], chunk_id=hit["chunk_id"]))
        h.rationale = good


def _postprocess(raw: dict, report: TailingsReport, diag: DiagnosticsResult,
                 stoplist: list[str], excluded_areas: list[str],
                 project_equipment: list[dict] | None = None) -> list[Hypothesis]:
    """Валидация ответа модели + детерминированный расчёт эффекта (раздел 6)."""
    known_types = set(pack()["hypothesis_types"].keys())
    # онтология линии проекта (раздел «Ограничения») вместо общей по домен-паку, если задана
    eq_source = _line_equipment_ontology(project_equipment) if project_equipment else equipment_list()
    ontology = {e["name"]: e for e in eq_source}
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
            # оборудования нет на линии -> выше риск/сложность внедрения (та же
            # формула ранжирования, что и для остальных гипотез — rank.py::_risk_norm)
            feas["complexity"] = "high"

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
