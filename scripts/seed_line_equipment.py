# -*- coding: utf-8 -*-
"""Синхронизация оборудования линий с регламентом (онтология domain-pack).

Производственной линии НОФ проставляется полный список оборудования из
спецификации кейса (domain_packs/flotation.yaml, секция equipment) — по одной
записи на позицию; внешней лаборатории-партнёру — базовый лабораторный набор.
Идемпотентно: существующие пары (имя, позиция) не дублируются.

Запуск: python scripts/seed_line_equipment.py [--base http://127.0.0.1:8000/api]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.domain import pack  # noqa: E402

PARTNER_LAB_EQUIPMENT = [
    {"name": "Лабораторная флотомашина 237 ФЛ-А", "category": "флотация"},
    {"name": "Лабораторная шаровая мельница 40МЛ", "category": "дробление/измельчение"},
    {"name": "Ситовой анализатор с набором сит 10–200 мкм", "category": "пробоподготовка"},
    {"name": "Атомно-абсорбционный спектрометр", "category": "элементный анализ"},
]


def http(method: str, base: str, path: str, body: dict | None = None):
    url = base + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


# «Гидроциклон ГЦ-660» и «ГЦ-660» — одна единица: тип-префикс не различает
_TYPE_PREFIX = ("гидроциклон ", "мельница ", "флотомашина ", "сгуститель ",
                "грохот ", "дробилка ", "классификатор ")


def _norm(name: str) -> str:
    n = " ".join(name.lower().split())
    for p in _TYPE_PREFIX:
        if n.startswith(p):
            n = n[len(p):]
    return n


def sync_line(base: str, line: dict, wanted: list[dict]):
    lid = urllib.parse.quote(str(line["id"]), safe="")
    rows = http("GET", base, f"/equipment?line_id={lid}")

    # чистка дублей (одно нормализованное имя + одна позиция = одна запись;
    # остаётся более короткое каноническое имя)
    seen: dict[tuple, dict] = {}
    removed = 0
    for e in sorted(rows, key=lambda x: len(x["name"])):
        key = (_norm(e["name"]), (e.get("position") or "").strip())
        if key in seen:
            http("DELETE", base, f"/equipment/{urllib.parse.quote(str(e['id']), safe='')}")
            removed += 1
        else:
            seen[key] = e

    added = 0
    for w in wanted:
        key = (_norm(w["name"]), (w.get("position") or "").strip())
        if key in seen:
            continue
        seen[key] = w
        http("POST", base, "/equipment", {
            "line_id": line["id"], "name": w["name"],
            "position": w.get("position") or "",
            "category": w.get("category") or ""})
        added += 1
    print(f"  {line['name']}: +{added}, дублей убрано {removed} (итого {len(seen)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000/api")
    args = ap.parse_args()

    lines = http("GET", args.base, "/lines")
    print(f"линий: {len(lines)}")

    # производственные линии НОФ — полный регламентный список
    ontology = pack().get("equipment", [])
    plant_rows = []
    for e in ontology:
        for pos in e.get("positions") or [""]:
            plant_rows.append({"name": e["name"], "position": pos,
                               "category": e.get("type", "")})
    for line in lines:
        if line.get("kind") == "производственная линия" and "НОФ" in line["name"]:
            sync_line(args.base, line, plant_rows)

    # внешняя лаборатория-партнёр — базовый набор
    for line in lines:
        if line.get("kind") == "лаборатория" and "партнёр" in line["name"].lower():
            sync_line(args.base, line, PARTNER_LAB_EQUIPMENT)

    print("готово")


if __name__ == "__main__":
    main()
