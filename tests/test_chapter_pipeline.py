from pathlib import Path
from types import SimpleNamespace

import tools.agent as agent_module
import tools.llm as llm_module
from tools.agent.book_state import BookStage, BookStateStore
from tools.chapter_memory import ChapterMemoryStore
from tools.init_project import init_project
from tools.novel_service import NovelApplicationService
from tools.review_store import ReviewStore
from tools.truth_manager import TruthFilesManager
from tools.workflow_scheduler import WorkflowScheduler


def _fake_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        llm_module.LLMConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace(model="fake-model")),
    )
    monkeypatch.setattr(llm_module, "LLMClient", lambda config: object())
    monkeypatch.setattr(
        agent_module,
        "AgentContext",
        lambda client, model, project_root: SimpleNamespace(
            client=client,
            model=model,
            project_root=project_root,
        ),
    )


def test_default_pipeline_commits_write_and_review_lifecycle(
    tmp_path: Path, monkeypatch
):
    init_project(tmp_path, "demo", "统一管线")
    _fake_llm(monkeypatch)
    writer_calls: list[dict] = []
    reviewer_calls: list[dict] = []

    class FakeWriter:
        def __init__(self, agent_ctx):
            self.agent_ctx = agent_ctx

        async def write_chapter(self, **kwargs):
            writer_calls.append(kwargs)
            return SimpleNamespace(
                title="第一章 钟差",
                content="雨落在钟楼上。",
                word_count=8,
                state_updates={
                    "current_state": "林岑已经进入钟楼。",
                    "particle_ledger": "旧信：仍未拆封。",
                    "character_matrix": "林岑 -> 守钟人：怀疑。",
                },
                chapter_summary="林岑在雨夜进入钟楼。",
                observations="钟楼每天慢十三秒。",
                token_usage={"total_tokens": 120},
            )

    class FakeReviewer:
        def __init__(self, agent_ctx):
            self.agent_ctx = agent_ctx

        async def review(self, **kwargs):
            reviewer_calls.append(kwargs)
            return SimpleNamespace(
                passed=True,
                score=96,
                summary="连续性与风格检查通过。",
                issues=[],
            )

    monkeypatch.setattr(agent_module, "WriterAgent", FakeWriter)
    monkeypatch.setattr(agent_module, "ReviewerAgent", FakeReviewer)

    service = NovelApplicationService(tmp_path)
    written = service.write_chapter(
        {
            "chapter_id": "ch_001",
            "target_words": 800,
            "guidance": "以钟声结束",
        }
    )
    reviewed = service.review_chapter("ch_001")

    assert written["ok"] is True
    assert reviewed["passed"] is True
    assert writer_calls[0]["context"]["target_words"] == 800
    assert "以钟声结束" in writer_calls[0]["context"]["external_context"]
    assert "雨落在钟楼上" in reviewer_calls[0]["content"]
    novel_root = tmp_path / "data" / "novels" / "demo"
    assert (novel_root / "data" / "manuscript" / "arc_001" / "ch_001.md").exists()
    memory = ChapterMemoryStore(tmp_path, "demo").load("ch_001")
    assert memory is not None and memory["summary"] == "林岑在雨夜进入钟楼。"
    truth = TruthFilesManager(tmp_path, "demo").load_truth_files()
    assert "林岑已经进入钟楼" in truth.current_state
    assert ReviewStore(tmp_path, "demo").load("ch_001")["score"] == 96
    workflow = WorkflowScheduler(tmp_path, "demo").load_workflow("ch_001")
    assert workflow is not None and workflow.current_stage == "user_confirm"
    state = BookStateStore(tmp_path, "demo").load_or_create()
    assert state.stage == BookStage.CHAPTER_PREFLIGHT
