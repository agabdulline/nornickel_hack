# -*- coding: utf-8 -*-
"""Единый LLM-клиент. Все вызовы модели идут через этот модуль.

Контракт (раздел 5 CLAUDE.md):
- конфиг только из .env (см. config.load_settings);
- auth_style: raw = Authorization без "Bearer " (GPTunnel), bearer = стандарт;
- LLM_EXTRA_BODY мёржится в тело каждого запроса;
- retry 3 попытки с экспоненциальной паузой; таймауты 120с strong / 60с fast;
- без ключа: chat() бросает LLMUnavailable — вызывающий код обязан отдать мок.
Ключ никогда не пишется в логи — только маска.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from .config import Settings, mask_key, settings as default_settings

log = logging.getLogger("llm")

TIMEOUT_STRONG = 120.0
TIMEOUT_FAST = 60.0
RETRIES = 3


class LLMUnavailable(RuntimeError):
    """Нет ключа или эндпоинт стабильно недоступен."""


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or default_settings

    @property
    def enabled(self) -> bool:
        return self.s.has_key

    def _headers(self) -> dict:
        auth = self.s.llm_api_key if self.s.llm_auth_style == "raw" else f"Bearer {self.s.llm_api_key}"
        return {"Content-Type": "application/json", "Authorization": auth}

    def chat(
        self,
        messages: list[dict],
        *,
        strong: bool = False,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """Возвращает {"content": str, "usage": dict, "model": str}."""
        if not self.enabled:
            raise LLMUnavailable("LLM_API_KEY не задан — работаем на моках")

        model = self.s.llm_model_strong if strong else self.s.llm_model_fast
        timeout = TIMEOUT_STRONG if strong else TIMEOUT_FAST
        body: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        body.update(self.s.llm_extra_body)

        url = f"{self.s.llm_base_url}/chat/completions"
        last_err: Exception | None = None
        for attempt in range(RETRIES):
            try:
                resp = httpx.post(url, json=body, headers=self._headers(), timeout=timeout)
                if resp.status_code == 400 and json_mode and "response_format" in body:
                    # эндпоинт не поддерживает response_format — повтор без него
                    body.pop("response_format")
                    continue
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return {"content": content, "usage": data.get("usage", {}), "model": data.get("model", model)}
            except (httpx.TransportError, httpx.HTTPStatusError, KeyError, json.JSONDecodeError) as e:
                last_err = e
                wait = 2 ** attempt
                log.warning("LLM попытка %d/%d не удалась (%s), пауза %dс; key=%s",
                            attempt + 1, RETRIES, type(e).__name__, wait, mask_key(self.s.llm_api_key))
                if attempt < RETRIES - 1:
                    time.sleep(wait)
        raise LLMUnavailable(f"LLM недоступна после {RETRIES} попыток: {type(last_err).__name__}")


def extract_json(text: str) -> Any:
    """Достаёт JSON из ответа модели: чистый JSON, ```json```-блок или первый {...}/[...]."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"не удалось извлечь JSON из ответа модели ({len(text)} симв.)")


client = LLMClient()


def log_startup_config() -> dict:
    """Лог конфига при старте бэкенда, ключ замаскирован."""
    cfg = default_settings.masked()
    log.info("LLM-конфиг: %s", cfg)
    return cfg
