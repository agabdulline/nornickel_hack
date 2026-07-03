# -*- coding: utf-8 -*-
"""Эмбеддер Yandex AI Studio (OpenAI-совместимый /embeddings, Bearer).

Разведано scripts/smoke_yandex_embed.py + probe:
- endpoint: https://ai.api.cloud.yandex.net/v1/embeddings
- модели (Text Embeddings v2): emb://<folder>/text-embeddings-v2-doc/latest (документы),
  emb://<folder>/text-embeddings-v2-query/latest (запросы) — СТРОГО асимметрично.
  Старые URI text-search-doc/query тоже живы, но это ДРУГАЯ модель (cos векторов
  одного текста ~0.04) — смешивать их в одной коллекции нельзя;
- dim=256; БАТЧА НЕТ («Array input must contain exactly one string») —
  параллелим до 8 одновременных запросов.

Retry с экспоненциальной паузой на 429/5xx, таймаут 30с,
обрезка текста до лимита модели (~2000 токенов).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import dotenv_values

from .embedder_base import Embedder

log = logging.getLogger("kb.embedder_yandex")

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 30.0
RETRIES = 5
MAX_PARALLEL = 8
MAX_RPS = 9.0     # квота Yandex ~10 RPS — держимся чуть ниже
MAX_CHARS = 6000  # старт; на 400 (превышение токенов) текст режется ещё


class YandexEmbedder(Embedder):
    dim = 256

    def __init__(self, api_key: str | None = None, folder: str | None = None,
                 base_url: str = "https://ai.api.cloud.yandex.net/v1"):
        env = dotenv_values(ROOT / ".env", encoding="utf-8-sig")
        self.api_key = api_key or env.get("LLM_API_KEY") or ""
        if not folder:
            m = re.search(r"(?:gpt|emb)://([^/]+)/", env.get("LLM_MODEL_STRONG") or "")
            folder = m.group(1) if m else ""
        if not self.api_key or not folder:
            raise RuntimeError("нет LLM_API_KEY/folder в .env — эмбеддер Yandex недоступен")
        self.url = f"{base_url}/embeddings"
        self.doc_model = f"emb://{folder}/text-embeddings-v2-doc/latest"
        self.query_model = f"emb://{folder}/text-embeddings-v2-query/latest"
        self._rate_lock = threading.Lock()
        self._next_slot = 0.0

    def _throttle(self):
        """Глобальный лимитер: не чаще MAX_RPS запросов в секунду."""
        with self._rate_lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + 1.0 / MAX_RPS
        if wait > 0:
            time.sleep(wait)

    def _post_one(self, model: str, text: str) -> list[float]:
        cut = text[:MAX_CHARS] if text.strip() else " "
        last = None
        for attempt in range(RETRIES):
            self._throttle()
            try:
                r = httpx.post(self.url, json={"model": model, "input": [cut]},
                               timeout=TIMEOUT,
                               headers={"Authorization": f"Bearer {self.api_key}"})
                if r.status_code == 400:
                    # превышение лимита токенов (цифры/латиница токенизируются плотнее) —
                    # ретраить бессмысленно, режем текст и пробуем снова
                    cut = cut[:int(len(cut) * 0.6)] or " "
                    log.info("400 от embeddings — режу текст до %d симв.", len(cut))
                    last = RuntimeError(f"400: {r.text[:120]}")
                    continue
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}",
                                                request=r.request, response=r)
                r.raise_for_status()
                return r.json()["data"][0]["embedding"]
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last = e
                wait = 2 ** attempt
                if attempt >= 1:  # первый ретрай молча — 429 при параллелизме это норма
                    log.warning("embeddings попытка %d/%d (%s), пауза %dс",
                                attempt + 1, RETRIES, type(e).__name__, wait)
                time.sleep(wait)
        raise RuntimeError(f"Yandex embeddings недоступны после {RETRIES} попыток: {last}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # батч не поддерживается API — до 8 параллельных одиночных запросов
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
            return list(pool.map(lambda t: self._post_one(self.doc_model, t), texts))

    def embed_query(self, text: str) -> list[float]:
        return self._post_one(self.query_model, text)
