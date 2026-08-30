"""Run isolated, profile-backed chapter model benchmarks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.model_profiles import ModelProfileStore, activate_model_profile
from tools.review_rubric import RUBRIC_VERSION

BENCHMARK_SCHEMA_VERSION = "openwrite.model-benchmark.v1"
BENCHMARK_PROMPT_VERSION = "writer-v1"

GenerationExecutor = Callable[[dict[str, Any], dict[str, Any], int, int], dict[str, Any]]
ReviewExecutor = Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]]


class BenchmarkFrameworkError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        framework: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.framework = dict(framework or {})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _safe_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(profile.get("id") or ""),
        "label": str(profile.get("label") or ""),
        "provider": str(profile.get("provider") or ""),
        "base_url": str(profile.get("base_url") or ""),
        "model": str(profile.get("model") or ""),
        "api_format": str(profile.get("api_format") or "chat"),
        "context_tokens": int(profile.get("context_tokens") or 0),
        "max_output_tokens": int(profile.get("max_output_tokens") or 0),
    }


def _reasoning_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("completion_tokens_details")
    if not isinstance(details, dict):
        details = usage.get("output_tokens_details")
    details = details if isinstance(details, dict) else {}
    return int(
        usage.get("reasoning_tokens")
        or details.get("reasoning_tokens")
        or details.get("reasoningTokens")
        or 0
    )


def _cost_details(usage: dict[str, Any]) -> tuple[float, bool]:
    explicit_reported = usage.get("cost_reported")
    if isinstance(explicit_reported, bool):
        reported = explicit_reported
    else:
        reported = any(key in usage for key in ("cost", "response_cost", "cost_usd"))
    # Provider-returned fields win over our normalized compatibility alias:
    # OpenRouter reports usage.cost; LiteLLM reports response_cost.
    for key in ("cost", "response_cost", "cost_usd"):
        if key not in usage:
            continue
        try:
            cost = float(usage[key])
        except (TypeError, ValueError, OverflowError):
            return 0.0, False
        if not math.isfinite(cost) or cost < 0:
            return 0.0, False
        return cost, reported
    return 0.0, False


def _usage_tokens(usage: dict[str, Any], canonical: str, compatible: str) -> int:
    try:
        return int(usage.get(canonical) or usage.get(compatible) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _usage_total_tokens(usage: dict[str, Any]) -> int:
    total = _usage_tokens(usage, "total_tokens", "total_tokens")
    if total:
        return total
    return _usage_tokens(usage, "prompt_tokens", "input_tokens") + _usage_tokens(
        usage, "completion_tokens", "output_tokens"
    )


def _safe_error_code(value: Any, fallback: str) -> str:
    code = str(value or fallback).strip().upper()
    normalized = re.sub(r"[^A-Z0-9_-]+", "_", code)[:80].strip("_")
    return normalized or fallback


def _review_diagnostics(review_v2: dict[str, Any]) -> dict[str, Any]:
    domains = [item for item in review_v2.get("domains") or [] if isinstance(item, dict)]
    gates = [item for item in review_v2.get("gates") or [] if isinstance(item, dict)]
    provenance = (
        review_v2.get("provenance") if isinstance(review_v2.get("provenance"), dict) else {}
    )
    errors = [item for item in provenance.get("errors") or [] if isinstance(item, dict)]
    return {
        "domains": [
            {
                "id": str(item.get("id") or ""),
                "status": str(item.get("status") or "inconclusive"),
                "coverage": float(item.get("coverage") or 0),
                "earned": float(item.get("earned") or 0),
                "max": float(item.get("max") or 0),
                "potential_max": float(item.get("potential_max") or 0),
            }
            for item in domains
        ],
        "inconclusive_domain_ids": [
            str(item.get("id") or "")
            for item in domains
            if str(item.get("status") or "") == "inconclusive"
        ],
        "gate_results": [
            {
                "id": str(item.get("id") or ""),
                "status": str(item.get("status") or "inconclusive"),
                "error_code": (
                    _safe_error_code(item.get("error", {}).get("code"), "GATE_REVIEW_FAILED")
                    if isinstance(item.get("error"), dict)
                    else None
                ),
            }
            for item in gates
        ],
        "audit_calls": int(provenance.get("audit_calls") or 0),
        "provider_errors": [
            {
                "domain": str(item.get("domain") or ""),
                "code": _safe_error_code(item.get("code"), "DOMAIN_REVIEW_FAILED"),
            }
            for item in errors
        ],
    }


class BenchmarkStore:
    def __init__(self, project_root: Path, novel_id: str):
        self.root = (
            Path(project_root).resolve() / "data" / "novels" / novel_id / "data" / "benchmarks"
        )

    def save(self, artifact: dict[str, Any]) -> Path:
        run_id = str(artifact.get("run_id") or "")
        if not re.fullmatch(r"bench_[A-Za-z0-9_-]{8,80}", run_id):
            raise ValueError("invalid benchmark run id")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{run_id}.json"
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.root,
            prefix=f".{run_id}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(artifact, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(target)
        return target

    def workspace_project(self, run_id: str, candidate_id: str) -> Path:
        for value, label in ((run_id, "run id"), (candidate_id, "candidate id")):
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,160}", str(value or "")):
                raise ValueError(f"invalid benchmark {label}")
        return self.root / run_id / "workspaces" / candidate_id / "project"

    def load(self, run_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"bench_[A-Za-z0-9_-]{8,80}", str(run_id or "")):
            return None
        path = self.root / f"{run_id}.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("bench_*.json"), reverse=True):
            record = self.load(path.stem)
            if record:
                records.append(
                    {
                        "run_id": record.get("run_id"),
                        "status": record.get("status"),
                        "chapter_id": record.get("chapter_id"),
                        "created_at": record.get("created_at"),
                        "context_hash": record.get("context_hash"),
                        "candidate_count": len(record.get("candidates") or []),
                        "evaluation_count": len(record.get("evaluations") or []),
                        "execution_mode": str(
                            (record.get("config") or {}).get("execution_mode") or "creative"
                        ),
                        "summary": record.get("summary") or {},
                    }
                )
            if len(records) >= max(1, min(100, int(limit))):
                break
        return records


class ModelBenchmarkService:
    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        profile_store: ModelProfileStore,
        *,
        generation_executor: GenerationExecutor | None = None,
        review_executor: ReviewExecutor | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.profile_store = profile_store
        self.store = BenchmarkStore(self.project_root, self.novel_id)
        self._generation_executor = generation_executor or self._generate_creative
        self._review_executor = review_executor or self._review_direct

    def surface(self, limit: int = 20) -> dict[str, Any]:
        return {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "runs": self.store.list(limit),
        }

    def run(
        self,
        payload: dict[str, Any],
        context_preview: dict[str, Any],
        *,
        progress: Callable[[str, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        writer_ids = self._profile_ids(
            payload.get("writer_profile_ids"), "writer_profile_ids", maximum=8
        )
        raw_reviewers = payload.get("reviewer_profile_ids")
        if raw_reviewers is None and payload.get("reviewer_profile_id"):
            raw_reviewers = [payload.get("reviewer_profile_id")]
        reviewer_ids = self._profile_ids(raw_reviewers, "reviewer_profile_ids", maximum=4)
        repeats = self._bounded_int(payload.get("repeats"), 1, 5, 1)
        concurrency = self._bounded_int(payload.get("concurrency"), 1, 4, 1)
        execution_mode = str(payload.get("execution_mode") or "framework").strip().lower()
        if execution_mode not in {"framework", "creative"}:
            raise ValueError("execution_mode must be framework or creative")
        chapter_id = str(context_preview.get("chapter_id") or payload.get("chapter_id") or "")
        match = re.fullmatch(r"ch_(\d+)", chapter_id)
        if match is None:
            raise ValueError("benchmark context has an invalid chapter id")
        chapter_number = int(match.group(1))
        target_words = self._bounded_int(
            payload.get("target_words"),
            200,
            12000,
            int(context_preview.get("target_words") or 3000),
        )
        packet = context_preview.get("packet")
        if not isinstance(packet, dict):
            raise ValueError("benchmark requires the full novel_context_preview packet")
        snapshot = {
            "chapter_id": chapter_id,
            "target_words": target_words,
            "packet": packet,
        }
        context_hash = "sha256:" + hashlib.sha256(_json_bytes(snapshot)).hexdigest()
        run_id = (
            "bench_"
            + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            + "_"
            + uuid.uuid4().hex[:10]
        )
        created_at = _utc_now()
        writer_profiles = {
            profile_id: self.profile_store.resolve_profile(profile_id, operation="chapter_write")
            for profile_id in writer_ids
        }
        reviewer_profiles = {
            profile_id: self.profile_store.resolve_profile(profile_id, operation="review")
            for profile_id in reviewer_ids
        }
        search_profile = (
            self.profile_store.resolve("search") if execution_mode == "framework" else None
        )
        route_snapshot = dict(self.profile_store.load().get("routes") or {})

        if progress:
            progress("model", "生成隔离的 benchmark 候选正文")
        candidates: list[dict[str, Any]] = []
        jobs = [
            (profile_id, repeat) for profile_id in writer_ids for repeat in range(1, repeats + 1)
        ]
        with ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="openwrite-benchmark-write"
        ) as pool:
            futures = {
                pool.submit(
                    self._run_generation,
                    writer_profiles[profile_id],
                    packet,
                    chapter_id,
                    chapter_number,
                    target_words,
                    run_id,
                    repeat,
                    execution_mode,
                    search_profile,
                ): (profile_id, repeat)
                for profile_id, repeat in jobs
            }
            for future in as_completed(futures):
                if cancelled and cancelled():
                    for pending in futures:
                        pending.cancel()
                    raise RuntimeError("benchmark cancelled")
                candidates.append(future.result())
        candidates.sort(key=lambda item: (str(item["writer_profile"]["id"]), int(item["repeat"])))

        if progress:
            progress("validating", "使用独立评审模型执行盲评")
        evaluations: list[dict[str, Any]] = []
        review_jobs = [
            (candidate, reviewer_profiles[reviewer_id])
            for candidate in candidates
            if candidate["reliability_status"] == "completed"
            for reviewer_id in reviewer_ids
        ]
        with ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="openwrite-benchmark-review"
        ) as pool:
            futures = {
                pool.submit(
                    self._run_review,
                    reviewer,
                    candidate,
                    packet,
                    execution_mode,
                    search_profile,
                ): (
                    str(candidate["candidate_id"]),
                    str(reviewer["id"]),
                )
                for candidate, reviewer in review_jobs
            }
            for future in as_completed(futures):
                if cancelled and cancelled():
                    for pending in futures:
                        pending.cancel()
                    raise RuntimeError("benchmark cancelled")
                evaluations.append(future.result())
        evaluations.sort(
            key=lambda item: (str(item["candidate_id"]), str(item["reviewer_profile"]["id"]))
        )

        if self.profile_store.load().get("routes") != route_snapshot:
            raise RuntimeError("benchmark mutated global model routes")
        completed_candidates = sum(item["reliability_status"] == "completed" for item in candidates)
        completed_evaluations = sum(
            item["execution_status"] in {"completed", "partial"} for item in evaluations
        )
        scores = [
            float(item["quality_score"])
            for item in evaluations
            if isinstance(item.get("quality_score"), (int, float))
        ]
        status = (
            "completed"
            if completed_candidates == len(candidates) and completed_evaluations == len(review_jobs)
            else ("partial" if completed_candidates else "failed")
        )
        billable_items = [*candidates, *evaluations]
        prompt_tokens = sum(
            _usage_tokens(dict(item.get("usage") or {}), "prompt_tokens", "input_tokens")
            for item in billable_items
        )
        completion_tokens = sum(
            _usage_tokens(dict(item.get("usage") or {}), "completion_tokens", "output_tokens")
            for item in billable_items
        )
        reasoning_tokens = sum(int(item.get("reasoning_tokens") or 0) for item in billable_items)
        reported_cost_items = sum(item.get("cost_reported") is True for item in billable_items)
        total_cost_usd = round(sum(float(item.get("cost_usd") or 0) for item in billable_items), 8)
        artifact = {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "run_id": run_id,
            "status": status,
            "created_at": created_at,
            "completed_at": _utc_now(),
            "chapter_id": chapter_id,
            "context_hash": context_hash,
            "context_snapshot": {
                "chapter_id": chapter_id,
                "target_words": target_words,
                "characters": list(context_preview.get("characters") or []),
                "manifest": context_preview.get("manifest") or {},
            },
            "prompt_version": BENCHMARK_PROMPT_VERSION,
            "rubric_version": RUBRIC_VERSION,
            "config": {
                "writer_profile_ids": writer_ids,
                "reviewer_profile_ids": reviewer_ids,
                "repeats": repeats,
                "target_words": target_words,
                "concurrency": concurrency,
                "blind_review": True,
                "run_scoped_profiles": True,
                "execution_mode": execution_mode,
            },
            "candidates": candidates,
            "evaluations": evaluations,
            "summary": {
                "requested_candidates": len(jobs),
                "completed_candidates": completed_candidates,
                "requested_evaluations": len(review_jobs),
                "completed_evaluations": completed_evaluations,
                "average_quality_score": round(sum(scores) / len(scores), 2) if scores else None,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "reasoning_tokens": reasoning_tokens,
                "total_tokens": sum(
                    _usage_total_tokens(dict(item.get("usage") or {})) for item in billable_items
                ),
                "total_cost_usd": total_cost_usd,
                "cost_reported_items": reported_cost_items,
                "cost_item_count": len(billable_items),
                "cost_complete": bool(billable_items)
                and reported_cost_items == len(billable_items),
            },
        }
        if progress:
            progress("committing", "保存隔离 benchmark artifact")
        path = self.store.save(artifact)
        return {
            "run_id": run_id,
            "status": status,
            "artifact_path": str(path),
            "context_hash": context_hash,
            "summary": artifact["summary"],
            "candidates": candidates,
            "evaluations": evaluations,
        }

    def _run_generation(
        self,
        profile: dict[str, Any],
        packet: dict[str, Any],
        chapter_id: str,
        chapter_number: int,
        target_words: int,
        run_id: str,
        repeat: int,
        execution_mode: str,
        search_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        candidate_id = f"{run_id}_{profile['id']}_{repeat}"
        workspace_path = ""
        try:
            if execution_mode == "framework":
                workspace = self._prepare_framework_workspace(run_id, candidate_id)
                workspace_path = str(workspace)
                result = self._generate_framework(
                    profile,
                    workspace,
                    packet,
                    chapter_id,
                    target_words,
                    search_profile,
                )
            else:
                result = self._generation_executor(profile, packet, chapter_number, target_words)
            usage = dict(result.get("usage") or {})
            cost_usd, cost_reported = _cost_details(usage)
            return {
                "candidate_id": candidate_id,
                "benchmark_run_id": run_id,
                "chapter_id": chapter_id,
                "repeat": repeat,
                "writer_profile": _safe_profile(profile),
                "reliability_status": "completed",
                "title": str(result.get("title") or ""),
                "content": str(result.get("content") or ""),
                "word_count": int(result.get("word_count") or 0),
                "finish_reason": str(result.get("finish_reason") or ""),
                "response_model": str(result.get("model") or ""),
                "response_provider": str(result.get("provider") or ""),
                "usage": usage,
                "reasoning_tokens": _reasoning_tokens(usage),
                "cost_usd": cost_usd,
                "cost_reported": cost_reported,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "execution_mode": execution_mode,
                "workspace_path": workspace_path,
                "framework": dict(result.get("framework") or {}),
                "error": None,
            }
        except Exception as exc:
            return {
                "candidate_id": candidate_id,
                "benchmark_run_id": run_id,
                "chapter_id": chapter_id,
                "repeat": repeat,
                "writer_profile": _safe_profile(profile),
                "reliability_status": "failed",
                "title": "",
                "content": "",
                "word_count": 0,
                "finish_reason": "",
                "response_model": "",
                "response_provider": "",
                "usage": {},
                "reasoning_tokens": 0,
                "cost_usd": 0,
                "cost_reported": False,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "execution_mode": execution_mode,
                "workspace_path": workspace_path,
                "framework": dict(getattr(exc, "framework", {}) or {}),
                "error": {
                    "code": str(getattr(exc, "code", "MODEL_RUN_FAILED")),
                    "message": exc.__class__.__name__,
                },
            }

    def _run_review(
        self,
        profile: dict[str, Any],
        candidate: dict[str, Any],
        packet: dict[str, Any],
        execution_mode: str,
        search_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            if execution_mode == "framework":
                result = self._review_framework(profile, candidate, search_profile)
            else:
                result = self._review_executor(profile, str(candidate["content"]), packet)
            usage = dict(result.get("token_usage") or result.get("usage") or {})
            cost_usd, cost_reported = _cost_details(usage)
            v2 = result.get("review_v2") if isinstance(result.get("review_v2"), dict) else {}
            return {
                "candidate_id": candidate["candidate_id"],
                "reviewer_profile": _safe_profile(profile),
                "execution_status": str(v2.get("execution_status") or "completed"),
                "quality_score": v2.get("quality_score", result.get("score")),
                "coverage": v2.get("coverage", 1),
                "gate_status": v2.get("gate_status", "pass"),
                "delivery_status": v2.get(
                    "delivery_status", "pass" if result.get("passed") else "revise"
                ),
                "production_gate_status": v2.get("production_gate_status", "not_recorded"),
                "issue_count": len(result.get("issue_details") or []),
                "review_diagnostics": _review_diagnostics(v2),
                "usage": usage,
                "reasoning_tokens": _reasoning_tokens(usage),
                "cost_usd": cost_usd,
                "cost_reported": cost_reported,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "execution_mode": execution_mode,
                "framework": dict(result.get("framework") or {}),
                "error": None,
            }
        except Exception as exc:
            return {
                "candidate_id": candidate["candidate_id"],
                "reviewer_profile": _safe_profile(profile),
                "execution_status": "failed",
                "quality_score": None,
                "coverage": 0,
                "gate_status": "inconclusive",
                "delivery_status": "inconclusive",
                "production_gate_status": "not_evaluated",
                "issue_count": 0,
                "usage": {},
                "reasoning_tokens": 0,
                "cost_usd": 0,
                "cost_reported": False,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "execution_mode": execution_mode,
                "framework": dict(getattr(exc, "framework", {}) or {}),
                "error": {
                    "code": str(getattr(exc, "code", "REVIEW_RUN_FAILED")),
                    "message": exc.__class__.__name__,
                },
            }

    def _prepare_framework_workspace(self, run_id: str, candidate_id: str) -> Path:
        source_config = self.project_root / "novel_config.yaml"
        source_novel = self.project_root / "data" / "novels" / self.novel_id
        if not source_config.is_file() or not source_novel.is_dir():
            raise BenchmarkFrameworkError(
                "benchmark source project is incomplete",
                code="BENCHMARK_SOURCE_INVALID",
            )
        workspace = self.store.workspace_project(run_id, candidate_id)
        if workspace.exists():
            raise BenchmarkFrameworkError(
                "benchmark workspace already exists",
                code="BENCHMARK_WORKSPACE_EXISTS",
            )
        workspace.mkdir(parents=True, mode=0o700)
        shutil.copy2(source_config, workspace / "novel_config.yaml")
        source_data = (source_novel / "data").resolve()

        def ignore(directory: str, names: list[str]) -> set[str]:
            ignored = {name for name in names if name == ".DS_Store" or name.endswith(".lock")}
            if Path(directory).resolve() == source_data:
                ignored.add("benchmarks")
            return ignored

        shutil.copytree(
            source_novel,
            workspace / "data" / "novels" / self.novel_id,
            ignore=ignore,
        )
        workspace.chmod(0o700)
        return workspace

    def _generate_framework(
        self,
        profile: dict[str, Any],
        workspace: Path,
        packet: dict[str, Any],
        chapter_id: str,
        target_words: int,
        search_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        from tools.chapter_pipeline import execute_write_chapter, load_chapter
        from tools.chapter_run_v2 import ChapterRunV2Store

        with activate_model_profile(profile, search_profile=search_profile):
            result = execute_write_chapter(
                workspace,
                {
                    "chapter_id": chapter_id,
                    "context_packet": packet,
                    "target_words": target_words,
                    "temperature": float(profile.get("temperature") or 0.7),
                },
            )
        run_id_v2 = str(result.get("run_id_v2") or "")
        manifest = ChapterRunV2Store(workspace, self.novel_id).load(run_id_v2)
        framework = self._framework_evidence(
            entrypoint="execute_write_chapter",
            run_id_v2=run_id_v2,
            manifest=manifest,
            committed_stage="commit",
            committed_key="chapter_committed",
            search_profile=search_profile,
        )
        if result.get("ok") is not True:
            raise BenchmarkFrameworkError(
                "production writing framework failed",
                code=_safe_error_code(result.get("code"), "FRAMEWORK_WRITE_FAILED"),
                framework=framework,
            )
        content = load_chapter(workspace, self.novel_id, chapter_id)
        if not content:
            raise BenchmarkFrameworkError(
                "production writing framework did not commit a chapter",
                code="FRAMEWORK_CHAPTER_MISSING",
                framework=framework,
            )
        if manifest is None or manifest.stages["commit"].status != "completed":
            raise BenchmarkFrameworkError(
                "production writing framework did not commit Chapter Run V2 evidence",
                code="FRAMEWORK_RUN_V2_INCOMPLETE",
                framework=framework,
            )
        return {
            "title": str(result.get("title") or ""),
            "content": content,
            "word_count": int(result.get("word_count") or 0),
            "finish_reason": str(result.get("finish_reason") or ""),
            "model": str(result.get("model") or ""),
            "provider": str(result.get("provider") or ""),
            "usage": dict(result.get("usage") or {}),
            "framework": framework,
        }

    def _review_framework(
        self,
        profile: dict[str, Any],
        candidate: dict[str, Any],
        search_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        from tools.chapter_pipeline import execute_review_chapter
        from tools.chapter_run_v2 import ChapterRunV2Store

        workspace = Path(str(candidate.get("workspace_path") or "")).resolve()
        try:
            expected_workspace = self.store.workspace_project(
                str(candidate.get("benchmark_run_id") or ""),
                str(candidate.get("candidate_id") or ""),
            ).resolve()
        except ValueError as exc:
            raise BenchmarkFrameworkError(
                "benchmark candidate identity is invalid",
                code="BENCHMARK_WORKSPACE_INVALID",
            ) from exc
        if workspace != expected_workspace or not workspace.is_dir():
            raise BenchmarkFrameworkError(
                "benchmark workspace does not match its candidate",
                code="BENCHMARK_WORKSPACE_INVALID",
            )
        framework = candidate.get("framework")
        framework = framework if isinstance(framework, dict) else {}
        run_id_v2 = str(framework.get("run_id_v2") or "")
        with activate_model_profile(profile, search_profile=search_profile):
            result = execute_review_chapter(
                workspace,
                {
                    "chapter_id": str(candidate.get("chapter_id") or ""),
                    "run_id_v2": run_id_v2,
                },
            )
        manifest = ChapterRunV2Store(workspace, self.novel_id).load(run_id_v2)
        framework_evidence = self._framework_evidence(
            entrypoint="execute_review_chapter",
            run_id_v2=run_id_v2,
            manifest=manifest,
            committed_stage="review",
            committed_key="review_committed",
            search_profile=search_profile,
        )
        if result.get("ok") is not True:
            raise BenchmarkFrameworkError(
                "production review framework failed",
                code=_safe_error_code(result.get("code"), "FRAMEWORK_REVIEW_FAILED"),
                framework=framework_evidence,
            )
        if manifest is None or manifest.stages["review"].status != "completed":
            raise BenchmarkFrameworkError(
                "production review framework did not commit Chapter Run V2 evidence",
                code="FRAMEWORK_REVIEW_EVIDENCE_INCOMPLETE",
                framework=framework_evidence,
            )
        return {
            **result,
            "framework": framework_evidence,
        }

    @staticmethod
    def _framework_evidence(
        *,
        entrypoint: str,
        run_id_v2: str,
        manifest: Any,
        committed_stage: str,
        committed_key: str,
        search_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        stages = (
            {name: stage.status for name, stage in manifest.stages.items()}
            if manifest is not None
            else {}
        )
        failed_stage = next((name for name, status in stages.items() if status == "failed"), "")
        failed = (
            manifest.stages.get(failed_stage) if manifest is not None and failed_stage else None
        )
        entrypoint_key = "review_entrypoint" if committed_stage == "review" else "write_entrypoint"
        return {
            entrypoint_key: entrypoint,
            "run_id_v2": run_id_v2,
            "stage_statuses": stages,
            committed_key: stages.get(committed_stage) == "completed",
            "failed_stage": failed_stage,
            "stage_error_code": _safe_error_code(
                getattr(failed, "error_code", ""), "RUN_STAGE_FAILED"
            )
            if failed is not None
            else "",
            "search_profile": _safe_profile(search_profile or {}),
        }

    def _generate_creative(
        self,
        profile: dict[str, Any],
        packet: dict[str, Any],
        chapter_number: int,
        target_words: int,
    ) -> dict[str, Any]:
        from tools.agent.base import AgentContext
        from tools.agent.writer import WriterAgent
        from tools.llm import LLMClient, LLMConfig

        with activate_model_profile(profile):
            config = LLMConfig.from_env()
            agent = WriterAgent(
                AgentContext(LLMClient(config), config.model, str(self.project_root), self.novel_id)
            )
            return asyncio.run(
                agent._creative_write(packet, chapter_number, config.temperature, target_words)
            )

    def _review_direct(
        self,
        profile: dict[str, Any],
        content: str,
        packet: dict[str, Any],
    ) -> dict[str, Any]:
        from tools.agent.base import AgentContext
        from tools.agent.reviewer import ReviewerAgent
        from tools.llm import LLMClient, LLMConfig

        with activate_model_profile(profile):
            config = LLMConfig.from_env()
            agent = ReviewerAgent(
                AgentContext(LLMClient(config), config.model, str(self.project_root), self.novel_id)
            )
            result = asyncio.run(agent.review(content, packet))
        issues = [agent._issue_payload(item) for item in result.issues]
        return {
            "score": result.score,
            "passed": result.passed,
            "issue_details": issues,
            "token_usage": result.token_usage,
            "review_v2": result.review_v2,
        }

    @staticmethod
    def _profile_ids(value: Any, field: str, *, maximum: int) -> list[str]:
        if not isinstance(value, list):
            raise ValueError(f"{field} must be a list")
        result = list(
            dict.fromkeys(str(item or "").strip() for item in value if str(item or "").strip())
        )
        if not result or len(result) > maximum:
            raise ValueError(f"{field} must contain 1-{maximum} profile ids")
        return result

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            number = int(default)
        return max(minimum, min(maximum, number))
