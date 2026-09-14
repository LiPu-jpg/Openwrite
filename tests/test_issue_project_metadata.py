import pytest
import yaml
import json
from threading import Thread
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import HTTPError

from tools.init_project import init_project
from tools.project_registry import ProjectRegistry
from tools.studio import StudioApplication, StudioError, create_server
from tools.export_preflight import ExportPreflightService


def test_init_metadata_is_yaml_safe_and_repeated_init_preserves_author(tmp_path):
    init_project(tmp_path, "demo", '书名: "雾城"', author="笔名: 甲", language="en")
    init_project(tmp_path, "demo", "other", author="replacement")
    config = yaml.safe_load((tmp_path / "novel_config.yaml").read_text())
    assert config["title"] == '书名: "雾城"'
    assert config["author"] == "笔名: 甲"
    assert config["language"] == "en"


def test_existing_project_metadata_can_be_completed_without_bypassing_export_gates(tmp_path):
    root = tmp_path / "novel"
    init_project(root, "demo", "雾城")
    config_path = root / "novel_config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config.pop("author")  # Simulate an older project.
    config["custom_setting"] = {"preserve": True}
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
    app = StudioApplication(root, project_registry=ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True))
    before = app._project_payload()
    result = app.update_project_metadata({"author": "测试作者", "expected_revision": before["metadata_revision"]})
    assert result["metadata"]["author"] == "测试作者"
    saved = yaml.safe_load(config_path.read_text())
    assert saved["custom_setting"] == {"preserve": True}
    assert saved["novel_id"] == "demo"
    report = ExportPreflightService(root, "demo").inspect(format_name="md", purpose="delivery")
    assert "METADATA_AUTHOR_MISSING" not in {item["code"] for item in report["blockers"]}
    with pytest.raises(StudioError):
        app.update_project_metadata({"author": "stale", "expected_revision": before["metadata_revision"]})
    for payload in ({"project_path": "/elsewhere"}, {"novel_id": "other"}, {"author": ["invalid"]}, {"language": "../bad"}):
        with pytest.raises(StudioError):
            app.update_project_metadata({**payload, "expected_revision": result["metadata_revision"]})
    assert config_path.read_text() == yaml.safe_dump(saved, allow_unicode=True, sort_keys=False)


def test_empty_author_remains_a_delivery_blocker(tmp_path):
    init_project(tmp_path, "demo", "雾城")
    report = ExportPreflightService(tmp_path, "demo").inspect(format_name="md", purpose="delivery")
    assert "METADATA_AUTHOR_MISSING" in {item["code"] for item in report["blockers"]}


def test_metadata_http_requires_auth_and_a_current_revision(tmp_path):
    root = tmp_path / "novel"
    init_project(root, "demo", "雾城")
    token = "test-instance-" + "x" * 32
    server = create_server(root, port=0, instance_token=token,
        project_registry=ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    url = f"http://127.0.0.1:{server.server_port}/api/project/metadata"
    try:
        payload = {"author": "HTTP 作者", "expected_revision": server.app._project_payload()["metadata_revision"]}
        def write(headers):
            return opener.open(Request(url, method="POST", data=json.dumps(payload).encode(), headers=headers), timeout=10)
        with pytest.raises(HTTPError) as unauthorized:
            write({"Content-Type": "application/json", "X-OpenWrite-Studio": "1"})
        assert unauthorized.value.code == 401
        headers = {"Content-Type": "application/json", "X-OpenWrite-Studio": "1", "Authorization": "Bearer " + token}
        with write(headers) as response:
            assert json.load(response)["metadata"]["author"] == "HTTP 作者"
        with pytest.raises(HTTPError) as stale:
            write(headers)
        assert stale.value.code == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
