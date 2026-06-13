from __future__ import annotations

import pytest

from tools.smart_story_adapter.config import AdapterConfig, ConfigError, redact_mapping


def valid_env() -> dict[str, str]:
    return {
        "AGENT_RUN_ID": "10",
        "AGENT_PROJECT_ID": "20",
        "AGENT_STORY_ID": "30",
        "AGENT_TASK_TYPE": "generate_private_draft",
        "AGENT_PROMPT": "Write the next chapter.",
        "AGENT_SOURCE_BRANCH": "main",
        "AGENT_OUTPUT_TARGET": "private_draft",
        "AGENT_RUN_DEADLINE_AT": "2026-06-09T12:30:00+00:00",
        "AGENT_MCP_ENDPOINT": "https://api.example.com/mcp/ai-agent",
        "AGENT_MCP_TOKEN": "mcp-secret",
        "AGENT_GIT_CLONE_URL": "https://git.example.com/smart/story.git",
        "AGENT_GIT_USERNAME": "smart-story-bot",
        "AGENT_GIT_PASSWORD": "git-secret",
        "AGENT_LLM_PROVIDER": "openai",
        "AGENT_LLM_MODEL": "gpt-4.1-mini",
        "AGENT_LLM_API_KEY": "llm-secret",
        "OPENWRITE_LANGUAGE": "vi",
    }


def test_config_parses_required_env_and_sets_workspace_default() -> None:
    config = AdapterConfig.from_env(valid_env())

    assert config.agent_run_id == 10
    assert config.agent_project_id == 20
    assert config.story_id == 30
    assert config.output_target == "private_draft"
    assert config.openwrite_language == "vi"
    assert config.workspace == "/workspace"


def test_config_rejects_missing_required_env() -> None:
    env = valid_env()
    env.pop("AGENT_MCP_TOKEN")

    with pytest.raises(ConfigError) as exc:
        AdapterConfig.from_env(env)

    assert exc.value.failure_category == "configuration_missing"
    assert "AGENT_MCP_TOKEN" in str(exc.value)


def test_redaction_masks_tokens_and_passwords() -> None:
    redacted = redact_mapping(valid_env())

    assert redacted["AGENT_MCP_TOKEN"] == "[redacted]"
    assert redacted["AGENT_GIT_PASSWORD"] == "[redacted]"
    assert redacted["AGENT_LLM_API_KEY"] == "[redacted]"
    assert redacted["AGENT_RUN_ID"] == "10"


def test_config_rejects_invalid_types() -> None:
    env = valid_env()
    env["AGENT_RUN_ID"] = "not_an_int"
    env["AGENT_RUN_DEADLINE_AT"] = "invalid_date"

    with pytest.raises(ConfigError) as exc:
        AdapterConfig.from_env(env)

    assert exc.value.failure_category == "configuration_invalid"
    error_msg = str(exc.value)
    assert "Invalid AGENT_RUN_ID" in error_msg
    assert "Invalid AGENT_RUN_DEADLINE_AT" in error_msg


def test_openwrite_env_generation() -> None:
    # Without BASE_URL
    env1 = valid_env()
    config1 = AdapterConfig.from_env(env1)
    ow_env1 = config1.openwrite_env()
    
    assert ow_env1 == {
        "LLM_PROVIDER": "openai",
        "LLM_MODEL": "gpt-4.1-mini",
        "LLM_API_KEY": "llm-secret",
        "OPENWRITE_LANGUAGE": "vi",
    }
    assert "LLM_BASE_URL" not in ow_env1

    # With BASE_URL
    env2 = valid_env()
    env2["AGENT_LLM_BASE_URL"] = "https://custom.api.com"
    config2 = AdapterConfig.from_env(env2)
    ow_env2 = config2.openwrite_env()

    assert ow_env2["LLM_BASE_URL"] == "https://custom.api.com"

