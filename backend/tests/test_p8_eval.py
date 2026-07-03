# -*- coding: utf-8 -*-
"""P8: eval отрабатывает в мок-режиме на всех 4 примерах (без сети)."""
import json
import subprocess
import sys

from backend.tests.conftest import ROOT, requires_data


@requires_data
def test_eval_mock_runs(tmp_path):
    """python eval/run_eval.py --mock проходит все 4 примера без падений."""
    import os
    r = subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run_eval.py"), "--mock", "--no-report"],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=600,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert "режим mock" in r.stdout
    for ex in ("Пример 1", "Пример 2", "Пример 3", "Пример 4"):
        assert ex in r.stdout
    assert "parse_ok': '4/4'" in r.stdout or "'parse_ok': '4/4'" in r.stdout

    # сырые данные записаны (report.md в тесте не трогаем: --no-report)
    runs = sorted((ROOT / "eval" / "out").glob("run_*_mock.json"))
    assert runs
    data = json.loads(runs[-1].read_text(encoding="utf-8"))
    assert len(data) == 4
    assert all(x["parse_ok"] for x in data)
    # Пример 1 парсится с issues, Пример 4 — оба типа хвостов
    ex1 = next(x for x in data if x["example"] == "Пример 1")
    assert ex1["parse_issues"] > 0
    ex4 = next(x for x in data if x["example"] == "Пример 4")
    assert "породные" in ex4["tail_types"] and "пирротиновые" in ex4["tail_types"]
