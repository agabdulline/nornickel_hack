# -*- coding: utf-8 -*-
"""Индексация корпуса (data/kb/chunks.jsonl) в chromadb на эмбеддингах Yandex.

Коллекция kb_yandex_v2, persist в chroma/ (корень репо), метаданные чанков
целиком. Лог каждые 100 чанков.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402

from kb.chunking import CHUNKS_JSONL  # noqa: E402
from kb.embedder_base import get_embedder  # noqa: E402

COLLECTION = "kb_yandex_v2"
CHROMA_DIR = ROOT / "chroma"
LOG_EVERY = 100


def main():
    resume = "--resume" in sys.argv
    chunks = [json.loads(line) for line in CHUNKS_JSONL.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    print(f"чанков к индексации: {len(chunks)}")

    embedder = get_embedder("yandex")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if resume:
        col = client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
        existing: set[str] = set()
        got = col.get(include=[])
        existing.update(got["ids"])
        before = len(chunks)
        chunks = [c for c in chunks if c["chunk_id"] not in existing]
        print(f"--resume: в коллекции уже {len(existing)}, осталось {len(chunks)}/{before}")
    else:
        try:
            client.delete_collection(COLLECTION)
            print(f"старая коллекция {COLLECTION} удалена")
        except Exception:  # noqa: BLE001 — её могло не быть
            pass
        col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    t0 = time.time()
    done = 0
    B = 64  # чанков на цикл (внутри эмбеддер бьёт по своим батчам)
    for i in range(0, len(chunks), B):
        part = chunks[i:i + B]
        emb = embedder.embed_documents([c["text"] for c in part])
        col.add(
            ids=[c["chunk_id"] for c in part],
            embeddings=emb,
            documents=[c["text"] for c in part],
            metadatas=[{
                "source_file": c["source_file"], "author": c["author"] or "",
                "year": str(c["year"] or ""), "title": c["title"] or "",
                "type": c["type"] or "", "page": c["page"] if c["page"] is not None else -1,
            } for c in part],
        )
        done += len(part)
        if done % LOG_EVERY < B:
            rate = done / (time.time() - t0)
            eta = (len(chunks) - done) / rate if rate else 0
            print(f"  {done}/{len(chunks)} ({rate:.0f} чанк/с, осталось ~{eta:.0f}с)")

    dt = time.time() - t0
    print(f"\nготово: {col.count()} векторов (dim={embedder.dim}) за {dt:.0f}с "
          f"-> {CHROMA_DIR}\\{COLLECTION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
