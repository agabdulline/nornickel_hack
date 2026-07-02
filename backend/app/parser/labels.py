# -*- coding: utf-8 -*-
"""Нормализация «гуляющих» меток: классы крупности и минеральные формы.

Метки различаются между файлами: «+71» vs «-125 +71», ведущие пробелы
(« -20 + 10»), суффикс «мкм», «Пирит» vs «Пирит/Другие Элемент 29 сульфиды».
Матчим не буквально, а по числам (regex) и по словарю синонимов из
domain_packs/flotation.yaml.
"""
from __future__ import annotations

import re
import unicodedata

from ..domain import pack

# специальные строки блока минералогии, не являющиеся формами
SPECIAL_UNALLOCATED = "__потери_расписать__"
SPECIAL_FREE_SLOT = "__свободный_слот__"

# пары чисел -> каноническая метка
_PAIR_TO_CANON = {
    (125, 71): "-125+71",
    (71, 45): "-71+45",
    (45, 20): "-45+20",
    (20, 10): "-20+10",
}


def norm_text(s) -> str:
    if s is None:
        return ""
    return unicodedata.normalize("NFC", str(s)).strip()


def normalize_size_label(raw) -> str | None:
    """«+125 мкм», « -20 + 10», «+71» -> каноническая метка или None."""
    s = norm_text(raw).lower().replace("мкм", "").strip()
    if not s:
        return None
    nums = [int(n) for n in re.findall(r"\d+", s)]
    if not nums:
        return None
    if len(nums) >= 2:
        a, b = max(nums[0], nums[1]), min(nums[0], nums[1])
        return _PAIR_TO_CANON.get((a, b), f"-{a}+{b}")
    n = nums[0]
    if "+" in s:
        # «+125» — надрешётный крупный; «+71» — верх без отдельного +125
        return "+125" if n >= 100 else ("-125+71" if n >= 45 else f"+{n}")
    if n <= 10:
        return "-10"
    return f"-{n}"


def normalize_form_label(raw) -> str | None:
    """Метка строки блока минералогии -> каноническая форма | SPECIAL_* | None."""
    s = norm_text(raw).lower()
    if not s:
        return None
    if "расписать" in s:
        return SPECIAL_UNALLOCATED
    if "свободный слот" in s:
        return SPECIAL_FREE_SLOT
    if s.startswith("итого") or "извлекаемый" in s:
        return None
    for entry in pack()["mineral_forms"]["synonyms"]:
        if re.search(entry["pattern"], s, re.IGNORECASE):
            return entry["canonical"]
    return None
