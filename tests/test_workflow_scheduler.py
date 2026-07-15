"""WorkflowScheduler 测试

覆盖写作流程调度器的核心功能：
- 工作流创建/加载/恢复
- 阶段推进（完成/失败/跳过）
- 状态查询（摘要/完成/等待用户）
- 持久化（YAML 格式）
- 活跃工作流列表
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.workflow_scheduler import (
    WorkflowScheduler,
    WorkflowState,
    StageRecord,
    STAGE_NAMES,
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def scheduler(tmp_path):
    """创建临时目录的 scheduler"""
    novel_id = "test_novel"
    base = tmp_path / "data" / "novels" / novel_id / "data" / "workflows"
    base.mkdir(parents=True)
    return WorkflowScheduler(project_root=tmp_path, novel_id=novel_id)


# ── StageRecord 模型 ─────────────────────────────────────────


class TestStageRecord:
    def test_defaults(self):
        sr = StageRecord(name="writing")
        assert sr.status == "pending"
        assert sr.started_at == ""
        assert sr.data == {}

    def test_to_dict(self):
        sr = StageRecord(name="writing", status="completed", message="done")
        d = sr.to_dict()
        assert d["name"] == "writing"
        assert d["status"] == "completed"

    def test_from_dict(self):
        d = {"name": "review", "status": "running", "message": "审查中"}
        sr = StageRecord.from_dict(d)
        assert sr.name == "review"
        assert sr.status == "running"
        assert sr.message == "审查中"


# ── WorkflowState 模型 ───────────────────────────────────────


class TestWorkflowState:
    def test_defaults(self):
        ws = WorkflowState(novel_id="test", chapter_id="ch_001")
        assert ws.current_stage == "context_assembly"
        assert ws.review_passed is True
        assert ws.stages == []

    def test_roundtrip(self):
        ws = WorkflowState(
            novel_id="test",
            chapter_id="ch_001",
            stages=[StageRecord(name="writing", status="completed")],
        )
        d = ws.to_dict()
        ws2 = WorkflowState.from_dict(d)
        assert ws2.novel_id == ws.novel_id
        assert len(ws2.stages) == 1
        assert ws2.stages[0].status == "completed"


# ── 工作流生命周期 ───────────────────────────────────────────


class TestWorkflowLifecycle:
    def test_uses_runtime_workflow_dir(self, tmp_path):
        scheduler = WorkflowScheduler(project_root=tmp_path, novel_id="test_novel")
        assert scheduler.workflow_dir == (
            tmp_path / "data" / "novels" / "test_novel" / "data" / "workflows"
        )

    def test_create_workflow(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        assert state.novel_id == "test_novel"
        assert state.chapter_id == "ch_001"
        assert state.current_stage == "context_assembly"
        assert len(state.stages) == len(STAGE_NAMES)
        assert all(s.status == "pending" for s in state.stages)

    def test_load_workflow(self, scheduler):
        scheduler.create_workflow("ch_001")
        loaded = scheduler.load_workflow("ch_001")
        assert loaded is not None
        assert loaded.chapter_id == "ch_001"

    def test_load_nonexistent(self, scheduler):
        assert scheduler.load_workflow("ch_999") is None

    def test_load_or_create_new(self, scheduler):
        state = scheduler.load_or_create("ch_002")
        assert state.chapter_id == "ch_002"

    def test_load_or_create_existing(self, scheduler):
        scheduler.create_workflow("ch_001")
        state = scheduler.load_or_create("ch_001")
        assert state.chapter_id == "ch_001"


# ── 阶段推进 ─────────────────────────────────────────────────


class TestStageProgression:
    def test_start_stage(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.start_stage(state, "context_assembly")
        stage = next(s for s in state.stages if s.name == "context_assembly")
        assert stage.status == "running"
        assert stage.started_at != ""

    def test_complete_stage(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.complete_stage(
            state, "context_assembly", message="完成"
        )
        stage = next(s for s in state.stages if s.name == "context_assembly")
        assert stage.status == "completed"
        assert state.current_stage == "writing"  # 自动推进

    def test_complete_writing_syncs_data(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.complete_stage(
            state, "writing", data={"draft_path": "/path/to/draft.md"}
        )
        assert state.draft_path == "/path/to/draft.md"

    def test_complete_review_syncs_data(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.complete_stage(
            state,
            "review",
            data={"passed": False, "errors": ["逻辑错误"], "warnings": ["警告"]},
        )
        assert state.review_passed is False
        assert state.review_errors == ["逻辑错误"]

    def test_complete_user_confirm_syncs(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.complete_stage(
            state, "user_confirm", data={"approved": True}
        )
        assert state.user_approved is True

    def test_complete_styling_syncs(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.complete_stage(
            state, "styling", data={"polished_path": "/path/polished.md"}
        )
        assert state.polished_path == "/path/polished.md"

    def test_fail_stage(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.fail_stage(state, "writing", "生成失败")
        stage = next(s for s in state.stages if s.name == "writing")
        assert stage.status == "failed"
        assert "writing: 生成失败" in state.error

    def test_restart_failed_stage_clears_stale_error(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.fail_stage(state, "writing", "生成失败")

        state = scheduler.start_stage(state, "writing")

        stage = next(s for s in state.stages if s.name == "writing")
        assert stage.status == "running"
        assert stage.completed_at == ""
        assert stage.message == ""
        assert state.error == ""

    def test_skip_stage(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.skip_stage(state, "review", "无需审查")
        stage = next(s for s in state.stages if s.name == "review")
        assert stage.status == "skipped"
        assert state.current_stage == "user_confirm"

    def test_full_pipeline(self, scheduler):
        """走完完整的6阶段流程"""
        state = scheduler.create_workflow("ch_001")
        for stage_name in STAGE_NAMES:
            state = scheduler.complete_stage(state, stage_name, message=f"{stage_name} done")
        assert scheduler.is_complete(state)


# ── 状态查询 ─────────────────────────────────────────────────


class TestStatusQueries:
    def test_get_status_summary(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state = scheduler.complete_stage(state, "context_assembly")
        summary = scheduler.get_status_summary(state)
        assert "ch_001" in summary
        assert "✅" in summary
        assert "context_assembly" in summary

    def test_is_complete_false(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        assert scheduler.is_complete(state) is False

    def test_is_complete_true(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        for s in state.stages:
            s.status = "completed"
        assert scheduler.is_complete(state) is True

    def test_is_complete_with_skipped(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        for s in state.stages:
            s.status = "skipped"
        assert scheduler.is_complete(state) is True

    def test_is_waiting_for_user(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        state.current_stage = "user_confirm"
        assert scheduler.is_waiting_for_user(state) is True

    def test_not_waiting_for_user(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        assert scheduler.is_waiting_for_user(state) is False


# ── 活跃工作流 ───────────────────────────────────────────────


class TestActiveWorkflows:
    def test_list_active_empty(self, scheduler):
        assert scheduler.list_active_workflows() == []

    def test_list_active_with_incomplete(self, scheduler):
        scheduler.create_workflow("ch_001")
        scheduler.create_workflow("ch_002")
        active = scheduler.list_active_workflows()
        assert len(active) == 2

    def test_list_active_excludes_complete(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        for s in state.stages:
            s.status = "completed"
        scheduler._save_state(state)

        scheduler.create_workflow("ch_002")

        active = scheduler.list_active_workflows()
        assert len(active) == 1
        assert active[0].chapter_id == "ch_002"


# ── 持久化 ───────────────────────────────────────────────────


class TestPersistence:
    def test_yaml_format(self, scheduler):
        state = scheduler.create_workflow("ch_001")
        path = scheduler._state_path("ch_001")
        raw = path.read_text(encoding="utf-8")
        # 应为 YAML 格式
        data = yaml.safe_load(raw)
        assert data["novel_id"] == "test_novel"
        assert data["chapter_id"] == "ch_001"

    def test_cross_session_recovery(self, scheduler, tmp_path):
        """模拟跨会话恢复"""
        state = scheduler.create_workflow("ch_001")
        scheduler.complete_stage(state, "context_assembly", message="已组装")

        # 创建新的 scheduler（模拟新会话）
        scheduler2 = WorkflowScheduler(
            project_root=tmp_path, novel_id="test_novel"
        )
        loaded = scheduler2.load_workflow("ch_001")
        assert loaded is not None
        assert loaded.current_stage == "writing"
        ctx_stage = next(s for s in loaded.stages if s.name == "context_assembly")
        assert ctx_stage.status == "completed"
