"""Settlement backfill for existing / imported chapters.

Gap being closed: chapter memory, runtime truth files and the character-state
index were only ever produced inside the chapter-write pipeline's settle stage.
Imported manuscripts (or chapters written before this feature) therefore never
got a settlement pass, so:

* context packets had no per-chapter recap of earlier chapters,
* continuity / foreshadowing / character-state surfaces had no facts to check,
* review's canon domain could not be verified and silently stayed inconclusive.

``run()`` replays an observer + settler pass over each chapter's **existing
prose** (never regenerating it), then commits results through the same
machinery the write pipeline uses: ChapterMemoryStore.save(),
``apply_runtime_delta_with_fallback()`` (legacy additive notes), and a final
character-state index refresh.

Robustness: per chapter the model call is a single compact prompt with a hard
output budget; on provider truncation / malformed output it retries once, and
if it still fails the chapter is persisted with a degraded memory record
(summary derived from the prose head) so that no chapter is left without
memory.  Every chapter is reported (applied / degraded / failed) and the run is
idempotent (``only_missing`` skips chapters that already have memory).
"""

from __future__ import annotations

from tools.llm import long_generation_stream
from tools.novel_workspace import count_writing_units

import asyncio
import logging
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

logger = logging.getLogger(__name__)

_CHAPTER_RE = re.compile(r"^ch_(\d+)\.md$")

# Marker stored as the memory ``observations`` value for chapters whose model
# pass failed (degraded record) so a later run can retry exactly those.
_DEGRADED_MARK = "（结算降级：模型未产出结构化结果）"

#: One compact extraction needs little room; a truncated answer means the model
#: spent the budget on reasoning, so the retry raises it.
SETTLE_MAX_TOKENS = 3200
#: Attempts per chapter. Each one changes a lever (budget, self-repair,
#: backoff); repeating the same request is what used to lose the chapter.
SETTLE_ATTEMPTS = 3


class _SettleStructureError(ValueError):
    """The model answered, but the answer did not parse.

    The raw text travels with the error so the next attempt can ask the model
    to repair its own answer instead of guessing again.
    """

    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


def _novel_root(project_root: Path, novel_id: str) -> Path:
    return Path(project_root).resolve() / "data" / "novels" / novel_id


def discover_chapters(
    project_root: Path, novel_id: str
) -> list[tuple[str, Path]]:
    """List ``(chapter_id, path)`` for every manuscript chapter, in order."""
    manuscript_dir = _novel_root(project_root, novel_id) / "data" / "manuscript"
    found: list[tuple[int, str, Path]] = []
    if manuscript_dir.is_dir():
        for path in manuscript_dir.rglob("ch_*.md"):
            match = _CHAPTER_RE.match(path.name)
            if match:
                found.append((int(match.group(1)), path.stem, path))
    found.sort(key=lambda item: item[0])
    return [(item[1], item[2]) for item in found]


def _load_chapter(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    title = ""
    body = text
    if text.startswith("#"):
        first, _, rest = text.partition("\n")
        title = first.lstrip("#").strip()
        body = rest.strip()
    if not title:
        title = path.stem
    return title, body


def _clean_text(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit]


def _memory_record(project_root: Path, novel_id: str, chapter_id: str) -> bool:
    try:
        from tools.chapter_memory import ChapterMemoryStore

        return (
            ChapterMemoryStore(Path(project_root), novel_id).load(chapter_id) is not None
        )
    except Exception:
        return False


def _chapter_sort_key(chapter_id: str) -> tuple[int, str]:
    """Order chapters by number so a mixed candidate list stays in book order."""
    digits = "".join(char for char in str(chapter_id) if char.isdigit())
    return (int(digits) if digits else 10**9, str(chapter_id))


def _degraded_ids(project_root: Path, novel_id: str) -> list[str]:
    """Chapters whose memory is a degraded record (model pass failed earlier)."""
    try:
        from tools.chapter_memory import ChapterMemoryStore

        store = ChapterMemoryStore(Path(project_root), novel_id)
        ids: list[str] = []
        for path in store.memory_dir.glob("ch_*.yaml"):
            record = store.load(path.stem)
            if isinstance(record, dict) and str(record.get("observations") or "") == _DEGRADED_MARK:
                ids.append(path.stem)
        return sorted(ids)
    except Exception:
        return []


def _strip_yaml_fence(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _parse_settle_yaml(text: str) -> dict[str, Any]:
    """Parse the compact settle YAML; raises ValueError when unusable."""
    fenced = re.search(r"```(?:yaml|yml|json)?\s*\n(.*?)```", str(text), re.S)
    raw = yaml.safe_load(fenced.group(1) if fenced else _strip_yaml_fence(text))
    if not isinstance(raw, dict):
        raise ValueError("settle output is not a mapping")
    out: dict[str, Any] = {}
    updates = raw.get("state_updates")
    if isinstance(updates, dict):
        for key in ("current_state", "ledger", "relationships"):
            value = updates.get(key)
            if isinstance(value, str) and value.strip():
                out[key] = value.strip()
    else:
        for key in ("current_state", "ledger", "relationships"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                out[key] = value.strip()
    observations = raw.get("observations")
    if isinstance(observations, str):
        out["observations"] = observations.strip()
    elif isinstance(observations, list):
        out["observations"] = "\n".join(str(item).strip() for item in observations if str(item).strip())
    summary = raw.get("chapter_summary")
    if isinstance(summary, str) and summary.strip():
        out["chapter_summary"] = summary.strip()
    if not (out.get("current_state") or out.get("ledger") or out.get("relationships") or out.get("observations") or out.get("chapter_summary")):
        raise ValueError("settle output contains no usable fields")
    return out


def _compact_settle(
    client: Any,
    chapter_id: str,
    title: str,
    content: str,
    truth_context: str,
    *,
    strict: bool = False,
    max_tokens: int = SETTLE_MAX_TOKENS,
    repair: str = "",
) -> dict[str, Any]:
    """One compact LLM call: observations + legacy state deltas + summary."""
    from tools.llm import Message

    system = (
        "你是小说的结算编辑。只从下面这【一章既有正文】中提取客观事实增量，"
        "不得改写正文、不得虚构。输出严格 YAML，不要代码围栏、不要解释、不要其他文本。\n"
        "结构（省略没有变化的字段）：\n"
        "observations: |\n"
        "  - 关键事实一行一条（角色状态/地点/事件/物品/伏笔/数值），不超过 12 条\n"
        "state_updates:\n"
        "  current_state: \"本章新增的世界当前状态（≤150字，只写新增）\"\n"
        "  ledger: \"本章新增的资源/账本事实（≤150字）\"\n"
        "  relationships: \"本章新增的角色关系/阵营事实（≤150字）\"\n"
        "chapter_summary: \"100-160字本章摘要\"\n"
        "若某字段确无新增则省略该字段；绝不要重写整份状态文件。"
    )
    user = (
        f"章节编号：{chapter_id}\n章节标题：{title}\n\n"
        f"章节正文（原文）：\n{content}\n\n"
        f"当前运行态摘要（只读参考，不要照抄）：\n{truth_context}\n\n"
        "请输出上述 YAML。"
    )
    if strict:
        user += "\n上一次结构无效。只输出 YAML mapping，必须包含 chapter_summary；不要解释或围栏。"
    if repair:
        # Self-repair: hand the invalid answer back so the model can fix its own
        # shape. Repeating the same request cannot fix a structure problem.
        user += (
            "\n\n你上一次的回答无法解析，原文如下（只保留其中可用的信息，"
            "重新输出为合法的 YAML mapping，不要输出任何其它文字）：\n"
            f"---\n{repair[:2000]}\n---"
        )
    response = client.chat(
        messages=[Message("system", system), Message("user", user)],
        temperature=0.0 if strict else 0.2,
        max_tokens=max_tokens,
        stream=long_generation_stream(),
        operation="settle_backfill",
        # The retry policy below is the only retry layer: two layers stack into
        # a burst, and the burst is what a rate limiter punishes.
        max_retries=0,
    )
    from tools.llm.response import classify_response

    classify_response(response.content, finish_reason=getattr(response, "finish_reason", ""))
    try:
        return _parse_settle_yaml(response.content)
    except (ValueError, yaml.YAMLError) as exc:
        raise _SettleStructureError(str(exc), str(response.content or "")) from exc


def analyze_existing_chapter(
    project_root: Path,
    novel_id: str,
    *,
    chapter_id: str,
    title: str,
    content: str,
    truth_context: str = "",
    profile: Optional[dict[str, Any]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """Pure model-facing fact extraction used by acceptance and backfill.

    The function never writes manuscript, memory, or runtime state. Callers bind
    and verify the source SHA before adopting its result.
    """
    from tools.chapter_pipeline import configure_writer_llm
    from tools.llm import LLMClient, LLMConfig
    from tools.model_profiles import activate_model_profile

    def call() -> dict[str, Any]:
        config = LLMConfig.from_env()
        configure_writer_llm(config)
        client = LLMClient(config)
        return asyncio.run(
            _settle_one(
                client,
                chapter_id,
                title,
                content,
                truth_context or "（无既有运行态）",
                cancelled=cancelled,
            )
        )

    if profile is not None:
        with activate_model_profile(profile):
            result = call()
    else:
        result = call()
    return {
        "degraded": bool(result.get("degraded")),
        "degraded_reason": str(result.get("degraded_reason") or ""),
        "failures": list(result.get("failures") or []),
        "chapter_summary": str(result.get("chapter_summary") or ""),
        "observations": str(result.get("observations") or ""),
        "legacy_updates": {
            key: result[key]
            for key in ("current_state", "ledger", "relationships")
            if str(result.get(key) or "").strip()
        },
        "state_delta": {},
    }


def _degraded_summary(content: str) -> str:
    cleaned = _clean_text(content, 200)
    cleaned = re.sub(r"^#+[\s#]*", "", cleaned).strip()
    return cleaned[:160] or "（本章未生成摘要，结算降级）"


async def _settle_one(
    client: Any,
    chapter_id: str,
    title: str,
    content: str,
    truth_context: str,
    *,
    cancelled: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """Retry structured-output failures with a lever that changes the outcome.

    A blind retry repeats the same request: a truncated answer stays truncated
    and an invalid structure stays invalid, so three fast attempts all fail
    and the chapter is degraded. Each attempt here changes exactly one lever:

    * a truncated answer is asked again with a bigger output budget,
    * an unparseable answer is handed back to the model for repair,
    * a provider failure waits out a backoff.

    Every failure keeps its reason, so a degraded chapter can say why.
    """
    from tools.llm.cancellation import ModelCancelledError, model_cancellation
    from tools.llm.retry import AttemptFailure, classify_failure, wait_before_retry

    failures: list[AttemptFailure] = []
    budget = SETTLE_MAX_TOKENS
    repair = ""
    for attempt in range(1, SETTLE_ATTEMPTS + 1):
        if cancelled and cancelled():
            raise ModelCancelledError("MODEL_CANCELLED: 结算已取消")
        try:
            with model_cancellation(cancelled) if callable(cancelled) else nullcontext():
                result = _compact_settle(
                    client,
                    chapter_id,
                    title,
                    content,
                    truth_context,
                    strict=attempt > 1,
                    max_tokens=budget,
                    repair=repair,
                )
        except _SettleStructureError as exc:
            failure = AttemptFailure(
                "MODEL_OUTPUT_UNPARSEABLE", str(exc), attempt, True, exc.raw[:200]
            )
            failures.append(failure)
            repair = exc.raw
            if attempt >= SETTLE_ATTEMPTS:
                break
            # The repair prompt is the lever; waiting only delays the fix.
            continue
        except ModelCancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            failure = classify_failure(exc, attempt=attempt)
            failures.append(failure)
            if not failure.retryable or attempt >= SETTLE_ATTEMPTS:
                break
            if failure.code == "MODEL_OUTPUT_TRUNCATED":
                budget = min(SETTLE_MAX_TOKENS * 3, int(budget * 1.5))
            if failure.needs_wait:
                # Only a provider-side failure needs the provider to breathe.
                wait_before_retry(attempt)
            continue
        # Every caller reads the same three fields, so a success carries them
        # too: an absent key is what made a healthy chapter look like it had
        # no verdict at all.
        result["degraded"] = False
        result["degraded_reason"] = ""
        result["failures"] = [item.as_dict() for item in failures]
        return result
    return {
        "chapter_summary": _degraded_summary(content),
        "observations": _DEGRADED_MARK,
        "degraded": True,
        "failures": [item.as_dict() for item in failures],
        "degraded_reason": failures[-1].code if failures else "MODEL_OUTPUT_INVALID",
    }


def run(
    project_root: Path,
    novel_id: str,
    *,
    chapter_ids: Optional[list[str]] = None,
    only_missing: bool = True,
    include_degraded: bool = True,
    profile: Optional[dict[str, Any]] = None,
    progress: Optional[Callable[[str, str], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    report: Optional[Callable[[int, int, str], None]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Backfill settlement for chapters (default: every chapter missing memory).

    Returns a summary dict; never mutates manuscript prose.
    """
    from tools.chapter_memory import ChapterMemoryStore
    from tools.chapter_pipeline import apply_runtime_delta_with_fallback
    from tools.character_state_index import CharacterStateIndex
    from tools.llm import LLMClient, LLMConfig
    from tools.llm.cancellation import ModelCancelledError
    from tools.model_profiles import activate_model_profile
    from tools.truth_manager import TruthFilesManager

    project_root = Path(project_root).resolve()
    chapters = discover_chapters(project_root, novel_id)
    wanted_ids = {str(cid) for cid in (chapter_ids or [])} or None
    candidates = [
        (cid, path) for cid, path in chapters if wanted_ids is None or cid in wanted_ids
    ]
    extra_ids: set[str] = set()
    if only_missing:
        candidates = [
            (cid, path)
            for cid, path in candidates
            if not _memory_record(project_root, novel_id, cid)
        ]
        if include_degraded:
            extra_ids = set(_degraded_ids(project_root, novel_id))
            # Merge into one dict and re-sort by chapter number. Prepending the
            # degraded chapters used to process them before earlier ones, so a
            # later chapter's model call saw a truth baseline that already
            # contained an earlier chapter's delta - "only what this chapter
            # adds" was extracted against the wrong baseline, and the snapshot
            # numbering stopped tracking chapter order.
            merged = dict(candidates)
            for cid, path in chapters:
                if cid in extra_ids and (wanted_ids is None or cid in wanted_ids):
                    merged.setdefault(cid, path)
            candidates = sorted(
                merged.items(), key=lambda item: _chapter_sort_key(item[0])
            )

    applied: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    truth_manager = TruthFilesManager(project_root, novel_id)
    memory = ChapterMemoryStore(project_root, novel_id)

    def _say(message: str) -> None:
        if log:
            log(message)

    if progress:
        progress("model", "逐章结算既有正文（只写记忆/真相，不改正文）")
    total = len(candidates)
    if report:
        report(0, total, "chapters")

    # Serialize the whole run. `load_truth_files` -> `create_snapshot` ->
    # `apply_runtime_delta_with_fallback` is a read-modify-write on the shared
    # truth files; without the lock two overlapping runs both reported success
    # while only one chapter's delta survived - and the other's memory record
    # was already written, so the default `only_missing` skipped it forever.
    from tools.project_lock import ProjectWriteLock

    with ProjectWriteLock(project_root, novel_id, operation="settle_backfill"):
        for index, (chapter_id, path) in enumerate(candidates, start=1):
            if cancelled and cancelled():
                break
            title, content = _load_chapter(path)
            try:
                truth = truth_manager.load_truth_files()
                truth_context = "\n".join(
                    _clean_text(part, 600)
                    for part in (
                        getattr(truth, "current_state", "") or "",
                        getattr(truth, "ledger", "") or "",
                        getattr(truth, "relationships", "") or "",
                    )
                    if part.strip()
                ) or "（无既有运行态）"

                def _call() -> dict[str, Any]:
                    config = LLMConfig.from_env()
                    # Reuse the write pipeline's thinking-mode policy (flash models
                    # must run with reasoning disabled, else they burn the whole
                    # output budget on reasoning and return empty "length" stops).
                    try:
                        from tools.chapter_pipeline import configure_writer_llm

                        configure_writer_llm(config)
                    except Exception:
                        pass
                    client = LLMClient(config)
                    return asyncio.run(
                        _settle_one(
                            client, chapter_id, title, content, truth_context, cancelled=cancelled
                        )
                    )

                if profile is not None:
                    with activate_model_profile(profile):
                        settled = _call()
                else:
                    settled = _call()

                observations = str(settled.get("observations") or "").strip()
                summary = str(settled.get("chapter_summary") or "").strip()
                updates = {
                    key: settled[key]
                    for key in ("current_state", "ledger", "relationships")
                    if str(settled.get(key) or "").strip()
                }
                snapshot = truth_manager.create_snapshot(max(index - 1, 0))
                try:
                    effective_delta, fallback = apply_runtime_delta_with_fallback(
                        truth_manager,
                        {},
                        updates,
                        chapter_id=chapter_id,
                        known_entities=[],
                    )
                    memory.save(
                        chapter_id=chapter_id,
                        title=title,
                        summary=summary,
                        word_count=count_writing_units(content),
                        observations=observations,
                        token_usage={},
                    )
                    (degraded if settled.get("degraded") else applied).append(
                        {
                            "chapter_id": chapter_id,
                            "word_count": count_writing_units(content),
                            "notes": bool(effective_delta or updates),
                            "fallback": bool(fallback),
                            "reason": str(settled.get("degraded_reason") or ""),
                            "failures": list(settled.get("failures") or []),
                        }
                    )
                    if settled.get("degraded"):
                        # A degraded chapter is a lost chapter: the recap is a
                        # placeholder, not a fact record. Say so loudly — the
                        # run still reports "completed" otherwise.
                        logger.warning(
                            "结算降级 %s: %s (%d 次尝试)",
                            chapter_id,
                            settled.get("degraded_reason") or "MODEL_OUTPUT_INVALID",
                            len(settled.get("failures") or []),
                        )
                    _say(f"applied {chapter_id} (notes={bool(effective_delta or updates)})")
                except Exception as exc:
                    try:
                        truth_manager.restore_snapshot(snapshot)
                    except Exception:
                        pass
                    # Degraded path: memory still persisted so the chapter is not
                    # left without a recap; truth delta is skipped.
                    memory.save(
                        chapter_id=chapter_id,
                        title=title,
                        summary=summary or _degraded_summary(content),
                        word_count=count_writing_units(content),
                        observations=observations or _DEGRADED_MARK,
                        token_usage={},
                    )
                    degraded.append({"chapter_id": chapter_id, "error": f"{type(exc).__name__}: {exc}"})
                    _say(f"degraded {chapter_id}: {type(exc).__name__}: {exc}")
            except ModelCancelledError:
                # A cancel request is not a degradation. Turning it into a
                # placeholder recap would keep the run going and report a
                # "lost" chapter that nobody asked to lose.
                raise
            except Exception as exc:
                # Even when the model pass fails, persist a degraded memory record
                # so the chapter is never left without a recap for later context /
                # review.  Truth deltas are skipped for such chapters.
                try:
                    memory.save(
                        chapter_id=chapter_id,
                        title=title,
                        summary=_degraded_summary(content),
                        word_count=count_writing_units(content),
                        observations=_DEGRADED_MARK,
                        token_usage={},
                    )
                    degraded.append({"chapter_id": chapter_id, "error": f"{type(exc).__name__}: {exc}"})
                    _say(f"degraded {chapter_id}: {type(exc).__name__}: {exc}")
                except Exception as save_exc:
                    failed.append(
                        {"chapter_id": chapter_id, "error": f"{type(save_exc).__name__}: {save_exc}"}
                    )
                    _say(f"failed {chapter_id}: {type(save_exc).__name__}: {save_exc}")
            if report:
                report(index, total, "chapters")

    try:
        CharacterStateIndex(project_root, novel_id).refresh()
    except Exception:
        pass

    return {
        "novel_id": novel_id,
        "checked": len(candidates),
        "applied": applied,
        "applied_count": len(applied),
        "degraded_count": len(degraded),
        "degraded": degraded,
        "failed_count": len(failed),
        "failed": failed,
        "only_missing": only_missing,
    }
