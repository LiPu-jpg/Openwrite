"""Who picks up the pieces when a step fails.

A failure used to reach the next attempt as one flat string, so the retry was
the identical request and made the identical mistake. Two things have to hold
for the next attempt to be worth anything:

* the reason has to travel with it - the retry has to read why the last one
  failed;
* the reason has to be a *kind* of reason - a provider hiccup, an unusable
  answer and a missing confirmation need three different responses, and the
  agent in front of the loop can only pick one if it can tell them apart.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from test_studio_tasks import _save_accepted_chapter, _wait
from tools.agent.react import ReActAgent
from tools.failure_diagnosis import (
    BUSY,
    CANCELLED,
    CONTENT,
    PERMISSION,
    TRANSPORT,
    diagnose,
    diagnose_exception,
    guidance_for,
)
from tools.init_project import init_project
from tools.llm.errors import RateLimitError
from tools.novel_service import NovelServiceError
from tools.studio import StudioApplication

# ── the diagnosis itself ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("PROVIDER_RATE_LIMIT", TRANSPORT),
        ("PROVIDER_NETWORK_ERROR", TRANSPORT),
        ("PROVIDER_TIMEOUT", TRANSPORT),
        ("MODEL_OUTPUT_TRUNCATED", CONTENT),
        ("MODEL_OUTPUT_UNPARSEABLE", CONTENT),
        ("CHAPTER_LENGTH_OUT_OF_RANGE", CONTENT),
        ("PROVIDER_AUTH_ERROR", PERMISSION),
        ("CONFIRMATION_REQUIRED", PERMISSION),
        ("PROJECT_BUSY", BUSY),
        ("TASK_CANCELLED", CANCELLED),
        ("SOMETHING_ELSE", "unknown"),
    ],
)
def test_a_code_is_named_as_a_kind_of_failure(code: str, category: str):
    assert diagnose(code, "boom").category == category


def test_only_a_provider_hiccup_is_worth_repeating_on_its_own():
    # A missing confirmation is a person, not a provider: retrying it burns
    # the budget and changes nothing.
    assert diagnose("PROVIDER_RATE_LIMIT").auto_retryable is True
    assert diagnose("CONFIRMATION_REQUIRED").auto_retryable is False
    assert diagnose("MODEL_OUTPUT_TRUNCATED").auto_retryable is False


def test_an_exception_without_a_code_is_still_classified():
    diagnosis = diagnose_exception(RateLimitError("请求过多", "429"))
    assert diagnosis.category == TRANSPORT
    assert diagnosis.code == "PROVIDER_RATE_LIMIT"


def test_the_guidance_line_names_the_failure_and_what_would_help():
    line = guidance_for(diagnose("MODEL_OUTPUT_TRUNCATED", "输出被截断").as_dict())
    assert "MODEL_OUTPUT_TRUNCATED" in line
    assert "输出被截断" in line
    assert "不要原样再发一次" in line


# ── the agent in front of the tool ───────────────────────────────────────────


def test_the_agent_is_told_what_kind_of_failure_it_is():
    payload = {
        "ok": False,
        "error": "输出被截断",
        "code": "MODEL_OUTPUT_TRUNCATED",
        "diagnosis": diagnose("MODEL_OUTPUT_TRUNCATED", "输出被截断").as_dict(),
    }
    reason = ReActAgent._tool_failure_reason(json.dumps(payload, ensure_ascii=False))
    assert "content" in reason
    assert "输出被截断" in reason
    # The hint is what tells the agent what to change.
    assert "不要原样再发一次" in reason


def test_a_tool_failure_without_a_diagnosis_still_reports_its_reason():
    payload = {"ok": False, "error": "未找到章节", "code": "NOT_FOUND"}
    assert ReActAgent._tool_failure_reason(json.dumps(payload, ensure_ascii=False)) == "未找到章节"


# ── the next attempt ─────────────────────────────────────────────────────────


def _outline(app: StudioApplication) -> None:
    outline = app.read_document("src/outline.md")
    app.write_document(
        outline["path"],
        """# 第一卷

## 第一幕

### 第一节

#### 第一章

开场。

#### 第二章

推进。
""",
        outline["version"],
    )


def test_the_retry_of_a_failed_chapter_reads_why_it_failed(tmp_path: Path) -> None:
    """The retry has to be a different request, not the same one again."""
    init_project(tmp_path, "demo")
    attempts: list[dict] = []
    failed_once: set[str] = set()

    def writer(root: Path, args: dict) -> dict:
        attempts.append(dict(args))
        chapter_id = args["chapter_id"]
        if chapter_id == "ch_001" and chapter_id not in failed_once:
            failed_once.add(chapter_id)
            raise NovelServiceError(
                "输出被截断，章节没有写完", code="MODEL_OUTPUT_TRUNCATED"
            )
        number = int(chapter_id.split("_")[1])
        path, acceptance = _save_accepted_chapter(
            root, chapter_id, f"第{number}章", f"第{number}章正文。"
        )
        return {
            "ok": True,
            "chapter_id": chapter_id,
            "title": f"第{number}章",
            "word_count": 6,
            "draft_path": str(path),
            "acceptance": acceptance,
        }

    def reviewer(root: Path, args: dict) -> dict:
        del root
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": True,
            "score": 90,
            "issues": 0,
            "issue_details": [],
        }

    app = StudioApplication(tmp_path, writer_executor=writer, review_executor=reviewer)
    _outline(app)
    try:
        task = app.create_task(
            {
                "type": "continuous_write",
                "input": {"max_chapters": 2, "minimum_review_score": 82, "max_failures": 2},
            }
        )
        completed = _wait(app, task["task_id"], {"completed"}, timeout=10)
        result = completed["result"]
        assert [item["chapter_id"] for item in result["completed_chapters"]] == ["ch_001", "ch_002"]

        # The first attempt had no guidance; the retry carries the reason.
        first = next(item for item in attempts if item["chapter_id"] == "ch_001")
        second = [item for item in attempts if item["chapter_id"] == "ch_001"][1]
        assert "输出被截断" not in str(first.get("guidance") or "")
        assert "输出被截断" in str(second.get("guidance") or "")

        # The chapter was written on the retry, so it is not failed any more.
        assert result["failed_chapters"] == []
        assert [item["chapter_id"] for item in result["recovered_chapters"]] == ["ch_001"]

        # The failure is recorded with a kind, not just a string.
        recorded = result["recovered_chapters"][0]
        assert recorded["diagnosis"]["category"] == CONTENT
        assert recorded["diagnosis"]["code"] == "MODEL_OUTPUT_TRUNCATED"
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_the_task_retry_carries_the_failure_memory(tmp_path: Path) -> None:
    """Retrying the whole task must not be a blind retry either."""
    from tools.task_runner import PersistentTaskRunner, TaskContext
    from tools.task_store import TaskStore

    init_project(tmp_path, "demo")
    store = TaskStore(tmp_path, "demo")
    original = store.create("continuous_write", {"max_chapters": 2})
    store.transition(
        original["task_id"],
        status="completed",
        updates={
            "result": {
                "completed_chapters": [{"chapter_id": "ch_001"}],
                "failed_chapters": [
                    {"chapter_id": "ch_002", "code": "MODEL_OUTPUT_TRUNCATED"}
                ],
                "failure_memory": {
                    "ch_002": {
                        "code": "MODEL_OUTPUT_TRUNCATED",
                        "guidance": "上一次失败（MODEL_OUTPUT_TRUNCATED）：输出被截断",
                    }
                },
                "usage": {"total_tokens": 120},
            }
        },
        event="task_progress_saved",
    )
    observed: dict = {}
    done = threading.Event()

    def handler(payload: dict, context: TaskContext) -> dict:
        del context
        observed.update(payload)
        done.set()
        return {}

    runner = PersistentTaskRunner(
        tmp_path, "demo", handlers={"continuous_write": handler}
    )
    try:
        runner.retry(original["task_id"])
        assert done.wait(10), "the retried task never ran"
        assert observed.get("_failure_memory", {}).get("ch_002", {}).get(
            "code"
        ) == "MODEL_OUTPUT_TRUNCATED"
    finally:
        runner.shutdown(wait=True)


def test_a_recovered_chapter_is_not_a_failed_chapter(tmp_path: Path) -> None:
    init_project(tmp_path, "demo")
    failed_once: set[str] = set()

    def writer(root: Path, args: dict) -> dict:
        chapter_id = args["chapter_id"]
        if chapter_id == "ch_001" and chapter_id not in failed_once:
            failed_once.add(chapter_id)
            raise NovelServiceError(
                "输出被截断，章节没有写完", code="MODEL_OUTPUT_TRUNCATED"
            )
        number = int(chapter_id.split("_")[1])
        path, acceptance = _save_accepted_chapter(
            root, chapter_id, f"第{number}章", f"第{number}章正文。"
        )
        return {
            "ok": True,
            "chapter_id": chapter_id,
            "title": f"第{number}章",
            "word_count": 6,
            "draft_path": str(path),
            "acceptance": acceptance,
        }

    def reviewer(root: Path, args: dict) -> dict:
        del root
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": True,
            "score": 90,
            "issues": 0,
            "issue_details": [],
        }

    app = StudioApplication(tmp_path, writer_executor=writer, review_executor=reviewer)
    _outline(app)
    try:
        task = app.create_task(
            {
                "type": "continuous_write",
                "input": {"max_chapters": 2, "minimum_review_score": 82, "max_failures": 2},
            }
        )
        completed = _wait(app, task["task_id"], {"completed"}, timeout=10)
        result = completed["result"]
        assert result["failed_chapters"] == []
        assert [item["chapter_id"] for item in result["recovered_chapters"]] == ["ch_001"]
        # The task runner decides "partial failure" from the failed list. A
        # chapter that was recovered must not make the whole task look broken.
        assert not result["failed_chapters"]
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)
