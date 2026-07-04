# -*- coding: utf-8 -*-
"""Оцифровка загруженной схемы фабрики в структуру флоушита.

Двухшаговый конвейер без vision-модели (её нет в конфиге):
1) Yandex Vision OCR снимает все подписи со схемы (узлы, режимы, реагенты);
2) FAST-модель собирает из подписей структуру nodes/streams в том же формате,
   что и оцифрованные схемы кейса (domain_packs flowsheets).
Результат — ЧЕРНОВИК (стрелки OCR не видит, последовательность приближенная,
сверху вниз) — UI помечает это и предлагает проверить.
"""
from __future__ import annotations

import json
import logging
import re

from .llm import LLMClient, LLMUnavailable, extract_json

log = logging.getLogger("flowsheet.digitize")

NODE_TYPES = ("crushing", "grinding", "classification", "flotation",
              "thickening", "magnetic", "gravity")

DIGITIZE_SYSTEM = """Ты — инженер-технолог обогатительной фабрики. Тебе передан
текст, снятый OCR со схемы цепи аппаратов / режимной карты флотации (подписи
узлов, времена, плотности, реагенты с расходами). Собери из него структуру схемы.

Правила:
- nodes: каждый технологический узел схемы. id — латиницей snake_case; name —
  как на схеме (по-русски); type — один из: crushing (дробление), grinding
  (измельчение), classification (классификация/гидроциклоны/грохочение),
  flotation (флотация/агитация/контактные чаны), thickening (сгущение),
  magnetic (магнитная сепарация), gravity (гравитация);
- у узла, где видны режимы: t_min (время, строкой как на схеме, напр. "12-16"),
  pct_solids (число, % твёрдого), reagents (объект «реагент: расход г/т»);
- streams: связи между узлами в технологической последовательности
  (сверху вниз/по нумерации операций); kind="tails" для хвостовых потоков
  (подписи «хвосты», «отвальные», «в отвал»), иначе kind="flow";
- НЕ выдумывай узлы и цифры, которых нет в тексте; непонятные обрывки пропускай.
Ответ строго JSON: {"nodes": [...], "streams": [...]}"""

# эвристика типа по имени узла — страховка от невалидного type из модели
_TYPE_HINTS = [
    (r"дробл|дроби", "crushing"),
    (r"измельч|мельниц|доизмельч|помол", "grinding"),
    (r"классифик|гидроцикл|грохо|сепарац по крупн", "classification"),
    (r"сгущ", "thickening"),
    (r"магнит", "magnetic"),
    (r"гравит|отсадк|концентрац стол", "gravity"),
    (r"флот|агитац|аэрац|контактн|перечист|пропарк", "flotation"),
]


def _norm_type(node: dict) -> str:
    t = str(node.get("type") or "").strip().lower()
    if t in NODE_TYPES:
        return t
    name = str(node.get("name") or "").lower()
    for pat, typ in _TYPE_HINTS:
        if re.search(pat, name):
            return typ
    return "flotation"


def structure_from_text(text: str, llm: LLMClient) -> dict:
    """Текст OCR -> валидированный флоушит {nodes, streams}."""
    if not getattr(llm, "enabled", False):
        raise LLMUnavailable("нет LLM-ключа — оцифровка недоступна")
    resp = llm.chat([{"role": "system", "content": DIGITIZE_SYSTEM},
                     {"role": "user", "content": text[:15000]}],
                    strong=True, json_mode=True)
    data = extract_json(resp["content"])
    if not isinstance(data, dict):
        raise ValueError("модель вернула не объект")

    nodes = []
    seen_ids: set[str] = set()
    for i, n in enumerate(data.get("nodes") or []):
        if not isinstance(n, dict) or not str(n.get("name") or "").strip():
            continue
        nid = re.sub(r"[^a-z0-9_]", "", str(n.get("id") or f"node_{i}").lower()) or f"node_{i}"
        while nid in seen_ids:
            nid += "_x"
        seen_ids.add(nid)
        node = {"id": nid, "name": str(n["name"]).strip()[:120], "type": _norm_type(n)}
        if n.get("t_min") not in (None, ""):
            node["t_min"] = str(n["t_min"])[:20]
        try:
            if n.get("pct_solids") is not None:
                node["pct_solids"] = float(n["pct_solids"])
        except (TypeError, ValueError):
            pass
        reagents = n.get("reagents")
        if isinstance(reagents, dict):
            clean = {}
            for k, v in list(reagents.items())[:10]:
                try:
                    clean[str(k)[:40]] = float(v)
                except (TypeError, ValueError):
                    continue
            if clean:
                node["reagents"] = clean
        nodes.append(node)
    if not nodes:
        raise ValueError("не удалось выделить ни одного узла схемы")

    streams = []
    for s in (data.get("streams") or []):
        if not isinstance(s, dict):
            continue
        frm, to = s.get("from"), s.get("to")
        if frm in seen_ids and (to in seen_ids or s.get("kind") == "tails"):
            streams.append({"from": frm, "to": to if to in seen_ids else frm,
                            "kind": "tails" if s.get("kind") == "tails" else "flow",
                            "name": (str(s.get("name") or "")[:80] or None)})
    log.info("Оцифровка: %d узлов, %d потоков", len(nodes), len(streams))
    return {"nodes": nodes, "streams": streams, "source_files": [],
            "digitized_from_upload": True}


def digitize_image(data: bytes, llm: LLMClient) -> dict:
    """Изображение схемы -> флоушит. OCR (~секунды) + FAST-структурирование."""
    from .kb import ocr as kb_ocr
    if not kb_ocr.available():
        raise LLMUnavailable("Vision OCR недоступен (нужен Yandex-ключ)")
    text = kb_ocr.ocr_image(data)
    if len(text.strip()) < 40:
        raise ValueError("на изображении не найден текст — это точно схема?")
    return structure_from_text(text, llm)
