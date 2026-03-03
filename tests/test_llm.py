"""Mock-based tests for LLM integration layer and agent LLM branches.

所有测试使用 mock，不需要真实 LLM API key。
验证：配置加载、路由选择、Agent LLM 分支逻辑、fallback 行为。
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))


# ---------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------


def test_load_llm_config_missing_file():
    """配置文件不存在时返回 disabled 默认配置。"""
    from tools.llm.config import load_llm_config

    config = load_llm_config(Path("/nonexistent/llm_config.yaml"))
    assert config.enabled is False
    # 新模型使用 models + routes，不再有 default_route


def test_load_llm_config_from_yaml():
    """从 YAML 文件正确加载配置。"""
    from tools.llm.config import load_llm_config

    raw = {
        "enabled": True,
        "retry_count": 3,
        "retry_delay": 0.5,
        "models": {
            "Claude-Opus": {
                "name": "Claude-Opus",
                "model": "anthropic/claude-opus-4-20250918",
                "api_base": "",
                "api_key_env": "ANTHROPIC_API_KEY",
                "max_tokens": 2048,
                "temperature": 0.3,
            },
            "DeepSeek": {
                "name": "DeepSeek",
                "model": "deepseek/deepseek-chat",
                "api_base": "",
                "api_key_env": "DEEPSEEK_API_KEY",
            },
            "GLM": {
                "name": "GLM",
                "model": "openai/glm-4.7",
                "api_base": "https://open.bigmodel.cn/api/paas/v4",
                "api_key_env": "ZHIPU_API_KEY",
            },
        },
        "routes": {
            "reasoning": {
                "models": ["Claude-Opus", "GLM"],
                "primary_index": 0,
            },
        },
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(raw, f)
        f.flush()
        config = load_llm_config(Path(f.name))

    assert config.enabled is True
    assert config.retry_count == 3
    assert "Claude-Opus" in config.models
    assert "GLM" in config.models
    assert "reasoning" in config.routes
    reasoning = config.routes["reasoning"]
    assert reasoning.models == ["Claude-Opus", "GLM"]
    assert reasoning.primary_index == 0


# ---------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------


def test_router_get_routes():
    """路由器按任务类型返回正确的模型链。"""
    from tools.llm.config import LLMConfig, ModelConfig, TaskRouteConfig
    from tools.llm.router import ModelRouter, TaskType

    config = LLMConfig(
        enabled=True,
        models={
            "Claude-Opus": ModelConfig(
                name="Claude-Opus",
                model="anthropic/claude-opus-4-20250918",
                api_base="",
            ),
            "DeepSeek": ModelConfig(
                name="DeepSeek",
                model="deepseek/deepseek-chat",
                api_base="",
            ),
            "Kimi": ModelConfig(
                name="Kimi",
                model="openai/k2.5",
                api_base="https://api.moonshot.cn/v1",
            ),
        },
        routes={
            "reasoning": TaskRouteConfig(
                models=["Claude-Opus", "DeepSeek"],
                primary_index=0,
            ),
            "generation": TaskRouteConfig(
                models=["Kimi"],
                primary_index=0,
            ),
        },
    )
    router = ModelRouter(config)

    routes = router.get_routes(TaskType.REASONING)
    assert len(routes) == 2
    assert routes[0]["model"] == "anthropic/claude-opus-4-20250918"
    assert routes[1]["model"] == "deepseek/deepseek-chat"

    gen_routes = router.get_routes(TaskType.GENERATION)
    assert len(gen_routes) == 1
    assert gen_routes[0]["model"] == "openai/k2.5"
    assert gen_routes[0]["api_base"] == "https://api.moonshot.cn/v1"


def test_router_fallback_to_default():
    """未配置的任务类型返回空列表（新模型行为）。"""
    from tools.llm.config import LLMConfig, ModelConfig, TaskRouteConfig
    from tools.llm.router import ModelRouter, TaskType

    config = LLMConfig(
        enabled=True,
        models={
            "DeepSeek": ModelConfig(
                name="DeepSeek",
                model="deepseek/deepseek-chat",
                api_base="",
            ),
        },
        routes={
            "reasoning": TaskRouteConfig(
                models=["DeepSeek"],
                primary_index=0,
            ),
        },
    )
    router = ModelRouter(config)
    # 有配置的任务类型返回路由
    routes = router.get_routes(TaskType.REASONING)
    assert len(routes) == 1
    assert routes[0]["model"] == "deepseek/deepseek-chat"

    # 无配置的任务类型返回空列表
    routes = router.get_routes(TaskType.STYLE)
    assert len(routes) == 0


# ---------------------------------------------------------------
# PromptBuilder tests
# ---------------------------------------------------------------


def test_prompt_builder_director():
    """Director prompt 构建正确。"""
    from tools.llm.prompts import PromptBuilder

    messages = PromptBuilder.director_plan(
        objective="推进主线",
        chapter_id="ch_003",
        context_summary="测试摘要",
        style_summary="风格摘要",
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "ch_003" in messages[1]["content"]
    assert "风格文档摘要" in messages[1]["content"]


def test_prompt_builder_librarian():
    """Librarian prompt 构建正确。"""
    from tools.llm.prompts import PromptBuilder

    messages = PromptBuilder.librarian_generate(
        chapter_id="ch_001",
        objective="测试目标",
        beats=["节拍1", "节拍2"],
        context={"outline": "大纲内容"},
    )
    assert len(messages) == 2
    assert "节拍1" in messages[1]["content"]


def test_prompt_builder_lore_checker():
    """LoreChecker prompt 构建正确。"""
    from tools.llm.prompts import PromptBuilder

    messages = PromptBuilder.lore_checker_review(
        draft="测试草稿",
        context={"characters": "角色信息"},
        forbidden=["禁词1"],
        required=["必含1"],
        strict=True,
    )
    assert len(messages) == 2
    assert "严格模式" in messages[0]["content"]
    assert "禁词1" in messages[1]["content"]


def test_prompt_builder_stylist():
    """Stylist prompt 构建正确。"""
    from tools.llm.prompts import PromptBuilder

    messages = PromptBuilder.stylist_polish(
        draft="测试草稿",
        style_profile_summary="风格档案",
        banned_phrases=["不禁", "缓缓说道"],
    )
    assert len(messages) == 2
    assert "不禁" in messages[0]["content"]
    assert "风格档案" in messages[0]["content"]


# ---------------------------------------------------------------
# LLMClient tests (mocked litellm)
# ---------------------------------------------------------------


def _make_mock_response(content: str = "mock response", model: str = "test-model"):
    """创建模拟的 litellm response 对象。"""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 20
    response.usage.total_tokens = 30
    return response


def test_llm_client_complete():
    """LLMClient.complete() 正确调用 litellm 并返回结果。"""
    from tools.llm.client import LLMClient

    mock_litellm = MagicMock()
    mock_litellm.completion.return_value = _make_mock_response("测试回复")

    client = LLMClient(retry_count=0)
    client._litellm = mock_litellm

    result = client.complete(
        messages=[{"role": "user", "content": "你好"}],
        model="test/model",
    )
    assert result.content == "测试回复"
    assert result.usage["total_tokens"] == 30
    mock_litellm.completion.assert_called_once()


def test_llm_client_retry_on_failure():
    """LLMClient 在失败时重试。"""
    from tools.llm.client import LLMClient

    mock_litellm = MagicMock()
    mock_litellm.completion.side_effect = [
        Exception("first fail"),
        _make_mock_response("重试成功"),
    ]

    client = LLMClient(retry_count=1, retry_delay=0.01)
    client._litellm = mock_litellm

    result = client.complete(
        messages=[{"role": "user", "content": "test"}],
        model="test/model",
    )
    assert result.content == "重试成功"
    assert mock_litellm.completion.call_count == 2


def test_llm_client_fallback():
    """complete_with_fallback 在首选模型失败时切换到备选。"""
    from tools.llm.client import LLMClient

    mock_litellm = MagicMock()
    mock_litellm.completion.side_effect = [
        Exception("primary fail"),
        Exception("primary retry fail"),
        Exception("primary retry2 fail"),
        _make_mock_response("fallback 成功"),
    ]

    client = LLMClient(retry_count=2, retry_delay=0.01)
    client._litellm = mock_litellm

    routes = [
        {
            "model": "primary/model",
            "max_tokens": 1024,
            "temperature": 0.7,
            "timeout": 30,
        },
        {
            "model": "fallback/model",
            "max_tokens": 1024,
            "temperature": 0.7,
            "timeout": 30,
        },
    ]
    result = client.complete_with_fallback(
        messages=[{"role": "user", "content": "test"}],
        routes=routes,
    )
    assert result.content == "fallback 成功"


# ---------------------------------------------------------------
# Agent LLM branch tests
# ---------------------------------------------------------------


def _make_mock_client_and_router(response_content: str):
    """创建 mock LLMClient + ModelRouter 对。"""
    from tools.llm.client import LLMResponse

    mock_client = MagicMock()
    mock_client.complete_with_fallback.return_value = LLMResponse(
        content=response_content,
        model="test/model",
        tool_calls=None,
    )
    mock_router = MagicMock()
    mock_router.get_routes.return_value = [
        {"model": "test/model", "max_tokens": 1024, "temperature": 0.7, "timeout": 30}
    ]
    return mock_client, mock_router


def test_director_llm_branch():
    """Director 在有 llm_client 时走 LLM 分支。"""
    from tools.agents.director_v2 import DirectorAgent

    llm_response = json.dumps(
        {
            "strict_lore": True,
            "priority_elements": ["高权重伏笔: f001"],
            "generation_instructions": "注意伏笔回收",
            "style_instructions": "保持幽默感",
            "notes": ["LLM决策备注"],
        }
    )
    mock_client, mock_router = _make_mock_client_and_router(llm_response)

    agent = DirectorAgent(llm_client=mock_client, router=mock_router)
    decision = agent.plan(
        objective="推进主线",
        context={"outline": "大纲", "characters": "角色"},
        chapter_id="ch_003",
    )
    assert decision.suggested_strict_lore is True
    assert "高权重伏笔: f001" in decision.priority_elements
    mock_client.complete_with_fallback.assert_called_once()


def test_director_llm_fallback_on_error():
    """Director LLM 调用失败时回退到规则引擎。"""
    from tools.agents.director_v2 import DirectorAgent

    mock_client = MagicMock()
    mock_client.complete_with_fallback.side_effect = RuntimeError("LLM down")
    mock_router = MagicMock()
    mock_router.get_routes.return_value = [
        {"model": "test/model", "max_tokens": 1024, "temperature": 0.7, "timeout": 30}
    ]

    agent = DirectorAgent(llm_client=mock_client, router=mock_router)
    decision = agent.plan(
        objective="推进主线",
        context={"outline": "大纲", "characters": "角色"},
        chapter_id="ch_003",
    )
    # Should still return a valid decision from rule-based fallback
    assert decision.chapter_id == "ch_003"
    assert "librarian" in decision.required_agents


def test_lore_checker_llm_advisory():
    """LoreChecker LLM 发现默认为 advisory warnings。"""
    from tools.agents.lore_checker import LoreCheckerAgent

    llm_response = json.dumps(
        {
            "passed": False,
            "errors": ["角色位置不一致"],
            "warnings": ["术语使用不规范"],
            "suggestions": ["建议增加过渡段"],
        }
    )
    mock_client, mock_router = _make_mock_client_and_router(llm_response)

    agent = LoreCheckerAgent(strict=False, llm_client=mock_client, router=mock_router)
    result = agent.check_draft(
        draft="测试草稿内容",
        forbidden=[],
        required=[],
    )
    # In non-strict mode, LLM errors become warnings (advisory)
    llm_warnings = [w for w in result.warnings if w.startswith("[LLM")]
    assert len(llm_warnings) >= 2  # error->warning + warning + suggestion
    assert result.passed  # No rule-based errors, LLM errors are advisory


def test_lore_checker_llm_strict():
    """LoreChecker strict 模式下 LLM errors 成为真正的 errors。"""
    from tools.agents.lore_checker import LoreCheckerAgent

    llm_response = json.dumps(
        {
            "passed": False,
            "errors": ["角色位置不一致"],
            "warnings": [],
            "suggestions": [],
        }
    )
    mock_client, mock_router = _make_mock_client_and_router(llm_response)

    agent = LoreCheckerAgent(strict=True, llm_client=mock_client, router=mock_router)
    result = agent.check_draft(
        draft="测试草稿内容",
        forbidden=[],
        required=[],
        strict=True,
    )
    llm_errors = [e for e in result.errors if e.startswith("[LLM")]
    assert len(llm_errors) == 1
    assert not result.passed


def test_stylist_llm_branch():
    """Stylist 在有 llm_client 时走 LLM 润色分支。"""
    from tools.agents.stylist import StylistAgent

    mock_client, mock_router = _make_mock_client_and_router(
        "润色后的文本，没有AI痕迹。"
    )

    agent = StylistAgent(llm_client=mock_client, router=mock_router)
    result = agent.polish("原始草稿，不禁微微一笑。")
    assert "润色后的文本" in result.text
    assert any("LLM" in e for e in result.edits)
    mock_client.complete_with_fallback.assert_called_once()


def test_stylist_llm_fallback_on_error():
    """Stylist LLM 失败时回退到规则引擎。"""
    from tools.agents.stylist import StylistAgent

    mock_client = MagicMock()
    mock_client.complete_with_fallback.side_effect = RuntimeError("LLM down")
    mock_router = MagicMock()
    mock_router.get_routes.return_value = [
        {"model": "test/model", "max_tokens": 1024, "temperature": 0.7, "timeout": 30}
    ]

    agent = StylistAgent(llm_client=mock_client, router=mock_router)
    result = agent.polish("原始草稿，不禁微微一笑。")
    # Should still return a valid result from rule-based fallback
    assert result.text is not None
    assert result.score is not None


def test_agents_without_llm_unchanged():
    """不传入 llm_client 时，所有 Agent 保持原有规则行为。"""
    from tools.agents.director_v2 import DirectorAgent
    from tools.agents.librarian import LibrarianAgent
    from tools.agents.lore_checker import LoreCheckerAgent
    from tools.agents.stylist import StylistAgent

    # Director
    director = DirectorAgent()
    decision = director.plan(
        objective="测试",
        context={"outline": "大纲"},
        chapter_id="ch_001",
    )
    assert decision.chapter_id == "ch_001"

    # LoreChecker
    checker = LoreCheckerAgent()
    result = checker.check_draft(draft="正常文本", forbidden=[], required=[])
    assert result.passed

    # Stylist
    stylist = StylistAgent()
    style_result = stylist.polish("正常文本")
    assert style_result.text is not None
