# -*- coding: utf-8 -*-
"""Промпты генерации гипотез (раздел 8 CLAUDE.md). Всё по-русски."""
from __future__ import annotations

import json

SYSTEM_GENERATE = """Ты — главный обогатитель научно-исследовательского института, 30 лет опыта
на медно-никелевых обогатительных фабриках (флотация сульфидных руд). Твоя задача — по
диагнозам потерь металла в хвостах предложить КОНКРЕТНЫЕ, проверяемые в лаборатории
гипотезы по снижению потерь.

Жёсткие правила:
1. На каждый диагноз — 2–4 гипотезы, суммарно 8–14 (если диагнозов мало — всё равно не
   меньше 10, расширяя охват смежными переделами: дробление, классификация, вспомогательные).
   Большинство экспертных гипотез — про измельчение и классификацию, флотационные — меньшинство.
1а. Тебе передан СПИСОК НАПРАВЛЕНИЙ ВМЕШАТЕЛЬСТВ по каждому диагнозу — пройдись по каждому
   направлению и предложи гипотезу, если оно уместно для этих данных и этой фабрики.
   Разные направления НЕ склеивай в одну гипотезу (футеровка и шаровая загрузка — две разные).
2. Каждая гипотеза конкретна: какой агрегат/параметр менять, на сколько, что это даст физически.
3. Цитаты — СТРОГО из переданных фрагментов литературы, с их chunk_id. Цитата — дословный
   фрагмент текста чанка, не длиннее 40 слов. Выдумывать цитаты и chunk_id НЕЛЬЗЯ.
4. Гипотезы по неизвлекаемым формам (примесь в пирротине, силикатная форма/валлериит, пирит)
   ЗАПРЕЩЕНЫ — их лечат металлургией, не флотацией.
5. Оборудование упоминай только из переданной онтологии фабрики. Если гипотеза требует
   оборудования, которого нет в онтологии, — так и укажи в поле equipment, оно будет помечено
   present_on_plant=false и capex=high.
6. План проверки: лабораторный тест → ОПИ (опытная линия против контрольной) → тираж.
   У КАЖДОГО шага числовой критерий успеха и провала (например «прирост извлечения ≥0.5 п.п.»).
7. Механизм — 2–4 предложения физики процесса, без воды.

Отвечай СТРОГО валидным JSON без комментариев."""


RESPONSE_SCHEMA_HINT = {
    "hypotheses": [{
        "title": "краткий заголовок действия",
        "process_area": "дробление|измельчение|классификация|флотация|реагентика|вспомогательные",
        "hypothesis_type": "regrind|liner|classification|screening|flotation_time|reagent|density|magnetic|automation|crushing|contact_tank|gravity|other",
        "element": "Ni|Cu",
        "diagnosis_rule": "R1|R2|R3",
        "target_cells": [{"key": "класс/форма/элемент, например +125/Закрытый Pnt/Cp/Ni"}],
        "mechanism": "2-4 предложения физики",
        "citations": [{"chunk_id": "id чанка", "quote": "дословная цитата ≤40 слов"}],
        "equipment": ["имена из онтологии"],
        "risks": ["риск 1", "риск 2"],
        "feasibility": {"capex": "low|med|high", "downtime_hours": 0, "complexity": "low|med|high"},
        "verification_plan": [{
            "n": 1, "action": "...", "resources": "...", "duration": "2-4 нед",
            "success_criterion": "числовой", "fail_criterion": "числовой"}],
        "effect_assumptions": "краткие допущения оценки эффекта",
    }]
}


def build_user_prompt(report_summary: dict, diagnoses: list[dict], chunks: list[dict],
                      equipment: list[dict], constraints: str, stoplist: list[str],
                      history_titles: list[str], excluded_areas: list[str],
                      intervention_menu: dict | None = None,
                      flowsheet_summary: dict | None = None,
                      reagent_hints: list[dict] | None = None,
                      few_shot: list[str] | None = None) -> str:
    chunk_lines = "\n\n".join(
        f"[{c['chunk_id']}] ({c['source']}, с. {c['page']}):\n{c['text'][:1200]}"
        for c in chunks) or "(фрагментов нет — генерируй без цитат, поле citations пустое)"
    eq_lines = "\n".join(
        f"- {e['name']} ({e.get('type', '')}; позиции: {', '.join(e.get('positions') or []) or '—'})"
        for e in equipment)
    parts = [
        f"ОТЧЁТ ПО ХВОСТАМ:\n{json.dumps(report_summary, ensure_ascii=False, indent=1)}",
        "ДИАГНОЗЫ (детерминированные правила R1-R3, с числами):\n" +
        json.dumps(diagnoses, ensure_ascii=False, indent=1),
        f"ФРАГМЕНТЫ ЛИТЕРАТУРЫ ДЛЯ ЦИТАТ:\n{chunk_lines}",
        f"ОБОРУДОВАНИЕ ФАБРИКИ (онтология):\n{eq_lines}",
    ]
    if intervention_menu:
        fired = {d.get("rule_id") for d in diagnoses}
        menu_lines = []
        for rule, directions in intervention_menu.items():
            if rule in fired:
                menu_lines.append(f"{rule}:")
                menu_lines += [f"  - {x}" for x in directions]
        if menu_lines:
            parts.append("НАПРАВЛЕНИЯ ВМЕШАТЕЛЬСТВ (пройдись по каждому, предложи гипотезу, "
                         "если уместно для этих данных):\n" + "\n".join(menu_lines))
    if flowsheet_summary:
        parts.append("РЕГЛАМЕНТ ФАБРИКИ (оцифрованная схема: узлы с режимами и хвостовые "
                     "потоки — предлагай вмешательства в КОНКРЕТНЫЕ узлы по их названиям):\n"
                     + json.dumps(flowsheet_summary, ensure_ascii=False, indent=1))
    if reagent_hints:
        parts.append("СИСТЕМНЫЕ ПОДСКАЗКИ ПО РЕАГЕНТАМ (реагент есть в режимной карте с "
                     "расходом 0 г/т, а в литературе есть данные о его эффективности — "
                     "рассмотри гипотезу о вводе, цитируй указанные источники):\n"
                     + json.dumps(reagent_hints, ensure_ascii=False, indent=1))
    if few_shot:
        parts.append("ОБРАЗЦЫ КОНКРЕТНОСТИ — реальные гипотезы экспертов ДРУГИХ фабрик "
                     "(показывают калибр детализации: конкретный агрегат/параметр/число; "
                     "НЕ копируй их — у твоей фабрики свои диагнозы и оборудование):\n- "
                     + "\n- ".join(few_shot))
    if constraints:
        parts.append(f"ОГРАНИЧЕНИЯ ПОЛЬЗОВАТЕЛЯ: {constraints}")
    if excluded_areas:
        parts.append(f"ИСКЛЮЧЁННЫЕ ПЕРЕДЕЛЫ (не предлагать): {', '.join(excluded_areas)}")
    if stoplist:
        parts.append("СТОП-ЛИСТ (эти направления уже отклонены, НЕ предлагать повторно):\n- "
                     + "\n- ".join(stoplist))
    if history_titles:
        parts.append("УЖЕ ПРЕДЛОЖЕННЫЕ РАНЕЕ (не дублировать):\n- " + "\n- ".join(history_titles))
    parts.append("Схема ответа (JSON):\n" + json.dumps(RESPONSE_SCHEMA_HINT, ensure_ascii=False))
    return "\n\n".join(parts)


# запросы к базе знаний по правилам диагностики
KB_QUERIES = {
    "R1": ["доизмельчение сростков пентландита халькопирита",
           "футеровка шаровой мельницы влияние на измельчение",
           "гидроциклон классификация крупность слива насадка",
           "тонкое грохочение перед флотацией",
           "раскрытие минерала крупность измельчения"],
    "R2": ["флотация шламов тонких частиц",
           "переизмельчение потери при флотации",
           "время флотации фронт контрольная операция",
           "плотность пульпы влияние на флотацию",
           "реагентный режим собиратель расход"],
    "R3": ["время флотации извлечение кинетика",
           "реагентный режим сульфидной флотации ксантогенат",
           "аэрация пульпы флотационная машина"],
}
