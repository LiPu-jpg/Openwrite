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

import asyncio
import re
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

_CHAPTER_RE = re.compile(r"^ch_(\d+)\.md$")

# Marker stored as the memory ``observations`` value for chapters whose model
# pass failed (degraded record) so a later run can retry exactly those.
_DEGRADED_MARK = "（结算降级：模型未产出结构化结果）"


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
    raw = yaml.safe_load(_strip_yaml_fence(text))
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
    response = client.chat(
        messages=[Message("system", system), Message("user", user)],
        temperature=0.2,
        max_tokens=3200,
        stream=False,
        operation="settle_backfill",
    )
    return _parse_settle_yaml(response.content)


def analyze_existing_chapter(
    project_root: Path,
    novel_id: str,
    *,
    chapter_id: str,
    title: str,
    content: str,
    truth_context: str = "",
    profile: Optional[dict[str, Any]] = None,
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
            )
        )

    if profile is not None:
        with activate_model_profile(profile):
            result = call()
    else:
        result = call()
    return {
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
) -> dict[str, Any]:
    """Compact settle with one retry; raises if both attempts fail."""
    try:
        return _compact_settle(client, chapter_id, title, content, truth_context)
    except Exception:
        # Retry with a trimmed body (transient truncation / noisy prose can
        # push the model off YAML); shorter input usually steadies it.
        trimmed = content[:4000]
        return _compact_settle(client, chapter_id, title, trimmed, truth_context)


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
            candidates = [
                (cid, path)
                for cid, path in chapters
                if cid in extra_ids and (wanted_ids is None or cid in wanted_ids)
            ] + candidates

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
                    _settle_one(client, chapter_id, title, content, truth_context)
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
                    word_count=len(content),
                    observations=observations,
                    token_usage={},
                )
                applied.append(
                    {
                        "chapter_id": chapter_id,
                        "word_count": len(content),
                        "notes": bool(effective_delta or updates),
                        "fallback": bool(fallback),
                    }
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
                    word_count=len(content),
                    observations=observations or _DEGRADED_MARK,
                    token_usage={},
                )
                degraded.append({"chapter_id": chapter_id, "error": f"{type(exc).__name__}: {exc}"})
                _say(f"degraded {chapter_id}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            # Even when the model pass fails, persist a degraded memory record
            # so the chapter is never left without a recap for later context /
            # review.  Truth deltas are skipped for such chapters.
            try:
                memory.save(
                    chapter_id=chapter_id,
                    title=title,
                    summary=_degraded_summary(content),
                    word_count=len(content),
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
