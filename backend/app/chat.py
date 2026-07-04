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
from .models import (ChartPoint, ChatAnswer, ChatChart, ChatReference, Hypothesis,
                     Project, TailingsReport)

log = logging.getLogger("chat")

SYSTEM_CHAT = """Ты — ассистент-интерпретатор системы «Фабрика гипотез» для технолога
обогатительной фабрики. Отвечай ТОЛЬКО из переданного контекста, по-русски, на уровне
инженера. Каждое число и утверждение снабжай ссылкой на источник в квадратных скобках:
[R1] — правило диагностики, [+125/Закрытый Pnt/Cp/Ni] — ячейка карты потерь,
[h03-ab12cd] — гипотеза, [abcdef123456:7] — фрагмент литературы.

Как отвечать:
- Сначала прямой ответ на вопрос (1–2 предложения), потом обоснование числами.
- Про ранжирование гипотез объясняй через формулу score и веса из контекста:
  что именно (эффект в $, CAPEX, риск, новизна) подняло или опустило гипотезу.
- Терминологию объясняй просто (сросток, шлам, извлекаемое); если вопрос чисто
  про термин — используй фрагменты литературы и дай ссылку [chunk_id].
- Если ответа в контексте нет — скажи прямо и предложи, куда посмотреть
  (какой экран, какое правило, какая ячейка).
- Пиши компактно: короткие абзацы, без воды; списки — через «- » с новой строки.
- Ссылки вставляй в текст ровно в том формате id, что дан в контексте.
- «Здесь», «на этой странице», «эта таблица/карточка» — это про экран из поля
  «где_сейчас_пользователь»; отвечай относительно того, что он видит.
- Если просят график/сравнить/показать распределение чисел — добавь 1–2 графика
  СТРОГО из чисел контекста (не выдумывай и не пересчитывай): 3–10 строк,
  одна величина на график, Ni и Cu — отдельными графиками. Если графика не
  просили, но сравнение по 3+ числам просится само — тоже можно один.

Ответ строго JSON: {"text": "ответ со ссылками в тексте",
"references": [{"type": "rule|cell|hypothesis|chunk", "id": "..."}],
"charts": [{"type": "bar", "title": "Потери Ni по классам", "unit": "т",
"data": [{"label": "+125", "value": 1471.3}]}]}
Поле charts опционально — пустой список, если график не нужен."""


# что пользователь видит на каждом экране — для вопросов «а что это тут?»
PAGE_CONTEXT = {
    "report": "Экран «Разбор отчёта»: сводные KPI (тоннаж, потери Ni/Cu, % извлекаемого), "
              "таблицы крупности и минералогии по Ni и Cu, подсветка битых/восстановленных "
              "значений с формулами восстановления, правка ячеек вручную.",
    "map": "Экран «Карта потерь»: тепловая матрица классы×формы по Ni и Cu, граф переделов "
           "фабрики по регламенту с подсветкой диагнозов, карточки диагнозов R1–R5 с "
           "числами, блок «Почему не предложено» (неизвлекаемые формы), аномалии данных.",
    "hypotheses": "Экран «Гипотезы»: ранжированный список карточек (механизм, цитаты из "
                  "литературы, эффект в т/$, оборудование, план проверки), слайдеры весов "
                  "ранжирования, фильтры переделов, кнопки Принять/Отклонить.",
    "export": "Экран «Отчёт и экспорт»: топ-5 гипотез таблицей, канбан статусов, дорожная "
              "карта испытаний (Гант: лаба → ОПИ → тираж, ромбы-ворота, конфликты "
              "ресурсов), кнопки экспорта DOCX/CSV/JSON.",
}


def build_context(question: str, report: TailingsReport, diag: DiagnosticsResult,
                  hypotheses: list[Hypothesis], project: Project,
                  kb_index: KBIndex | None = None,
                  roadmap: list[dict] | None = None,
                  page: str | None = None) -> dict:
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

    hyp_short = [{"№": i + 1, "id": h.id, "заголовок": h.title, "score": h.score,
                  "статус": h.status, "эффект_т": h.effect.tonnes_expected,
                  "эффект_$": h.effect.money_usd, "передел": h.process_area,
                  "capex": (h.feasibility or {}).get("capex"),
                  "novelty": (h.novelty or {}).get("score"),
                  "совпала_с_экспертной": bool((h.novelty or {}).get("prior_matches")),
                  "цитат_подтверждено": sum(1 for c in h.rationale if c.verified)}
                 for i, h in enumerate(hypotheses)]
    mentioned = [h for h in hypotheses
                 if h.id.lower() in q_low or _title_mentioned(h.title, q_low)]
    # эвристики «гипотеза №1», «первая гипотеза» и т.п.
    m = re.search(r"№\s*(\d+)|гипотез[аыу]\s+(\d+)", q_low)
    if m:
        n = int(m.group(1) or m.group(2))
        if 1 <= n <= len(hypotheses):
            mentioned.append(hypotheses[n - 1])
    if hypotheses and re.search(r"\bперв(ая|ой|ую|ое)\b|\bглавн(ая|ой|ую)\s+гипотез", q_low):
        mentioned.append(hypotheses[0])
    mentioned_full = [h.model_dump() for h in {h.id: h for h in mentioned}.values()][:3]

    # KB: вопрос + заголовки упомянутых гипотез (чтобы литература была в тему)
    kb = kb_index or default_index()
    kb_hits = kb.search(question, k=5)
    seen_chunks = {h["chunk_id"] for h in kb_hits}
    for h_ment in list({h.id: h for h in mentioned}.values())[:2]:
        for hit in kb.search(h_ment.title, k=2):
            if hit["chunk_id"] not in seen_chunks:
                seen_chunks.add(hit["chunk_id"])
                kb_hits.append(hit)
    kb_ctx = [{"chunk_id": h["chunk_id"], "источник": h["source"], "страница": h["page"],
               "текст": h["text"][:800]} for h in kb_hits[:7]]

    roadmap_ctx = [{"гипотеза": it.get("hypothesis_id"), "стадия": it.get("stage"),
                    "старт": it.get("start"), "конец": it.get("end"),
                    "ресурс": it.get("resource"),
                    "ждёт": it.get("shifted_reason")}
                   for it in (roadmap or [])[:24]]

    return {
        "вопрос": question,
        "где_сейчас_пользователь": PAGE_CONTEXT.get(page or "",
                                                    "экран не определён"),
        "проект": {"название": project.name or None, "объект": project.plant,
                   "фабрика": project.factory, "цель": project.goal or None,
                   "ограничения": project.constraints or None},
        "отчёт": report_ctx,
        "диагнозы": diag_ctx,
        "почему_не_предложено": not_proposed_ctx,
        "гипотезы_кратко": hyp_short,
        "гипотезы_полные_упомянутые": mentioned_full,
        "дорожная_карта": roadmap_ctx,
        "фрагменты_литературы": kb_ctx,
        "веса_ранжирования": project.weights,
        "формула_score": "score = w_money·норм(эффект $) + w_capex·(1−CAPEX) + "
                         "w_risk·(1−риск) + w_novelty·novelty; без подтверждённых "
                         "цитат — штраф ×0.75",
        "стоп_лист": project.stoplist,
    }


def _title_mentioned(title: str, q_low: str) -> bool:
    words = [w for w in re.findall(r"[а-яёa-z]{5,}", title.lower())]
    hits = sum(1 for w in words if w in q_low)
    return len(words) > 0 and hits >= max(2, len(words) // 2)


def answer(question: str, history: list[dict], report: TailingsReport,
           diag: DiagnosticsResult, hypotheses: list[Hypothesis], project: Project,
           kb_index: KBIndex | None = None, llm: LLMClient | None = None,
           roadmap: list[dict] | None = None, page: str | None = None) -> ChatAnswer:
    llm = llm or default_client
    ctx = build_context(question, report, diag, hypotheses, project, kb_index,
                        roadmap, page)

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
        charts = _parse_charts(data.get("charts"))
    except (LLMUnavailable, ValueError) as e:
        log.warning("чат: LLM недоступна (%s) — детерминированный ответ", e)
        return _offline_answer(ctx, diag, hypotheses, question)

    if not refs:  # модель забыла references — вытащим из текста
        refs = _scan_references(text, report, diag, hypotheses,
                                kb_chunk_ids={c["chunk_id"]
                                              for c in ctx["фрагменты_литературы"]})
    return ChatAnswer(text=text, references=refs, charts=charts)


def _parse_charts(raw) -> list[ChatChart]:
    """Валидация графиков из ответа модели: максимум 2, по 3–12 числовых точек;
    всё кривое молча отбрасывается — график опционален."""
    charts: list[ChatChart] = []
    for ch in (raw or [])[:2]:
        if not isinstance(ch, dict) or not str(ch.get("title", "")).strip():
            continue
        points = []
        for p in (ch.get("data") or [])[:12]:
            try:
                points.append(ChartPoint(label=str(p["label"])[:40],
                                         value=float(p["value"])))
            except (KeyError, TypeError, ValueError):
                continue
        if len(points) >= 3:
            title = str(ch["title"])[:80].strip()
            unit = str(ch.get("unit", ""))[:12].strip()
            if unit:  # модель любит дублировать единицу в заголовке
                title = re.sub(rf",?\s*(\(\s*{re.escape(unit)}\s*\)|{re.escape(unit)})$",
                               "", title).strip()
            charts.append(ChatChart(title=title, unit=unit, data=points))
    return charts


def _scan_references(text: str, report: TailingsReport, diag: DiagnosticsResult,
                     hypotheses: list[Hypothesis],
                     kb_chunk_ids: set[str] | None = None) -> list[ChatReference]:
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
    for cid in kb_chunk_ids or set():
        if cid in text:
            refs.append(ChatReference(type="chunk", id=cid))
    seen = set()
    out = []
    for r in refs:
        if (r.type, r.id) not in seen:
            seen.add((r.type, r.id))
            out.append(r)
    return out[:10]


def _offline_answer(ctx: dict, diag: DiagnosticsResult,
                    hypotheses: list[Hypothesis] | None = None,
                    question: str = "") -> ChatAnswer:
    """Без LLM: честный детерминированный ответ по данным пайплайна.
    Простые намерения (неизвлекаемое, гипотезы) закрываем без модели."""
    q_low = question.lower()
    prefix = "LLM недоступна, отвечаю по данным пайплайна. "

    if re.search(r"график|диаграмм|распределен", q_low) and ctx["отчёт"].get("классы"):
        charts = []
        for el in ("Ni", "Cu"):
            pts = [ChartPoint(label=k["класс"], value=k.get(f"{el}_т") or 0.0)
                   for k in ctx["отчёт"]["классы"] if k.get(f"{el}_т") is not None]
            if len(pts) >= 3:
                charts.append(ChatChart(title=f"Потери {el} по классам крупности",
                                        unit="т", data=pts))
        if charts:
            return ChatAnswer(text=prefix + "Распределение потерь по классам крупности "
                              "из отчёта — на графиках ниже.", charts=charts)

    if "неизвлека" in q_low and ctx.get("почему_не_предложено"):
        lines = [f"- {n.get('form', '?')} ({n.get('element', '')}): "
                 f"{n.get('tonnes', '—')} т — {n.get('reason', '')}"
                 for n in ctx["почему_не_предложено"][:6]]
        return ChatAnswer(text=prefix + "Неизвлекаемые формы (раздел «Почему не предложено»):\n"
                          + "\n".join(lines), references=[])

    if hypotheses and ("гипотез" in q_low or "score" in q_low or "ранж" in q_low):
        top = hypotheses[:3]
        lines = [f"- №{i + 1} [{h.id}] {h.title}: score {h.score:.2f}, "
                 f"до {h.effect.tonnes_expected:.0f} т, ${h.effect.money_usd:,.0f}"
                 for i, h in enumerate(top)]
        return ChatAnswer(
            text=prefix + "Топ гипотез по score (веса: "
                 f"{ctx.get('веса_ранжирования')}):\n" + "\n".join(lines),
            references=[ChatReference(type="hypothesis", id=h.id) for h in top])

    if diag.diagnoses:
        d = diag.diagnoses[0]
        return ChatAnswer(
            text=prefix + f"Главный диагноз [{d.rule_id}]: {d.text}",
            references=[ChatReference(type="rule", id=d.rule_id)] +
                       [ChatReference(type="cell", id=k) for k in d.cell_keys[:3]])
    return ChatAnswer(text="LLM недоступна, а диагнозов по отчёту нет — проверьте, "
                           "загружен ли отчёт.", references=[])
