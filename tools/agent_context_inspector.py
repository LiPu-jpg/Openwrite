"""Read-only inspection of the exact first request sent to an OpenWrite agent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from models.token_estimation import estimate_measurement, estimate_text_tokens
from tools.llm import LLMResponse, Message


class AgentContextInspectionError(RuntimeError):
    pass


class _CaptureClient:
    def __init__(self):
        self.messages: list[Message] = []

    def chat(self, *, messages: list[Message], **kwargs: Any) -> LLMResponse:
        del kwargs
        self.messages = list(messages)
        return LLMResponse(content="[]", provider="context-inspector")


class AgentContextInspector:
    AGENTS = {"canonical", "writer", "reviewer", "dante", "goethe"}

    def __init__(self, project_root: Path):
        from tools.novel_service import NovelApplicationService

        self.project_root = Path(project_root).resolve()
        self.service = NovelApplicationService(self.project_root)
        self.novel_id = self.service.novel_id

    def inspect(
        self,
        chapter_id: str = "next",
        *,
        agent: str = "canonical",
        instruction: str = "",
        guidance: str = "",
        target_words: int = 0,
        exclude_latest_session_turn: bool = False,
    ) -> dict[str, Any]:
        clean_agent = str(agent or "canonical").strip().lower()
        if clean_agent not in self.AGENTS:
            raise AgentContextInspectionError(f"不支持的 Agent: {clean_agent}")
        chapter = self.service.resolve_chapter_id(chapter_id)
        packet = self.service.assemble_packet(chapter)
        if clean_agent == "writer":
            result = self._inspect_writer(chapter, packet, guidance, target_words)
        elif clean_agent == "reviewer":
            result = self._inspect_reviewer(chapter, packet)
        elif clean_agent == "dante":
            result = self._inspect_dante(
                chapter,
                packet,
                instruction,
                exclude_latest_session_turn=exclude_latest_session_turn,
            )
        elif clean_agent == "goethe":
            result = self._inspect_goethe(
                chapter,
                packet,
                instruction,
                exclude_latest_session_turn=exclude_latest_session_turn,
            )
        else:
            result = self._inspect_canonical(chapter, packet)
        result.update(
            {
                "schema_version": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "novel_id": self.novel_id,
                "chapter_id": chapter,
                "agent": clean_agent,
                "model": self._model_identity(),
                "context_manifest": packet.get("context_manifest", {}),
            }
        )
        revision_payload = {
            "messages": result.get("messages", []),
            "tools": result.get("tools", []),
            "agent_payload": result.get("agent_payload", {}),
            "request_config": result.get("request_config", {}),
        }
        result["inspection_revision"] = "sha256:" + hashlib.sha256(
            json.dumps(
                revision_payload, ensure_ascii=False, sort_keys=True, default=str
            ).encode("utf-8")
        ).hexdigest()
        return result

    def render_markdown(self, inspection: dict[str, Any]) -> str:
        lines = [
            f"# Agent 初始上下文检查：{inspection['agent']}",
            "",
            f"- 小说：{inspection['novel_id']}",
            f"- 章节：{inspection['chapter_id']}",
            f"- 阶段：{inspection.get('stage') or 'initial'}",
            f"- 上下文修订：{inspection['inspection_revision']}",
        ]
        model = inspection.get("model", {})
        if model:
            lines.append(
                f"- 模型：{model.get('provider') or '未配置'} / {model.get('model') or '未配置'}"
            )
        request_config = inspection.get("request_config", {})
        if request_config:
            lines.append(
                "- 请求："
                f"thinking={request_config.get('thinking') or 'provider_default'}, "
                f"max_output_tokens={request_config.get('max_output_tokens') or 'agent_default'}"
            )
        warnings = inspection.get("warnings", [])
        if warnings:
            lines.extend(["", "## 注意事项", ""])
            lines.extend(f"- {item}" for item in warnings)
        checks = inspection.get("checks", [])
        if checks:
            lines.extend(
                [
                    "",
                    "## 完整性检查",
                    "",
                    "| 字段 | 级别 | 状态 | 字符数 |",
                    "|---|---|---:|---:|",
                ]
            )
            for item in checks:
                lines.append(
                    f"| {item['field']} | {item['importance']} | "
                    f"{item['status']} | {item['characters']} |"
                )
        manifest = inspection.get("context_manifest", {})
        items = manifest.get("items", []) if isinstance(manifest, dict) else []
        if items:
            lines.extend(
                [
                    "",
                    "## 来源清单",
                    "",
                    "| Section | 层级 | 字符数 | Revision | 来源 |",
                    "|---|---:|---:|---|---|",
                ]
            )
            for item in items:
                sources = "<br>".join(
                    f"{source.get('path')} ({source.get('revision')})"
                    for source in item.get("sources", [])
                )
                lines.append(
                    f"| {item.get('section')} | {item.get('level')} | "
                    f"{item.get('characters')} | {item.get('revision')} | {sources} |"
                )
        messages = inspection.get("messages", [])
        if messages:
            lines.extend(["", "## 实际首轮消息"])
            for index, message in enumerate(messages, start=1):
                lines.extend(
                    [
                        "",
                        f"### {index}. {str(message.get('role') or '').upper()}",
                        "",
                        str(message.get("content") or ""),
                    ]
                )
        tools = inspection.get("tools", [])
        if tools:
            lines.extend(["", "## 可用工具", ""])
            lines.extend(
                f"- `{item['name']}`：{item.get('description') or ''}" for item in tools
            )
        return "\n".join(lines).rstrip() + "\n"

    def _inspect_canonical(
        self, chapter_id: str, packet: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "stage": "canonical_packet",
            "messages": [],
            "tools": [],
            "agent_payload": packet,
            "checks": self._checks(
                packet,
                required=("author_intent", "creative_focus", "outline"),
                recommended=(
                    "core_documents",
                    "previous_chapter_content",
                    "character_documents",
                    "setting_documents",
                    "continuity_documents",
                    "style_documents",
                ),
            ),
            "warnings": [],
        }

    def _inspect_writer(
        self,
        chapter_id: str,
        packet: dict[str, Any],
        guidance: str,
        target_words: int,
    ) -> dict[str, Any]:
        from tools.agent.writer import WriterAgent
        from tools.chapter_pipeline import build_writer_payload, configure_writer_llm
        from tools.context_builder import ContextBuilder
        from tools.llm import LLMConfig
        from tools.truth_manager import TruthFilesManager

        context = ContextBuilder(self.project_root, self.novel_id).build_generation_context(
            chapter_id
        )
        truth = TruthFilesManager(self.project_root, self.novel_id).load_truth_files()
        effective_target = int(target_words or getattr(context, "target_words", 0) or 6000)
        payload = build_writer_payload(
            context=context,
            truth=truth,
            packet=packet,
            guidance=str(guidance or "").strip(),
            target_words=effective_target,
        )
        writer = WriterAgent.__new__(WriterAgent)
        request_config = configure_writer_llm(LLMConfig.from_env())
        messages = [
            Message("system", writer._build_creative_system_prompt(payload)),
            Message(
                "user",
                writer._build_creative_user_prompt(
                    payload,
                    chapter_number=self._chapter_number(chapter_id),
                    target_words=effective_target,
                ),
            ),
        ]
        return {
            "stage": "creative_write",
            "messages": self._messages(messages),
            "tools": [],
            "agent_payload": payload,
            "request_config": request_config,
            "checks": self._checks(
                payload,
                required=("author_intent", "creative_focus", "outline", "current_state"),
                recommended=(
                    "active_characters",
                    "foreshadowing_summary",
                    "ledger",
                    "relationships",
                    "recent_chapters",
                    "chapter_summaries",
                    "style_profile",
                ),
            ),
            "warnings": self._compression_warnings(packet),
        }

    def _inspect_reviewer(
        self, chapter_id: str, packet: dict[str, Any]
    ) -> dict[str, Any]:
        from tools.agent.base import AgentContext
        from tools.agent.reviewer import ReviewerAgent
        from tools.chapter_pipeline import build_review_payload, load_chapter
        from tools.chapter_run_store import ChapterRunStore
        from tools.truth_manager import TruthFilesManager

        content = load_chapter(self.project_root, self.novel_id, chapter_id)
        if not content:
            raise AgentContextInspectionError(f"审稿上下文需要已存在章节: {chapter_id}")
        from tools.context_builder import ContextBuilder

        generation_context = ContextBuilder(
            self.project_root, self.novel_id
        ).build_generation_context(chapter_id)
        payload = build_review_payload(packet, context=generation_context)
        run = ChapterRunStore(self.project_root, self.novel_id).latest_for_chapter(
            chapter_id, statuses={"written", "reviewed"}
        )
        if run is not None and run.effective_target_words > 0:
            payload["target_words"] = run.effective_target_words
        prewrite = TruthFilesManager(
            self.project_root, self.novel_id
        ).load_snapshot_before(self._chapter_number(chapter_id))
        if prewrite is not None:
            payload["current_state"] = prewrite.current_state
            payload["relationships"] = prewrite.relationships
        capture = _CaptureClient()
        reviewer = ReviewerAgent(
            AgentContext(capture, "context-inspector", str(self.project_root))
        )
        asyncio.run(reviewer._llm_audit(content, payload))
        return {
            "stage": "llm_audit",
            "messages": self._messages(capture.messages),
            "tools": [],
            "agent_payload": {**payload, "chapter_content": content},
            "checks": self._checks(
                payload,
                required=(
                    "author_intent",
                    "creative_focus",
                    "outline",
                    "current_state",
                ),
                recommended=(
                    "character_profiles",
                    "relationships",
                    "style_profile",
                    "recent_chapters",
                    "target_words",
                ),
            ),
            "warnings": self._compression_warnings(packet),
        }

    def _inspect_dante(
        self,
        chapter_id: str,
        packet: dict[str, Any],
        instruction: str,
        *,
        exclude_latest_session_turn: bool,
    ) -> dict[str, Any]:
        from tools.agent.book_state import BookState, BookStateStore
        from tools.agent.dante import (
            DEFAULT_DANTE_SYSTEM_PROMPT,
            DanteChatAgent,
            _build_dante_tool_definitions,
        )
        from tools.agent.session_state import DanteSessionState, SessionStateStore

        agent = DanteChatAgent(
            self.project_root,
            self.novel_id,
            react_agent=SimpleNamespace(),
            tool_executors={},
            action_executors={},
        )
        session_store = SessionStateStore(self.project_root, self.novel_id)
        agent.session_state = self._read_dataclass_state(
            session_store,
            DanteSessionState(session_id=session_store.session_id),
        )
        book_store = BookStateStore(self.project_root, self.novel_id)
        agent.book_state = self._read_dataclass_state(
            book_store, BookState(novel_id=self.novel_id)
        )
        messages = [Message("system", DEFAULT_DANTE_SYSTEM_PROMPT)]
        messages.extend(
            agent._build_context_messages(
                include_recent_turns=not exclude_latest_session_turn
            )
        )
        messages.append(Message("user", instruction or "（尚未提供用户指令）"))
        return self._react_result(
            "dante_react_initial",
            messages,
            _build_dante_tool_definitions(),
            packet,
            instruction,
        )

    def _inspect_goethe(
        self,
        chapter_id: str,
        packet: dict[str, Any],
        instruction: str,
        *,
        exclude_latest_session_turn: bool,
    ) -> dict[str, Any]:
        from tools.agent.goethe_session_state import (
            GoetheSessionState,
            GoetheSessionStateStore,
        )
        from tools.goethe import (
            DEFAULT_GOETHE_SYSTEM_PROMPT,
            GoetheChatAgent,
            _build_goethe_tool_definitions,
        )

        agent = GoetheChatAgent(
            project_root=self.project_root,
            novel_id=self.novel_id,
            react_agent=SimpleNamespace(),
            tool_layer_factory=lambda *args: {},
        )
        store = GoetheSessionStateStore(self.project_root, self.novel_id)
        agent.session_state = self._read_dataclass_state(
            store, GoetheSessionState(session_id=store.session_id)
        )
        messages = [Message("system", DEFAULT_GOETHE_SYSTEM_PROMPT)]
        messages.extend(
            agent._build_context_messages(
                include_recent_turns=not exclude_latest_session_turn
            )
        )
        messages.append(Message("user", instruction or "（尚未提供用户指令）"))
        return self._react_result(
            "goethe_react_initial",
            messages,
            _build_goethe_tool_definitions(),
            packet,
            instruction,
        )

    def _react_result(
        self,
        stage: str,
        messages: list[Message],
        tools: list[Any],
        packet: dict[str, Any],
        instruction: str,
    ) -> dict[str, Any]:
        warnings = [
            "Dante/Goethe 首轮不会自动接收整份章节 canonical packet；"
            "需要由 Agent 调用 get_context、get_outline_structure 等只读工具。"
        ]
        if not str(instruction or "").strip():
            warnings.append("未提供 --instruction；USER 消息使用占位文本。")
        return {
            "stage": stage,
            "messages": self._messages(messages),
            "tools": [asdict(tool) for tool in tools],
            "agent_payload": {
                "instruction": instruction,
                "canonical_packet_available_via_tools": True,
                "canonical_packet_revision": packet.get("context_manifest", {}).get(
                    "revision", ""
                ),
            },
            "checks": self._checks(
                {
                    "system_prompt": messages[0].content if messages else "",
                    "session_context": "\n".join(
                        message.content for message in messages[1:-1]
                    ),
                    "instruction": instruction,
                    "tools": tools,
                },
                required=("system_prompt", "tools"),
                recommended=("session_context", "instruction"),
            ),
            "warnings": warnings,
        }

    @staticmethod
    def _read_dataclass_state(store: Any, default: Any) -> Any:
        path = Path(store.path)
        if not path.is_file():
            return default
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return default
        if not isinstance(payload, dict):
            return default
        try:
            return store._from_dict(payload)
        except Exception:
            return default

    @staticmethod
    def _messages(messages: list[Message]) -> list[dict[str, Any]]:
        return [
            {
                "role": message.role,
                "content": message.content,
                "characters": len(message.content),
                "estimated_tokens": estimate_text_tokens(message.content),
                "measurement": estimate_measurement(
                    text_scope="complete_message_content",
                    includes_wrapper_overhead=True,
                ),
                "revision": hashlib.sha256(message.content.encode("utf-8")).hexdigest()[
                    :16
                ],
            }
            for message in messages
        ]

    @staticmethod
    def _checks(
        payload: dict[str, Any], *, required: tuple[str, ...], recommended: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        checks = []
        for importance, fields in (("required", required), ("recommended", recommended)):
            for field in fields:
                value = payload.get(field)
                rendered = AgentContextInspector._render_value(value)
                checks.append(
                    {
                        "field": field,
                        "importance": importance,
                        "status": "included" if rendered.strip() else "missing",
                        "characters": len(rendered),
                    }
                )
        return checks

    @staticmethod
    def _compression_warnings(packet: dict[str, Any]) -> list[str]:
        compression = packet.get("compression")
        if not isinstance(compression, dict):
            return []
        warnings = []
        for key in ("truncated_character_documents", "dropped_character_documents"):
            values = compression.get(key) or []
            if values:
                warnings.append(f"{key}: {', '.join(str(item) for item in values)}")
        if compression.get("within_budget") is False:
            warnings.append("canonical packet 在压缩后仍超过预算。")
        return warnings

    @staticmethod
    def _render_value(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return "\n".join(
                f"{key}: {rendered}"
                for key, item in value.items()
                if (rendered := AgentContextInspector._render_value(item)).strip()
            )
        if isinstance(value, (list, tuple)):
            return "\n".join(
                rendered
                for item in value
                if (rendered := AgentContextInspector._render_value(item)).strip()
            )
        return str(value or "")

    @staticmethod
    def _chapter_number(chapter_id: str) -> int:
        try:
            return int(str(chapter_id).rsplit("_", 1)[-1])
        except ValueError:
            return 1

    @staticmethod
    def _model_identity() -> dict[str, str]:
        try:
            from tools.model_profiles import active_model_profile

            profile = active_model_profile() or {}
        except Exception:
            profile = {}
        return {
            "provider": str(profile.get("provider") or os.getenv("LLM_PROVIDER", "")),
            "model": str(profile.get("model") or os.getenv("LLM_MODEL", "")),
            "api_format": str(
                profile.get("api_format") or os.getenv("LLM_API_FORMAT", "chat")
            ),
        }
