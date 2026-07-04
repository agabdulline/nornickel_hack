# -*- coding: utf-8 -*-
"""Работа с оцифрованными схемами фабрик (domain_packs/flotation.yaml, секция flowsheets).

Схема оцифрована один раз из изображений кейса (Схемы флотации/, Регламенты/) —
рантайм-распознавания нет, только детерминированный справочник.

Контракт секции:
flowsheets:
  "<фабрика>":                # НОФ | ТОФ | КГМК
    source_files: [...]
    nodes:
      - id: str               # уникален внутри фабрики
        name: str             # реальное название операции со схемы
        type: crushing|grinding|classification|flotation|thickening|magnetic|gravity
        t_min: "28-32"|null   # время, мин (строка-диапазон или число)
        pct_solids: 32|null
        reagents: {"Ксантогенат": 130, "ДМДК": 0}|null   # г/т; 0 = предусмотрен, не подаётся
        equipment_positions: ["5-3"]|null
    streams:
      - {from: id, to: id|"выход", kind: feed|concentrate|tails|sands|overflow|middlings,
         gamma: null|число, beta_cu: ..., beta_ni: ..., eps_cu: ..., eps_ni: ...}
"""
from __future__ import annotations

from .domain import pack

# какие типы узлов «лечат» правила диагностики
RULE_NODE_TYPES = {
    "R1": ("grinding", "classification", "crushing"),
    "R2": ("flotation", "classification"),
    "R3": ("flotation",),
}


def detect_factory(source_name: str, plant: str = "") -> str | None:
    """КГМК | НОФ | ТОФ по имени файла/названию фабрики. НОФ вкр и мед — одна схема НОФ."""
    low = f"{source_name} {plant}".lower()
    if "кгмк" in low or "кольск" in low:
        return "КГМК"
    if "тоф" in low or "талнах" in low:
        return "ТОФ"
    if "ноф" in low or "норильск" in low or "вкр" in low or "мед" in low:
        return "НОФ"
    return None


def get_flowsheet(factory: str | None) -> dict | None:
    if not factory:
        return None
    return (pack().get("flowsheets") or {}).get(factory)


def factories_available() -> list[str]:
    return sorted((pack().get("flowsheets") or {}).keys())


def _info_richness(n: dict) -> int:
    """Сколько режимных данных знает узел — такие узлы информативнее для диагноза."""
    return sum((n.get("t_min") is not None, n.get("pct_solids") is not None,
                bool(n.get("reagents")), bool(n.get("equipment_positions"))))


def nodes_for_rule(rule_id: str, flowsheet: dict) -> list[dict]:
    """Узлы схемы, к которым привязывается диагноз: контрольные флотации в приоритете
    (R2/R3), далее по информативности режимных данных."""
    types = RULE_NODE_TYPES.get(rule_id, ())
    nodes = [n for n in flowsheet.get("nodes", []) if n.get("type") in types]
    control_first = rule_id in ("R2", "R3")
    nodes.sort(key=lambda n: (
        not (control_first and "контрольн" in (n.get("name") or "").lower()),
        -_info_richness(n)))
    return nodes


def node_regime_line(node: dict) -> str:
    """«по регламенту: <узел>, t=..., %тв=..., реагенты=...» — только известные поля."""
    parts = [node.get("name", node.get("id", "?"))]
    if node.get("t_min") is not None:
        parts.append(f"t={node['t_min']} мин")
    if node.get("pct_solids") is not None:
        parts.append(f"%тв={node['pct_solids']}")
    reagents = node.get("reagents") or {}
    if reagents:
        parts.append("реагенты: " + ", ".join(f"{k}={v} г/т" for k, v in reagents.items()))
    if node.get("equipment_positions"):
        parts.append("поз. " + ", ".join(node["equipment_positions"]))
    return "по регламенту: " + ", ".join(parts)


def summarize_for_prompt(factory: str | None) -> dict | None:
    """Выжимка flowsheet для промпта генератора: узлы с режимами + хвостовые потоки."""
    fs = get_flowsheet(factory)
    if not fs:
        return None
    nodes = []
    by_id = {}
    for n in fs.get("nodes", []):
        by_id[n["id"]] = n
        entry = {"узел": n.get("name"), "тип": n.get("type")}
        if n.get("t_min") is not None:
            entry["t_мин"] = n["t_min"]
        if n.get("pct_solids") is not None:
            entry["%тв"] = n["pct_solids"]
        if n.get("reagents"):
            entry["реагенты_г_т"] = n["reagents"]
        if n.get("equipment_positions"):
            entry["позиции"] = n["equipment_positions"]
        nodes.append(entry)
    tails = []
    for s in fs.get("streams", []):
        if s.get("kind") != "tails":
            continue
        src = by_id.get(s.get("from"), {})
        t = {"из_узла": src.get("name", s.get("from"))}
        for k in ("gamma", "beta_cu", "beta_ni", "eps_cu", "eps_ni"):
            if s.get(k) is not None:
                t[k] = s[k]
        tails.append(t)
    if not nodes:   # схема-заглушка: только исходные изображения (как у КГМК)
        return None
    return {"фабрика": factory, "узлы": nodes, "хвостовые_потоки": tails}


def zero_reagent_hints(factory: str | None, kb_index=None) -> list[dict]:
    """Реагент с расходом 0 г/т в регламенте + источники в KB о его эффективности →
    подсказка генератору предложить ввод реагента со ссылкой (кейс: ДМДК=0 на ТОФ)."""
    fs = get_flowsheet(factory)
    if not fs:
        return []
    hints = []
    for n in fs.get("nodes", []):
        for reagent, dose in (n.get("reagents") or {}).items():
            if dose != 0:
                continue
            hit_info = []
            if kb_index is not None:
                try:
                    hits = kb_index.search(f"{reagent} флотация эффективность реагент", k=2)
                    hit_info = [{"chunk_id": h["chunk_id"], "source": h["source"],
                                 "page": h.get("page")} for h in hits
                                if reagent.lower() in h["text"].lower()]
                except Exception:  # noqa: BLE001 — подсказка не должна ронять генерацию
                    hit_info = []
            if hit_info:
                hints.append({
                    "узел": n.get("name"), "реагент": reagent,
                    "подсказка": f"Реагент {reagent} предусмотрен режимной картой узла "
                                 f"«{n.get('name')}», но расход 0 г/т — не подаётся. В базе "
                                 f"знаний есть источники о его эффективности — рассмотри "
                                 f"гипотезу о вводе реагента со ссылкой на источник.",
                    "источники": hit_info,
                })
    return hints
