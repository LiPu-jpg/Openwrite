import json
import secrets
import threading
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

urlopen = build_opener(ProxyHandler({})).open

import pytest

from tools.project_registry import ProjectRegistry
from tools.studio import create_server
from tools.managed_runtime import create_managed_server


def test_managed_server_authenticates_reads_and_writes_before_workspace_resolution(tmp_path):
    token = secrets.token_hex(32)
    server = create_managed_server(tmp_path, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for path, method in [("/api/health", "GET"), ("/api/workspace", "GET"), ("/api/project/init", "POST")]:
            with pytest.raises(HTTPError) as failure:
                urlopen(Request(base + path, method=method, headers={"X-OpenWrite-Studio": "1"}), timeout=5)
            assert failure.value.code == 401
        with urlopen(Request(base + "/api/health", headers={"Authorization": f"Bearer {token}"}), timeout=5) as response:
            health = json.load(response)
        assert health == {"ok": True, "core_version": "5.8.1", "contract_version": 1}
        assert token not in json.dumps(health)
        assert not (tmp_path / "novel_config.yaml").exists()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.workspace_manager.shutdown(wait=True)
        server.server_close()


def test_managed_server_refuses_non_loopback_or_weak_token(tmp_path):
    for host, token in [("0.0.0.0", "x" * 64), ("127.0.0.1", "short")]:
        with pytest.raises(ValueError):
            create_server(tmp_path, host=host, instance_token=token)


def test_managed_preferences_ignore_default_machine_store(tmp_path, monkeypatch):
    from tools.studio_preferences import StudioModelSettingsStore
    legacy = StudioModelSettingsStore(tmp_path / "legacy")
    legacy.save_credential("legacy-secret-must-not-be-inherited")
    monkeypatch.setenv("OPENWRITE_STUDIO_CONFIG_DIR", str(legacy.directory))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    server = create_managed_server(tmp_path / "isolated", secrets.token_hex(32))
    try:
        import os
        assert not os.environ.get("LLM_API_KEY")
        assert server.app._model_settings_store.directory == tmp_path / "isolated/config"
        assert server.app._model_profile_store.directory == tmp_path / "isolated/config"
        assert legacy.load_credential() == "legacy-secret-must-not-be-inherited"
    finally:
        server.workspace_manager.shutdown(wait=True)
        server.server_close()
