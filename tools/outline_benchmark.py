"""Isolated outline planning through the production Architect and reviewer APIs."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tools.agent.reviewer import ReviewerAgent
from tools.benchmark_execution import BenchmarkExecution
from tools.benchmark_tasks import OUTLINE_DIMENSIONS, OUTLINE_RUBRIC_VERSION, benchmark_pipeline


class OutlineBenchmarkError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        framework: dict[str, Any],
        usage: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.framework = framework
        self.usage = usage or {}


def _save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_outline_window(outlines: list[Any], start: int, count: int) -> list[dict[str, Any]]:
    chapters = [
        asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item) for item in outlines
    ]
    numbers = [item.get("number") for item in chapters]
    if (
        len(chapters) != count
        or any(type(number) is not int for number in numbers)
        or sorted(numbers) != list(range(start, start + count))
    ):
        raise ValueError(f"章纲编号必须恰为第 {start}-{start + count - 1} 章，不能缺章、重复或越界")
    for chapter in chapters:
        for field in ("title", "summary", "dramatic_position", "content_focus", "emotional_arc"):
            if not isinstance(chapter.get(field), str) or not chapter[field].strip():
                raise ValueError(f"第 {chapter['number']} 章缺少 {field}")
        for field in ("goals", "involved_characters", "involved_settings", "beats", "hooks"):
            value = chapter.get(field)
            if (
                not isinstance(value, list)
                or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)
            ):
                raise ValueError(f"第 {chapter['number']} 章缺少有效 {field}")
        if type(chapter.get("estimated_words")) is not int or chapter["estimated_words"] <= 0:
            raise ValueError(f"第 {chapter['number']} 章预估字数无效")
    return sorted(chapters, key=lambda item: item["number"])


def _render(chapters: list[dict[str, Any]]) -> str:
    labels = {
        "dramatic_position": "戏剧位置",
        "content_focus": "内容焦点",
        "goals": "本章目标",
        "estimated_words": "预估字数",
        "involved_characters": "出场角色",
        "involved_settings": "涉及设定",
        "emotional_arc": "情感弧线",
        "beats": "节拍",
        "hooks": "悬念",
    }
    sections = []
    for chapter in chapters:
        lines = [f"#### 第{chapter['number']}章：{chapter['title']}", "", chapter["summary"], ""]
        for key, label in labels.items():
            value = chapter[key]
            lines.append(f"> {label}: {', '.join(value) if isinstance(value, list) else value}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + "\n"


def generate_outline_candidate(
    workspace: Path, novel_id: str, packet: dict[str, Any]
) -> dict[str, Any]:
    from models.token_estimation import estimate_text_tokens
    from tools.agent.base import AgentContext
    from tools.agent.writer import WriterAgent
    from tools.architect import ArchitectAgent
    from tools.benchmark_tasks import BenchmarkInputError
    from tools.llm import LLMClient, LLMConfig

    root = workspace / "data" / "novels" / novel_id / "data" / "planning" / "benchmark_outline"
    pipeline = benchmark_pipeline("outline", "framework")
    trace = BenchmarkExecution(root / "execution.json", pipeline)
    framework = {
        "pipeline_id": pipeline["id"],
        "write_entrypoint": "ArchitectAgent.generate_outline",
        "outline_artifact_committed": False,
        "artifact_path": str(root / "outline.json"),
    }
    stage = "context"
    agent = None
    try:
        trace.start(stage)
        _save(root / "context.json", packet)
        trace.complete(stage, root / "context.json")
        stage = "plan"
        trace.start(stage)
        config = LLMConfig.from_env()
        count = int(packet["outline_chapter_count"])
        output_budget = min(config.max_tokens, max(8192, min(32768, count * 1536)))
        estimated_input = estimate_text_tokens(str(packet["planning_context"])) + 4096
        if estimated_input + output_budget > config.context_tokens:
            raise BenchmarkInputError(
                "完整规划上下文与输出预算超过所选模型容量，请选择更大上下文模型或缩小规划范围",
                code="BENCHMARK_CONTEXT_TOO_LARGE",
            )
        agent = ArchitectAgent(
            AgentContext(LLMClient(config), config.model, str(workspace), novel_id)
        )
        start, count = int(packet["outline_start_chapter"]), int(packet["outline_chapter_count"])
        outlines = asyncio.run(
            agent.generate_outline(
                str(packet.get("title") or novel_id),
                str(packet.get("genre") or "unspecified"),
                "",
                count,
                start_chapter=start,
                planning_context=str(packet["planning_context"]),
            )
        )
        raw = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in outlines]
        _save(root / "plan.json", raw)
        trace.complete(stage, root / "plan.json")
        stage = "validate"
        trace.start(stage)
        chapters = validate_outline_window(outlines, start, count)
        _save(
            root / "validation.json",
            {"ok": True, "chapter_numbers": [item["number"] for item in chapters]},
        )
        trace.complete(stage, root / "validation.json")
        stage = "commit"
        trace.start(stage)
        content = _render(chapters)
        _save(root / "outline.json", {"chapters": chapters, "task_type": "outline"})
        (root / "outline.md").write_text(content, encoding="utf-8")
        trace.complete(stage, root / "outline.json")
        framework["outline_artifact_committed"] = True
        framework.update(trace.evidence())
        metadata = dict(getattr(agent, "last_response_metadata", {}) or {})
        usage = WriterAgent._merge_usage(
            *[item.get("usage") or {} for item in getattr(agent, "response_metadata_history", [])]
        )
        return {
            "title": f"第 {start}-{start + count - 1} 章大纲",
            "content": content,
            "outline_start_chapter": chapters[0]["number"],
            "outline_end_chapter": chapters[-1]["number"],
            "outline_chapter_count": len(chapters),
            "outline_chapters": chapters,
            "framework": framework,
            **metadata,
            "usage": usage,
        }
    except Exception as exc:
        code = str(getattr(exc, "code", "OUTLINE_WINDOW_INVALID"))
        trace.fail(stage, code)
        framework.update(
            failed_stage=stage,
            stage_error_code=code,
            **trace.evidence(),
        )
        raise OutlineBenchmarkError(
            str(exc),
            code=code,
            framework=framework,
            usage=WriterAgent._merge_usage(
                *[
                    item.get("usage") or {}
                    for item in getattr(agent, "response_metadata_history", [])
                ]
            ),
        ) from exc


class OutlineReviewerAgent(ReviewerAgent):
    """Reuse evidence-backed domain review while excluding prose-only heuristics."""

    def _rule_based_check(self, content: str, target_words: int = 0) -> list:
        return []

    def _detect_ai_tells(self, content: str) -> list:
        return []

    def _build_audit_user_prompt(self, *args, **kwargs):
        prompt, report = super()._build_audit_user_prompt(*args, **kwargs)
        return (
            "本次对象是拟议章节大纲，不是已发生的正文事实。只评审规划的因果、人物、情节、节奏与正典约束；"
            "允许大纲用条目描述，不要求对白、成文细节或正文文风。"
            "缺少必要正典时标记 inconclusive。\n\n" + prompt,
            report,
        )


def review_outline_candidate(
    workspace: Path, novel_id: str, content: str, packet: dict[str, Any], reviewer_id: str
) -> dict[str, Any]:
    from tools.agent.base import AgentContext
    from tools.llm import LLMClient, LLMConfig

    root = workspace / "data" / "novels" / novel_id / "data" / "planning" / "benchmark_outline"
    pipeline = benchmark_pipeline("outline", "framework")
    previous = json.loads((root / "execution.json").read_text(encoding="utf-8"))
    trace = BenchmarkExecution(
        root / f"review_{reviewer_id}.execution.json", pipeline, previous=previous
    )
    framework = {
        "pipeline_id": pipeline["id"],
        "review_entrypoint": "OutlineReviewerAgent.review",
        "review_scope": "outline",
        "review_dimensions": list(OUTLINE_DIMENSIONS),
    }
    artifact = root / f"review_{reviewer_id}.json"
    try:
        trace.start("review")
        config = LLMConfig.from_env()
        agent = OutlineReviewerAgent(
            AgentContext(LLMClient(config), config.model, str(workspace), novel_id)
        )
        context = {
            **packet,
            "target_words": 0,
            "review_form": "outline",
            "form": "outline",
            "outline": str(packet.get("planning_context") or ""),
        }
        result = asyncio.run(agent.review(content, context, dimensions=list(OUTLINE_DIMENSIONS)))
        v2 = dict(result.review_v2)
        v2["rubric_version"] = OUTLINE_RUBRIC_VERSION
        v2["review_scope"] = "outline"
        _save(artifact, v2)
        trace.complete("review", artifact, status=str(v2.get("execution_status") or "completed"))
        framework.update(trace.evidence(), artifact_path=str(artifact))
    except Exception as exc:
        code = str(getattr(exc, "code", "OUTLINE_REVIEW_FAILED"))
        _save(
            artifact,
            {"execution_status": "failed", "error": {"code": code, "message": type(exc).__name__}},
        )
        trace.fail("review", code, artifact)
        framework.update(
            trace.evidence(),
            artifact_path=str(artifact),
            failed_stage="review",
            stage_error_code=code,
        )
        raise OutlineBenchmarkError(str(exc), code=code, framework=framework) from exc
    return {
        "score": result.score,
        "passed": result.passed,
        "issue_details": [agent._issue_payload(issue) for issue in result.issues],
        "token_usage": result.token_usage,
        "review_v2": v2,
        "framework": framework,
    }
