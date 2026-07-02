# -*- coding: utf-8 -*-
"""FastAPI-приложение «Фабрика гипотез»."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .llm import log_startup_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Фабрика гипотез", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    log_startup_config()


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_configured": settings.has_key}


def _include_routers():
    """Роутеры фаз подключаются по мере готовности модулей."""
    try:
        from .api import router as api_router
        app.include_router(api_router)
    except ImportError:
        pass


_include_routers()
