# -*- coding: utf-8 -*-
"""P1: парсер эталонных гипотез из docx."""
from backend.app.parser.docx import parse_expert_hypotheses
from backend.tests.conftest import find_case_file, requires_data

EXPECTED_COUNTS = {
    r"Пример 1/Гипотезы.*\.docx$": 5,
    r"Пример 2/Гипотезы.*\.docx$": 6,
    r"Пример 3/Гипотезы.*\.docx$": 8,
    r"Пример 4/Гипотезы.*\.docx$": 8,
}


@requires_data
def test_expert_hypotheses_counts():
    for pattern, expected in EXPECTED_COUNTS.items():
        path = find_case_file(pattern)
        items = parse_expert_hypotheses(path)
        assert len(items) == expected, f"{pattern}: {len(items)} != {expected}"
        assert [x["n"] for x in items] == list(range(1, expected + 1))
        assert all(len(x["title"]) > 10 for x in items)


@requires_data
def test_example2_titles_content():
    items = parse_expert_hypotheses(find_case_file(r"Пример 2/Гипотезы.*\.docx$"))
    joined = " ".join(x["title"].lower() for x in items)
    assert "футеровки" in joined
    assert "фронта флотации" in joined
