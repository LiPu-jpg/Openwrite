"""Bridge the bundled DeepResearch framework into an OpenWrite novel workspace."""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from tools.llm.response import redact_sensitive_text
from tools.studio_preferences import StudioResearchSettingsStore
from tools.task_runner import TaskCancelled, TaskContext

MAX_PROCESS_OUTPUT_BYTES = 2_000_000
MAX_ERROR_DETAIL_CHARS = 1200

RESEARCH_EPISODE_FAILED_MESSAGE = (
    "DeepResearch 未通过内部质量或预算门，失败产物已保留供诊断"
)


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _metric_number(metrics: dict[str, Any], key: str) -> tuple[float | None, bool]:
    """Read a numeric metric, distinguishing absent from an explicit 0."""
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, False
    return value, True


def _normalize_model_profile(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "id": _nullable_text(value.get("id")),
        "label": _nullable_text(value.get("label")),
        "model": _nullable_text(value.get("model")),
        "provider": _nullable_text(value.get("provider")),
    }


def _normalize_usage(raw_block: Any, metrics: dict[str, Any]) -> dict[str, Any]:
    block = raw_block if isinstance(raw_block, dict) else {}
    if block:
        value = block.get("total_tokens")
        reported = bool(block.get("reported"))
    else:
        value, reported = _metric_number(metrics, "totalTokenCount")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"total_tokens": None, "reported": False}
    return {
        "total_tokens": int(value) if reported else None,
        "reported": reported,
    }


def _normalize_cost(raw_block: Any, metrics: dict[str, Any]) -> dict[str, Any]:
    block = raw_block if isinstance(raw_block, dict) else {}
    if block:
        value = block.get("value")
        reported = bool(block.get("reported"))
    else:
        value, reported = _metric_number(metrics, "estimatedCostUsd")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {"value": None, "reported": False}
    return {
        "value": float(value) if reported else None,
        "reported": reported,
    }


def normalize_report_metadata(
    raw: Any, *, report_id: str = "", content: str | None = None
) -> dict[str, Any]:
    """Map any stored report metadata (old or new) onto the stable report DTO.

    Every field is always present; data an old archive never recorded comes
    back as an explicit null instead of being fabricated.
    """
    metadata = raw if isinstance(raw, dict) else {}
    metrics = metadata.get("metrics")
    metrics = dict(metrics) if isinstance(metrics, dict) else {}
    sources = metadata.get("sources")
    normalized_sources: list[dict[str, Any]] | None = None
    if isinstance(sources, list):
        normalized_sources = [
            {
                "title": str(entry.get("title") or ""),
                "url": str(entry.get("url") or ""),
                "source_type": str(entry.get("source_type") or ""),
                "cited": bool(entry.get("cited")),
            }
            for entry in sources
            if isinstance(entry, dict)
        ]
    sources_status = metadata.get("sources_status")
    if sources_status not in {"ok", "unavailable"}:
        sources_status = "ok" if normalized_sources is not None else "unavailable"
    word_count = metadata.get("word_count")
    if isinstance(word_count, bool) or not isinstance(word_count, int):
        word_count = len(content) if content is not None else None
    latency_ms = metadata.get("latency_ms")
    if isinstance(latency_ms, bool) or not isinstance(latency_ms, int):
        latency_ms = None
    failure = metadata.get("failure")
    if isinstance(failure, dict):
        failure = {
            "code": str(failure.get("code") or ""),
            "message": str(failure.get("message") or ""),
        }
    else:
        failure = None
    status = str(metadata.get("status") or "unknown")
    if status in {"completed", "complete"}:
        status = "succeeded"
    if status not in {"succeeded", "failed", "needs_human_review", "unknown"}:
        status = "unknown"
    return {
        "id": report_id or str(metadata.get("id") or ""),
        "title": str(metadata.get("title") or report_id or ""),
        "prompt": str(metadata.get("prompt") or ""),
        "status": status,
        "episode_id": _nullable_text(metadata.get("episode_id")),
        "task_id": _nullable_text(metadata.get("task_id")),
        "created_at": _nullable_text(metadata.get("created_at")),
        "completed_at": _nullable_text(metadata.get("completed_at")),
        "model_profile": _normalize_model_profile(metadata.get("model_profile")),
        "search_provider": _nullable_text(metadata.get("search_provider")),
        "sources": normalized_sources,
        "sources_status": sources_status,
        "source_count": (
            len(normalized_sources) if normalized_sources is not None else None
        ),
        "word_count": word_count,
        "latency_ms": latency_ms,
        "usage": _normalize_usage(metadata.get("usage"), metrics),
        "cost_usd": _normalize_cost(metadata.get("cost_usd"), metrics),
        "failure": failure,
        "metrics": metrics,
    }


class ResearchServiceError(RuntimeError):
    """Expected failure while preparing or running a research episode."""

    def __init__(self, message: str, *, code: str = "RESEARCH_ERROR"):
        super().__init__(message)
        self.code = code


class ResearchService:
    """Run the vendored TypeScript framework and archive its report in the novel."""

    def __init__(
        self,
        novel_root: Path,
        *,
        framework_root: Path | None = None,
        settings_store: StudioResearchSettingsStore | None = None,
    ):
        self.novel_root = Path(novel_root).resolve()
        self.framework_root = (
            framework_root
            or Path(__file__).resolve().parents[1] / "integrations" / "deepresearch"
        ).resolve()
        self.research_root = self.novel_root / "data" / "research"
        self.report_root = self.research_root / "reports"
        self.artifact_root = self.research_root / "artifacts"
        base_store = settings_store or StudioResearchSettingsStore()
        # Non-secret settings live next to the research artifacts of THIS
        # workspace; credentials stay machine-global inside the store.
        self.settings_store = base_store.for_workspace(
            self.research_root / "settings.json"
        )

    def status(self) -> dict[str, Any]:
        node = shutil.which("node")
        pnpm = shutil.which("pnpm")
        package_ready = (self.framework_root / "package.json").is_file()
        dependencies_ready = (self.framework_root / "node_modules").is_dir()
        return {
            "available": bool(node and pnpm and package_ready and dependencies_ready),
            "node_ready": bool(node),
            "pnpm_ready": bool(pnpm),
            "package_ready": package_ready,
            "dependencies_ready": dependencies_ready,
            "setup_hint": (
                "深度研究依赖尚未安装，请按项目文档完成一次运行环境初始化"
                if package_ready and not dependencies_ready
                else ""
            ),
            "settings": self.settings_store.surface(),
            "reports": self.list_reports(),
        }

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.settings_store.save(payload)
        except ValueError as exc:
            raise ResearchServiceError(str(exc), code="INVALID_RESEARCH_SETTINGS") from exc

    def list_reports(self) -> list[dict[str, Any]]:
        if not self.report_root.is_dir():
            return []
        reports: list[dict[str, Any]] = []
        for metadata_path in sorted(
            self.report_root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
        ):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            report_path = metadata_path.with_suffix(".md")
            if not report_path.is_file():
                continue
            entry = normalize_report_metadata(metadata, report_id=metadata_path.stem)
            entry["path"] = str(report_path.relative_to(self.novel_root))
            entry["bytes"] = report_path.stat().st_size
            reports.append(entry)
        return reports

    def read_report(self, report_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", report_id):
            raise ResearchServiceError("研究报告 ID 无效", code="INVALID_INPUT")
        metadata_path = self.report_root / f"{report_id}.json"
        report_path = self.report_root / f"{report_id}.md"
        if not metadata_path.is_file() or not report_path.is_file():
            raise ResearchServiceError("研究报告不存在", code="REPORT_NOT_FOUND")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            content = report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResearchServiceError(
                "研究报告读取失败", code="REPORT_READ_FAILED"
            ) from exc
        return {
            "id": report_id,
            "metadata": normalize_report_metadata(
                metadata, report_id=report_id, content=content
            ),
            "content": content,
        }

    def run(
        self,
        payload: dict[str, Any],
        context: TaskContext,
        *,
        model_profile: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ResearchServiceError("研究问题不能为空", code="INVALID_INPUT")
        if len(prompt) > 20000:
            raise ResearchServiceError(
                "研究问题不能超过 20000 个字符", code="INVALID_INPUT"
            )
        availability = self.status()
        if not availability["available"]:
            raise ResearchServiceError(
                availability["setup_hint"] or "DeepResearch 运行环境不可用",
                code="RESEARCH_RUNTIME_UNAVAILABLE",
            )
        pnpm = shutil.which("pnpm")
        if not pnpm:
            raise ResearchServiceError(
                "DeepResearch 运行环境不可用", code="RESEARCH_RUNTIME_UNAVAILABLE"
            )

        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.report_root.mkdir(parents=True, exist_ok=True)
        episode_dir = self.artifact_root / f"episode_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        session_id = f"S_openwrite_{uuid.uuid4().hex[:16]}"
        search = str(
            payload.get("search")
            or self.settings_store.load_settings().get("search_provider")
            or "bocha"
        ).strip().lower()
        if search not in {"bocha", "bing", "jina", "none"}:
            raise ResearchServiceError("深度研究搜索提供方无效", code="INVALID_INPUT")
        command = [
            pnpm,
            "research",
            "--prompt",
            prompt,
            "--session",
            session_id,
            "--artifactDir",
            str(self.artifact_root),
            "--no-stream",
            "--lang",
            str(payload.get("language") or "zh-CN"),
            "--quality",
            str(payload.get("quality") or "balanced"),
            "--search",
            search,
        ]
        llm = str(payload.get("llm") or "").strip().lower()
        if llm:
            command.extend(["--llm", llm])
        for payload_key, flag in (
            ("cycles", "--cycles"),
            ("max_cost_usd", "--max-cost-usd"),
        ):
            if payload.get(payload_key) not in {None, ""}:
                command.extend([flag, str(payload[payload_key])])

        env = self._research_environment(
            {**payload, "search": search}, model_profile=model_profile
        )
        context.phase("preparing", "准备 DeepResearch 运行环境")
        context.checkpoint()
        run_started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        started_monotonic = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=self.framework_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            start_new_session=(os.name == "posix"),
        )
        output = bytearray()
        selector = selectors.DefaultSelector()
        if process.stdout is not None:
            selector.register(process.stdout, selectors.EVENT_READ)
        try:
            context.phase("model", "DeepResearch 正在检索和组织证据")
            while process.poll() is None:
                for selector_key, _ in selector.select(timeout=0.4):
                    chunk = os.read(selector_key.fd, 8192)
                    if chunk:
                        self._append_process_output(output, chunk)
                if context.cancellation_requested():
                    if os.name == "posix":
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise TaskCancelled("研究任务已取消")
            if process.stdout is not None:
                chunk = process.stdout.read()
                if chunk:
                    self._append_process_output(output, chunk)
        finally:
            selector.close()
            if process.stdout is not None:
                process.stdout.close()
        latency_ms = int((time.monotonic() - started_monotonic) * 1000)
        if process.returncode != 0:
            detail = redact_sensitive_text(
                output.decode("utf-8", errors="replace").strip()[
                    -MAX_ERROR_DETAIL_CHARS:
                ]
            )
            raise ResearchServiceError(
                f"DeepResearch 执行失败{': ' + detail if detail else ''}",
                code="RESEARCH_PROCESS_FAILED",
            )

        context.phase("validating", "校验研究报告产物")
        summary = self._parse_summary(output.decode("utf-8", errors="replace"))
        reported_path = Path(str(summary.get("report") or ""))
        source_report: Path | None = reported_path if reported_path.is_file() else None
        if source_report is None:
            source_report = self._find_report(episode_dir, self.artifact_root)
        if source_report is None or not source_report.is_file():
            raise ResearchServiceError(
                "DeepResearch 未生成可用报告", code="REPORT_NOT_FOUND"
            )
        source_report = self._validated_report_path(source_report)
        episode_id = str(summary.get("episodeId") or source_report.parent.name)
        report_id = re.sub(r"[^A-Za-z0-9_-]+", "_", episode_id).strip("_") or session_id
        target_report = self.report_root / f"{report_id}.md"
        target_metadata = self.report_root / f"{report_id}.json"
        context.phase("committing", "归档研究报告到当前作品")
        shutil.copyfile(source_report, target_report)
        report_text = target_report.read_text(encoding="utf-8")
        sources, sources_status = self._episode_sources(
            summary, source_report, report_text
        )
        metrics = summary.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        total_tokens, tokens_reported = _metric_number(metrics, "totalTokenCount")
        cost_value, cost_reported = _metric_number(metrics, "estimatedCostUsd")
        episode_status = summary.get("status", "unknown")
        failure = None
        if episode_status == "failed":
            failure = {
                "code": "RESEARCH_EPISODE_FAILED",
                "message": RESEARCH_EPISODE_FAILED_MESSAGE,
            }
        metadata = {
            "title": prompt[:120],
            "prompt": prompt,
            "status": episode_status,
            "episode_id": episode_id,
            "created_at": run_started_at,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "artifact_ref": str(source_report.parent.relative_to(self.novel_root)),
            "metrics": metrics,
            "task_id": task_id,
            "model_profile": _normalize_model_profile(model_profile),
            "search_provider": search,
            "latency_ms": latency_ms,
            "word_count": len(report_text),
            "sources": sources,
            "sources_status": sources_status,
            "usage": {
                "total_tokens": int(total_tokens) if tokens_reported else None,
                "reported": tokens_reported,
            },
            "cost_usd": {
                "value": float(cost_value) if cost_reported else None,
                "reported": cost_reported,
            },
            "failure": failure,
        }
        target_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if metadata["status"] == "failed":
            raise ResearchServiceError(
                RESEARCH_EPISODE_FAILED_MESSAGE,
                code="RESEARCH_EPISODE_FAILED",
            )
        return {
            "report_id": report_id,
            "episode_id": episode_id,
            "status": metadata["status"],
            "path": str(target_report.relative_to(self.novel_root)),
            "metrics": metadata["metrics"],
        }

    def _research_environment(
        self,
        payload: dict[str, Any],
        *,
        model_profile: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if isinstance(value, str)}
        search = str(payload.get("search") or "bocha").strip().lower()
        try:
            env.update(self.settings_store.environment(search))
        except ValueError as exc:
            raise ResearchServiceError(
                str(exc), code="RESEARCH_SEARCH_CREDENTIAL_MISSING"
            ) from exc
        if search != "jina":
            jina_key = self.settings_store.credential("jina")
            if jina_key:
                env["JINA_API_KEY"] = jina_key
                env.setdefault("FETCH_MODE", "fallback")
        if model_profile is not None:
            profile_provider = str(model_profile.get("provider") or "openai").strip().lower()
            if profile_provider == "anthropic":
                raise ResearchServiceError(
                    "DeepResearch 当前需要 OpenAI-compatible 模型档案；"
                    "请为深度研究路由选择其他档案",
                    code="RESEARCH_MODEL_UNSUPPORTED",
                )
            env["AGENT_PROVIDER"] = "openai"
            env["OPENAI_API_KEY"] = str(model_profile.get("api_key") or "").strip()
            env["OPENAI_BASE_URL"] = str(model_profile.get("base_url") or "").strip()
            env["AGENT_MODEL"] = str(model_profile.get("model") or "").strip()
            env["OPENAI_WIRE_API"] = (
                "responses"
                if str(model_profile.get("api_format") or "chat").strip().lower()
                == "responses"
                else "chat_completions"
            )
            return env
        provider = str(payload.get("llm") or "").strip().lower()
        if not provider:
            provider = str(env.get("LLM_PROVIDER") or "bigmodel").strip().lower()
            if provider == "anthropic":
                provider = "openai"
        env["AGENT_PROVIDER"] = provider
        api_key = env.get("LLM_API_KEY", "").strip()
        model = env.get("LLM_MODEL", "").strip()
        base_url = env.get("LLM_BASE_URL", "").strip()
        if provider in {"openai", "custom"}:
            if api_key:
                env["OPENAI_API_KEY"] = api_key
            if model:
                env["AGENT_MODEL"] = model
            if base_url:
                env["OPENAI_BASE_URL"] = base_url
        elif provider == "deepseek":
            if api_key:
                env["DEEPSEEK_API_KEY"] = api_key
            if model:
                env["DEEPSEEK_MODEL"] = model
            if base_url:
                env["DEEPSEEK_BASE_URL"] = base_url
        elif provider in {"bigmodel", "glm", "zhipu"} and api_key:
            env["BIGMODEL_API_KEY"] = api_key
            if model:
                env["BIGMODEL_MODEL"] = model
            if base_url:
                env["BIGMODEL_BASE_URL"] = base_url
        return env

    @staticmethod
    def _append_process_output(output: bytearray, chunk: bytes) -> None:
        output.extend(chunk)
        overflow = len(output) - MAX_PROCESS_OUTPUT_BYTES
        if overflow > 0:
            del output[:overflow]

    def _validated_report_path(self, report_path: Path) -> Path:
        resolved = report_path.resolve()
        if not resolved.is_relative_to(self.artifact_root.resolve()):
            raise ResearchServiceError(
                "DeepResearch 报告位于允许的产物目录之外",
                code="INVALID_REPORT_PATH",
            )
        return resolved

    @staticmethod
    def _parse_summary(output: str) -> dict[str, Any]:
        try:
            value = json.loads(output.strip())
            if isinstance(value, dict) and ("report" in value or "episodeId" in value):
                return value
        except json.JSONDecodeError:
            pass
        start = output.find("{")
        end = output.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(output[start : end + 1])
                if isinstance(value, dict) and ("report" in value or "episodeId" in value):
                    return value
            except json.JSONDecodeError:
                pass
        for line in reversed([line.strip() for line in output.splitlines() if line.strip()]):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and ("report" in value or "episodeId" in value):
                return value
        raise ResearchServiceError(
            "无法解析 DeepResearch 运行结果", code="INVALID_RESEARCH_RESULT"
        )

    def _episode_sources(
        self, summary: dict[str, Any], source_report: Path, report_text: str
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """Extract real per-source rows from the episode evidence index.

        The framework writes ``evidence-index.json`` next to the episode
        report (``globalEvidenceIndex`` of the report bundle, see
        ``packages/contracts/src/report.ts``); each row carries the citation
        title, URL and source tier. ``cited`` is derived from the citation
        marker actually appearing in the archived report body. When no
        parseable index exists the episode honestly reports ``unavailable``.
        """
        candidates = []
        reported = str(summary.get("evidenceIndex") or "").strip()
        if reported:
            candidates.append(Path(reported))
        candidates.append(source_report.parent / "evidence-index.json")
        artifact_root = self.artifact_root.resolve()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(artifact_root) or not resolved.is_file():
                continue
            try:
                entries = json.loads(resolved.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(entries, list):
                continue
            sources = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                citation_id = str(entry.get("citationId") or "")
                sources.append(
                    {
                        "title": str(entry.get("title") or ""),
                        "url": str(
                            entry.get("url") or entry.get("canonicalUrl") or ""
                        ),
                        "source_type": str(entry.get("sourceTier") or ""),
                        "cited": bool(citation_id)
                        and f"[{citation_id}]" in report_text,
                    }
                )
            return sources, "ok"
        return None, "unavailable"

    @staticmethod
    def _find_report(episode_dir: Path, artifact_root: Path) -> Path | None:
        for root in (episode_dir, artifact_root):
            candidates = sorted(
                root.glob("*/report.md"), key=lambda path: path.stat().st_mtime, reverse=True
            )
            if candidates:
                return candidates[0]
        return None
