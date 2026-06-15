from __future__ import annotations

from pathlib import Path


def test_dockerfile_contains_adapter_entrypoint_and_workspace_contract() -> None:
    text = Path("Dockerfile").read_text(encoding="utf-8")

    assert "WORKDIR /workspace" in text
    assert "pip install --no-cache-dir -e /opt/openwrite" in text
    assert "smart-story-openwrite-adapter" in text
    assert "OPENWRITE_RESOURCE_ROOT=/usr/local/share/openwrite" in text
