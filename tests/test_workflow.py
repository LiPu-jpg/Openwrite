"""Tests for the workflow system.

Tests cover:
- Workflow data models
- Workflow registry
- Director workflow integration
- Web API endpoints
"""

from pathlib import Path
from typing import Dict, Any

import pytest

# Import workflow models
from tools.models.workflow import (
    WorkflowPhase,
    WorkflowDefinition,
    WorkflowState,
    WorkflowStatus,
    WorkflowSessionContext,
)
from tools.models.intent import (
    TaskIntent,
    IntentConfidence,
    IntentDecision,
    DirectorResponse,
    ConversationSession,
    SuggestedAction,
    PhaseOption,
)


# ═══════════════════════════════════════════════════════════════════════
# Workflow Models Tests
# ═══════════════════════════════════════════════════════════════════════


class TestWorkflowPhase:
    """Test WorkflowPhase model."""

    def test_create_phase_minimal(self):
        """Test creating a phase with minimal fields."""
        phase = WorkflowPhase(phase_id="test", name="Test Phase")
        assert phase.phase_id == "test"
        assert phase.name == "Test Phase"
        assert phase.available_tools == []
        assert phase.required_tools == []
        assert phase.context_keys == []
        assert phase.auto_advance is False

    def test_create_phase_full(self):
        """Test creating a phase with all fields."""
        phase = WorkflowPhase(
            phase_id="generate",
            name="生成草稿",
            description="生成章节草稿",
            available_tools=["librarian"],
            required_tools=["librarian"],
            context_keys=["outline", "characters"],
            user_prompt="正在生成草稿...",
            questions=["是否满意?"],
            auto_advance=True,
            next_phase="review",
            conditions={"approved=true": "complete", "approved=false": "revise"},
            options=[{"id": "opt1", "label": "选项1"}],
        )
        assert phase.phase_id == "generate"
        assert len(phase.available_tools) == 1
        assert phase.auto_advance is True
        assert "approved=true" in phase.conditions


class TestWorkflowDefinition:
    """Test WorkflowDefinition model."""

    def test_create_workflow_minimal(self):
        """Test creating a workflow with minimal fields."""
        workflow = WorkflowDefinition(
            workflow_id="test_workflow",
            name="Test Workflow",
        )
        assert workflow.workflow_id == "test_workflow"
        assert workflow.name == "Test Workflow"
        assert workflow.phases == []
        assert workflow.priority == 0

    def test_create_workflow_with_phases(self):
        """Test creating a workflow with phases."""
        phases = [
            WorkflowPhase(phase_id="start", name="开始"),
            WorkflowPhase(phase_id="end", name="结束"),
        ]
        workflow = WorkflowDefinition(
            workflow_id="simple",
            name="Simple Workflow",
            phases=phases,
            entry_phase="start",
        )
        assert len(workflow.phases) == 2
        assert workflow.entry_phase == "start"

    def test_get_phase(self):
        """Test getting a phase by ID."""
        phases = [
            WorkflowPhase(phase_id="phase1", name="阶段1"),
            WorkflowPhase(phase_id="phase2", name="阶段2"),
        ]
        workflow = WorkflowDefinition(
            workflow_id="test",
            name="Test",
            phases=phases,
        )
        assert workflow.get_phase("phase1") is not None
        assert workflow.get_phase("phase1").name == "阶段1"
        assert workflow.get_phase("nonexistent") is None

    def test_get_entry_phase(self):
        """Test getting entry phase."""
        phases = [
            WorkflowPhase(phase_id="first", name="第一"),
            WorkflowPhase(phase_id="second", name="第二"),
        ]
        workflow = WorkflowDefinition(
            workflow_id="test",
            name="Test",
            phases=phases,
            entry_phase="second",
        )
        entry = workflow.get_entry_phase()
        assert entry is not None
        assert entry.phase_id == "second"

    def test_get_phase_index(self):
        """Test getting phase index."""
        phases = [
            WorkflowPhase(phase_id="a", name="A"),
            WorkflowPhase(phase_id="b", name="B"),
            WorkflowPhase(phase_id="c", name="C"),
        ]
        workflow = WorkflowDefinition(
            workflow_id="test",
            name="Test",
            phases=phases,
        )
        assert workflow.get_phase_index("a") == 0
        assert workflow.get_phase_index("b") == 1
        assert workflow.get_phase_index("c") == 2
        assert workflow.get_phase_index("d") == -1


class TestWorkflowState:
    """Test WorkflowState model."""

    def test_create_state(self):
        """Test creating a workflow state."""
        state = WorkflowState(
            workflow_id="test",
            current_phase="start",
        )
        assert state.workflow_id == "test"
        assert state.current_phase == "start"
        assert state.status == WorkflowStatus.ACTIVE
        assert state.phase_history == []

    def test_advance_to(self):
        """Test advancing to next phase."""
        state = WorkflowState(
            workflow_id="test",
            current_phase="phase1",
        )
        state.advance_to("phase2")
        assert state.current_phase == "phase2"
        assert state.phase_history == ["phase1"]

    def test_complete(self):
        """Test completing workflow."""
        state = WorkflowState(
            workflow_id="test",
            current_phase="final",
        )
        state.complete()
        assert state.status == WorkflowStatus.COMPLETED
        assert "final" in state.phase_history

    def test_fail(self):
        """Test failing workflow."""
        state = WorkflowState(
            workflow_id="test",
            current_phase="error",
        )
        state.fail("Something went wrong")
        assert state.status == WorkflowStatus.FAILED
        assert state.error_message == "Something went wrong"

    def test_pause_resume(self):
        """Test pause and resume."""
        state = WorkflowState(
            workflow_id="test",
            current_phase="mid",
        )
        state.pause()
        assert state.status == WorkflowStatus.PAUSED
        state.resume()
        assert state.status == WorkflowStatus.ACTIVE

    def test_phase_data(self):
        """Test phase data operations."""
        state = WorkflowState(
            workflow_id="test",
            current_phase="phase1",
        )
        state.set_phase_data("key1", "value1")
        assert state.get_phase_data("key1") == "value1"
        assert state.get_phase_data("nonexistent", "default") == "default"


class TestWorkflowSessionContext:
    """Test WorkflowSessionContext model."""

    def test_start_workflow(self):
        """Test starting a workflow."""
        ctx = WorkflowSessionContext()
        state = ctx.start_workflow("workflow1", "phase1")
        assert state.workflow_id == "workflow1"
        assert state.current_phase == "phase1"
        assert ctx.active_workflow == state

    def test_get_active_workflow(self):
        """Test getting active workflow."""
        ctx = WorkflowSessionContext()
        ctx.start_workflow("w1", "p1")
        active = ctx.get_active_workflow()
        assert active is not None
        assert active.workflow_id == "w1"

    def test_complete_active_workflow(self):
        """Test completing active workflow."""
        ctx = WorkflowSessionContext()
        ctx.start_workflow("w1", "p1")
        completed = ctx.complete_active_workflow()
        assert completed is not None
        assert completed.status == WorkflowStatus.COMPLETED
        assert ctx.active_workflow is None
        assert len(ctx.workflow_history) == 1


# ═══════════════════════════════════════════════════════════════════════
# Intent Models Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTaskIntent:
    """Test TaskIntent enum."""

    def test_intent_values(self):
        """Test intent enum values."""
        assert TaskIntent.UNKNOWN.value == "unknown"
        assert TaskIntent.WRITE_CHAPTER.value == "write_chapter"
        assert TaskIntent.OUTLINE_ASSIST.value == "outline_assist"
        assert TaskIntent.STYLE_COMPOSE.value == "style_compose"

    def test_intent_comparison(self):
        """Test intent comparison."""
        assert TaskIntent.WRITE_CHAPTER == TaskIntent.WRITE_CHAPTER
        assert TaskIntent.WRITE_CHAPTER != TaskIntent.OUTLINE_ASSIST


class TestIntentDecision:
    """Test IntentDecision model."""

    def test_create_decision(self):
        """Test creating an intent decision."""
        decision = IntentDecision(
            intent=TaskIntent.WRITE_CHAPTER,
            confidence=IntentConfidence.HIGH,
            confidence_score=0.9,
            matched_keywords=["写章节"],
        )
        assert decision.intent == TaskIntent.WRITE_CHAPTER
        assert decision.confidence == IntentConfidence.HIGH
        assert decision.confidence_score == 0.9

    def test_default_values(self):
        """Test default values."""
        decision = IntentDecision()
        assert decision.intent == TaskIntent.UNKNOWN
        assert decision.confidence == IntentConfidence.LOW
        assert decision.confidence_score == 0.0


class TestDirectorResponse:
    """Test DirectorResponse model."""

    def test_create_response(self):
        """Test creating a response."""
        response = DirectorResponse(
            success=True,
            message="操作成功",
            detected_intent=TaskIntent.WRITE_CHAPTER,
        )
        assert response.success is True
        assert response.message == "操作成功"

    def test_workflow_active_check(self):
        """Test is_workflow_active method."""
        response = DirectorResponse(success=True)
        assert response.is_workflow_active() is False

        state = WorkflowState(workflow_id="test", current_phase="p1")
        response = DirectorResponse(success=True, workflow_state=state)
        assert response.is_workflow_active() is True

    def test_progress_percentage(self):
        """Test progress percentage calculation."""
        response = DirectorResponse(success=True, phase_progress=0.5)
        assert response.get_progress_percentage() == 50.0


class TestConversationSession:
    """Test ConversationSession model."""

    def test_create_session(self):
        """Test creating a session."""
        session = ConversationSession(session_id="test123")
        assert session.session_id == "test123"
        assert session.message_history == []

    def test_add_message(self):
        """Test adding messages."""
        session = ConversationSession(session_id="test")
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there")
        assert len(session.message_history) == 2
        assert session.message_history[0]["role"] == "user"

    def test_workflow_state(self):
        """Test workflow state operations."""
        session = ConversationSession(session_id="test")
        state_dict = {"workflow_id": "w1", "current_phase": "p1"}
        session.set_workflow_state(state_dict)
        assert session.get_workflow_state() == state_dict
        session.clear_workflow_state()
        assert session.get_workflow_state() is None


# ═══════════════════════════════════════════════════════════════════════
# Workflow Registry Tests
# ═══════════════════════════════════════════════════════════════════════


class TestWorkflowRegistry:
    """Test WorkflowRegistry."""

    def test_register_workflow(self):
        """Test registering a workflow."""
        from tools.workflow_registry import WorkflowRegistry

        registry = WorkflowRegistry()
        registry.clear()

        workflow = WorkflowDefinition(
            workflow_id="test_reg",
            name="Test Registration",
            trigger_intents=["write_chapter"],
        )
        registry.register(workflow)

        retrieved = registry.get_workflow("test_reg")
        assert retrieved is not None
        assert retrieved.name == "Test Registration"

        registry.unregister("test_reg")

    def test_match_workflow_by_intent(self):
        """Test matching workflow by intent."""
        from tools.workflow_registry import WorkflowRegistry

        registry = WorkflowRegistry()
        registry.clear()

        workflow = WorkflowDefinition(
            workflow_id="chapter_writer",
            name="Chapter Writer",
            trigger_intents=["write_chapter"],
            trigger_keywords=["写章节"],
            requires_novel_id=False,  # 允许无 novel_id
        )
        registry.register(workflow)

        # Verify workflow is registered
        assert registry.get_workflow("chapter_writer") is not None

        # Get workflows for intent
        workflows_for_intent = registry.get_workflows_for_intent(TaskIntent.WRITE_CHAPTER)
        assert len(workflows_for_intent) > 0, "No workflows found for write_chapter intent"

        matched = registry.match_workflow(
            intent=TaskIntent.WRITE_CHAPTER,
            user_message="我想写章节",
            context={},
        )
        assert matched is not None
        assert matched.workflow_id == "chapter_writer"

        registry.unregister("chapter_writer")

    def test_load_from_yaml(self):
        """Test loading workflows from YAML."""
        from tools.workflow_registry import WorkflowRegistry

        registry = WorkflowRegistry()
        registry.clear()

        # Check if workflows directory exists
        yaml_path = Path("workflows/chapter_writing.yaml")
        if yaml_path.exists():
            count = registry.load_from_yaml(yaml_path)
            assert count >= 1
            assert registry.get_workflow("chapter_writing") is not None


# ═══════════════════════════════════════════════════════════════════════
# Director Integration Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDirectorWorkflowIntegration:
    """Test Director workflow integration."""

    def test_classify_intent(self):
        """Test intent classification."""
        from tools.agents.director import DirectorAgent

        director = DirectorAgent()

        # Test chapter writing intent
        decision = director.classify_intent("写第三章")
        assert decision.intent == TaskIntent.WRITE_CHAPTER

        # Test outline assist intent
        decision = director.classify_intent("创建大纲")
        assert decision.intent == TaskIntent.OUTLINE_ASSIST

        # Test help intent
        decision = director.classify_intent("帮助")
        assert decision.intent == TaskIntent.HELP

    def test_process_request_general_chat(self):
        """Test processing general chat request."""
        from tools.agents.director import DirectorAgent

        director = DirectorAgent()
        response = director.process_request_with_workflow("你好")

        assert response.success is True
        assert response.detected_intent == TaskIntent.GENERAL_CHAT
        assert "OpenWrite" in response.message or "创作助手" in response.message

    def test_process_request_help(self):
        """Test processing help request."""
        from tools.agents.director import DirectorAgent

        director = DirectorAgent()
        response = director.process_request_with_workflow("帮助")

        assert response.success is True
        assert response.detected_intent == TaskIntent.HELP
        assert "使用指南" in response.message or "功能" in response.message

    def test_session_continuity(self):
        """Test session continuity across requests."""
        from tools.agents.director import DirectorAgent

        director = DirectorAgent()

        # First request
        response1 = director.process_request_with_workflow(
            "你好", session_id="test_session"
        )
        assert response1.session_id == "test_session"

        # Second request with same session
        response2 = director.process_request_with_workflow(
            "帮助", session_id="test_session"
        )
        assert response2.session_id == "test_session"


# ═══════════════════════════════════════════════════════════════════════
# Web API Tests
# ═══════════════════════════════════════════════════════════════════════


class TestWorkflowWebAPI:
    """Test workflow Web API endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from fastapi.testclient import TestClient
        from tools.web import create_app

        app = create_app()
        return TestClient(app)

    def test_list_workflows(self, client):
        """Test listing workflows."""
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert "categories" in data

    def test_get_workflow_detail(self, client):
        """Test getting workflow detail."""
        # First get list to find a workflow
        list_response = client.get("/api/workflows")
        workflows = list_response.json()["workflows"]

        if workflows:
            workflow_id = workflows[0]["id"]
            response = client.get(f"/api/workflows/{workflow_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == workflow_id
            assert "phases" in data

    def test_get_nonexistent_workflow(self, client):
        """Test getting nonexistent workflow."""
        response = client.get("/api/workflows/nonexistent_workflow_12345")
        assert response.status_code == 404

    def test_chat_endpoint(self, client):
        """Test chat endpoint."""
        response = client.post(
            "/api/chat",
            json={"message": "你好"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "message" in data

    def test_workflow_registry_summary(self, client):
        """Test workflow registry summary."""
        response = client.get("/api/workflows/registry/summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_workflows" in data
