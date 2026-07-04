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
from .index import KBIndex, detect_lang

log = logging.getLogger("kb.translate")

_LOCK = threading.Lock()
_CACHE: dict[str, str] | None = None

TRANSLATE_SYSTEM = """ЦЕЛЕВОЙ ЯЗЫК: РУССКИЙ. Каждый text в ответе должен быть
написан по-русски кириллицей, независимо от языка оригинала (английский,
китайский) и национальности авторов.

Ты — технический переводчик в области обогащения полезных ископаемых.
Переведи фрагменты статей НА РУССКИЙ. Требования:
- термины отрасли переводи корректно (hydrocyclone apex/spigot — «песковая
  насадка гидроциклона»; grinding media — «мелющие тела»; cut size — «граница
  разделения»; underflow/overflow — «пески»/«слив»; термин 浮选 — «флотация»);
- числа, единицы, обозначения, DOI и ссылки на рисунки/таблицы сохраняй как есть;
- имена авторов можно оставить латиницей;
- переводи весь фрагмент, ничего не сокращая и не добавляя.
Ответ строго JSON: {"translations": [{"n": 0, "text": "перевод на русском"}, ...]}"""


def _is_ru(text: str) -> bool:
    """Перевод обязан быть русским — flash иногда путает целевой язык."""
    return detect_lang(text) == "ru"


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


def translate_texts(texts: list[str], llm: LLMClient) -> dict[str, str]:
    """Перевод произвольных коротких текстов (цитаты гипотез) -> {текст: перевод}.
    Тот же дисковый кэш (ключ — хэш текста) и та же валидация языка."""
    with _LOCK:
        cache = _load_cache()
        out: dict[str, str] = {}
        todo: list[tuple[str, str]] = []
        for t in dict.fromkeys(texts):  # уникальные, порядок сохраняем
            if not t.strip():
                continue
            k = "txt:" + hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]
            if k in cache and _is_ru(cache[k]):
                out[t] = cache[k]
            else:
                todo.append((k, t))
    if todo:
        if not getattr(llm, "enabled", False):
            return out
        got = _run_batches(todo, llm)
        with _LOCK:
            for k, tr_text in got.items():
                _load_cache()[k] = tr_text
            _save_cache()
        by_key = dict(todo)
        out.update({by_key[k]: v for k, v in got.items() if k in by_key})
    return out


def pretranslate_document(doc_id: str, kb: KBIndex, llm: LLMClient) -> int:
    """Фоновый пре-перевод всех чанков нерусского документа: наполняет кэш,
    чтобы читалка открывалась мгновенно. -> сколько чанков переведено."""
    meta = kb.docs.get(doc_id) or {}
    if meta.get("lang", "ru") == "ru":
        return 0
    cids = [c["chunk_id"] for c in kb.chunks if c["doc_id"] == doc_id]
    done = 0
    for i in range(0, len(cids), 12):
        done += len(translate_chunks(cids[i:i + 12], kb, llm))
    log.info("Пре-перевод «%s»: %d/%d фрагментов в кэше",
             meta.get("source", doc_id), done, len(cids))
    return done


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
            # кэш валидируем и при чтении: отравленная запись (не-русский
            # перевод от сбойного вызова) перезапрашивается, а не отдаётся
            if k in cache and _is_ru(cache[k]):
                out[cid] = cache[k]
            else:
                todo.append((cid, chunk["text"]))

    if todo:
        if not getattr(llm, "enabled", False):
            raise LLMUnavailable("нет LLM-ключа — перевод недоступен")
        got = _run_batches(todo, llm)
        text_by_cid = dict(todo)
        with _LOCK:
            for cid, tr_text in got.items():
                out[cid] = tr_text
                _load_cache()[_key(cid, text_by_cid[cid])] = tr_text
            _save_cache()
        log.info("Перевод: %d фрагментов новых, %d из кэша",
                 len(got), len(out) - len(got))
    return out


def _run_batches(todo: list[tuple[str, str]], llm: LLMClient) -> dict[str, str]:
    """(ключ, текст) -> {ключ: русский перевод}. Порции по 3 параллельно,
    валидация целевого языка, один ретрай для отклонённых."""

    def one_batch(batch: list[tuple[str, str]]) -> dict[str, str]:
        payload = [{"n": i, "text": t[:2500]} for i, (_k, t) in enumerate(batch)]
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

    from concurrent.futures import ThreadPoolExecutor
    batches = [todo[i:i + 3] for i in range(0, len(todo), 3)]
    with ThreadPoolExecutor(max_workers=min(4, len(batches))) as pool:
        results = list(pool.map(one_batch, batches))
    got = {k: t for res in results for k, t in res.items()}

    # переводы не по-русски отбрасываем; один ретрай для отклонённых
    bad = [k for k, t in got.items() if not _is_ru(t)]
    if bad:
        log.warning("Перевод: %d фрагментов не на русском — ретрай", len(bad))
        text_by = dict(todo)
        retry = one_batch([(k, text_by[k]) for k in bad])
        for k in bad:
            if k in retry and _is_ru(retry[k]):
                got[k] = retry[k]
            else:
                got.pop(k, None)
    return got
