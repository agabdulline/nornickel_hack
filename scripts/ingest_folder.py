# -*- coding: utf-8 -*-
"""Массовый инжест папки с литературой в БЗ (для больших корпусов —
«Научный клубок»: тысяча+ PDF).

Отличия от штучной загрузки:
- батч-режим: все документы парсятся и чанкуются в память, ОДНА запись
  chunks.jsonl/meta.json (штучный add_document переписывал бы 150-МБ файл
  тысячу раз);
- dense-эмбеддинг отдельным проходом с чекпоинтами (resumable: уже
  закодированные документы пропускаются по наличию векторов в chroma);
  порядок — сначала ВКЛЮЧЁННЫЕ темы, чтобы рабочий домен заработал первым;
- сканы без текстового слоя пропускаются (репортятся), OCR не запускается;
- темы/языки — автоклассификация; темы вне рабочего домена выключаются
  (enabled=false), тумблером в UI возвращаются;
- .docx читается python-docx; .doc/.xls/.pptx пропускаются.

Запуск: python scripts/ingest_folder.py <папка> [--log FILE]
        python scripts/ingest_folder.py --dense-only [--log FILE]  # догнать вектора
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("folder", nargs="?", default="")
ap.add_argument("--dense-only", action="store_true",
                help="только докатить dense-вектора для уже загруженного текста")
ap.add_argument("--log", default="")
args = ap.parse_args()
if args.log:
    sys.stdout = sys.stderr = open(args.log, "a", buffering=1, encoding="utf-8")

import fitz  # noqa: E402

from backend.app.kb.index import default_index, doc_lang, doc_topic  # noqa: E402
from backend.app.kb.ingest import detect_scan  # noqa: E402
from backend.app.kb.textnorm import chunk_pages, normalize_page_text  # noqa: E402

# рабочий домен кейса: остальные темы выключаются (тумблер вернёт)
ENABLED_TOPICS = {"флотация", "измельчение и классификация", "дробление"}


def read_pdf(path: Path) -> list[tuple[int, str]] | None:
    doc = fitz.open(path)
    try:
        if detect_scan(doc):
            return None
        return [(i + 1, normalize_page_text(doc[i].get_text("text") or ""))
                for i in range(doc.page_count)]
    finally:
        doc.close()


def read_docx(path: Path) -> list[tuple[int, str]] | None:
    try:
        import docx
        d = docx.Document(str(path))
        text = "\n".join(p.text for p in d.paragraphs)
        return [(1, normalize_page_text(text))] if len(text) > 400 else None
    except Exception:  # noqa: BLE001 — битые docx пропускаем
        return None


def ingest_text_pass(folder: Path, kb) -> None:
    files = sorted(list(folder.rglob("*.pdf")) + list(folder.rglob("*.docx")))
    print(f"файлов к разбору: {len(files)}", flush=True)
    known_ids = set(kb.docs)
    added = skipped_scan = skipped_known = failed = 0
    t0 = time.time()
    new_chunks: list[dict] = []
    for i, path in enumerate(files):
        rel = unicodedata.normalize("NFC", str(path.relative_to(folder)))
        doc_id = "kl" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
        if doc_id in known_ids:
            skipped_known += 1
            continue
        try:
            pages = read_pdf(path) if path.suffix.lower() == ".pdf" else read_docx(path)
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {rel[:80]}: {type(e).__name__}", flush=True)
            failed += 1
            continue
        if not pages:
            skipped_scan += 1
            continue
        chunks = chunk_pages(pages)
        if not chunks:
            skipped_scan += 1
            continue
        texts = [c["text"] for c in chunks]
        topic = doc_topic(texts)
        name = unicodedata.normalize("NFC", path.name)
        for n, ch in enumerate(chunks):
            new_chunks.append({
                "chunk_id": f"{doc_id}:{n}", "doc_id": doc_id, "source": name,
                "page_start": ch["page_start"], "page_end": ch["page_end"],
                "text": ch["text"],
            })
        kb.docs[doc_id] = {"source": name, "pages": len(pages), "chunks": len(chunks),
                           "status": "indexed", "lang": doc_lang(texts), "topic": topic,
                           "enabled": topic in ENABLED_TOPICS}
        added += 1
        if added % 100 == 0:
            print(f"  разобрано {added} (прошло {time.time()-t0:.0f}с)", flush=True)
    kb.chunks.extend(new_chunks)
    kb._bm25 = None
    with kb._lock:
        kb._save()
    print(f"текстовый проход: добавлено {added}, сканов пропущено {skipped_scan}, "
          f"уже было {skipped_known}, ошибок {failed}, чанков теперь {len(kb.chunks)} "
          f"({time.time()-t0:.0f}с)", flush=True)


def dense_pass(kb) -> None:
    """Докат dense-векторов: приоритет включённым, чекпоинт по документам."""
    from backend.app.kb.embed import encode, get_embedder
    model, name = get_embedder()
    if model is None:
        print("эмбеддер недоступен — dense пропущен", flush=True)
        return
    stored = kb.meta.get("embed_model")
    if stored and stored != name:
        print(f"embed_model {stored} != {name} — прерываю (нужен полный реиндекс)", flush=True)
        return
    col = kb._collection()
    ordered = sorted(kb.docs.items(),
                     key=lambda kv: (not kv[1].get("enabled", True), kv[0]))
    t0 = time.time()
    done_docs = 0
    for doc_id, meta in ordered:
        part = [c for c in kb.chunks if c["doc_id"] == doc_id]
        if not part:
            continue
        have = set(col.get(ids=[c["chunk_id"] for c in part]).get("ids") or [])
        todo = [c for c in part if c["chunk_id"] not in have]
        if not todo:
            continue
        for i in range(0, len(todo), 64):
            pp = todo[i:i + 64]
            emb = encode(model, name, [c["text"] for c in pp])
            col.add(ids=[c["chunk_id"] for c in pp],
                    embeddings=[list(map(float, e)) for e in emb],
                    metadatas=[{"source": c["source"], "page": c["page_start"]}
                               for c in pp])
        done_docs += 1
        if done_docs % 20 == 0:
            print(f"  dense: {done_docs} документов, {time.time()-t0:.0f}с, "
                  f"векторов в коллекции {col.count()}", flush=True)
    kb.meta["embed_model"] = name
    with kb._lock:
        kb._save_meta()
    print(f"dense-проход завершён: +{done_docs} документов, всего векторов "
          f"{col.count()} ({time.time()-t0:.0f}с)", flush=True)


def main():
    kb = default_index()
    print(f"старт: доков {len(kb.docs)}, чанков {len(kb.chunks)}", flush=True)
    if not args.dense_only:
        if not args.folder:
            sys.exit("укажите папку или --dense-only")
        ingest_text_pass(Path(args.folder), kb)
    dense_pass(kb)
    by_topic: dict[str, int] = {}
    for m in kb.docs.values():
        by_topic[m.get("topic", "?")] = by_topic.get(m.get("topic", "?"), 0) + 1
    print("итог по темам:", by_topic, flush=True)


if __name__ == "__main__":
    main()
