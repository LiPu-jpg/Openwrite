from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


SECRET_KEYS = ("TOKEN", "PASSWORD", "API_KEY", "SECRET")


class AdapterError(Exception):
    def __init__(self, message: str, failure_category: str, user_message: str) -> None:
        super().__init__(message)
        self.failure_category = failure_category
        self.user_message = user_message


class ConfigError(AdapterError):
    pass


@dataclass(frozen=True)
class AdapterConfig:
    agent_run_id: int
    agent_project_id: int
    story_id: int
    task_type: str
    prompt: str
    source_branch: str
    source_commit_sha: str | None
    output_target: str
    run_deadline_at: datetime | None
    mcp_endpoint: str
    mcp_token: str
    git_clone_url: str
    git_username: str
    git_password: str
    llm_provider: str
    llm_model: str
    llm_api_key: str
    llm_base_url: str | None
    openwrite_language: str
    workspace: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "AdapterConfig":
        required = [
            "AGENT_RUN_ID",
            "AGENT_PROJECT_ID",
            "AGENT_STORY_ID",
            "AGENT_TASK_TYPE",
            "AGENT_PROMPT",
            "AGENT_SOURCE_BRANCH",
            "AGENT_MCP_ENDPOINT",
            "AGENT_MCP_TOKEN",
            "AGENT_GIT_CLONE_URL",
            "AGENT_GIT_USERNAME",
            "AGENT_GIT_PASSWORD",
            "AGENT_LLM_PROVIDER",
            "AGENT_LLM_MODEL",
            "AGENT_LLM_API_KEY",
            "OPENWRITE_LANGUAGE",
        ]
        
        errors = []
        missing = [key for key in required if not str(env.get(key, "")).strip()]
        if missing:
            errors.append("Missing required environment variables: " + ", ".join(missing))

        agent_run_id = 0
        if "AGENT_RUN_ID" not in missing:
            try:
                agent_run_id = int(env["AGENT_RUN_ID"])
            except ValueError:
                errors.append("Invalid AGENT_RUN_ID: must be an integer.")

        agent_project_id = 0
        if "AGENT_PROJECT_ID" not in missing:
            try:
                agent_project_id = int(env["AGENT_PROJECT_ID"])
            except ValueError:
                errors.append("Invalid AGENT_PROJECT_ID: must be an integer.")

        story_id = 0
        if "AGENT_STORY_ID" not in missing:
            try:
                story_id = int(env["AGENT_STORY_ID"])
            except ValueError:
                errors.append("Invalid AGENT_STORY_ID: must be an integer.")

        run_deadline_at = None
        deadline_raw = env.get("AGENT_RUN_DEADLINE_AT")
        if deadline_raw and str(deadline_raw).strip():
            try:
                run_deadline_at = datetime.fromisoformat(deadline_raw)
            except ValueError:
                errors.append("Invalid AGENT_RUN_DEADLINE_AT: must be a valid ISO format datetime.")

        if errors:
            failure_category = "configuration_missing" if missing else "configuration_invalid"
            raise ConfigError(
                " | ".join(errors),
                failure_category,
                "Thiếu hoặc sai định dạng cấu hình runtime AI bắt buộc.",
            )

        return cls(
            agent_run_id=agent_run_id,
            agent_project_id=agent_project_id,
            story_id=story_id,
            task_type=env["AGENT_TASK_TYPE"],
            prompt=env["AGENT_PROMPT"],
            source_branch=env["AGENT_SOURCE_BRANCH"],
            source_commit_sha=env.get("AGENT_SOURCE_COMMIT_SHA") or None,
            output_target=env.get("AGENT_OUTPUT_TARGET", "private_draft"),
            run_deadline_at=run_deadline_at,
            mcp_endpoint=env["AGENT_MCP_ENDPOINT"],
            mcp_token=env["AGENT_MCP_TOKEN"],
            git_clone_url=env["AGENT_GIT_CLONE_URL"],
            git_username=env["AGENT_GIT_USERNAME"],
            git_password=env["AGENT_GIT_PASSWORD"],
            llm_provider=env["AGENT_LLM_PROVIDER"],
            llm_model=env["AGENT_LLM_MODEL"],
            llm_api_key=env["AGENT_LLM_API_KEY"],
            llm_base_url=env.get("AGENT_LLM_BASE_URL") or None,
            openwrite_language=env["OPENWRITE_LANGUAGE"],
            workspace=env.get("OPENWRITE_WORKSPACE") or "/workspace",
        )

    def openwrite_env(self) -> dict[str, str]:
        env = {
            "LLM_PROVIDER": self.llm_provider,
            "LLM_MODEL": self.llm_model,
            "LLM_API_KEY": self.llm_api_key,
            "OPENWRITE_LANGUAGE": self.openwrite_language,
        }
        if self.llm_base_url:
            env["LLM_BASE_URL"] = self.llm_base_url
        return env


def redact_mapping(values: Mapping[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in values.items():
        if any(secret in key.upper() for secret in SECRET_KEYS):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = value
    return redacted
