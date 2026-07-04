# -*- coding: utf-8 -*-
"""Перевод фрагментов источников на русский (читалка en/zh документов).

FAST-модель, батч до 8 чанков одним вызовом. Переводы кэшируются на диске
(storage/kb/translations.json) — повторное чтение мгновенно и без токенов.
Ключ кэша включает хэш текста: при переиндексации документа с изменившимся
текстом перевод пересчитывается.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading

from ..config import STORAGE
from ..llm import LLMClient, LLMUnavailable, extract_json
from .index import KBIndex

log = logging.getLogger("kb.translate")

_LOCK = threading.Lock()
_CACHE: dict[str, str] | None = None

TRANSLATE_SYSTEM = """Ты — технический переводчик в области обогащения полезных
ископаемых. Переведи фрагменты статей на русский язык. Требования:
- термины отрасли переводи корректно (hydrocyclone apex/spigot — песковая
  насадка гидроциклона; grinding media — мелющие тела; cut size — граница
  разделения; underflow/overflow — пески/слив; 浮选 — флотация и т.п.);
- числа, единицы, обозначения и ссылки на рисунки/таблицы сохраняй как есть;
- переводи весь фрагмент, ничего не сокращая и не добавляя.
Ответ строго JSON: {"translations": [{"n": 0, "text": "перевод"}, ...]}"""


def _cache_path():
    return STORAGE / "kb" / "translations.json"


def _load_cache() -> dict[str, str]:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(_cache_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CACHE = {}
    return _CACHE


def _save_cache():
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_CACHE, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _key(chunk_id: str, text: str) -> str:
    return f"{chunk_id}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]}"


def translate_chunks(chunk_ids: list[str], kb: KBIndex, llm: LLMClient) -> dict[str, str]:
    """-> {chunk_id: русский перевод}. Кэш + один батч-вызов FAST-модели
    для недостающих. Неизвестные chunk_id молча пропускаются."""
    with _LOCK:
        cache = _load_cache()
        out: dict[str, str] = {}
        todo: list[tuple[str, str]] = []  # (chunk_id, text)
        for cid in chunk_ids[:12]:
            chunk = kb.get_chunk(cid)
            if not chunk:
                continue
            k = _key(cid, chunk["text"])
            if k in cache:
                out[cid] = cache[k]
            else:
                todo.append((cid, chunk["text"]))

    if todo:
        if not getattr(llm, "enabled", False):
            raise LLMUnavailable("нет LLM-ключа — перевод недоступен")

        def one_batch(batch: list[tuple[str, str]]) -> dict[str, str]:
            payload = [{"n": i, "text": t[:2500]} for i, (_cid, t) in enumerate(batch)]
            resp = llm.chat([{"role": "system", "content": TRANSLATE_SYSTEM},
                             {"role": "user",
                              "content": json.dumps(payload, ensure_ascii=False)}],
                            strong=False, json_mode=True)
            data = extract_json(resp["content"])
            if isinstance(data, list):
                data = {"translations": data}
            res: dict[str, str] = {}
            for tr in (data.get("translations") or []):
                try:
                    i = int(tr["n"])
                    if str(tr["text"]).strip():
                        res[batch[i][0]] = str(tr["text"])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
            return res

        # порции по 3 параллельно: холодный перевод страницы читалки (6 чанков)
        # укладывается в один «длинный вызов», а не в два последовательных
        from concurrent.futures import ThreadPoolExecutor
        batches = [todo[i:i + 3] for i in range(0, len(todo), 3)]
        with ThreadPoolExecutor(max_workers=min(4, len(batches))) as pool:
            results = list(pool.map(one_batch, batches))
        got = {cid: text for res in results for cid, text in res.items()}
        text_by_cid = dict(todo)
        with _LOCK:
            for cid, tr_text in got.items():
                out[cid] = tr_text
                _load_cache()[_key(cid, text_by_cid[cid])] = tr_text
            _save_cache()
        log.info("Перевод: %d фрагментов новых, %d из кэша",
                 len(got), len(out) - len(got))
    return out
