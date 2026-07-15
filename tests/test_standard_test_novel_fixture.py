from pathlib import Path
import re

import pytest
import yaml

from tools.frontmatter import parse_toml_front_matter
from tools.outline_parser import OutlineMdParser


PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOVEL_ROOT = PROJECT_ROOT / "data" / "novels" / "test_novel"

pytestmark = pytest.mark.skipif(
    not (NOVEL_ROOT / "src" / "outline.md").exists(),
    reason="标准样例已从公开仓库移除",
)


def test_test_novel_is_a_rich_standard_sample_fixture():
    background_meta, background_body = parse_toml_front_matter(
        (NOVEL_ROOT / "src" / "story" / "background.md").read_text(encoding="utf-8")
    )
    background_draft = (NOVEL_ROOT / "data" / "planning" / "background_draft.md").read_text(
        encoding="utf-8"
    )
    foundation_meta, foundation_body = parse_toml_front_matter(
        (NOVEL_ROOT / "src" / "story" / "foundation.md").read_text(encoding="utf-8")
    )
    foundation_draft = (NOVEL_ROOT / "data" / "planning" / "foundation_draft.md").read_text(
        encoding="utf-8"
    )

    assert len(str(background_meta.get("summary", ""))) >= 40
    assert len(background_body.strip()) >= 300
    assert len(str(foundation_meta.get("summary", ""))) >= 40
    assert len(foundation_body.strip()) >= 300
    assert (NOVEL_ROOT / "src" / "story" / "background.md").read_text(encoding="utf-8") == background_draft
    assert (NOVEL_ROOT / "src" / "story" / "foundation.md").read_text(encoding="utf-8") == foundation_draft

    outline = OutlineMdParser().parse(
        (NOVEL_ROOT / "src" / "outline.md").read_text(encoding="utf-8"),
        "test_novel",
    )
    assert outline.master is not None
    assert len(outline.master.summary.strip()) >= 120
    assert len(outline.chapters) >= 20
    assert len(outline.sections) >= 5

    outline_src = (NOVEL_ROOT / "src" / "outline.md").read_text(encoding="utf-8")
    outline_draft = (NOVEL_ROOT / "data" / "planning" / "outline_draft.md").read_text(
        encoding="utf-8"
    )
    assert outline_src == outline_draft
    assert "OPENWRITE:LONG_RANGE_PLAN:START" in outline_src
    assert "全书长线规划" in outline_draft
    assert "ch_351" in outline_draft
    assert "ch_520" in outline_draft

    entities = list((NOVEL_ROOT / "src" / "world" / "entities").glob("*.md"))
    assert len(entities) >= 8

    manuscript_dir = NOVEL_ROOT / "data" / "manuscript"
    manuscripts = list(manuscript_dir.glob("arc_*/*.md"))
    assert len(manuscripts) >= 6
    assert any(len(path.read_text(encoding="utf-8")) >= 3000 for path in manuscripts)

    for truth_name in ("current_state", "ledger", "relationships"):
        meta, body = parse_toml_front_matter(
            (NOVEL_ROOT / "data" / "world" / f"{truth_name}.md").read_text(encoding="utf-8")
        )
        assert meta.get("type") == "runtime_truth"
        assert len(body.strip()) >= 120

    style_fp = yaml.safe_load(
        (NOVEL_ROOT / "data" / "style" / "fingerprint.yaml").read_text(encoding="utf-8")
    )
    assert style_fp["voice"] != "待定义"
    assert style_fp["language_style"] != "待定义"
    assert style_fp["rhythm"] != "待定义"

    workflow_files = list((NOVEL_ROOT / "data" / "workflows").glob("*.yaml"))
    assert len(workflow_files) >= 4
    workflow_names = {path.name for path in workflow_files}
    assert {
        "book_state.yaml",
        "wf_ch_001.yaml",
        "wf_ch_002.yaml",
        "wf_ch_003.yaml",
        "wf_ch_004.yaml",
        "wf_ch_005.yaml",
        "wf_ch_006.yaml",
    }.issubset(workflow_names)
    assert not any(name.startswith("ch_") for name in workflow_names)
    assert "wf_ch_integ_001.yaml" not in workflow_names


def test_test_novel_outline_uses_canonical_concept_ids():
    outline_text = (NOVEL_ROOT / "src" / "outline.md").read_text(encoding="utf-8")
    concept_lines = re.findall(r"^> 涉及设定:\s*(.+)$", outline_text, re.MULTILINE)

    assert concept_lines
    for line in concept_lines:
        for item in [part.strip() for part in line.split(",") if part.strip()]:
            assert re.fullmatch(r"[a-z0-9_]+", item), item
