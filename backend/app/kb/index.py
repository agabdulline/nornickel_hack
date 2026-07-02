# -*- coding: utf-8 -*-
"""Индекс базы знаний: чанки (jsonl) + BM25 + dense (chromadb, опционально).

Правило 8а CLAUDE.md: индекс хранит имя эмбеддинг-модели; при смене
EMBED_MODEL — автоматический реиндекс dense-части, а не тихая выдача мусора.
Гибридный поиск: reciprocal rank fusion BM25- и dense-выдач.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from rank_bm25 import BM25Plus

from ..config import STORAGE, settings
from .embed import encode, get_embedder
from .textnorm import tokenize

log = logging.getLogger("kb.index")

RRF_K = 60
CAND = 40  # кандидатов с каждой ветки до слияния


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

    def _save(self):
        self.meta["docs"] = self.docs
        self._meta_path.write_text(json.dumps(self.meta, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        with self._chunks_path.open("w", encoding="utf-8") as f:
            for c in self.chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # ---------- наполнение ----------
    def add_document(self, doc_id: str, source: str, pages: list[tuple[int, str]],
                     chunks: list[dict], status: str = "indexed") -> dict:
        """Регистрирует документ; chunks — из textnorm.chunk_pages."""
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
        self.docs[doc_id] = {"source": source, "pages": len(pages),
                             "chunks": len(chunks), "status": status}
        self._bm25 = None
        self._save()
        if status == "indexed" and self.use_dense and chunks:
            self._dense_add(doc_id)
        return self.docs[doc_id]

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
        for i in range(0, len(batch), 64):
            part = batch[i:i + 64]
            emb = encode(model, name, [c["text"] for c in part])
            col.add(ids=[c["chunk_id"] for c in part],
                    embeddings=[list(map(float, e)) for e in emb],
                    metadatas=[{"source": c["source"], "page": c["page_start"]} for c in part])
        self.meta["embed_model"] = name
        self._save()

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
        for i in range(0, len(part), 64):
            pp = part[i:i + 64]
            emb = encode(model, name, [c["text"] for c in pp])
            col.add(ids=[c["chunk_id"] for c in pp],
                    embeddings=[list(map(float, e)) for e in emb],
                    metadatas=[{"source": c["source"], "page": c["page_start"]} for c in pp])
        self.meta["embed_model"] = name
        self._save()

    # ---------- поиск ----------
    def search(self, query: str, k: int = 5) -> list[dict]:
        """Гибрид BM25 + dense через RRF. Деградирует до BM25-only без модели."""
        if not self.chunks:
            return []
        by_id = {c["chunk_id"]: c for c in self.chunks}
        ranks: dict[str, float] = {}

        self._ensure_bm25()
        q_tokens = set(tokenize(query))
        scores = self._bm25.get_scores(tokenize(query))
        # кандидаты — только чанки, содержащие хотя бы один токен запроса
        # (BM25Plus даёт положительный baseline даже без совпадений)
        cand_idx = [i for i in range(len(self.chunks)) if self._token_sets[i] & q_tokens]
        bm25_order = sorted(cand_idx, key=lambda i: -scores[i])[:CAND]
        bm25_scores = {}
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
                    got = col.query(query_embeddings=[list(map(float, q))],
                                    n_results=min(CAND, col.count()))
                    for rank, cid in enumerate(got["ids"][0]):
                        if cid in by_id:
                            ranks[cid] = ranks.get(cid, 0) + 1.0 / (RRF_K + rank + 1)
                    dense_used = True
            except Exception as e:  # noqa: BLE001
                log.warning("dense-поиск упал (%s), BM25-only", type(e).__name__)

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


_default_index: KBIndex | None = None


def default_index() -> KBIndex:
    global _default_index
    if _default_index is None:
        _default_index = KBIndex()
    return _default_index
