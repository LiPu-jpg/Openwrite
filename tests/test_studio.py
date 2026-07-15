import json
from http import HTTPStatus
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tools.agent.book_state import BookStage, BookStateStore
from tools.cli import _save_chapter
from tools.init_project import init_project
from tools.studio import StudioApplication, StudioError, create_server
from tools.workflow_scheduler import WorkflowScheduler


def _read_json(url: str) -> dict:
    with build_opener(ProxyHandler({})).open(url) as response:
        return json.loads(response.read())


def test_studio_workspace_exposes_novel_only_documents(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")
    _save_chapter(tmp_path, "demo", "ch_001", "第一章 雨夜", "门外有人。")

    payload = StudioApplication(tmp_path).workspace()

    assert payload["snapshot"]["title"] == "雾城来信"
    assert payload["documents"]["story"][0]["path"] == "src/outline.md"
    assert payload["documents"]["chapters"][0]["path"].endswith("ch_001.md")
    assert set(payload["documents"]) == {"story", "characters", "world", "chapters"}


def test_studio_bootstraps_first_project_without_cli(tmp_path: Path):
    app = StudioApplication(tmp_path)

    before = app.workspace()
    assert before["initialized"] is False
    assert before["snapshot"]["title"] == "新小说"

    after = app.initialize_project({"novel_id": "mist_city", "title": "雾城来信"})

    assert after["initialized"] is True
    assert after["snapshot"]["novel_id"] == "mist_city"
    assert after["snapshot"]["title"] == "雾城来信"
    assert (tmp_path / "novel_config.yaml").exists()


def test_studio_model_configuration_is_session_only_and_never_echoes_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    app = StudioApplication(tmp_path)

    payload = app.configure_model(
        {
            "provider": "openai",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": "session-test-secret",
            "api_format": "chat",
        }
    )

    assert payload["model"] == {"configured": True, "name": "deepseek-chat"}
    assert "session-test-secret" not in json.dumps(payload)
    assert "session-test-secret" not in (tmp_path / "novel_config.yaml").read_text(encoding="utf-8")


def test_studio_document_write_is_atomic_and_version_checked(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)
    document = app.read_document("src/story/background.md")

    saved = app.write_document(
        document["path"],
        "# 故事背景\n\n一座只在雨夜出现的城。\n",
        document["version"],
    )

    assert "雨夜" in saved["content"]
    with pytest.raises(StudioError) as conflict:
        app.write_document(document["path"], "旧内容", document["version"])
    assert conflict.value.status == HTTPStatus.CONFLICT


def test_studio_rejects_paths_outside_novel_documents(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)

    with pytest.raises(StudioError) as traversal:
        app.read_document("../../README.md")
    assert traversal.value.status == HTTPStatus.FORBIDDEN

    with pytest.raises(StudioError):
        app.write_document("data/workflows/book_state.yaml", "x", None)


def test_studio_focus_and_writer_reuse_openwrite_pipeline(tmp_path: Path, monkeypatch):
    init_project(tmp_path, "demo")
    monkeypatch.setenv("LLM_API_KEY", "configured-for-test")
    calls: list[dict] = []

    def fake_writer(root: Path, args: dict) -> dict:
        calls.append(args)
        path = _save_chapter(root, "demo", args["chapter_id"], "第一章", "测试正文")
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": "第一章",
            "word_count": 4,
            "draft_path": str(path),
            "truth_updates": {},
        }

    def fake_reviewer(root: Path, args: dict) -> dict:
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": False,
            "score": 90,
            "issues": 1,
            "summary": "警告 1 项",
            "issue_details": [
                {
                    "severity": "warning",
                    "category": "节奏检查",
                    "description": "开场略慢",
                    "suggestion": "提前冲突",
                    "dimension": 7,
                }
            ],
        }

    app = StudioApplication(
        tmp_path,
        writer_executor=fake_writer,
        review_executor=fake_reviewer,
    )
    updated = app.update_focus(
        {
            "goal": "完成开篇承诺",
            "must_keep": ["雨夜意象"],
            "must_avoid": ["解释真相"],
        }
    )
    assert updated["snapshot"]["creative_focus"]["goal"] == "完成开篇承诺"

    result = app.write_next_chapter({"target_words": 800, "guidance": "从敲门声开始"})
    assert calls[0]["target_words"] == 800
    assert result["result"]["chapter_id"] == "ch_001"
    assert len(result["workspace"]["documents"]["chapters"]) == 1
    written_state = BookStateStore(tmp_path, "demo").load_or_create()
    assert written_state.stage == BookStage.REVIEW_AND_REVISE
    workflow = WorkflowScheduler(tmp_path, "demo").load_workflow("ch_001")
    assert workflow is not None
    assert next(stage for stage in workflow.stages if stage.name == "writing").status == "completed"

    chapter_path = result["workspace"]["documents"]["chapters"][0]["path"]
    review = app.review_chapter({"path": chapter_path})
    assert review["result"]["score"] == 90
    review_path = tmp_path / "data" / "novels" / "demo" / "data" / "reviews" / "ch_001.json"
    assert review_path.exists()
    refreshed = app.workspace()
    assert refreshed["documents"]["chapters"][0]["review"]["score"] == 90
    assert "90 分" in refreshed["documents"]["chapters"][0]["subtitle"]
    reviewed_state = BookStateStore(tmp_path, "demo").load_or_create()
    assert reviewed_state.stage == BookStage.REVIEW_AND_REVISE
    assert reviewed_state.blocking_reason == "review_revision_requested"


def test_studio_http_serves_ui_api_and_blocks_unsigned_writes(tmp_path: Path):
    init_project(tmp_path, "demo")
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(ProxyHandler({}))
    try:
        health = _read_json(f"{base}/api/health")
        assert health == {"ok": True}

        with opener.open(f"{base}/") as response:
            html = response.read().decode("utf-8")
            assert "OpenWrite Studio" in html
            assert "default-src 'self'" in response.headers["Content-Security-Policy"]

        request = Request(
            f"{base}/api/focus",
            method="POST",
            data=json.dumps({"goal": "测试"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as denied:
            opener.open(request)
        assert denied.value.code == HTTPStatus.FORBIDDEN

        document = _read_json(
            f"{base}/api/document?path=src%2Fstory%2Fbackground.md"
        )
        assert isinstance(document["version"], str)
        save_request = Request(
            f"{base}/api/document",
            method="PUT",
            data=json.dumps(
                {
                    "path": document["path"],
                    "content": "# 故事背景\n\nHTTP 保存测试。\n",
                    "version": document["version"],
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-OpenWrite-Studio": "1",
            },
        )
        with opener.open(save_request) as response:
            saved = json.loads(response.read())
        assert "HTTP 保存测试" in saved["content"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_sync_create_import_and_context_preview(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")
    app = StudioApplication(tmp_path)
    assert app.workspace()["version"] == "5.8.0"

    character = app.create_document(
        {"kind": "character", "name": "林岑", "description": "在雨夜追查旧信的记者。"}
    )
    assert character["document"]["path"].startswith("src/characters/")
    world = app.create_document(
        {"kind": "world", "name": "雾城钟楼", "description": "每天少走十三秒。"}
    )
    assert world["document"]["path"].startswith("src/world/entities/")

    synced = app.sync_project()
    assert synced["after"]["needs_sync"] is False
    assert synced["after"]["cards"] == 1

    imported = app.import_text(
        {
            "filename": "旧稿.txt",
            "content": "第一章 雨夜\n门外有人。\n\n第二章 回声\n门后没有人。",
            "arc_id": "arc_001",
        }
    )
    assert [item["chapter_id"] for item in imported["imported"]] == ["ch_001", "ch_002"]

    preview = app.context_preview("ch_001")
    assert preview["chapter_id"] == "ch_001"
    assert "作者意图" in preview["markdown"]

    with pytest.raises(StudioError) as conflict:
        app.create_document({"kind": "character", "name": "林岑"})
    assert conflict.value.status == HTTPStatus.CONFLICT
    operations = app.workspace()["operations"]
    assert operations["sync"]["needs_sync"] is False
    assert any(item["name"] == "项目配置" and item["ok"] for item in operations["diagnostics"])


def test_studio_continuity_and_foreshadowing_management(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)

    created = app.manage_foreshadowing(
        {
            "action": "create",
            "node_id": "hook_clock_001",
            "content": "钟楼每天少走十三秒",
            "weight": 8,
            "created_at": "ch_001",
            "target_chapter": "ch_010",
        }
    )

    nodes = created["continuity"]["foreshadowing"]["nodes"]
    assert nodes[0]["id"] == "hook_clock_001"
    assert created["workspace"]["snapshot"]["pending_foreshadowing"] == 1
    assert created["continuity"]["foreshadowing_validation"]["valid"] is True


def test_studio_chat_and_source_extraction_use_injected_real_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    monkeypatch.setenv("LLM_API_KEY", "configured-for-test")
    chat_calls: list[tuple[str, str]] = []
    source_calls: list[dict] = []

    def fake_chat(root: Path, novel_id: str, agent: str, message: str) -> dict:
        chat_calls.append((agent, message))
        return {"content": f"{agent} 已收到：{message}"}

    def fake_source(root: Path, payload: dict) -> dict:
        source_calls.append(payload)
        source_root = root / "data" / "novels" / "demo" / "data" / "sources" / payload["source_id"]
        (source_root / "style").mkdir(parents=True)
        (source_root / "source.md").write_text("# 来源", encoding="utf-8")
        return {"ok": True, "source_id": payload["source_id"]}

    app = StudioApplication(
        tmp_path,
        chat_executor=fake_chat,
        source_executor=fake_source,
    )
    chat = app.chat_turn({"agent": "goethe", "message": "整理第一篇"})
    assert chat["content"] == "goethe 已收到：整理第一篇"
    assert chat_calls == [("goethe", "整理第一篇")]

    extracted = app.source_action(
        {
            "action": "extract",
            "source_id": "reference_01",
            "focus": "style",
            "content": "雨落在旧钟楼上。",
        }
    )
    assert extracted["result"]["ok"] is True
    assert source_calls[0]["focus"] == "style"
    packs = extracted["workspace"]["operations"]["source_packs"]
    assert packs[0]["source_id"] == "reference_01"


def test_studio_http_exposes_context_and_import_routes(tmp_path: Path):
    init_project(tmp_path, "demo")
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(ProxyHandler({}))
    try:
        context = _read_json(f"{base}/api/context?chapter=ch_001")
        assert context["chapter_id"] == "ch_001"

        request = Request(
            f"{base}/api/import",
            method="POST",
            data=json.dumps(
                {
                    "filename": "draft.md",
                    "content": "# 第一章 雨夜\n\n门外有人。",
                    "arc_id": "arc_001",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(request) as response:
            payload = json.loads(response.read())
        assert payload["imported"][0]["chapter_id"] == "ch_001"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_http_can_initialize_an_empty_workspace(tmp_path: Path):
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(ProxyHandler({}))
    try:
        assert _read_json(f"{base}/api/workspace")["initialized"] is False
        request = Request(
            f"{base}/api/project/init",
            method="POST",
            data=json.dumps({"novel_id": "web_novel", "title": "前端新书"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(request) as response:
            payload = json.loads(response.read())
        assert payload["initialized"] is True
        assert payload["snapshot"]["title"] == "前端新书"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
