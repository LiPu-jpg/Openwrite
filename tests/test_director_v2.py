"""Tests for SkillBasedDirector (Director V2).

测试基于 SkillRegistry 的意图识别和 ToolExecutor 的工具调用。
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# 获取项目根目录（有 skills 目录）
PROJECT_ROOT = Path(__file__).parent.parent


class TestSkillBasedDirectorInit:
    """测试 SkillBasedDirector 初始化。"""

    def test_init_default(self, tmp_path):
        """测试默认初始化。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        assert director.project_root == tmp_path
        assert director.novel_id is None
        assert director._llm_client is None
        assert director._router is None
        assert director._skill_registry is None
        assert director._tool_executor is None

    def test_init_with_novel_id(self, tmp_path):
        """测试带 novel_id 的初始化。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(
            project_root=tmp_path,
            novel_id="test_novel",
        )

        assert director.novel_id == "test_novel"


class TestSkillBasedDirectorLazyLoad:
    """测试延迟加载属性。"""

    def test_skill_registry_lazy_load(self, tmp_path):
        """测试 SkillRegistry 延迟加载。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        # 初始为 None
        assert director._skill_registry is None

        # 访问属性时加载
        registry = director.skill_registry
        assert registry is not None
        assert director._skill_registry is registry

    def test_tool_executor_lazy_load(self, tmp_path):
        """测试 ToolExecutor 延迟加载。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(
            project_root=tmp_path,
            novel_id="test_novel",
        )

        # 初始为 None
        assert director._tool_executor is None

        # 访问属性时加载
        executor = director.tool_executor
        assert executor is not None
        assert director._tool_executor is executor

    def test_main_prompt_lazy_load(self, tmp_path):
        """测试主提示词延迟加载。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        # 初始为 None
        assert director._main_prompt is None

        # 访问属性时加载（使用默认提示词，因为没有配置文件）
        prompt = director.main_prompt
        assert prompt is not None
        assert "OpenWrite" in prompt

    def test_main_prompt_from_config(self, tmp_path):
        """测试从配置文件加载主提示词。"""
        from tools.agents.director_v2 import SkillBasedDirector

        # 创建配置文件
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        prompt_file = config_dir / "main_prompt.md"
        prompt_file.write_text("# Custom Prompt\n\nThis is a custom prompt.")

        director = SkillBasedDirector(project_root=tmp_path)
        prompt = director.main_prompt

        assert "Custom Prompt" in prompt



@pytest.mark.skip(reason="classify_intent 方法已修改为 LLM-only，需要 LLM 配置")
class TestSkillBasedDirectorIntent:
    """测试意图识别。"""

    def test_classify_intent_writing(self, tmp_path):
        """测试写作意图识别。"""
        from tools.agents.director_v2 import SkillBasedDirector

        # 使用项目根目录（有 skills 目录）
        director = SkillBasedDirector(project_root=PROJECT_ROOT)

        intent = director.classify_intent("写第1章")

        assert intent.intent.value == "write_chapter"
        assert intent.confidence_score > 0

    def test_classify_intent_outline(self, tmp_path):
        """测试大纲意图识别。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=PROJECT_ROOT)

        intent = director.classify_intent("创建大纲")

        assert intent.intent.value == "outline_assist"
        assert len(intent.matched_keywords) > 0

    def test_classify_intent_style(self, tmp_path):
        """测试风格意图识别。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=PROJECT_ROOT)

        intent = director.classify_intent("风格初始化")

        assert intent.intent.value == "style_compose"

    def test_classify_intent_general_chat(self, tmp_path):
        """测试通用对话意图。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        intent = director.classify_intent("你好")

        assert intent.intent.value == "general_chat"
        assert intent.confidence_score < 0.5

    def test_extract_entities_chapter(self, tmp_path):
        """测试章节实体提取。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        entities = director._extract_entities("写第3章")

        assert any("chapter" in e for e in entities)

    def test_extract_entities_character(self, tmp_path):
        """测试角色实体提取。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        entities = director._extract_entities("李逍遥说他想去")

        assert any("character" in e for e in entities)


class TestSkillBasedDirectorToolExecution:
    """测试工具执行。"""

    def test_execute_tool_read_file(self, tmp_path):
        """测试读取文件工具。"""
        from tools.agents.director_v2 import SkillBasedDirector

        # 创建测试文件
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        director = SkillBasedDirector(project_root=tmp_path)
        result = director.execute_tool("read_file", {"path": "test.txt"})

        assert result.get("success") is True
        assert "Hello, World!" in result.get("result", "")

    def test_execute_tool_list_files(self, tmp_path):
        """测试列出文件工具。"""
        from tools.agents.director_v2 import SkillBasedDirector

        # 创建测试文件
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")

        director = SkillBasedDirector(project_root=tmp_path)
        result = director.execute_tool("list_files", {"directory": "."})

        assert result.get("success") is True
        files = result.get("result", [])
        assert len(files) >= 2

    def test_execute_tool_unknown(self, tmp_path):
        """测试未知工具。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)
        result = director.execute_tool("unknown_tool", {})

        assert result.get("success") is False
        assert "Unknown tool" in result.get("error", "")


class TestSkillBasedDirectorContext:
    """测试上下文加载。"""

    def test_load_context_no_novel_id(self, tmp_path):
        """测试无 novel_id 时的上下文加载。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)
        result = director.load_context("outline")

        assert result is None

    def test_load_context_with_novel_id(self, tmp_path):
        """测试有 novel_id 时的上下文加载。"""
        from tools.agents.director_v2 import SkillBasedDirector

        # 创建测试数据
        novel_dir = tmp_path / "data" / "novels" / "test_novel" / "outline"
        novel_dir.mkdir(parents=True)
        hierarchy_file = novel_dir / "hierarchy.yaml"
        hierarchy_file.write_text("chapters:\n  ch_001:\n    title: Test Chapter\n")

        director = SkillBasedDirector(project_root=tmp_path, novel_id="test_novel")
        result = director.load_context("outline")

        assert result is not None
        assert "1 章" in result



@pytest.mark.skip(reason="process_request 行为已修改为使用 Skill 匹配 fallback")
class TestSkillBasedDirectorProcessRequest:
    """测试请求处理。"""

    def test_process_request_general_chat(self, tmp_path):
        """测试通用对话请求。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)
        response = director.process_request("你好")

        assert response.success is True
        assert "OpenWrite" in response.message
        assert len(response.suggested_actions) > 0

    def test_process_request_help(self, tmp_path):
        """测试帮助请求。"""
        from tools.agents.director_v2 import SkillBasedDirector

        # 使用项目根目录（有 skills 目录）
        director = SkillBasedDirector(project_root=PROJECT_ROOT)
        response = director.process_request("帮助")

        assert response.success is True
        # 帮助请求现在返回通用对话响应，包含可用功能列表
        assert "OpenWrite" in response.message or "可用功能" in response.message


    def test_process_request_writing(self, tmp_path):
        """测试写作请求。"""
        from tools.agents.director_v2 import SkillBasedDirector

        # 使用项目根目录（有 skills 目录）
        director = SkillBasedDirector(project_root=PROJECT_ROOT, novel_id="test_novel")
        response = director.process_request("写第1章")

        assert response.success is True
        assert response.detected_intent.value == "write_chapter"
        assert response.detected_workflow == "writing_chapter"

    def test_process_request_outline(self, tmp_path):
        """测试大纲请求。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=PROJECT_ROOT)
        response = director.process_request("创建大纲")

        assert response.success is True
        assert response.detected_intent.value == "outline_assist"

    def test_process_request_style(self, tmp_path):
        """测试风格请求。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=PROJECT_ROOT)
        response = director.process_request("风格初始化")

        assert response.success is True
        assert response.detected_intent.value == "style_compose"


class TestSkillBasedDirectorChapterExtraction:
    """测试章节 ID 提取。"""

    def test_extract_chapter_id_chinese(self, tmp_path):
        """测试中文格式章节 ID。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        assert director._extract_chapter_id("写第1章") == "ch_001"
        assert director._extract_chapter_id("写第10章") == "ch_010"
        assert director._extract_chapter_id("写第100章") == "ch_100"

    def test_extract_chapter_id_underscore(self, tmp_path):
        """测试下划线格式章节 ID。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        assert director._extract_chapter_id("写 ch_001") == "ch_001"
        assert director._extract_chapter_id("修改 ch_abc") == "ch_abc"

    def test_extract_chapter_id_english(self, tmp_path):
        """测试英文格式章节 ID。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        assert director._extract_chapter_id("write chapter 1") == "ch_001"
        assert director._extract_chapter_id("chapter 5 content") == "ch_005"

    def test_extract_chapter_id_none(self, tmp_path):
        """测试无章节 ID。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        assert director._extract_chapter_id("你好") is None
        assert director._extract_chapter_id("创建大纲") is None


class TestSkillBasedDirectorSkillMapping:
    """测试 Skill 到 TaskIntent 的映射。"""

    def test_map_skill_to_intent_writing(self, tmp_path):
        """测试 writing skill 映射。"""
        from tools.agents.director_v2 import SkillBasedDirector
        from tools.models.intent import TaskIntent

        director = SkillBasedDirector(project_root=tmp_path)

        assert director._map_skill_to_intent("writing") == TaskIntent.WRITE_CHAPTER

    def test_map_skill_to_intent_outline(self, tmp_path):
        """测试 outline skill 映射。"""
        from tools.agents.director_v2 import SkillBasedDirector
        from tools.models.intent import TaskIntent

        director = SkillBasedDirector(project_root=tmp_path)

        assert director._map_skill_to_intent("outline") == TaskIntent.OUTLINE_ASSIST

    def test_map_skill_to_intent_style(self, tmp_path):
        """测试 style skill 映射。"""
        from tools.agents.director_v2 import SkillBasedDirector
        from tools.models.intent import TaskIntent

        director = SkillBasedDirector(project_root=tmp_path)

        assert director._map_skill_to_intent("style") == TaskIntent.STYLE_COMPOSE

    def test_map_skill_to_intent_unknown(self, tmp_path):
        """测试未知 skill 映射。"""
        from tools.agents.director_v2 import SkillBasedDirector
        from tools.models.intent import TaskIntent

        director = SkillBasedDirector(project_root=tmp_path)

        assert director._map_skill_to_intent("unknown_skill") == TaskIntent.UNKNOWN


class TestSkillBasedDirectorPipelineV2Compatibility:
    """测试 Pipeline V2 兼容性。"""

    def test_plan_rule_based(self, tmp_path):
        """测试规则引擎路由决策。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)
        decision = director.plan(
            objective="写第一章",
            context={"outline": "测试大纲"},
            chapter_id="ch_001",
        )

        assert decision.objective == "写第一章"
        assert decision.chapter_id == "ch_001"
        assert "librarian" in decision.required_agents
        assert "lore_checker" in decision.required_agents

    def test_plan_with_stylist(self, tmp_path):
        """测试带 stylist 的路由决策。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)
        decision = director.plan(
            objective="写第一章",
            context={},
            chapter_id="ch_001",
            use_stylist=True,
        )

        assert "stylist" in decision.required_agents

    def test_plan_strict_lore_detection(self, tmp_path):
        """测试严格逻辑检查检测。"""
        from tools.agents.director_v2 import SkillBasedDirector

        director = SkillBasedDirector(project_root=tmp_path)

        # 高风险关键词
        decision = director.plan(
            objective="本章是战斗高潮",
            context={},
            chapter_id="ch_001",
        )
        assert decision.suggested_strict_lore is True

        # 普通章节
        decision = director.plan(
            objective="日常描写",
            context={},
            chapter_id="ch_002",
        )
        assert decision.suggested_strict_lore is False


class TestDirectorAgentAlias:
    """测试 DirectorAgent 别名（向后兼容）。"""

    def test_director_agent_is_skill_based_director(self, tmp_path):
        """测试 DirectorAgent 是 SkillBasedDirector 的别名。"""
        from tools.agents.director_v2 import DirectorAgent, SkillBasedDirector

        assert DirectorAgent is SkillBasedDirector

    def test_director_agent_can_be_instantiated(self, tmp_path):
        """测试 DirectorAgent 可以被实例化。"""
        from tools.agents.director_v2 import DirectorAgent

        director = DirectorAgent(project_root=tmp_path)
        assert isinstance(director, DirectorAgent)
