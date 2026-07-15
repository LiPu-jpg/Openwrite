from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.agent.book_state import BookStage, BookStateStore
from tools.cli import _save_chapter
from tools.init_project import init_project
from tools.novel_service import NovelApplicationService, NovelServiceError
from tools.workflow_scheduler import WorkflowScheduler


def test_service_unifies_context_sync_and_writer_contract(tmp_path: Path):
    init_project(tmp_path, "demo", "统一入口")
    calls: list[dict] = []

    def writer(root: Path, args: dict) -> dict:
        calls.append(args)
        path = _save_chapter(root, "demo", args["chapter_id"], "第一章", "正文")
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": "第一章",
            "word_count": 2,
            "draft_path": str(path),
            "truth_updates": {},
        }

    service = NovelApplicationService(tmp_path, writer_executor=writer)
    sync = service.sync()
    preview = service.context_preview("ch_001")
    result = service.write_chapter(
        {"chapter_id": "ch_001", "target_words": 800, "guidance": "雨夜开场"}
    )

    assert sync["after"]["needs_sync"] is False
    assert preview["chapter_id"] == "ch_001"
    assert "作者意图" in preview["markdown"]
    assert result["ok"] is True
    assert calls[0]["context_packet"]["chapter_id"] == "ch_001"
    assert calls[0]["target_words"] == 800
    workflow = WorkflowScheduler(tmp_path, "demo").load_workflow("ch_001")
    assert workflow is not None and workflow.current_stage == "review"
    assert BookStateStore(tmp_path, "demo").load_or_create().stage == BookStage.REVIEW_AND_REVISE


def test_service_unifies_review_persistence_and_lifecycle(tmp_path: Path):
    init_project(tmp_path, "demo")
    _save_chapter(tmp_path, "demo", "ch_001", "第一章", "正文")

    def reviewer(root: Path, args: dict) -> dict:
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": True,
            "score": 97,
            "issues": 0,
            "summary": "通过",
            "issue_details": [],
        }

    service = NovelApplicationService(tmp_path, review_executor=reviewer)
    result = service.review_chapter("latest")

    assert result["score"] == 97
    assert (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "reviews"
        / "ch_001.json"
    ).exists()
    workflow = WorkflowScheduler(tmp_path, "demo").load_workflow("ch_001")
    assert workflow is not None and workflow.current_stage == "user_confirm"
    assert BookStateStore(tmp_path, "demo").load_or_create().stage == BookStage.CHAPTER_PREFLIGHT


def test_service_continuity_and_error_contract(tmp_path: Path):
    init_project(tmp_path, "demo")
    service = NovelApplicationService(tmp_path)

    created = service.manage_foreshadowing(
        {
            "action": "create",
            "node_id": "hook_001",
            "content": "旧钟每天慢十三秒",
            "weight": 8,
            "created_at": "ch_001",
        }
    )

    assert created["continuity"]["foreshadowing"]["nodes"][0]["id"] == "hook_001"
    with pytest.raises(NovelServiceError) as invalid:
        service.context_preview("chapter-one")
    assert invalid.value.code == "INVALID_INPUT"


def test_service_unifies_document_and_source_contracts(tmp_path: Path):
    init_project(tmp_path, "demo")
    calls: list[dict] = []

    def extract_source(root: Path, args: dict) -> dict:
        calls.append(args)
        source_root = (
            root
            / "data"
            / "novels"
            / "demo"
            / "data"
            / "sources"
            / args["source_id"]
        )
        (source_root / "style").mkdir(parents=True)
        (source_root / "source.md").write_text("# 来源", encoding="utf-8")
        return {"ok": True, "source_id": args["source_id"], "focus": args["focus"]}

    service = NovelApplicationService(tmp_path, source_executor=extract_source)
    character = service.create_document(
        kind="character",
        name="林岑",
        description="调查旧信的记者。",
    )
    source_file = tmp_path / "reference.txt"
    source_file.write_text("雨落在旧钟楼上。", encoding="utf-8")
    extracted = service.extract_source(
        source_id="reference_01",
        source_file=source_file,
        focus="style",
    )
    reviewed = service.review_source("reference_01")

    assert character.name == "林岑.md"
    assert extracted["ok"] is True
    assert calls == [
        {
            "source_id": "reference_01",
            "source_file": str(source_file),
            "focus": "style",
            "chunk_size": 30000,
            "content": "雨落在旧钟楼上。",
        }
    ]
    assert reviewed["source_id"] == "reference_01"
    assert "来源审阅" in reviewed["review_report"]

    with pytest.raises(NovelServiceError) as conflict:
        service.create_document(kind="character", name="林岑")
    assert conflict.value.code == "CONFLICT"


def test_service_unifies_focus_import_workspace_and_export(tmp_path: Path):
    init_project(tmp_path, "demo", "统一书架")
    service = NovelApplicationService(tmp_path)
    service.update_focus(
        goal="让主角主动承担第一次代价",
        must_keep=["雨夜意象"],
        must_avoid=["天降解围"],
    )
    source = tmp_path / "draft.md"
    source.write_text(
        "# 第一章 雨夜\n\n门外有人。\n\n# 第二章 回声\n\n门后无人。",
        encoding="utf-8",
    )

    imported = service.import_book(source, arc_id="arc_001")
    snapshot = service.workspace_snapshot()
    output = service.export_book(tmp_path / "exports" / "demo.md", title="统一书架")

    assert service.focus_snapshot()["goal"] == "让主角主动承担第一次代价"
    assert [item["chapter_id"] for item in imported["imported"]] == [
        "ch_001",
        "ch_002",
    ]
    assert imported["next_chapter"] == "ch_003"
    assert snapshot["chapters"] == 2
    assert "第一章 雨夜" in output.read_text(encoding="utf-8")
    service.clear_focus()
    assert service.focus_snapshot()["goal"] == ""


def test_service_owns_market_radar_execution(tmp_path: Path, monkeypatch):
    import tools.agent as agent_module
    import tools.llm as llm_module
    import tools.radar as radar_module

    init_project(tmp_path, "demo")

    class FakeRadar:
        def __init__(self, context):
            self.context = context

        async def scan_market(self, *, platforms, top_n):
            assert platforms == ["novel-platform"]
            assert top_n == 1
            return SimpleNamespace(
                platform_recommendations=[
                    SimpleNamespace(
                        confidence=0.9,
                        platform="novel-platform",
                        genre="悬疑",
                        concept="钟楼误差",
                        reasoning="适合长篇连续伏笔",
                        benchmarks=["参考结构"],
                    )
                ],
                trends=["连续性悬疑"],
            )

    monkeypatch.setattr(
        llm_module.LLMConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace(model="fake-model")),
    )
    monkeypatch.setattr(llm_module, "LLMClient", lambda config: object())
    monkeypatch.setattr(
        agent_module,
        "AgentContext",
        lambda client, model, project_root: SimpleNamespace(),
    )
    monkeypatch.setattr(radar_module, "RadarAgent", FakeRadar)

    result = NovelApplicationService(tmp_path).market_radar(
        platforms=["novel-platform"], top_n=1
    )

    assert result["recommendations"][0]["concept"] == "钟楼误差"
    assert result["trends"] == ["连续性悬疑"]
