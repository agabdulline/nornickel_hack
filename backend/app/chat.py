# -*- coding: utf-8 -*-
"""Чат-интерпретатор проекта (раздел 8.1 CLAUDE.md).

Не general-purpose чат, а слой интерпретации поверх пайплайна: отвечает про
ЭТОТ отчёт, диагнозы и гипотезы. Контекст собирается детерминированно ПЕРЕД
вызовом модели; модель обязана отвечать только из контекста со ссылками
[R1] / [+125/Закрытый Pnt/Cp/Ni] / [h01-xxxx] / [chunk_id] / [Глембоцкий, с. N].
"""
from __future__ import annotations

import json
import logging
import re

from .diagnostics import DiagnosticsResult
from .kb.index import KBIndex, default_index
from .llm import LLMClient, LLMUnavailable, client as default_client, extract_json
from .models import ChatAnswer, ChatReference, Hypothesis, Project, TailingsReport

log = logging.getLogger("chat")

SYSTEM_CHAT = """Ты — ассистент-интерпретатор системы «Фабрика гипотез» для технолога
обогатительной фабрики. Отвечай ТОЛЬКО из переданного контекста, по-русски, на уровне
инженера. Каждое число и утверждение снабжай ссылкой на источник в квадратных скобках:
[R1] — правило диагностики, [+125/Закрытый Pnt/Cp/Ni] — ячейка карты потерь,
[h03-ab12cd] — гипотеза, [abcdef123456:7] — фрагмент литературы.
Если ответа в контексте нет — скажи прямо и предложи, куда посмотреть.
Терминологию объясняй просто (сросток, шлам, извлекаемое).

Ответ строго JSON: {"text": "ответ со ссылками в тексте",
"references": [{"type": "rule|cell|hypothesis|chunk", "id": "..."}]}"""


def build_context(question: str, report: TailingsReport, diag: DiagnosticsResult,
                  hypotheses: list[Hypothesis], project: Project,
                  kb_index: KBIndex | None = None) -> dict:
    """Детерминированная сборка контекста (что именно видит модель)."""
    q_low = question.lower()

    top_cells = sorted([c for c in report.cells if (c.tonnes or 0) > 0],
                       key=lambda c: -(c.tonnes or 0))[:12]
    report_ctx = {
        "фабрика": report.plant, "тип_хвостов": report.tail_type,
        "хвосты_СМТ": report.tails_tonnes, "содержание_%": report.grade,
        "потери_т": report.losses_tonnes,
        "извлекаемо": {"т": report.recoverable_total, "%": report.recoverable_pct},
        "классы": [{"класс": s.label, "доля_%": s.share_pct,
                    "Ni_т": s.element_tonnes.get("Ni"), "Cu_т": s.element_tonnes.get("Cu")}
                   for s in report.size_classes],
        "топ_ячейки_потерь": [{"ячейка": c.key, "т": c.tonnes, "извлекаемо": c.recoverable,
                               "происхождение": c.provenance} for c in top_cells],
        "issues": [i.message for i in report.issues[:10]],
    }

    diag_ctx = [{"правило": d.rule_id, "элемент": d.element, "зона": d.zone,
                 "текст": d.text, "входные_числа": d.inputs, "ячейки": d.cell_keys}
                for d in diag.diagnoses]
    not_proposed_ctx = diag.not_proposed

    hyp_short = [{"id": h.id, "заголовок": h.title, "score": h.score, "статус": h.status,
                  "эффект_т": h.effect.tonnes_expected, "эффект_$": h.effect.money_usd,
                  "передел": h.process_area} for h in hypotheses]
    mentioned = [h for h in hypotheses
                 if h.id.lower() in q_low or _title_mentioned(h.title, q_low)]
    # эвристика «гипотеза №1» и т.п.
    m = re.search(r"№\s*(\d+)|гипотез[аыу]\s+(\d+)", q_low)
    if m:
        n = int(m.group(1) or m.group(2))
        if 1 <= n <= len(hypotheses):
            mentioned.append(hypotheses[n - 1])
    mentioned_full = [h.model_dump() for h in {h.id: h for h in mentioned}.values()][:3]

    kb_hits = (kb_index or default_index()).search(question, k=5)
    kb_ctx = [{"chunk_id": h["chunk_id"], "источник": h["source"], "страница": h["page"],
               "текст": h["text"][:800]} for h in kb_hits]

    return {
        "вопрос": question,
        "отчёт": report_ctx,
        "диагнозы": diag_ctx,
        "почему_не_предложено": not_proposed_ctx,
        "гипотезы_кратко": hyp_short,
        "гипотезы_полные_упомянутые": mentioned_full,
        "фрагменты_литературы": kb_ctx,
        "веса_ранжирования": project.weights,
        "стоп_лист": project.stoplist,
    }


def _title_mentioned(title: str, q_low: str) -> bool:
    words = [w for w in re.findall(r"[а-яёa-z]{5,}", title.lower())]
    hits = sum(1 for w in words if w in q_low)
    return len(words) > 0 and hits >= max(2, len(words) // 2)


def answer(question: str, history: list[dict], report: TailingsReport,
           diag: DiagnosticsResult, hypotheses: list[Hypothesis], project: Project,
           kb_index: KBIndex | None = None, llm: LLMClient | None = None) -> ChatAnswer:
    llm = llm or default_client
    ctx = build_context(question, report, diag, hypotheses, project, kb_index)

    # STRONG — только для длинной истории или сравнения гипотез
    strong = len(history) > 6 or "сравн" in question.lower()

    messages = [{"role": "system", "content": SYSTEM_CHAT}]
    for msg in history[-8:]:
        role = msg.get("role") if msg.get("role") in ("user", "assistant") else "user"
        messages.append({"role": role, "content": str(msg.get("content", ""))[:2000]})
    messages.append({"role": "user",
                     "content": f"КОНТЕКСТ ПРОЕКТА:\n{json.dumps(ctx, ensure_ascii=False)}\n\n"
                                f"ВОПРОС: {question}"})
    try:
        resp = llm.chat(messages, strong=strong, json_mode=True)
        data = extract_json(resp["content"])
        text = data.get("text", "")
        refs = [ChatReference(type=r.get("type", "rule"), id=str(r.get("id", "")))
                for r in data.get("references", [])
                if r.get("type") in ("rule", "cell", "hypothesis", "chunk")]
    except (LLMUnavailable, ValueError) as e:
        log.warning("чат: LLM недоступна (%s) — детерминированный ответ", e)
        return _offline_answer(ctx, diag)

    if not refs:  # модель забыла references — вытащим из текста
        refs = _scan_references(text, report, diag, hypotheses)
    return ChatAnswer(text=text, references=refs)


def _scan_references(text: str, report: TailingsReport, diag: DiagnosticsResult,
                     hypotheses: list[Hypothesis]) -> list[ChatReference]:
    refs: list[ChatReference] = []
    for d in diag.diagnoses:
        if re.search(rf"\[{d.rule_id}\]|\b{d.rule_id}\b", text):
            refs.append(ChatReference(type="rule", id=d.rule_id))
    for c in report.cells:
        if c.key in text:
            refs.append(ChatReference(type="cell", id=c.key))
    for h in hypotheses:
        if h.id in text:
            refs.append(ChatReference(type="hypothesis", id=h.id))
    seen = set()
    out = []
    for r in refs:
        if (r.type, r.id) not in seen:
            seen.add((r.type, r.id))
            out.append(r)
    return out[:10]


def _offline_answer(ctx: dict, diag: DiagnosticsResult) -> ChatAnswer:
    """Без LLM: честный ответ с главным диагнозом и ссылками."""
    if diag.diagnoses:
        d = diag.diagnoses[0]
        return ChatAnswer(
            text=f"LLM недоступна, отвечаю по данным пайплайна. Главный диагноз [{d.rule_id}]: "
                 f"{d.text}",
            references=[ChatReference(type="rule", id=d.rule_id)] +
                       [ChatReference(type="cell", id=k) for k in d.cell_keys[:3]])
    return ChatAnswer(text="LLM недоступна, а диагнозов по отчёту нет — проверьте, "
                           "загружен ли отчёт.", references=[])
