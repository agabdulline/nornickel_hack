# -*- coding: utf-8 -*-
"""Доступ к доменному пакету domain_packs/flotation.yaml."""
from __future__ import annotations

from functools import lru_cache

import yaml

from .config import DOMAIN_PACK


@lru_cache(maxsize=1)
def pack() -> dict:
    return yaml.safe_load(DOMAIN_PACK.read_text(encoding="utf-8"))


def capture_rate(hypothesis_type: str) -> float:
    types = pack().get("hypothesis_types", {})
    entry = types.get(hypothesis_type) or types.get("other", {})
    return float(entry.get("capture_rate", 0.15))


def verification_profile(hypothesis_type: str) -> dict:
    profiles = pack().get("verification_profiles", {})
    return profiles.get(hypothesis_type) or profiles.get("other", {})


def equipment_list() -> list[dict]:
    return pack().get("equipment", [])


def type_equipment(hypothesis_type: str) -> list[str]:
    return pack().get("type_to_equipment", {}).get(hypothesis_type, [])
