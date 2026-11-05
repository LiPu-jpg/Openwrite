"""Craft rubric (craft/ai_patterns.yaml) consumption contracts.

Three separate defects let rules that the rubric declares never fire:
regex entries tested as literal substrings, a `severity` key nothing read, and
whole pattern groups with no consumer at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.agent.reviewer import (
    _matches_pattern,
    _pattern_budget,
    _pattern_severity,
)

RUBRIC = Path(__file__).parent.parent / "craft" / "ai_patterns.yaml"


@pytest.fixture(scope="module")
def rubric() -> dict:
    return yaml.safe_load(RUBRIC.read_text(encoding="utf-8"))


def test_regex_entries_fire_instead_of_being_tested_as_literals():
    """Two entries are regexes but were tested with `pattern in content`.

    "仿佛.*一样" and "如同.*一般" could therefore never match, so both simile
    cliche gates were dead.
    """
    assert _matches_pattern("仿佛.*一样", "她的笑容仿佛春天的花一样灿烂。")
    assert _matches_pattern("如同.*一般", "他的眼神如同深潭一般幽暗。")
    # A literal entry still matches literally.
    assert _matches_pattern("不禁", "他不禁愣住了。")
    assert not _matches_pattern("不禁", "他愣住了。")
    # An unusable regex is skipped, not fatal.
    assert not _matches_pattern("([unclosed", "anything")


def test_declared_severity_maps_onto_a_review_severity():
    """The `severity` key was dead data.

    The consumer hardcoded "warning", so a high-severity banned phrase and a
    low-severity cliche produced identical issues and the author could not
    triage by severity.
    """
    assert _pattern_severity({"severity": "low"}) == "info"
    assert _pattern_severity({"severity": "medium"}) == "warning"
    # `critical` is reserved for factual/continuity defects that block a chapter
    # (review_rubric.HARD_SEVERITIES), so craft high must NOT map onto it.
    assert _pattern_severity({"severity": "high"}) == "warning"
    assert _pattern_severity({}) == "warning"


def test_every_declared_group_is_consumed(rubric: dict):
    """info_dump_patterns and structure_patterns had no reader at all.

    设定堆砌, 信息倾倒 and the "首先/其次/最后" family are the gates a writer
    most needs; the rubric declared them and nothing scored them.
    """
    for group in ("banned_patterns", "cliched_patterns", "info_dump_patterns", "structure_patterns"):
        items = rubric.get(group) or []
        assert items, f"{group} is declared but empty"
        for item in items:
            assert _matches_pattern(str(item.get("pattern", "")), "x" * 50) in (True, False)


def test_detection_config_supplies_a_per_1000_char_budget(rubric: dict):
    """The per-1000-word threshold was declared and never consumed.

    Without it a single cliche in a 200-character fragment raised an AI-structure
    warning, when the rubric's intent is to report only above a density.
    """
    budget = _pattern_budget(rubric)
    assert budget is not None and budget > 0
    # A rubric without the config yields None rather than a guessed threshold.
    assert _pattern_budget({}) is None
    assert _pattern_budget({"detection_config": {}}) is None
