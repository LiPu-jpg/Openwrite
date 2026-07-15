from http import HTTPStatus
from pathlib import Path

import pytest

import tools.chapter_pipeline as chapter_pipeline_module
from tools.agent.tool_layers import build_goethe_tool_layers
from tools.agent.tool_runtime import build_tool_executors
from tools.init_project import init_project
from tools.novel_service import NovelApplicationService, NovelServiceError
from tools.source_pack import SourcePackService
from tools.studio import StudioApplication


def test_agent_and_studio_project_the_same_canonical_packet(tmp_path: Path):
    init_project(tmp_path, "demo", "统一上下文")
    service = NovelApplicationService(tmp_path)
    studio = StudioApplication(tmp_path)
    tools = build_tool_executors(tmp_path)

    canonical = service.context_preview("ch_001")
    studio_preview = studio.context_preview("ch_001")
    agent_preview = tools["get_context"]({"chapter_id": "ch_001"})

    assert agent_preview["context_packet"] == canonical["packet"]
    assert studio_preview["markdown"] == canonical["markdown"]
    assert agent_preview["target_words"] == studio_preview["target_words"]


def test_studio_and_agent_write_send_identical_normalized_payload(
    tmp_path: Path, monkeypatch
):
    init_project(tmp_path, "demo", "统一写章")
    monkeypatch.setenv("LLM_API_KEY", "test-only")
    calls: list[dict] = []

    def fake_pipeline(root: Path, args: dict) -> dict:
        calls.append(args)
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": "第一章",
            "word_count": 800,
            "draft_path": str(root / "ch_001.md"),
            "truth_updates": {},
        }

    monkeypatch.setattr(
        chapter_pipeline_module,
        "execute_write_chapter",
        fake_pipeline,
    )
    studio = StudioApplication(tmp_path)
    tools = build_tool_executors(tmp_path)
    studio.write_next_chapter(
        {"target_words": 800, "guidance": "雨夜开场", "temperature": 0.6}
    )
    tools["write_chapter"](
        {
            "chapter_id": "next",
            "target_words": 800,
            "guidance": "雨夜开场",
            "temperature": 0.6,
        }
    )

    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert calls[0]["chapter_id"] == "ch_001"
    assert calls[0]["context_packet"]["chapter_id"] == "ch_001"


def test_source_review_is_identical_in_service_studio_and_goethe(tmp_path: Path):
    init_project(tmp_path, "demo", "统一来源")
    source = SourcePackService(tmp_path, "demo")
    root = source.source_root("reference")
    (root / "style").mkdir(parents=True)
    (root / "source.md").write_text("# 来源\n\n只取可复用技法。", encoding="utf-8")

    expected = NovelApplicationService(tmp_path).review_source("reference")[
        "review_report"
    ]
    studio = StudioApplication(tmp_path).source_action(
        {"action": "review", "source_id": "reference"}
    )["result"]
    goethe_layers = build_goethe_tool_layers(tmp_path, "demo")
    goethe = goethe_layers["action_tool_executors"]["review_source_pack"](
        {"source_id": "reference"}
    )

    assert studio["review_report"] == expected
    assert goethe["review_report"] == expected


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("INVALID_INPUT", HTTPStatus.BAD_REQUEST),
        ("CONFLICT", HTTPStatus.CONFLICT),
        ("PROJECT_BUSY", HTTPStatus.CONFLICT),
        ("NOT_FOUND", HTTPStatus.NOT_FOUND),
        ("INVALID_PROJECT", HTTPStatus.PRECONDITION_FAILED),
        ("OPERATION_FAILED", HTTPStatus.BAD_GATEWAY),
    ],
)
def test_service_error_codes_have_one_studio_http_contract(code: str, status: int):
    translated = StudioApplication._translate_service_error(
        NovelServiceError("failure", code=code)
    )

    assert translated.status == status
