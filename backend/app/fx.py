# -*- coding: utf-8 -*-
"""Курс USD→RUB для отображения денежного эффекта.

Источник — ЦБ РФ: сперва JSON-зеркало cbr-xml-daily.ru, затем официальный
XML cbr.ru (оба без ключа). Успех кэшируется на 12 ч, а фолбэк — только на
5 мин (транзиентный сбой сети не «залипает» на полдня). Если оба недоступны
(закрытый контур) — курс по умолчанию из доменного пакета (rub_per_usd),
в ответе source="default".

Внутреннее хранение эффекта — USD (биржевые цены металлов, USD/т);
конвертация в ₽ — только при отображении (UI, DOCX, CSV).
"""
from __future__ import annotations

import logging
import re
import time

import httpx

from .domain import pack

log = logging.getLogger("fx")

_TTL_OK = 12 * 3600
_TTL_FAIL = 300
_cache: dict | None = None
_cached_at = 0.0
_cache_ttl = 0.0


def _from_mirror() -> dict | None:
    """JSON-зеркало cbr-xml-daily.ru."""
    r = httpx.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=4)
    r.raise_for_status()
    data = r.json()
    return {"rub_per_usd": round(float(data["Valute"]["USD"]["Value"]), 2),
            "date": str(data.get("Date", ""))[:10] or None, "source": "cbr"}


def _from_official() -> dict | None:
    """Официальный XML ЦБ (десятичная запятая, дата в атрибуте Date=ДД.ММ.ГГГГ)."""
    r = httpx.get("https://www.cbr.ru/scripts/XML_daily.asp", timeout=4)
    r.raise_for_status()
    xml = r.content.decode("windows-1251", errors="replace")
    m = re.search(r'<Valute[^>]*>\s*<NumCode>840</NumCode>.*?<Value>([\d,]+)</Value>',
                  xml, re.S)
    if not m:
        return None
    d = re.search(r'Date="(\d{2})\.(\d{2})\.(\d{4})"', xml)
    date = f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None
    return {"rub_per_usd": round(float(m.group(1).replace(",", ".")), 2),
            "date": date, "source": "cbr"}


def get_fx() -> dict:
    """-> {"rub_per_usd": float, "date": "YYYY-MM-DD"|None, "source": "cbr"|"default"}"""
    global _cache, _cached_at, _cache_ttl
    now = time.time()
    if _cache is not None and now - _cached_at < _cache_ttl:
        return _cache
    fx: dict | None = None
    for fetch in (_from_mirror, _from_official):
        try:
            fx = fetch()
            if fx:
                break
        except Exception as e:  # noqa: BLE001 — любой сбой сети/формата -> следующий источник
            log.warning("курс ЦБ: %s недоступен (%s)", fetch.__name__, type(e).__name__)
    if fx is None:
        fx = {"rub_per_usd": float(pack().get("rub_per_usd", 90)),
              "date": None, "source": "default"}
    _cache, _cached_at = fx, now
    _cache_ttl = _TTL_OK if fx["source"] == "cbr" else _TTL_FAIL
    return fx
