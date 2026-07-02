# -*- coding: utf-8 -*-
"""Ленивая загрузка эмбеддинг-модели. Без неё KB работает на BM25-only."""
from __future__ import annotations

import logging
import os

from ..config import ROOT, settings

log = logging.getLogger("kb.embed")

os.environ.setdefault("HF_HOME", str(ROOT / "models_cache"))

_model = None
_model_name: str | None = None
FALLBACK_MODEL = "intfloat/multilingual-e5-small"


def get_embedder(model_name: str | None = None):
    """-> (model, имя) или (None, None), если недоступна (нет пакета/сети/памяти)."""
    global _model, _model_name
    name = model_name or settings.embed_model
    if _model is not None and _model_name == name:
        return _model, _model_name
    for candidate in (name, FALLBACK_MODEL):
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(candidate)
            _model_name = candidate
            if candidate != name:
                log.warning("Эмбеддинг-модель %s недоступна, fallback: %s", name, candidate)
            return _model, _model_name
        except Exception as e:  # noqa: BLE001 — деградация до BM25 важнее точной причины
            log.warning("Не удалось загрузить эмбеддинг-модель %s: %s", candidate, type(e).__name__)
    return None, None


def encode(model, name: str, texts: list[str], query: bool = False):
    """Учитывает префиксы e5-моделей."""
    if "e5" in (name or "").lower():
        prefix = "query: " if query else "passage: "
        texts = [prefix + t for t in texts]
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
