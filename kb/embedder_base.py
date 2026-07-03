# -*- coding: utf-8 -*-
"""Интерфейс эмбеддеров базы знаний. Провайдер выбирается env EMBED_PROVIDER.

ВАЖНО: интерфейс зафиксирован — реализации для других провайдеров («local»
на другом ПК) обязаны его соблюдать, не меняя сигнатур.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod


class Embedder(ABC):
    """Асимметричный эмбеддер: документы и запросы кодируются РАЗНЫМИ моделями."""

    dim: int  # размерность вектора

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Векторы для чанков корпуса (doc-модель)."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Вектор для поискового запроса (query-модель)."""


def get_embedder(provider: str | None = None) -> Embedder:
    provider = (provider or os.environ.get("EMBED_PROVIDER") or "yandex").lower()
    if provider == "yandex":
        from .embedder_yandex import YandexEmbedder
        return YandexEmbedder()
    if provider == "local":
        # TODO: локальный эмбеддер (bge-m3/e5) — реализация на другом ПК,
        # интерфейс Embedder не менять.
        raise NotImplementedError("EMBED_PROVIDER=local ещё не реализован")
    raise ValueError(f"неизвестный EMBED_PROVIDER: {provider}")
