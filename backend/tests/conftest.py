# -*- coding: utf-8 -*-
import os
import re
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA_CASE = ROOT / "data" / "case"

# на CI данных кейса нет — такие тесты пропускаются
requires_data = pytest.mark.skipif(
    not DATA_CASE.exists(), reason="data/case отсутствует (например, на CI)"
)


def find_case_file(regex: str) -> Path | None:
    """Ищет файл в data/case по regex к NFC-нормализованному относительному пути."""
    if not DATA_CASE.exists():
        return None
    pattern = re.compile(regex)
    for entry_root, _dirs, files in os.walk(DATA_CASE):
        for f in files:
            rel = os.path.relpath(os.path.join(entry_root, f), DATA_CASE)
            rel_nfc = unicodedata.normalize("NFC", rel.replace(os.sep, "/"))
            if pattern.search(rel_nfc):
                return Path(entry_root) / f
    return None


@pytest.fixture(scope="session")
def data_case() -> Path:
    return DATA_CASE
