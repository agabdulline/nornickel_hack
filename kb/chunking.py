# -*- coding: utf-8 -*-
"""Чанкование корпуса базы знаний — общий код для всех эмбеддинг-провайдеров.

- PDF: pymupdf постранично (page в метаданных); сканы без текстового слоя
  (<200 симв/стр по 5 пробам) пропускаются с предупреждением.
- txt: целиком.
- Нормализация: склейка переносов, схлопывание разреженных букв, двойных пробелов.
- Чанки ~500 токенов с перехлёстом ~80 (токены оцениваются как символы/3.5 —
  для русского это консервативная оценка BPE).

Запуск как скрипт: прогон по data/kb/books + data/kb/extra ->
data/kb/chunks.jsonl + сводка по документам.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOKS_DIR = ROOT / "data" / "kb" / "books"
EXTRA_DIR = ROOT / "data" / "kb" / "extra"
OCR_DIR = ROOT / "data" / "kb" / "ocr"      # *.pages.jsonl из scripts/ocr_scan_book.py
SOURCES_CSV = ROOT / "data" / "kb" / "sources.csv"
CHUNKS_JSONL = ROOT / "data" / "kb" / "chunks.jsonl"

TARGET_TOKENS = 500
OVERLAP_TOKENS = 80
CHARS_PER_TOKEN = 3.5
TARGET_CHARS = int(TARGET_TOKENS * CHARS_PER_TOKEN)     # ~1750
OVERLAP_CHARS = int(OVERLAP_TOKENS * CHARS_PER_TOKEN)   # ~280
SCAN_CHARS_PER_PAGE = 200

_HYPHEN_RE = re.compile(r"([а-яёa-z])[\-­]\s*\n\s*([а-яёa-z])", re.IGNORECASE)
_SPACED_RE = re.compile(r"\b(?:[А-Яа-яЁёA-Za-z][ \t]+){2,}[А-Яа-яЁёA-Za-z]\b")
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")
_LAT1SUP_RE = re.compile(r"[À-ÿ]")
_CYR_RE = re.compile(r"[а-яА-ЯёЁ]")


def fix_mojibake(text: str) -> str:
    """Чинит битый текстовый слой PDF: кириллица cp1251, показанная как latin-1
    («Áîëîáîâ» -> «Болобов»). Встречается в PDF ГИАБ."""
    if not text:
        return text
    lat1 = len(_LAT1SUP_RE.findall(text))
    cyr = len(_CYR_RE.findall(text))
    if lat1 <= max(cyr, 20):
        return text
    for enc in ("cp1252", "latin-1"):
        try:
            return text.encode(enc, errors="replace").decode("cp1251", errors="replace")
        except (UnicodeError, LookupError):
            continue
    return text

# метаданные 5 учебников кейса (в sources.csv их нет)
BOOKS_META = {
    "geokniga-flotacionnye-metody-obogashcheniya": {
        "author": "В.А. Глембоцкий, В.И. Классен", "year": "1981",
        "title": "Флотационные методы обогащения", "type": "book"},
    "geokniga-metallurgiya-blagorodnyh-metallov": {
        "author": "И.Н. Масленицкий и др.", "year": "1987",
        "title": "Металлургия благородных металлов", "type": "book"},
    "geokniga-tehnologiyaobogashcheniyapoleznyhiskopaemyh": {
        "author": "—", "year": "", "title": "Технология обогащения полезных ископаемых",
        "type": "book"},
    "geokniga_lodeyshchikovvvtehnologiyaizvlecheniyazolotaiserebraizupornyh1": {
        "author": "В.В. Лодейщиков", "year": "1999",
        "title": "Технология извлечения золота и серебра из упорных руд",
        "type": "book_gold"},  # непрофильный для Cu-Ni домен — помечаем для фильтрации
    "tehnologiya_izvlecheniya_zolota_i_serebra_iz_upornogo_zolotosoderzhaschego": {
        "author": "—", "year": "",
        "title": "Технология извлечения золота и серебра из упорного золотосодержащего сырья",
        "type": "article"},
}


@dataclass
class Chunk:
    chunk_id: str
    source_file: str
    author: str
    year: str
    title: str
    type: str
    page: int | None      # первая страница чанка (PDF); None для txt
    text: str = field(repr=False, default="")


# --- фильтр служебных чанков (по итогам ручной валидации eval/kb_manual_check.md) ---
SERVICE_MARKERS = re.compile(
    r"^\s*(СПИСОК ЛИТЕРАТУРЫ|БИБЛИОГРАФИЧЕСКИЙ СПИСОК|СОДЕРЖАНИЕ|ОГЛАВЛЕНИЕ|REFERENCES|"
    r"ЛИТЕРАТУРА\b)", re.IGNORECASE | re.MULTILINE)
# для обрезки хвоста маркер ищем БЕЗ якоря строки (в PDF «СПИСОК ЛИТЕРАТУРЫ»
# часто прилипает к концу предложения) и только в верхнем регистре
_TAIL_MARKERS = re.compile(r"СПИСОК ЛИТЕРАТУРЫ|БИБЛИОГРАФИЧЕСКИЙ СПИСОК|REFERENCES\b")
_CAPTION_RE = re.compile(r"\b(Рис\.|Табл(?:ица)?\.?|Fig\.)")


def is_service_chunk(text: str) -> bool:
    """Титулы служебных разделов, таблицы/мета, сплошные подписи к рисункам.

    Пороги калиброваны на корпусе (см. eval/kb_manual_check.md): short-строки 0.8 —
    инженерный текст с формулами и жёсткими переносами не должен отсеиваться.
    """
    if SERVICE_MARKERS.search(text[:300]):
        return True
    digits = sum(c.isdigit() for c in text) / max(len(text), 1)
    if digits > 0.25:
        return True  # шапки/тела таблиц, патентная мета
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 8:
        short = sum(1 for ln in lines if len(ln.strip()) < 25)
        if short / len(lines) > 0.8:
            return True  # оглавление / столбец таблицы / патентные регистры
    caps = len(_CAPTION_RE.findall(text))
    return caps * 1000 / max(len(text), 1) > 3


def trim_service_tail(text: str) -> str:
    """Обрезает всё после «СПИСОК ЛИТЕРАТУРЫ…» — библиография бесполезна для цитат.
    Если содержательного текста до маркера мало, чанк отбраковывается по длине."""
    m = _TAIL_MARKERS.search(text)
    if m and m.start() > 100:
        return text[:m.start()].rstrip()
    return text


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = fix_mojibake(text)
    text = _HYPHEN_RE.sub(r"\1\2", text)
    text = _SPACED_RE.sub(lambda m: re.sub(r"[ \t]+", "", m.group(0)), text)
    text = _MULTISPACE_RE.sub(" ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def approx_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def _split_units(pages: list[tuple[int | None, str]]) -> list[tuple[str, int | None]]:
    """Страницы -> абзацы (текст, страница)."""
    units = []
    for page_no, text in pages:
        for p in re.split(r"\n\s*\n", text or ""):
            p = p.strip()
            if len(p) > 1:
                # гигантские абзацы режем принудительно
                while len(p) > TARGET_CHARS * 2:
                    units.append((p[:TARGET_CHARS], page_no))
                    p = p[TARGET_CHARS:]
                units.append((p, page_no))
    return units


def chunk_document(pages: list[tuple[int | None, str]], meta: dict,
                   source_file: str) -> list[Chunk]:
    """pages: [(номер страницы|None, нормализованный текст)] -> чанки."""
    units = _split_units(pages)
    chunks: list[Chunk] = []
    buf: list[tuple[str, int | None]] = []
    size = 0
    stem = Path(source_file).stem

    def flush():
        nonlocal buf, size
        text = trim_service_tail("\n".join(u for u, _ in buf).strip())
        if len(text) < 80 or is_service_chunk(text):
            buf, size = [], 0
            return
        chunks.append(Chunk(
            chunk_id=f"{stem}:{len(chunks):04d}",
            source_file=source_file,
            author=meta.get("author", ""), year=str(meta.get("year", "")),
            title=meta.get("title", ""), type=meta.get("type", ""),
            page=buf[0][1], text=text))
        tail, acc = [], 0
        for u in reversed(buf):
            if acc + len(u[0]) > OVERLAP_CHARS:
                break
            tail.insert(0, u)
            acc += len(u[0])
        buf, size = tail, acc

    for unit, page_no in units:
        buf.append((unit, page_no))
        size += len(unit)
        if size >= TARGET_CHARS:
            flush()
    flush()
    return chunks


def is_scan(doc) -> bool:
    n = doc.page_count
    if n == 0:
        return True
    idxs = sorted({min(n - 1, round(i * (n - 1) / 4)) for i in range(min(5, n))})
    total = sum(len(doc[i].get_text() or "") for i in idxs)
    return total / len(idxs) < SCAN_CHARS_PER_PAGE


def load_pdf(path: Path) -> list[tuple[int | None, str]] | None:
    import fitz
    with fitz.open(path) as doc:
        if is_scan(doc):
            return None
        return [(i + 1, normalize_text(doc[i].get_text("text") or ""))
                for i in range(doc.page_count)]


def load_txt(path: Path) -> list[tuple[int | None, str]]:
    return [(None, normalize_text(path.read_text(encoding="utf-8", errors="replace")))]


def load_ocr_jsonl(path: Path) -> list[tuple[int | None, str]]:
    """Постраничный OCR-результат Vision (scripts/ocr_scan_book.py)."""
    pages = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            pages.append((rec["page"], normalize_text(rec["text"])))
    pages.sort(key=lambda p: p[0])
    return pages


def load_sources_meta() -> dict[str, dict]:
    meta: dict[str, dict] = {}
    if SOURCES_CSV.exists():
        with SOURCES_CSV.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter=";"):
                meta[Path(row["file"]).stem] = row
    return meta


def doc_meta(path: Path, sources: dict[str, dict]) -> dict:
    if path.stem in sources:
        return sources[path.stem]
    if path.stem in BOOKS_META:
        return BOOKS_META[path.stem]
    return {"author": "", "year": "", "title": path.stem, "type": "unknown"}


def chunk_corpus(dirs: list[Path] | None = None) -> tuple[list[Chunk], dict[str, int]]:
    dirs = dirs or [BOOKS_DIR, EXTRA_DIR]
    sources = load_sources_meta()
    all_chunks: list[Chunk] = []
    per_doc: dict[str, int] = {}
    ocr_stems = {p.name.replace(".pages.jsonl", "") for p in OCR_DIR.glob("*.pages.jsonl")} \
        if OCR_DIR.exists() else set()
    for d in dirs:
        for path in sorted(d.glob("*")):
            if path.suffix.lower() not in (".pdf", ".txt"):
                continue
            if path.suffix.lower() == ".pdf":
                if path.stem in ocr_stems:
                    continue  # для скана есть OCR-результат — возьмём его ниже
                pages = load_pdf(path)
                if pages is None:
                    print(f"  SKIP (скан без текста, OCR-результата нет): {path.name}")
                    per_doc[path.name] = 0
                    continue
            else:
                pages = load_txt(path)
            chunks = chunk_document(pages, doc_meta(path, sources), path.name)
            per_doc[path.name] = len(chunks)
            all_chunks.extend(chunks)
    # OCR-нутые сканы: источник цитат — исходный PDF (имя сохраняем)
    for jf in sorted(OCR_DIR.glob("*.pages.jsonl")) if OCR_DIR.exists() else []:
        stem = jf.name.replace(".pages.jsonl", "")
        source_name = stem + ".pdf"
        pages = load_ocr_jsonl(jf)
        chunks = chunk_document(pages, doc_meta(Path(source_name), sources), source_name)
        per_doc[source_name + " (OCR)"] = len(chunks)
        all_chunks.extend(chunks)
    return all_chunks, per_doc


def main():
    chunks, per_doc = chunk_corpus()
    with CHUNKS_JSONL.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
    print("\nчанков по документам:")
    for name, n in per_doc.items():
        print(f"  {n:5d}  {name}")
    tok = sum(approx_tokens(c.text) for c in chunks)
    print(f"\nвсего чанков: {len(chunks)}, ~{tok:,} токенов -> {CHUNKS_JSONL}".replace(",", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
