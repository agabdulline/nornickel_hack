# -*- coding: utf-8 -*-
"""P0: скаффолд жив, конфиг безопасен, данные на месте."""
import json

from fastapi.testclient import TestClient

from backend.app.config import ROOT, load_settings, mask_key
from backend.app.main import app
from backend.tests.conftest import find_case_file, requires_data


def test_health():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_settings_loaded_and_masked():
    s = load_settings()
    assert s.llm_base_url.startswith("http")
    masked = json.dumps(s.masked(), ensure_ascii=False)
    if s.has_key and len(s.llm_api_key) > 12:
        assert s.llm_api_key not in masked, "ключ утёк в маскированный конфиг"
    assert mask_key("shds-abcdefghijklmnop").count("...") == 1
    assert mask_key("") == "<нет ключа>"


def test_env_is_gitignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [line.strip() for line in gitignore]


def test_extra_body_parsed():
    s = load_settings()
    assert isinstance(s.llm_extra_body, dict)


@requires_data
def test_case_files_present():
    assert find_case_file(r"Пример 2/Хвосты.*Вкр\.xlsx$") is not None
    assert find_case_file(r"Пример 1/Хвосты.*\.xlsx$") is not None
    assert find_case_file(r"Пример 4/Гипотезы.*\.docx$") is not None
    assert find_case_file(r"Дополнительные материалы/.*flotacionnye.*\.pdf$") is not None
