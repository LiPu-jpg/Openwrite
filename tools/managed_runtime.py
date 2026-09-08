"""Private stdio handshake for a dsh-owned, loopback-only Core process."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from tools.project_registry import ProjectRegistry
from tools.studio import create_server
from tools.studio_http import health_payload
from tools.studio_preferences import StudioModelSettingsStore
from tools.model_profiles import ModelProfileStore


def create_managed_server(state: Path, token: str):
    """All machine state belongs to this dsh home, including model credentials."""
    return create_server(
        state, host="127.0.0.1", port=0,
        project_registry=ProjectRegistry(state / "projects.json"),
        model_settings_store=StudioModelSettingsStore(state / "config"),
        model_profile_store=ModelProfileStore(state / "config"),
        reference_library_root=state / "reference-library",
        instance_token=token,
    )


def main() -> int:
    # The credential never appears in argv, environment, logs, or ready output.
    request = json.loads(sys.stdin.readline())
    state = Path(request["state_dir"]).resolve()
    state.mkdir(parents=True, exist_ok=True)
    server = create_managed_server(state, request["token"])

    def parent_channel() -> None:
        # EOF also stops an orphan when the parent crashes (including Windows).
        sys.stdin.read()
        server.shutdown()

    threading.Thread(target=parent_channel, daemon=True).start()
    print(json.dumps({**health_payload(), "port": server.server_port}), flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.workspace_manager.shutdown(wait=True)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
