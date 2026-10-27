"""Public HTTP regression for #109 B-13; no fuzzy or line-start matching."""

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tools.init_project import init_project
from tools.project_registry import ProjectRegistry
from tools.studio import create_server


@pytest.mark.parametrize("newline", ["\n", "\r\n", "mixed"])
@pytest.mark.parametrize("selector", ["old_text", "range"])
def test_inline_quote_anchor_preview_apply_and_undo_preserve_bytes(tmp_path, newline, selector):
    init_project(tmp_path, "demo")
    path = tmp_path / "data/novels/demo/src/world/rules.md"
    eol = "\n" if newline == "mixed" else newline
    original = eol.join(["# 规则", "行中 > 唯一原文", "第二行", "## 下一节", "保留正文", ""])
    if newline == "mixed":
        original = original.replace("# 规则\n", "# 规则\r\n").replace("第二行\n", "第二行\r\n")
    path.write_bytes(original.encode())
    registry = ProjectRegistry(tmp_path / "isolated-registry.json", allow_ephemeral=True)
    server = create_server(tmp_path, port=0, project_registry=registry)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    opener = build_opener(ProxyHandler({}))
    url = f"http://127.0.0.1:{server.server_port}/api/document/change-plan"

    def post(payload):
        request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers={
            "Content-Type": "application/json", "X-OpenWrite-Studio": "1",
        })
        with opener.open(request, timeout=5) as response:
            return json.loads(response.read())["data"]

    replacement = "替换原文"
    edit = {"old_text": "> 唯一原文", "new_text": replacement}
    old = "> 唯一原文"
    if selector == "range":
        old = original[original.index(old):original.index("## 下一节")]
        replacement += eol
        edit = {"start_text": "> 唯一原文", "end_text": "## 下一节",
                "end_inclusive": False, "new_text": replacement}
    try:
        preview = post({"action": "preview", "path": "src/world/rules.md", "edits": [edit]})
        assert path.read_bytes() == original.encode()
        assert preview["applied"] is False and preview["would_change"] is True
        applied = post({"action": "apply", "confirm": True, "preview_token": preview["preview_token"]})
        assert path.read_bytes() == original.replace(old, replacement).encode()
        post({"action": "undo", "confirm": True, "preview_token": applied["undo_preview_token"]})
        assert path.read_bytes() == original.encode()
        with pytest.raises(HTTPError) as mismatch:
            post({"action": "preview", "path": "src/world/rules.md", "edits": [
                {"old_text": ">\u00a0唯一原文", "new_text": "不得写入"},
            ]})
        error = json.loads(mismatch.value.read())
        assert mismatch.value.code == 400
        assert error["code"] == "OLD_TEXT_NOT_FOUND"
        assert error["details"]["suggested_old_text"] == "> 唯一原文"
        assert error["details"]["mismatch_kind"] == "whitespace"
        assert error["details"]["similarity_basis"] == "whitespace_collapsed"
        assert path.read_bytes() == original.encode()
    finally:
        server.shutdown()
        server.workspace_manager.shutdown(wait=True)
        server.server_close()
        worker.join(timeout=2)
