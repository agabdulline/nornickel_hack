# -*- coding: utf-8 -*-
"""Разведка API эмбеддингов Yandex AI Studio для ключа из .env.

Пробуем по порядку:
1) OpenAI-совместимый POST {LLM_BASE_URL}/embeddings (Bearer);
2) нативный Foundation Models textEmbedding (Api-Key).
Нужны обе модели: text-search-doc (документы) и text-search-query (запросы).
Выводим: эндпоинт, формат авторизации, имена моделей, размерность. Ключ маскируем.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import mask_key, settings  # noqa: E402

FOLDER = (re.search(r"gpt://([^/]+)/", settings.llm_model_strong) or [None, ""])[1]
KEY = settings.llm_api_key
DOC_URI = f"emb://{FOLDER}/text-search-doc/latest"
QUERY_URI = f"emb://{FOLDER}/text-search-query/latest"
NATIVE_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"

print(f"folder: {FOLDER} | key: {mask_key(KEY)}")


def try_openai_compat() -> dict | None:
    url = f"{settings.llm_base_url}/embeddings"
    for model in (DOC_URI, QUERY_URI):
        try:
            r = httpx.post(url, timeout=30,
                           headers={"Authorization": f"Bearer {KEY}"},
                           json={"model": model, "input": ["пробный текст про флотацию"]})
            print(f"[openai-compat] {model.split('/')[-2]}: HTTP {r.status_code}")
            if r.status_code != 200:
                print("   ", r.text[:200])
                return None
            data = r.json()
            dim = len(data["data"][0]["embedding"])
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
            print(f"[openai-compat] {type(e).__name__}: {e}")
            return None
    # проверка батча: input из 2 строк
    r = httpx.post(url, timeout=30, headers={"Authorization": f"Bearer {KEY}"},
                   json={"model": DOC_URI, "input": ["раз", "два"]})
    batch = ("поддерживается (input: list)" if r.status_code == 200 else
             f"НЕТ (HTTP {r.status_code}: {r.json().get('error', {}).get('message', '')[:60]}) "
             f"— параллелим до 8 запросов")
    return {"mode": "openai-compat", "endpoint": url, "auth": "Authorization: Bearer <key>",
            "doc_model": DOC_URI, "query_model": QUERY_URI, "dim": dim, "batch": batch}


def try_native() -> dict | None:
    dim = None
    for uri in (DOC_URI, QUERY_URI):
        try:
            r = httpx.post(NATIVE_URL, timeout=30,
                           headers={"Authorization": f"Api-Key {KEY}"},
                           json={"modelUri": uri, "text": "пробный текст про флотацию"})
            print(f"[native] {uri.split('/')[-2]}: HTTP {r.status_code}")
            if r.status_code != 200:
                print("   ", r.text[:200])
                return None
            dim = len(r.json()["embedding"])
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
            print(f"[native] {type(e).__name__}: {e}")
            return None
    return {"mode": "native", "endpoint": NATIVE_URL, "auth": "Authorization: Api-Key <key>",
            "doc_model": DOC_URI, "query_model": QUERY_URI, "dim": dim,
            "batch": "нет (1 текст/запрос) — параллелим до 8"}


def main():
    result = try_openai_compat() or try_native()
    if not result:
        print("ОБА способа не работают — проверьте ключ/квоты")
        return 1
    print("\nРАБОЧАЯ КОНФИГУРАЦИЯ:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    (ROOT / "data" / "kb" / "embed_api.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
