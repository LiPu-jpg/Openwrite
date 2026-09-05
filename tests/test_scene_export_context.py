from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

from tools.agent.writer import WriterAgent
from tools.chapter_pipeline import build_writer_payload
from tools.context_builder import ContextBuilder
from tools.context_manifest import build_context_manifest
from tools.context_protection import generation_protected_items
from tools.export_preflight import ExportPreflightService
from tools.init_project import init_project
from tools.novel_service import NovelApplicationService
from tools.novel_workspace import export_manuscript
from tools.scene_structure import SceneStructureService


def _project(root: Path, *, reversed_chapters: bool = False) -> Path:
    init_project(root, "demo", "场景导出测试")
    novel = root / "data" / "novels" / "demo"
    chapter_blocks = [
        "#### 第2章：回声\n\n第二章目标。\n",
        "#### 第1章：雨夜\n\n第一章目标。\n",
    ]
    if not reversed_chapters:
        chapter_blocks.reverse()
    (novel / "src" / "outline.md").write_text(
        "# 第一卷\n\n## 第一幕\n\n### 第一节\n\n" + "\n".join(chapter_blocks),
        encoding="utf-8",
    )
    chapters = {
        "ch_001": (
            "# 第一章 雨夜\n\n"
            "## 场景一：站台\n\n"
            "<!-- OPENWRITE:SCENE id=internal-one -->\n"
            "林岚在雨中抵达。\n\n"
            "## 场景二：钟楼\n\n"
            "旧钟敲了十三下。\n"
        ),
        "ch_002": (
            "# 第二章 回声\n\n"
            "## 场景一：来信\n\n"
            "周明拆开旧信。\n\n"
            "## 场景二：离站\n\n"
            "列车驶出海城。\n"
        ),
    }
    for chapter_id, content in chapters.items():
        path = novel / "data" / "manuscript" / "arc_001" / f"{chapter_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return novel


def _migrate(root: Path) -> dict:
    service = SceneStructureService(root, "demo")
    preview = service.migration_preview()
    return service.apply_migration(
        expected_preview_revision=preview["preview_revision"], confirm=True
    )["scene_structure"]


def test_legacy_exports_remain_exact_without_scene_sidecar(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    before = {
        path.relative_to(novel): path.read_bytes() for path in novel.rglob("*") if path.is_file()
    }

    markdown = export_manuscript(
        tmp_path, "demo", tmp_path / "legacy.md", format_name="md", title="旧书"
    )
    plain = export_manuscript(
        tmp_path, "demo", tmp_path / "legacy.txt", format_name="txt", title="旧书"
    )

    assert markdown.read_text(encoding="utf-8") == (
        "# 旧书\n\n"
        "# 第一章 雨夜\n\n## 场景一：站台\n\n"
        "<!-- OPENWRITE:SCENE id=internal-one -->\n林岚在雨中抵达。\n\n"
        "## 场景二：钟楼\n\n旧钟敲了十三下。\n\n"
        "# 第二章 回声\n\n## 场景一：来信\n\n周明拆开旧信。\n\n"
        "## 场景二：离站\n\n列车驶出海城。\n"
    )
    assert plain.read_text(encoding="utf-8").startswith("旧书\n\n第一章 雨夜\n")
    assert {
        path.relative_to(novel): path.read_bytes() for path in novel.rglob("*") if path.is_file()
    } == before
    assert not (novel / "data" / "story_structure").exists()


def test_current_scene_exports_follow_reading_and_scene_order_without_losing_chinese(
    tmp_path: Path,
) -> None:
    _project(tmp_path, reversed_chapters=True)
    surface = _migrate(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    chapter = next(item for item in surface["chapters"] if item["chapter_id"] == "ch_002")
    scenes = [
        item
        for item in surface["scenes"]
        if item["chapter"]["document_id"] == chapter["document_id"]
    ]
    surface = service.move(
        scenes[1]["scene_id"],
        target_chapter_id="ch_002",
        target_index=0,
        expected_revision=surface["revision"],
        expected_source_revision=chapter["revision"],
        expected_target_revision=chapter["revision"],
    )["scene_structure"]
    moved = next(
        item
        for item in surface["scenes"]
        if item["chapter"]["chapter_id"] == "ch_002" and item["order"] == 0
    )
    service.update_metadata(
        moved["scene_id"],
        expected_revision=surface["revision"],
        story_time_sort_key="0010",
        story_time_label="十年前",
        characters=["周明"],
        locations=["海城"],
        events=["离站"],
    )
    preflight = ExportPreflightService(tmp_path, "demo").inspect(format_name="md", purpose="backup")
    assert preflight["actual_order"] == ["ch_002", "ch_001"]
    assert preflight["scene_structure"]["status"] == "current"

    md = export_manuscript(tmp_path, "demo", tmp_path / "book.md", title="场景书")
    txt = export_manuscript(
        tmp_path, "demo", tmp_path / "book.txt", format_name="txt", title="场景书"
    )
    epub = export_manuscript(
        tmp_path, "demo", tmp_path / "book.epub", format_name="epub", title="场景书"
    )
    md_text = md.read_text(encoding="utf-8")
    txt_text = txt.read_text(encoding="utf-8")

    assert md_text.index("第二章 回声") < md_text.index("第一章 雨夜")
    assert md_text.index("列车驶出海城") < md_text.index("周明拆开旧信")
    assert "OPENWRITE:SCENE" not in md_text
    assert "OPENWRITE:SCENE" not in txt_text
    for phrase in ("林岚在雨中抵达", "旧钟敲了十三下", "周明拆开旧信", "列车驶出海城"):
        assert md_text.count(phrase) == 1
        assert txt_text.count(phrase) == 1
    with zipfile.ZipFile(epub) as archive:
        first = archive.read("OEBPS/text/chapter-0001.xhtml").decode("utf-8")
        second = archive.read("OEBPS/text/chapter-0002.xhtml").decode("utf-8")
    assert "第二章 回声" in first and "第一章 雨夜" in second
    assert first.index("列车驶出海城") < first.index("周明拆开旧信")
    assert "OPENWRITE:SCENE" not in first + second


def test_stale_scene_structure_blocks_delivery_but_backup_keeps_complete_prose(
    tmp_path: Path,
) -> None:
    novel = _project(tmp_path)
    _migrate(tmp_path)
    chapter = novel / "data" / "manuscript" / "arc_001" / "ch_001.md"
    chapter.write_text(
        chapter.read_text(encoding="utf-8") + "\n旁路新增的中文正文。\n",
        encoding="utf-8",
    )

    backup = ExportPreflightService(tmp_path, "demo").inspect(format_name="md", purpose="backup")
    delivery = ExportPreflightService(tmp_path, "demo").inspect(
        format_name="md", purpose="delivery"
    )

    assert backup["scene_structure"]["status"] == "stale"
    stale_chapter = next(
        item for item in backup["scene_structure"]["chapters"] if item["chapter_id"] == "ch_001"
    )
    assert stale_chapter["source_revision"] != stale_chapter["current_source_revision"]
    assert "SCENE_STRUCTURE_NOT_CURRENT" in {item["code"] for item in backup["warnings"]}
    assert backup["can_export"] is True
    assert "SCENE_STRUCTURE_NOT_CURRENT" in {item["code"] for item in delivery["blockers"]}
    assert delivery["can_export"] is False

    output = NovelApplicationService(tmp_path).export_book(
        tmp_path / "backup.md", format_name="md", purpose="backup"
    )
    exported = output.read_text(encoding="utf-8")
    assert "林岚在雨中抵达" in exported
    assert "旧钟敲了十三下" in exported
    assert "旁路新增的中文正文" in exported


def test_context_uses_only_current_scene_facts_and_reports_stale_exclusion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    novel = _project(tmp_path)
    surface = _migrate(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    scene = next(item for item in surface["scenes"] if item["chapter"]["chapter_id"] == "ch_001")
    service.update_metadata(
        scene["scene_id"],
        expected_revision=surface["revision"],
        story_time_sort_key="0020",
        story_time_label="雨夜当晚",
        characters=["林岚"],
        locations=["旧钟楼"],
        events=["钟响十三次"],
    )
    monkeypatch.setenv("OPENWRITE_SEMANTIC_CONTEXT", "0")

    current = ContextBuilder(tmp_path, "demo").build_generation_context("ch_001")
    scene_context = current.scene_context
    assert scene_context["status"] == "current"
    assert scene_context["freshness"] == "current"
    assert scene_context["source_revision"].startswith("sha256:")
    assert scene_context["current_source_revision"] == scene_context["source_revision"]
    assert "雨夜当晚" in current.to_prompt_context()
    assert "旧钟楼" in current.to_prompt_context()
    assert "scene_context" in generation_protected_items(current)
    writer_payload = build_writer_payload(
        context=current,
        truth=SimpleNamespace(relationships=""),
        packet={},
        guidance="",
        target_words=1200,
    )
    writer_prompt = WriterAgent._build_creative_user_prompt(
        object(), writer_payload, chapter_number=1, target_words=1200
    )
    assert "本章场景结构（按顺序落实）" in writer_prompt
    assert "钟响十三次" in writer_prompt
    manifest = build_context_manifest(
        novel,
        {"scene_context": scene_context, "compression": current.compression},
    )
    scene_item = next(item for item in manifest["items"] if item["section"] == "scene_context")
    assert scene_item["freshness"] == "current"
    assert scene_item["source_revision"] == scene_context["source_revision"]
    assert scene_item["protected"] is True

    chapter = novel / "data" / "manuscript" / "arc_001" / "ch_001.md"
    chapter.write_text(chapter.read_text(encoding="utf-8") + "\n新的旁路修改。\n", encoding="utf-8")
    stale = ContextBuilder(tmp_path, "demo").build_generation_context("ch_001")
    assert stale.scene_context["status"] == "excluded"
    assert stale.scene_context["freshness"] == "stale"
    assert stale.scene_context["source_revision"] != stale.scene_context["current_source_revision"]
    assert "本章场景结构（当前正文）" not in stale.to_prompt_context()
    assert "scene_context" not in generation_protected_items(stale)
    stale_manifest = build_context_manifest(novel, {"scene_context": stale.scene_context})
    assert not any(item["section"] == "scene_context" for item in stale_manifest["items"])
    excluded = next(
        item for item in stale_manifest["excluded_items"] if item["section"] == "scene_context"
    )
    assert excluded["reason"] == "scene_structure_not_current"
    assert excluded["freshness"] == "stale"
