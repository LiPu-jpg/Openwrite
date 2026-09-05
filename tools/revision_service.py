"""Reviewable, conflict-aware manuscript revisions."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.post_validator import PostWriteValidator
from tools.project_lock import ProjectBusyError, ProjectWriteLock
from tools.review_store import ReviewStore, normalize_review_issues
from tools.revision_store import RevisionStore, RevisionStoreError

MAX_CHAPTER_BYTES = 2 * 1024 * 1024
REVISION_ACTIONS = {
    "rewrite": "按要求重写",
    "expand": "扩写并补足必要细节",
    "compress": "压缩冗余表达",
    "pace": "调整叙事节奏",
    "dialogue": "增强对话的行动性与人物区分",
    "naturalize": "减少模板化和机械表达",
    "custom": "执行用户给出的具体修改要求",
}


class RevisionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "REVISION_FAILED",
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        self.details = details or {}


RevisionGenerator = Callable[[dict[str, Any]], dict[str, Any] | str]
RevisionValidator = Callable[[str, str], list[dict[str, Any]]]


class RevisionService:
    """Create proposals first; mutate canonical manuscript only on explicit apply."""

    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        *,
        generator: RevisionGenerator | None = None,
        validator: RevisionValidator | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.store = RevisionStore(self.project_root, self.novel_id)
        self.generator = generator or self._default_generator
        self.validator = validator or self._default_validator

    @staticmethod
    def fingerprint(content: str) -> str:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def create_selection(
        self,
        *,
        chapter_id: str,
        start: int,
        end: int,
        instruction: str = "",
        action: str = "rewrite",
        target_units: int = 0,
        original_text: str = "",
        full_chapter: bool = False,
        review_issue_ids: list[str] | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        path = self._chapter_path(chapter_id)
        content = path.read_text(encoding="utf-8")
        if full_chapter:
            start, end = 0, len(content)
        start, end = self._validated_range(content, start, end)
        selected = content[start:end]
        if original_text and selected != original_text:
            raise RevisionError(
                "所选原文已变化，请重新选择后再生成提案",
                code="DOCUMENT_CONFLICT",
                recoverable=True,
                details={"chapter_id": chapter_id},
            )
        clean_action = str(action or "rewrite").strip()
        if clean_action not in REVISION_ACTIONS:
            raise RevisionError("未知修订方式", code="INVALID_REVISION_ACTION")
        clean_instruction = str(instruction or "").strip()
        if len(clean_instruction) > 4000:
            raise RevisionError("修订要求不能超过 4000 字", code="INVALID_INPUT")
        target = self._bounded_target(target_units)
        request = {
            "action": clean_action,
            "instruction": clean_instruction,
            "target_units": target,
        }
        generation = self._generate(
            chapter_id=chapter_id,
            content=content,
            start=start,
            end=end,
            request=request,
            review_issues=[],
        )
        proposal = self._new_proposal(
            chapter_id=chapter_id,
            kind=kind
            or ("full_chapter_revision" if full_chapter else "selection_rewrite"),
            content=content,
            start=start,
            end=end,
            request=request,
            review_issue_ids=review_issue_ids or [],
            generation=generation,
        )
        self.store.save(proposal)
        return self.present(proposal)

    def create_from_review(
        self,
        *,
        chapter_id: str,
        issue_ids: list[str],
        instruction: str = "",
        target_units: int = 0,
        expected_review_revision: str = "",
        expected_document_revision: str = "",
    ) -> dict[str, Any]:
        clean_ids = [str(item).strip() for item in issue_ids if str(item).strip()]
        if not clean_ids:
            raise RevisionError("至少选择一个审稿问题", code="INVALID_INPUT")
        review_store = ReviewStore(self.project_root, self.novel_id)
        revisioned_review = review_store.load_revisioned(chapter_id)
        if revisioned_review is None:
            raise RevisionError("未找到该章节的审稿结果", code="REVIEW_NOT_FOUND")
        review, review_revision = revisioned_review
        expected_review = str(expected_review_revision or "").strip()
        if expected_review and expected_review != review_revision:
            raise RevisionError(
                "审稿结果已变化，请重新选择问题",
                code="REVIEW_CONFLICT",
                recoverable=True,
                details={"expected": expected_review, "current": review_revision},
            )
        issues = normalize_review_issues(chapter_id, review.get("issue_details", []))
        selected = [item for item in issues if item["id"] in set(clean_ids)]
        if len(selected) != len(set(clean_ids)):
            raise RevisionError("部分审稿问题不存在或已变化", code="REVIEW_ISSUE_NOT_FOUND")
        path = self._chapter_path(chapter_id)
        content = path.read_text(encoding="utf-8")
        document_revision = self.fingerprint(content)
        expected_document = str(expected_document_revision or "").strip()
        if expected_document and expected_document != document_revision:
            raise RevisionError(
                "正文已变化，请重新打开审稿问题",
                code="DOCUMENT_CONFLICT",
                recoverable=True,
                details={"expected": expected_document, "current": document_revision},
            )
        review_source_revision = str(review.get("source_revision") or "").strip()
        if review.get("stale") or (
            review_source_revision and review_source_revision != document_revision
        ):
            raise RevisionError(
                "审稿结果对应的正文已经变化，请先重新评审",
                code="REVIEW_STALE",
                recoverable=True,
                details={
                    "review_source_revision": review_source_revision,
                    "current_document_revision": document_revision,
                },
            )
        anchors = [self._resolve_issue_anchor(content, issue) for issue in selected]
        if any(anchor is None for anchor in anchors):
            missing = [
                issue["id"]
                for issue, anchor in zip(selected, anchors, strict=True)
                if anchor is None
            ]
            raise RevisionError(
                "所选审稿问题缺少可定位的正文证据",
                code="ISSUE_NOT_ANCHORED",
                recoverable=True,
                details={"issue_ids": missing},
            )
        resolved = [anchor for anchor in anchors if anchor is not None]
        start = min(item[0] for item in resolved)
        end = max(item[1] for item in resolved)
        request = {
            "action": "review_fix",
            "instruction": str(instruction or "").strip(),
            "target_units": self._bounded_target(target_units),
        }
        generation = self._generate(
            chapter_id=chapter_id,
            content=content,
            start=start,
            end=end,
            request=request,
            review_issues=selected,
        )
        current_review = review_store.load_revisioned(chapter_id)
        current_content = path.read_text(encoding="utf-8")
        current_document_revision = self.fingerprint(current_content)
        if current_review is None or current_review[1] != review_revision:
            raise RevisionError(
                "模型生成期间审稿结果发生变化，提案未保存",
                code="REVIEW_CONFLICT",
                recoverable=True,
                details={
                    "expected": review_revision,
                    "current": "" if current_review is None else current_review[1],
                },
            )
        if current_document_revision != document_revision:
            raise RevisionError(
                "模型生成期间正文发生变化，提案未保存",
                code="DOCUMENT_CONFLICT",
                recoverable=True,
                details={
                    "expected": document_revision,
                    "current": current_document_revision,
                },
            )
        proposal = self._new_proposal(
            chapter_id=chapter_id,
            kind="review_fix",
            content=content,
            start=start,
            end=end,
            request=request,
            review_issue_ids=clean_ids,
            generation=generation,
        )
        proposal["review_revision"] = review_revision
        proposal["review_source_revision"] = review_source_revision
        proposal["review_issue_provenance"] = [
            {
                "issue_id": str(issue["id"]),
                "dimension": str(issue.get("dimension") or ""),
                "evidence": dict(issue.get("evidence") or {}),
                "anchor": dict(issue.get("anchor") or {}),
            }
            for issue in selected
        ]
        self.store.save(proposal)
        return self.present(proposal)

    def get(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.store.load(proposal_id)
        if proposal is None:
            raise RevisionError("修订提案不存在", code="REVISION_NOT_FOUND")
        return self.present(proposal)

    def list(self, *, chapter_id: str = "", status: str = "") -> list[dict[str, Any]]:
        try:
            proposals = self.store.list(
                chapter_id=chapter_id or None,
                status=status or None,
            )
        except RevisionStoreError as exc:
            raise RevisionError(str(exc), code="INVALID_INPUT") from exc
        return [self.present(item) for item in proposals]

    def reject(self, proposal_id: str) -> dict[str, Any]:
        try:
            proposal = self.store.update_status(
                proposal_id,
                "rejected",
                expected={"proposed", "stale"},
                updates={"rejected_at": self._now()},
            )
        except RevisionStoreError as exc:
            raise self._store_error(exc) from exc
        return self.present(proposal)

    def regenerate(self, proposal_id: str) -> dict[str, Any]:
        previous = self.get(proposal_id)
        selection = previous.get("selection") or {}
        if previous.get("status") == "applied":
            raise RevisionError("已应用的提案不能重新生成", code="REVISION_ALREADY_APPLIED")
        self.reject(proposal_id)
        if previous.get("kind") == "review_fix":
            return self.create_from_review(
                chapter_id=str(previous["chapter_id"]),
                issue_ids=list(previous.get("review_issue_ids") or []),
                instruction=str((previous.get("request") or {}).get("instruction") or ""),
                target_units=int((previous.get("request") or {}).get("target_units") or 0),
                expected_review_revision=str(previous.get("review_revision") or ""),
                expected_document_revision=str(previous.get("source_revision") or ""),
            )
        return self.create_selection(
            chapter_id=str(previous["chapter_id"]),
            start=int(selection.get("start") or 0),
            end=int(selection.get("end") or 0),
            instruction=str((previous.get("request") or {}).get("instruction") or ""),
            action=str((previous.get("request") or {}).get("action") or "rewrite"),
            target_units=int((previous.get("request") or {}).get("target_units") or 0),
            original_text=str(selection.get("original_text") or ""),
            full_chapter=previous.get("kind") == "full_chapter_revision",
        )

    def apply(
        self,
        proposal_id: str,
        *,
        replacement_text: str | None = None,
        selected_hunk_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        proposal = self.store.load(proposal_id)
        if proposal is None:
            raise RevisionError("修订提案不存在", code="REVISION_NOT_FOUND")
        if proposal.get("status") != "proposed":
            raise RevisionError(
                "只有待确认提案可以应用",
                code="REVISION_NOT_PROPOSED",
                details={"status": proposal.get("status")},
            )
        chapter_id = str(proposal["chapter_id"])
        path = self._chapter_path(chapter_id)
        try:
            with ProjectWriteLock(
                self.project_root,
                self.novel_id,
                operation=f"revision:{proposal_id}",
            ):
                locked_proposal = self.store.load(proposal_id)
                if locked_proposal is None:
                    raise RevisionError("修订提案不存在", code="REVISION_NOT_FOUND")
                if locked_proposal.get("status") != "proposed":
                    raise RevisionError(
                        "只有待确认提案可以应用",
                        code="REVISION_NOT_PROPOSED",
                        details={"status": locked_proposal.get("status")},
                    )
                proposal = locked_proposal
                current = path.read_text(encoding="utf-8")
                self._check_conflict(proposal, current)
                selection = proposal.get("selection") or {}
                start = int(selection.get("start") or 0)
                end = int(selection.get("end") or 0)
                replacement, accepted_hunks = self._accepted_replacement(
                    proposal,
                    replacement_text=replacement_text,
                    selected_hunk_ids=selected_hunk_ids,
                )
                if len(replacement.encode("utf-8")) > MAX_CHAPTER_BYTES:
                    raise RevisionError(
                        "确认后的替换文本过大",
                        code="REVISION_RESULT_TOO_LARGE",
                    )
                proposal = self.store.update_status(
                    proposal_id,
                    "proposed",
                    expected={"proposed"},
                    updates={
                        "accepted_replacement_text": replacement,
                        "selected_hunk_ids": accepted_hunks,
                        "accepted_at": self._now(),
                    },
                )
                updated = f"{current[:start]}{replacement}{current[end:]}"
                findings = self.validator(current, updated)
                blocking = [item for item in findings if item.get("blocking")]
                if blocking:
                    raise RevisionError(
                        "修订结果未通过提交校验",
                        code="REVISION_VALIDATION_FAILED",
                        recoverable=True,
                        details={"findings": blocking},
                    )
                from tools.manuscript_editing import ManuscriptVersionStore

                checkpoint_reason = (
                    "full_rewrite"
                    if proposal.get("kind") == "full_chapter_revision"
                    else "ai_revision"
                )
                history_version = ManuscriptVersionStore(
                    self.project_root, self.novel_id
                ).checkpoint(
                    chapter_id,
                    reason=checkpoint_reason,
                    label=f"应用修订 {proposal_id} 前",
                    content=current,
                )
                backup = self.store.save_backup(chapter_id, proposal_id, current)
                self._atomic_write(path, updated)
                try:
                    applied = self.store.update_status(
                        proposal_id,
                        "applied",
                        expected={"proposed"},
                        updates={
                            "applied_at": self._now(),
                            "applied_revision": self.fingerprint(updated),
                            "backup_path": backup.relative_to(self.novel_root).as_posix(),
                            "history_version_id": history_version.version_id,
                            "validation": findings,
                        },
                    )
                    self._mark_review_stale(chapter_id, proposal_id, applied)
                except Exception:
                    self._atomic_write(path, current)
                    raise
                from tools.manuscript_acceptance import ManuscriptAcceptanceService

                acceptance = ManuscriptAcceptanceService(
                    self.project_root, self.novel_id
                ).start_acceptance(
                    chapter_id,
                    source="revision",
                    expected_previous_revision=self.fingerprint(current),
                )
        except ProjectBusyError as exc:
            raise RevisionError(str(exc), code="PROJECT_BUSY", recoverable=True) from exc
        except RevisionStoreError as exc:
            raise self._store_error(exc) from exc
        result = self.present(applied)
        result["document"] = {
            "path": path.relative_to(self.novel_root).as_posix(),
            "content": updated,
            "revision": self.fingerprint(updated),
            "version": str(path.stat().st_mtime_ns),
        }
        result["acceptance"] = acceptance
        from tools.mutation_summary import build_mutation_summary

        result["mutation_summary"] = build_mutation_summary(
            operation="revision.apply",
            entity_kind="manuscript",
            entity_id=chapter_id,
            path=result["document"]["path"],
            before=str((proposal.get("selection") or {}).get("original_text") or ""),
            after=replacement,
            source_revision=str(proposal.get("source_revision") or ""),
            result_revision=result["document"]["revision"],
            field_prefix="content.selection",
            flatten=False,
        )
        return result

    def _accepted_replacement(
        self,
        proposal: dict[str, Any],
        *,
        replacement_text: str | None,
        selected_hunk_ids: list[str] | None,
    ) -> tuple[str, list[str]]:
        proposed = str(proposal.get("replacement_text") or "")
        if selected_hunk_ids is None:
            return (
                proposed if replacement_text is None else str(replacement_text),
                [],
            )

        accepted_hunks = [str(item).strip() for item in selected_hunk_ids]
        if (
            not accepted_hunks
            or any(not item for item in accepted_hunks)
            or len(set(accepted_hunks)) != len(accepted_hunks)
        ):
            raise RevisionError("差异块选择格式无效", code="INVALID_INPUT")

        original = str((proposal.get("selection") or {}).get("original_text") or "")
        segments = self._diff(original, proposed)["segments"]
        available_hunks = {
            str(item.get("id"))
            for item in segments
            if item.get("tag") != "equal"
        }
        if any(item not in available_hunks for item in accepted_hunks):
            raise RevisionError("差异块选择已失效", code="INVALID_INPUT")

        selected = set(accepted_hunks)
        composed = "".join(
            str(item.get("after") if item.get("id") in selected else item.get("before"))
            for item in segments
        )
        if replacement_text is not None and str(replacement_text) != composed:
            raise RevisionError(
                "确认文本与所选差异块不一致",
                code="HUNK_SELECTION_MISMATCH",
                recoverable=True,
                details={"selected_hunk_ids": accepted_hunks},
            )
        canonical_order = [
            str(item.get("id"))
            for item in segments
            if item.get("id") in selected
        ]
        return composed, canonical_order

    def present(self, proposal: dict[str, Any]) -> dict[str, Any]:
        payload = dict(proposal)
        original = str((payload.get("selection") or {}).get("original_text") or "")
        replacement = str(payload.get("replacement_text") or "")
        payload["diff"] = self._diff(original, replacement)
        hunk_ids = [str(item["id"]) for item in payload["diff"]["hunks"]]
        payload["issue_hunk_provenance"] = [
            {
                "issue_id": str(issue_id),
                "hunk_ids": hunk_ids,
                "relation": "generated_in_shared_proposal_scope",
                "review_revision": str(payload.get("review_revision") or ""),
                "source_revision": str(payload.get("source_revision") or ""),
            }
            for issue_id in payload.get("review_issue_ids") or []
        ]
        return payload

    def _new_proposal(
        self,
        *,
        chapter_id: str,
        kind: str,
        content: str,
        start: int,
        end: int,
        request: dict[str, Any],
        review_issue_ids: list[str],
        generation: dict[str, Any],
    ) -> dict[str, Any]:
        replacement = str(generation.get("replacement_text") or "").strip("\n")
        if not replacement:
            raise RevisionError("模型没有返回可用的替换文本", code="EMPTY_REVISION_RESULT")
        return {
            "proposal_id": self.store.create_id(),
            "chapter_id": chapter_id,
            "kind": kind,
            "status": "proposed",
            "source_revision": self.fingerprint(content),
            "selection": {
                "start": start,
                "end": end,
                "original_text": content[start:end],
            },
            "request": request,
            "review_issue_ids": review_issue_ids,
            "replacement_text": replacement,
            "rationale": str(generation.get("rationale") or "").strip(),
            "risk_flags": self._string_list(generation.get("risk_flags")),
            "created_at": self._now(),
            "applied_at": None,
        }

    def _generate(
        self,
        *,
        chapter_id: str,
        content: str,
        start: int,
        end: int,
        request: dict[str, Any],
        review_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "chapter_id": chapter_id,
            "selection": content[start:end],
            "context_before": content[max(0, start - 1600) : start],
            "context_after": content[end : end + 1600],
            "request": request,
            "review_issues": review_issues,
        }
        try:
            generated = self.generator(payload)
        except RevisionError:
            raise
        except Exception as exc:
            raise RevisionError(f"修订生成失败: {exc}", code="REVISION_GENERATION_FAILED") from exc
        if isinstance(generated, str):
            return {"replacement_text": generated, "rationale": "", "risk_flags": []}
        if not isinstance(generated, dict):
            raise RevisionError("修订生成器返回了无效结果", code="INVALID_REVISION_RESULT")
        return generated

    def _default_generator(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.llm import LLMClient, LLMConfig, Message

        request = payload["request"]
        action = str(request.get("action") or "rewrite")
        instruction = str(request.get("instruction") or "")
        target_units = int(request.get("target_units") or 0)
        issues = payload.get("review_issues") or []
        issue_text = "\n".join(
            f"- {item.get('summary')}: {item.get('suggestion')}"
            for item in issues
        )
        user_prompt = f"""修订目标：{REVISION_ACTIONS.get(action, action)}
补充要求：{instruction or '无'}
目标长度：{target_units or '保持与原文相近'}
相关审稿问题：
{issue_text or '无'}

前文（只供衔接）：
{payload.get('context_before') or '无'}

需要修改的原文：
{payload.get('selection')}

后文（只供衔接）：
{payload.get('context_after') or '无'}
"""
        response = LLMClient(LLMConfig.from_env()).chat(
            [
                Message(
                    "system",
                    "你是小说修订编辑。只修改指定范围，不改变未授权的事件结果和正典。"
                    "返回 JSON 对象，字段为 replacement_text、rationale、risk_flags。"
                    "replacement_text 只放可直接替换原文的 Markdown，不加代码围栏。",
                ),
                Message("user", user_prompt),
            ],
            temperature=0.45,
            stream=False,
        )
        return self._parse_generation(response.content)

    @staticmethod
    def _parse_generation(content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {"replacement_text": text, "rationale": "", "risk_flags": []}
        if not isinstance(payload, dict):
            raise RevisionError("模型返回的 JSON 不是对象", code="INVALID_REVISION_RESULT")
        return payload

    def _chapter_path(self, chapter_id: str) -> Path:
        if not re.fullmatch(r"ch_\d+", str(chapter_id or "")):
            raise RevisionError("章节 ID 必须形如 ch_001", code="INVALID_INPUT")
        matches = list((self.novel_root / "data" / "manuscript").glob(f"**/{chapter_id}.md"))
        if not matches:
            raise RevisionError("章节正文不存在", code="DOCUMENT_NOT_FOUND")
        if len(matches) > 1:
            raise RevisionError("章节正文路径不唯一", code="AMBIGUOUS_DOCUMENT")
        return matches[0]

    @staticmethod
    def _validated_range(content: str, start: int, end: int) -> tuple[int, int]:
        try:
            clean_start = int(start)
            clean_end = int(end)
        except (TypeError, ValueError) as exc:
            raise RevisionError("选区位置必须是整数", code="INVALID_SELECTION") from exc
        if clean_start < 0 or clean_end <= clean_start or clean_end > len(content):
            raise RevisionError("请选择有效的正文范围", code="INVALID_SELECTION")
        return clean_start, clean_end

    @staticmethod
    def _bounded_target(value: int) -> int:
        try:
            target = int(value or 0)
        except (TypeError, ValueError) as exc:
            raise RevisionError("目标字数必须是整数", code="INVALID_INPUT") from exc
        if target < 0 or target > 12000:
            raise RevisionError("目标字数必须在 0 到 12000 之间", code="INVALID_INPUT")
        return target

    def _check_conflict(self, proposal: dict[str, Any], content: str) -> None:
        selection = proposal.get("selection") or {}
        start = int(selection.get("start") or 0)
        end = int(selection.get("end") or 0)
        original = str(selection.get("original_text") or "")
        current_revision = self.fingerprint(content)
        if (
            current_revision != proposal.get("source_revision")
            or start < 0
            or end > len(content)
            or content[start:end] != original
        ):
            try:
                self.store.update_status(
                    str(proposal["proposal_id"]),
                    "stale",
                    expected={"proposed"},
                    updates={"stale_at": self._now(), "current_revision": current_revision},
                )
            except RevisionStoreError:
                pass
            raise RevisionError(
                "原文已变化，请重新生成修改提案",
                code="DOCUMENT_CONFLICT",
                recoverable=True,
                details={
                    "proposal_id": proposal.get("proposal_id"),
                    "chapter_id": proposal.get("chapter_id"),
                    "expected_revision": proposal.get("source_revision"),
                    "current_revision": current_revision,
                },
            )

    @staticmethod
    def _resolve_issue_anchor(content: str, issue: dict[str, Any]) -> tuple[int, int] | None:
        evidence = issue.get("evidence") or {}
        quote = str(evidence.get("quote") or "")
        anchor = issue.get("anchor") or {}
        try:
            start_hint = int(anchor.get("start_hint"))
            end_hint = int(anchor.get("end_hint"))
        except (TypeError, ValueError):
            start_hint = end_hint = -1
        if 0 <= start_hint < end_hint <= len(content):
            if not quote or content[start_hint:end_hint] == quote:
                return start_hint, end_hint
        if quote:
            first = content.find(quote)
            if first >= 0 and content.find(quote, first + 1) < 0:
                return first, first + len(quote)
        return None

    @staticmethod
    def _default_validator(before: str, after: str) -> list[dict[str, Any]]:
        if not after.strip():
            return [{"code": "EMPTY_DOCUMENT", "message": "章节不能为空", "blocking": True}]
        if "\x00" in after:
            return [{"code": "INVALID_CHARACTER", "message": "章节包含空字符", "blocking": True}]
        if len(after.encode("utf-8")) > MAX_CHAPTER_BYTES:
            return [{"code": "DOCUMENT_TOO_LARGE", "message": "章节超过 2 MB", "blocking": True}]
        if before.lstrip().startswith("# ") and not after.lstrip().startswith("# "):
            return [
                {
                    "code": "MISSING_CHAPTER_HEADING",
                    "message": "章节标题被移除",
                    "blocking": True,
                }
            ]
        before_errors = {
            (item.rule, item.description)
            for item in PostWriteValidator().validate(before)
            if item.severity == "error"
        }
        findings: list[dict[str, Any]] = []
        for item in PostWriteValidator().validate(after):
            key = (item.rule, item.description)
            introduced = item.severity == "error" and key not in before_errors
            findings.append(
                {
                    "code": item.rule.upper(),
                    "message": item.description,
                    "severity": item.severity,
                    "location": item.location or "",
                    "blocking": introduced,
                }
            )
        return findings

    def _mark_review_stale(
        self,
        chapter_id: str,
        proposal_id: str,
        proposal: dict[str, Any],
    ) -> None:
        store = ReviewStore(self.project_root, self.novel_id)
        store.mark_stale(
            chapter_id,
            reason="chapter_revised",
            current_source_revision=str(proposal.get("applied_revision") or ""),
            history_entry={
                "proposal_id": proposal_id,
                "applied_at": proposal.get("applied_at"),
                "applied_revision": str(proposal.get("applied_revision") or ""),
                "issue_ids": list(proposal.get("review_issue_ids") or []),
                "original_issue_ids": list(proposal.get("review_issue_ids") or []),
                "review_revision": str(proposal.get("review_revision") or ""),
                "source_revision": str(proposal.get("source_revision") or ""),
            },
        )

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            temp_path.replace(path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _diff(original: str, replacement: str) -> dict[str, Any]:
        before = original.splitlines(keepends=True)
        after = replacement.splitlines(keepends=True)
        unified = "".join(
            difflib.unified_diff(
                before,
                after,
                fromfile="原文",
                tofile="提案",
                lineterm="\n",
            )
        )
        matcher = difflib.SequenceMatcher(a=before, b=after)
        segments = []
        hunks = []
        hunk_index = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            segment = {
                "tag": tag,
                "before": "".join(before[i1:i2]),
                "after": "".join(after[j1:j2]),
            }
            if tag != "equal":
                segment["id"] = f"hunk_{hunk_index}"
                hunk_index += 1
                hunks.append(dict(segment))
            segments.append(segment)
        return {
            "unified": unified,
            "hunks": hunks,
            "segments": segments,
            "stats": {
                "removed_units": len(original),
                "added_units": len(replacement),
                "delta_units": len(replacement) - len(original),
            },
        }

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _store_error(exc: RevisionStoreError) -> RevisionError:
        message = str(exc)
        if "not found" in message.lower():
            return RevisionError("修订提案不存在", code="REVISION_NOT_FOUND")
        if "status is" in message.lower():
            return RevisionError("修订提案状态已变化", code="REVISION_STATUS_CONFLICT")
        return RevisionError(message, code="REVISION_STORE_FAILED")
