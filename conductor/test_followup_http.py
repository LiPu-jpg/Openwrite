"""Exercise follow-up contracts through the candidate Core's real HTTP transport."""

import hashlib
import json
import subprocess
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from tools.chapter_lifecycle import archive_chapter_artifacts
from tools.chapter_run_v2 import ChapterRunV2Store
from tools.init_project import init_project
from tools.project_registry import ProjectRegistry
from tools.studio import create_server


@pytest.fixture
def studio(tmp_path):
    init_project(tmp_path, "demo")
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)

    def writer(*_args):
        pytest.fail("HTTP dry-run must never invoke a writer")

    revision_calls = []

    def revision(_root, payload):
        revision_calls.append(payload)
        return {
            "replacement_text": "修订后的正文",
            "rationale": "fixture",
            "risk_flags": [],
        }

    server = create_server(
        tmp_path,
        port=0,
        project_registry=registry,
        writer_executor=writer,
        revision_executor=revision,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))

    def request(path, payload=None):
        req = Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"X-OpenWrite-Studio": "1", "Content-Type": "application/json"},
        )
        with opener.open(req, timeout=10) as response:
            return response.headers, json.loads(response.read())

    request.revision_calls = revision_calls

    try:
        yield tmp_path, request
    finally:
        server.shutdown()
        server.server_close()
        server.app._task_runner.shutdown(wait=True)
        thread.join(timeout=3)


def test_http_dry_run_keeps_tasks_empty_and_reports_no_public_mutation(studio):
    _, request = studio
    _, before = request("/api/tasks")
    headers, result = request(
        "/api/write",
        {
            "dry_run": True,
            "chapter_id": "ch_001",
            "target_words": 2000,
            "guidance": "雨停之后再开门。",
        },
    )
    assert headers["X-OpenWrite-Mutated"] == "0"
    assert result["dry_run"] and result["model_call_count"] == 0
    assert "task_id" not in result
    assert result["context"]["agent_payload"]["target_words"] == 2000
    assert "雨停之后再开门。" in str(result["context"]["writer_messages"])
    _, after = request("/api/tasks")
    assert before["data"]["tasks"] == after["data"]["tasks"] == []


def test_http_archived_history_returns_original_artifacts(studio):
    root, request = studio
    store = ChapterRunV2Store(root, "demo")
    run = store.create("ch_001")
    store.start_stage(run, "context")
    artifact = store.write_artifact(run, "context", {"original": "原始上下文"})
    store.complete_stage(run, "context", artifact=artifact)
    archive_chapter_artifacts(root / "data/novels/demo", "ch_001", "http_delete_test")
    _, current = request("/api/chapter-runs-v2", {"action": "list"})
    assert current["runs"] == []
    _, history = request(
        "/api/chapter-runs-v2", {"action": "list", "include_archived": True}
    )
    assert history["count"] == 1
    old = history["runs"][0]
    assert old["run_id"] == run.run_id and old["archived"]
    assert old["next_stage"] is None
    assert json.loads(Path(old["stages"]["context"]["artifact"]).read_text()) == {
        "original": "原始上下文"
    }


@pytest.mark.parametrize("client", ["panel", "standalone"])
@pytest.mark.parametrize(
    "raw,quote",
    [
        ("# 门\n😀前选中\n正文\n尾部", "选中\n正文"),
        ("# 门\r\n前\r\n选中\r\n正文\r\n尾部", "选中\n正文"),
        ("选中正文\r\n😀\n选中正文\r尾部", "选中正文"),
        ("# 门\r\n😀\n选中正文", "选中正文"),
    ],
)
def test_browser_selection_reaches_real_revision_http_without_offset_drift(
    studio, client, raw, quote
):
    import tools.studio_application as core

    root, request = studio
    path = root / "data/novels/demo/data/manuscript/arc_001/ch_001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw.encode("utf-8"))
    revision = "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
    plugin = Path(__file__).resolve().parents[1]
    module = (
        plugin / "packages/studio-panel/src/client/manuscript-selection.ts"
        if client == "panel"
        else Path(core.__file__).parent / "studio_assets/js/selection-coordinates.js"
    )
    script = """
import {readFileSync} from 'node:fs'; import {pathToFileURL} from 'node:url';
const data = JSON.parse(readFileSync(0,'utf8'));
const helper = await import(pathToFileURL(data.module).href);
const view = data.raw.replace(/\\r\\n?/g,'\\n');
const start = view.lastIndexOf(data.quote), end = start + data.quote.length;
let body;
if(data.client === 'panel') {
 const selected = helper.manuscriptSelectionFromRange(view,start,end);
 const result = helper.selectionPolishRequest({kind:'expand',chapterId:'ch_001',selection:selected,
  documentContent:data.raw, documentRevision:data.revision,reviewRevision:'',reviewFresh:false,issueIds:[]});
 if(!result.ok) throw Error(result.reason); body=result.body;
} else {
 const selected=helper.mapEditorRange(data.raw,view,start,end);
 if(!selected) throw Error('No exact mapping');
 body={chapter_id:'ch_001',start:selected.start,end:selected.end,original_text:selected.text,
  expected_document_revision:data.revision,action:'expand'};
}
process.stdout.write(JSON.stringify(body));
"""
    completed = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        input=json.dumps(
            {
                "module": str(module),
                "client": client,
                "raw": raw,
                "quote": quote,
                "revision": revision,
            }
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert raw[payload["start"] : payload["end"]] == payload["original_text"]
    _, result = request("/api/revisions/selection", payload)
    proposal = result["data"]
    assert proposal["selection"]["original_text"] == payload["original_text"]
    assert proposal["source_revision"] == revision
    assert len(request.revision_calls) == 1
    assert path.read_bytes() == raw.encode("utf-8")
    # A concurrent edit outside the selected quote must also reject stale input.
    path.write_bytes((raw + "\n外部变更").encode("utf-8"))
    with pytest.raises(HTTPError) as changed:
        request("/api/revisions/selection", payload)
    assert changed.value.code == 409
    assert json.loads(changed.value.read())["code"] == "DOCUMENT_CONFLICT"
    assert len(request.revision_calls) == 1
