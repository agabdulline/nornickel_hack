# -*- coding: utf-8 -*-
"""Ленивая загрузка эмбеддинг-модели. Без неё KB работает на BM25-only."""
from __future__ import annotations

import logging
import os
import time

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
            log.info("Загрузка эмбеддинг-модели «%s» (кэш моделей: %s; при первом запуске — "
                     "скачивание весов, это долго)…", candidate, os.environ.get("HF_HOME"))
            t0 = time.perf_counter()
            _model = SentenceTransformer(candidate)
            _model_name = candidate
            # метод переименован в sentence-transformers 5.x — поддержим оба
            _dim_fn = (getattr(_model, "get_embedding_dimension", None)
                       or getattr(_model, "get_sentence_embedding_dimension", None))
            dim = _dim_fn() if _dim_fn else "?"
            device = str(getattr(_model, "device", "?"))
            log.info("Эмбеддинг-модель «%s» готова за %.1fс (dim=%s, device=%s)",
                     candidate, time.perf_counter() - t0, dim, device)
            if candidate != name:
                log.warning("Эмбеддинг-модель %s недоступна, fallback: %s", name, candidate)
            return _model, _model_name
        except Exception as e:  # noqa: BLE001 — деградация до BM25 важнее точной причины
            log.warning("Не удалось загрузить эмбеддинг-модель %s: %s: %s",
                        candidate, type(e).__name__, e)
    log.warning("Ни одна эмбеддинг-модель не загрузилась — KB работает на BM25-only")
    return None, None


def encode(model, name: str, texts: list[str], query: bool = False):
    """Учитывает префиксы e5-моделей."""
    if "e5" in (name or "").lower():
        prefix = "query: " if query else "passage: "
        texts = [prefix + t for t in texts]
    t0 = time.perf_counter()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    log.debug("encode: %d текст(ов)%s → %.3fс", len(texts), " (query)" if query else "",
              time.perf_counter() - t0)
    return vecs
