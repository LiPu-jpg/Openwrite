import json
from pathlib import Path

import yaml

from tools.init_project import init_project
from tools.source_pack import SourcePackService


def test_source_pack_refresh_review_and_promotion_are_cli_independent(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")
    service = SourcePackService(tmp_path, "demo")
    source_root = service.source_root("clock_reference")
    batch_root = source_root / "extraction" / "batch_results"
    batch_root.mkdir(parents=True)
    (batch_root / "batch_000.yaml").write_text(
        yaml.safe_dump(
            {
                "findings": {
                    "craft": ["用物件偏差制造悬念", "对话保留潜台词"],
                    "author": ["克制的第三人称叙述", "短句推动节奏"],
                    "novel": [
                        "规则：钟楼每天会少走十三秒",
                        "组织：守钟人协会负责维护钟楼",
                        "时间：三年前钟楼曾经停摆",
                    ],
                    "summary": "以钟表误差推动悬疑。",
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    progress_root = source_root / "extraction"
    (progress_root / "progress.json").write_text(
        json.dumps(
            {
                "current_phase": "completed",
                "completed_count": 1,
                "pending_count": 0,
                "progress_pct": 100,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service.refresh_documents("clock_reference")
    review = service.render_review("clock_reference")
    promoted = service.promote("clock_reference", "all")

    assert promoted == ["style", "setting", "world"]
    assert "来源审阅：clock_reference" in review
    assert "进度: 100%" in review
    assert "以钟表误差推动悬疑" in (source_root / "source.md").read_text(
        encoding="utf-8"
    )
    config = yaml.safe_load((tmp_path / "novel_config.yaml").read_text(encoding="utf-8"))
    assert config["style_id"] == "clock_reference"
    novel_root = tmp_path / "data" / "novels" / "demo"
    assert "来源提取：clock_reference" in (
        novel_root / "src" / "story" / "foundation.md"
    ).read_text(encoding="utf-8")
    assert "钟楼每天会少走十三秒" in (
        novel_root / "src" / "world" / "rules.md"
    ).read_text(encoding="utf-8")
    assert list((novel_root / "src" / "world" / "entities").glob("*.md"))
