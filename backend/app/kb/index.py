# -*- coding: utf-8 -*-
"""Индекс базы знаний: чанки (jsonl) + BM25 + dense (chromadb, опционально).

Правило 8а CLAUDE.md: индекс хранит имя эмбеддинг-модели; при смене
EMBED_MODEL — автоматический реиндекс dense-части, а не тихая выдача мусора.
Гибридный поиск: reciprocal rank fusion BM25- и dense-выдач.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from rank_bm25 import BM25Plus

from ..config import STORAGE, settings
from .embed import encode, get_embedder
from .textnorm import tokenize

log = logging.getLogger("kb.index")

RRF_K = 60
CAND = 40  # кандидатов с каждой ветки до слияния
# вес dense-ветки в RRF: калиброван на ручной валидации корпуса (перебор
# 1.0/1.3/1.5/2.0 по 6 экспертным запросам); также поднимает кросс-языковые
# совпадения (русский запрос -> английский/китайский источник), которые
# BM25-ветка не видит вовсе
DENSE_WEIGHT = 2.0


def detect_lang(text: str) -> str:
    """Язык текста по алфавиту: ru / en / zh (для группировки источников)."""
    sample = text[:5000]
    cyr = sum(1 for ch in sample if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
    cjk = sum(1 for ch in sample if "一" <= ch <= "鿿")
    lat = sum(1 for ch in sample if "a" <= ch.lower() <= "z")
    best = max(("ru", cyr), ("zh", cjk), ("en", lat), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else "ru"


# темы источников — для группировки в БЗ и включения/выключения подборок под кейс
TOPICS = ["флотация", "измельчение и классификация", "дробление",
          "металлургия благородных металлов", "прочее"]

_TOPIC_STEMS: dict[str, tuple[str, ...]] = {
    "флотация": ("флотац", "пенн", "собират", "ксантог", "аэрац", "депресс",
                 "пирротин", "пентланд", "реагент", "flotation", "froth",
                 "collector", "depressant", "浮选", "抑制"),
    "измельчение и классификация": ("измельч", "мельниц", "классифик",
                                    "гидроциклон", "грохо", "помол", "футеров",
                                    "шаров", "насадк", "mill", "grind", "hydrocyclon",
                                    "screen", "classif", "磨矿", "分级", "旋流器", "钢球"),
    "дробление": ("дробл", "дробилк", "щеков", "конусн", "crush", "破碎"),
    "металлургия благородных металлов": ("золот", "серебр", "благородн", "упорн",
                                         "цианир", "автоклав", "gold", "silver",
                                         "refractory", "cyanid", "金", "浸出"),
}


def doc_topic(texts: list[str]) -> str:
    """Тема документа: подсчёт вхождений тематических стемов по пробам текста.
    Детерминированно; при нуле совпадений — «прочее»."""
    sample = " ".join(t[:3000] for t in texts[:12]).lower()
    if not sample.strip():
        return "прочее"
    scores = {t: sum(sample.count(s) for s in stems)
              for t, stems in _TOPIC_STEMS.items()}
    best = max(_TOPIC_STEMS, key=lambda t: scores[t])
    return best if scores[best] > 0 else "прочее"


def doc_lang(texts: list[str]) -> str:
    """Язык документа по долям алфавитов во всём тексте (сэмпл до 30 чанков,
    равномерно по документу). Голосование по чанкам здесь не работает:
    у китайских статей английские аннотации/DOI/списки литературы перетягивают
    большинство чанков в en. Иероглифы плотнее буквенного письма (нет пробелов,
    один знак ≈ слово), поэтому для zh достаточно 12% CJK-знаков."""
    if not texts:
        return "ru"
    n = len(texts)
    idxs = sorted({round(i * (n - 1) / 29) for i in range(30)}) if n > 30 else range(n)
    sample = " ".join(texts[i][:3000] for i in idxs)
    cyr = sum(1 for ch in sample if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
    cjk = sum(1 for ch in sample if "一" <= ch <= "鿿")
    lat = sum(1 for ch in sample if "a" <= ch.lower() <= "z")
    total = cyr + cjk + lat
    if total == 0:
        return "ru"
    if cjk / total > 0.12:
        return "zh"
    # лёгкий перевес кириллице: русские статьи всегда несут английские
    # аннотации/списки литературы, обратное почти не встречается
    return "ru" if cyr >= lat * 0.85 else "en"


class KBIndex:
    def __init__(self, root: Path | None = None, use_dense: bool = True):
        self.root = Path(root) if root else STORAGE / "kb"
        self.root.mkdir(parents=True, exist_ok=True)
        self.use_dense = use_dense
        self.chunks: list[dict] = []       # {chunk_id, doc_id, source, page_start, page_end, text}
        self.docs: dict[str, dict] = {}    # doc_id -> {source, pages, chunks, status}
        self.meta: dict = {}
        self._bm25: BM25Plus | None = None
        self._token_sets: list[set] | None = None
        self._chroma = None
        # мутируют из разных потоков: request-threadpool uvicorn + фоновый OCR
        self._lock = threading.RLock()
        self._load()

    # ---------- персистентность ----------
    @property
    def _chunks_path(self) -> Path:
        return self.root / "chunks.jsonl"

    @property
    def _meta_path(self) -> Path:
        return self.root / "meta.json"

    def _load(self):
        if self._meta_path.exists():
            self.meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
            self.docs = self.meta.get("docs", {})
        if self._chunks_path.exists():
            with self._chunks_path.open(encoding="utf-8") as f:
                self.chunks = [json.loads(line) for line in f if line.strip()]
        self._bm25 = None
        # миграция старых индексов: докам без lang/enabled/topic — дефолты
        changed = False
        for doc_id, d in self.docs.items():
            if "enabled" not in d:
                d["enabled"] = True
                changed = True
            if "lang" not in d:
                d["lang"] = doc_lang([c["text"] for c in self.chunks
                                      if c["doc_id"] == doc_id])
                changed = True
            if "topic" not in d:
                d["topic"] = doc_topic([c["text"] for c in self.chunks
                                        if c["doc_id"] == doc_id])
                changed = True
        if changed:
            with self._lock:
                self._save_meta()

    @staticmethod
    def _atomic_write(path: Path, text: str):
        """Запись через tmp + os.replace: параллельный читатель никогда не
        увидит усечённый файл (конкурентные _save из OCR-треда и API)."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _save_meta(self):
        """Лёгкое сохранение только meta.json (статусы, enabled, прогресс OCR) —
        не переписывает многомегабайтный chunks.jsonl."""
        self.meta["docs"] = self.docs
        self._atomic_write(self._meta_path,
                           json.dumps(self.meta, ensure_ascii=False, indent=1))

    def _save(self):
        self._save_meta()
        self._atomic_write(self._chunks_path,
                           "".join(json.dumps(c, ensure_ascii=False) + "\n"
                                   for c in self.chunks))

    # ---------- наполнение ----------
    def add_document(self, doc_id: str, source: str, pages: list[tuple[int, str]],
                     chunks: list[dict], status: str = "indexed") -> dict:
        """Регистрирует документ; chunks — из textnorm.chunk_pages."""
        with self._lock:
            self.chunks = [c for c in self.chunks if c["doc_id"] != doc_id]
            for n, ch in enumerate(chunks):
                self.chunks.append({
                    "chunk_id": f"{doc_id}:{n}",
                    "doc_id": doc_id,
                    "source": source,
                    "page_start": ch["page_start"],
                    "page_end": ch["page_end"],
                    "text": ch["text"],
                })
            prev = self.docs.get(doc_id, {})
            texts = [ch["text"] for ch in chunks]
            self.docs[doc_id] = {"source": source, "pages": len(pages),
                                 "chunks": len(chunks), "status": status,
                                 "lang": doc_lang(texts) if chunks
                                 else prev.get("lang", "ru"),
                                 "topic": doc_topic(texts) if chunks
                                 else prev.get("topic", "прочее"),
                                 "enabled": prev.get("enabled", True)}
            self._bm25 = None
            self._save()
        if status.startswith("indexed") and self.use_dense and chunks:
            self._dense_add(doc_id)
        return self.docs[doc_id]

    def delete_document(self, doc_id: str) -> bool:
        """Удаляет документ: чанки, dense-векторы, запись в docs."""
        with self._lock:
            if doc_id not in self.docs:
                return False
            part_ids = [c["chunk_id"] for c in self.chunks if c["doc_id"] == doc_id]
            self.chunks = [c for c in self.chunks if c["doc_id"] != doc_id]
            self.docs.pop(doc_id)
            self._bm25 = None
            self._save()
        if part_ids and self.use_dense:
            try:
                self._collection().delete(ids=part_ids)
            except Exception as e:  # noqa: BLE001 — dense мог быть не собран
                log.warning("dense-удаление «%s» не удалось (%s)", doc_id, type(e).__name__)
        log.info("Документ «%s» удалён (%d чанков)", doc_id, len(part_ids))
        return True

    # ---------- BM25 ----------
    def _ensure_bm25(self):
        if self._bm25 is None and self.chunks:
            toks = [tokenize(c["text"]) for c in self.chunks]
            # BM25Plus: не зануляет idf на маленьком корпусе (в отличие от Okapi)
            self._bm25 = BM25Plus(toks)
            self._token_sets = [set(t) for t in toks]

    # ---------- dense (chroma) ----------
    def _dense_ready(self) -> bool:
        if not self.use_dense:
            return False
        try:
            import chromadb  # noqa: F401
        except ImportError:
            return False
        model, name = get_embedder()
        if model is None:
            return False
        stored = self.meta.get("embed_model")
        if stored and stored != name:
            log.warning("EMBED_MODEL сменилась (%s -> %s) — авто-реиндекс dense", stored, name)
            self._dense_rebuild(model, name)
        elif not stored and self.chunks:
            self._dense_rebuild(model, name)
        return True

    def _collection(self):
        if self._chroma is None:
            import chromadb
            client = chromadb.PersistentClient(path=str(self.root / "chroma"))
            self._chroma = client.get_or_create_collection(
                "kb_chunks", metadata={"hnsw:space": "cosine"})
        return self._chroma

    def _dense_rebuild(self, model, name: str):
        import chromadb
        self._chroma = None
        shutil.rmtree(self.root / "chroma", ignore_errors=True)
        col = self._collection()
        batch = [c for c in self.chunks]
        total = len(batch)
        log.info("Dense-реиндекс: %d чанков, модель «%s»…", total, name)
        t0 = time.perf_counter()
        for i in range(0, total, 64):
            part = batch[i:i + 64]
            emb = encode(model, name, [c["text"] for c in part])
            col.add(ids=[c["chunk_id"] for c in part],
                    embeddings=[list(map(float, e)) for e in emb],
                    metadatas=[{"source": c["source"], "page": c["page_start"]} for c in part])
            log.info("  dense-реиндекс: %d/%d чанков закодировано", min(i + 64, total), total)
        self.meta["embed_model"] = name
        self._save()
        log.info("Dense-реиндекс завершён за %.1fс (%d векторов, модель «%s»)",
                 time.perf_counter() - t0, total, name)

    def _dense_add(self, doc_id: str):
        model, name = get_embedder()
        if model is None:
            return
        try:
            import chromadb  # noqa: F401
        except ImportError:
            return
        stored = self.meta.get("embed_model")
        if stored and stored != name:
            self._dense_rebuild(model, name)
            return
        col = self._collection()
        part = [c for c in self.chunks if c["doc_id"] == doc_id]
        try:
            col.delete(ids=[c["chunk_id"] for c in part])
        except Exception:  # noqa: BLE001 — ids могло не быть
            pass
        log.info("Dense-индексация документа «%s»: %d чанков, модель «%s»…",
                 doc_id, len(part), name)
        t0 = time.perf_counter()
        for i in range(0, len(part), 64):
            pp = part[i:i + 64]
            emb = encode(model, name, [c["text"] for c in pp])
            col.add(ids=[c["chunk_id"] for c in pp],
                    embeddings=[list(map(float, e)) for e in emb],
                    metadatas=[{"source": c["source"], "page": c["page_start"]} for c in pp])
        self.meta["embed_model"] = name
        self._save()
        log.info("Dense-индексация «%s» завершена за %.1fс (%d векторов)",
                 doc_id, time.perf_counter() - t0, len(part))

    # ---------- поиск ----------
    def _disabled_docs(self) -> set[str]:
        return {doc_id for doc_id, d in self.docs.items() if d.get("enabled") is False}

    def search(self, query: str, k: int = 5, dense_only: bool = False) -> list[dict]:
        """Гибрид BM25 + dense через RRF. Деградирует до BM25-only без модели.
        Выключенные пользователем источники (enabled=false) не участвуют.
        dense_only=True — только векторная ветка: кросс-языковые совпадения
        (русский запрос -> en/zh источник), которые BM25 глушит в гибриде;
        без dense-модели тихо деградирует к обычному гибриду."""
        # BM25-часть — под локом: delete_document/add_document из других
        # потоков реассайнят chunks и сбрасывают _bm25 (иначе NoneType/рассинхрон)
        skip_bm25 = dense_only and self.use_dense
        with self._lock:
            if not self.chunks:
                return []
            off = self._disabled_docs()
            off_chunks = sum(d.get("chunks", 0) for doc_id, d in self.docs.items()
                             if doc_id in off)
            by_id = {c["chunk_id"]: c for c in self.chunks if c["doc_id"] not in off}
            ranks: dict[str, float] = {}
            bm25_scores: dict[str, float] = {}
            bm25_order: list[int] = []

            if not skip_bm25:
                self._ensure_bm25()
                q_tokens = set(tokenize(query))
                scores = self._bm25.get_scores(tokenize(query))
                # кандидаты — только чанки, содержащие хотя бы один токен запроса
                # (BM25Plus даёт положительный baseline даже без совпадений)
                cand_idx = [i for i in range(len(self.chunks))
                            if self._token_sets[i] & q_tokens
                            and self.chunks[i]["doc_id"] not in off]
                bm25_order = sorted(cand_idx, key=lambda i: -scores[i])[:CAND]
                for rank, idx in enumerate(bm25_order):
                    cid = self.chunks[idx]["chunk_id"]
                    ranks[cid] = ranks.get(cid, 0) + 1.0 / (RRF_K + rank + 1)
                    bm25_scores[cid] = float(scores[idx])

        dense_used = False
        if self._dense_ready():
            model, name = get_embedder()
            try:
                col = self._collection()
                if col.count() > 0:
                    q = encode(model, name, [query], query=True)[0]
                    # chroma не фильтрует по doc_id — добираем кандидатов на
                    # объём выключенных чанков, чтобы после пост-фильтра
                    # dense-ветка не схлопнулась (выключена крупная книга)
                    got = col.query(query_embeddings=[list(map(float, q))],
                                    n_results=min(CAND + off_chunks, col.count()))
                    dense_rank = 0
                    for cid in got["ids"][0]:
                        if cid in by_id:
                            ranks[cid] = ranks.get(cid, 0) + \
                                DENSE_WEIGHT / (RRF_K + dense_rank + 1)
                            dense_rank += 1
                            if dense_rank >= CAND:
                                break
                    dense_used = True
            except Exception as e:  # noqa: BLE001
                log.warning("dense-поиск упал (%s), BM25-only", type(e).__name__)

        log.info("KB-поиск «%s»: %s, BM25-кандидатов=%d, k=%d",
                 (query[:50] + "…") if len(query) > 50 else query,
                 "гибрид BM25+dense" if dense_used else "BM25-only", len(bm25_order), k)
        top = sorted(ranks.items(), key=lambda kv: -kv[1])[:k]
        out = []
        for cid, score in top:
            c = by_id[cid]
            out.append({
                "chunk_id": cid,
                "text": c["text"],
                "source": c["source"],
                "page": c["page_start"],
                "page_end": c["page_end"],
                "score": round(score, 5),
                "bm25": round(bm25_scores.get(cid, 0.0), 3),
                "dense_used": dense_used,
            })
        return out

    def get_chunk(self, chunk_id: str) -> dict | None:
        for c in self.chunks:
            if c["chunk_id"] == chunk_id:
                return c
        return None

    def documents(self) -> list[dict]:
        return [{"doc_id": k, **v} for k, v in self.docs.items()]

    def doc_enabled(self, doc_id: str) -> bool:
        d = self.docs.get(doc_id)
        return bool(d) and d.get("enabled") is not False

    def set_doc_meta(self, doc_id: str, **fields) -> bool:
        """Обновление статуса/прогресса СУЩЕСТВУЮЩЕГО документа. Несуществующий
        (например, удалённый во время фонового OCR) не создаётся заново —
        возвращается False, вызывающий решает сам."""
        with self._lock:
            if doc_id not in self.docs:
                return False
            self.docs[doc_id].update(fields)
            self._save_meta()  # чанки не менялись — chunks.jsonl не переписываем
        return True


_default_index: KBIndex | None = None


def default_index() -> KBIndex:
    global _default_index
    if _default_index is None:
        _default_index = KBIndex()
    return _default_index
