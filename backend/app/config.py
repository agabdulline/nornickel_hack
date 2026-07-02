# -*- coding: utf-8 -*-
"""Конфигурация проекта. Единственный источник LLM-конфига — .env в корне репо."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
DATA_CASE = ROOT / "data" / "case"
STORAGE = ROOT / "storage"
DOMAIN_PACK = ROOT / "domain_packs" / "flotation.yaml"

# экономика эффекта, $/т металла (раздел 6 CLAUDE.md)
METAL_PRICE_USD = {"Ni": 16500.0, "Cu": 9000.0}


def mask_key(key: str | None) -> str:
    """Маскирует ключ для логов/экспорта: первые 5 + последние 4 символа."""
    if not key:
        return "<нет ключа>"
    if len(key) <= 12:
        return "***"
    return f"{key[:5]}...{key[-4:]}"


@dataclass
class Settings:
    llm_base_url: str = "https://gptunnel.ru/v1"
    llm_api_key: str = ""
    llm_model_strong: str = "deepseek-v4-pro"
    llm_model_fast: str = "deepseek-v4-pro"
    llm_auth_style: str = "raw"  # raw | bearer
    llm_extra_body: dict = field(default_factory=dict)
    embed_model: str = "BAAI/bge-m3"

    @property
    def has_key(self) -> bool:
        return bool(self.llm_api_key)

    def masked(self) -> dict:
        """Конфиг для логов — ключ замаскирован."""
        return {
            "LLM_BASE_URL": self.llm_base_url,
            "LLM_API_KEY": mask_key(self.llm_api_key),
            "LLM_MODEL_STRONG": self.llm_model_strong,
            "LLM_MODEL_FAST": self.llm_model_fast,
            "LLM_AUTH_STYLE": self.llm_auth_style,
            "LLM_EXTRA_BODY": self.llm_extra_body,
            "EMBED_MODEL": self.embed_model,
        }


def load_settings(env_path: Path | None = None) -> Settings:
    """Читает .env из корня репо; переменные окружения процесса имеют приоритет."""
    path = env_path or (ROOT / ".env")
    values: dict[str, str | None] = {}
    if path.exists():
        values.update(dotenv_values(path, encoding="utf-8-sig"))
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL_STRONG", "LLM_MODEL_FAST",
              "LLM_AUTH_STYLE", "LLM_EXTRA_BODY", "EMBED_MODEL"):
        if os.environ.get(k):
            values[k] = os.environ[k]

    extra_raw = (values.get("LLM_EXTRA_BODY") or "").strip()
    try:
        extra = json.loads(extra_raw) if extra_raw else {}
        if not isinstance(extra, dict):
            extra = {}
    except json.JSONDecodeError:
        extra = {}

    s = Settings(
        llm_base_url=(values.get("LLM_BASE_URL") or Settings.llm_base_url).rstrip("/"),
        llm_api_key=values.get("LLM_API_KEY") or "",
        llm_model_strong=values.get("LLM_MODEL_STRONG") or Settings.llm_model_strong,
        llm_model_fast=values.get("LLM_MODEL_FAST") or Settings.llm_model_fast,
        llm_auth_style=(values.get("LLM_AUTH_STYLE") or "raw").lower(),
        llm_extra_body=extra,
        embed_model=values.get("EMBED_MODEL") or Settings.embed_model,
    )
    return s


settings = load_settings()
