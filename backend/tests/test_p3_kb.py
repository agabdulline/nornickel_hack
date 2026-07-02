# -*- coding: utf-8 -*-
"""P3: нормализация текста, чанкование, детектор скана, BM25-поиск (без тяжёлых моделей)."""
import pytest

from backend.app.kb.index import KBIndex
from backend.app.kb.textnorm import chunk_pages, normalize_page_text, tokenize
from backend.tests.conftest import find_case_file, requires_data


def test_normalize_hyphenation():
    assert normalize_page_text("для повыше-\nния извлечения") == "для повышения извлечения"
    assert normalize_page_text("сро-\n стков") == "сростков"


def test_normalize_spaced_letters():
    assert "Для" in normalize_page_text("Д л я повышения")
    assert "флотация" in normalize_page_text("ф л о т а ц и я идёт")
    # обычный текст не портится
    assert normalize_page_text("мельница и шар") == "мельница и шар"


def test_chunking_pages_and_overlap():
    pages = [(1, "Первый абзац про флотацию сульфидов. " * 20),
             (2, "Второй абзац про измельчение руды. " * 20),
             (3, "Третий абзац про классификацию. " * 20)]
    chunks = chunk_pages(pages, target=600, overlap=150)
    assert len(chunks) >= 3
    assert chunks[0]["page_start"] == 1
    assert chunks[-1]["page_end"] == 3
    assert all(len(c["text"]) >= 50 for c in chunks)


def test_tokenizer_stems():
    # грубый стемминг: разные формы слова дают один токен
    assert tokenize("флотация")[0] == tokenize("флотации")[0] == "флотац"
    assert tokenize("доизмельчение")[0] == tokenize("доизмельчения")[0]


def test_bm25_only_index(tmp_path):
    idx = KBIndex(root=tmp_path, use_dense=False)
    pages1 = [(1, "Доизмельчение сростков пентландита повышает извлечение никеля. " * 5)]
    pages2 = [(1, "Реагентный режим флотации шламов требует дозирования собирателя. " * 5)]
    idx.add_document("d1", "Книга А.pdf", pages1, chunk_pages(pages1, target=200))
    idx.add_document("d2", "Книга Б.pdf", pages2, chunk_pages(pages2, target=200))

    hits = idx.search("доизмельчение сростков пентландит", k=3)
    assert hits and hits[0]["source"] == "Книга А.pdf"
    assert hits[0]["page"] == 1
    assert idx.get_chunk(hits[0]["chunk_id"])["text"].startswith("Доизмельчение")

    hits2 = idx.search("реагенты для флотации шламов", k=3)
    assert hits2 and hits2[0]["source"] == "Книга Б.pdf"

    # персистентность: новый инстанс видит документы
    idx2 = KBIndex(root=tmp_path, use_dense=False)
    assert len(idx2.documents()) == 2
    assert idx2.search("пентландит", k=1)


@requires_data
def test_scan_detector_on_real_pdfs():
    import fitz
    from backend.app.kb.ingest import detect_scan

    scan = find_case_file(r"lodeyshchikov.*\.pdf$")
    text = find_case_file(r"tehnologiyaobogashcheniya.*\.pdf$")
    with fitz.open(scan) as d:
        assert detect_scan(d) is True, "455-страничный скан должен определяться как скан"
    with fitz.open(text) as d:
        assert detect_scan(d) is False


@requires_data
def test_ingest_small_real_pdf(tmp_path):
    from backend.app.kb.ingest import ingest_pdf
    idx = KBIndex(root=tmp_path, use_dense=False)
    path = find_case_file(r"tehnologiyaobogashcheniya.*\.pdf$")  # 36 страниц
    res = ingest_pdf(path, index=idx)
    assert res["status"] == "indexed"
    assert res["pages"] == 36
    assert res["chunks"] > 10
    hits = idx.search("обогащение полезных ископаемых", k=3)
    assert hits


@requires_data
def test_ingest_scan_marks_status(tmp_path):
    from backend.app.kb.ingest import ingest_pdf
    idx = KBIndex(root=tmp_path, use_dense=False)
    path = find_case_file(r"lodeyshchikov.*\.pdf$")
    res = ingest_pdf(path, index=idx)
    assert res["status"] == "scan_no_text"
    assert res["chunks"] == 0
    docs = idx.documents()
    assert docs[0]["status"] == "scan_no_text"
