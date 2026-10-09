"""Private stdio handshake for a dsh-owned, loopback-only Core process."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from tools.project_registry import ProjectRegistry
from tools.studio import create_server
from tools.studio_http import health_payload
from tools.studio_preferences import StudioModelSettingsStore
from tools.model_profiles import ModelProfileStore

# A stuck request thread (e.g. a wedged embedding probe) must not keep this
# process alive after serve_forever returns; the bridge can only restart a
# process that actually exits.
FINALIZE_TIMEOUT_SECONDS = 10


def _prewarm_embedding_dependencies() -> None:
    """Import embedding heavyweights off the request path.

    ``tools.embedding_runtime`` is imported lazily from request handlers. On
    Windows the first ``import numpy`` inside such a request thread can stall
    in the module loader forever, hanging the handler and eventually wedging
    the whole backend (alive but no longer serving). numpy is needed by every
    embedding path, so load it on the startup thread; fastembed is only used
    for on-device embeddings and costs seconds, so it loads best-effort in a
    background thread — both keep the function-level lazy imports as fallback.
    """
    try:
        import numpy  # noqa: F401
    except ImportError:
        pass

    def _load_fastembed() -> None:
        try:
            import fastembed  # noqa: F401
        except ImportError:
            pass

    threading.Thread(target=_load_fastembed, daemon=True, name="fastembed-prewarm").start()


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
    _prewarm_embedding_dependencies()
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
        # Finalize off the main thread with a hard deadline: workspace
        # shutdown waits for in-flight request threads, and one that never
        # ends would leave this process alive but refusing connections — a
        # zombie the host cannot restart. Better to die loudly.
        finalized = threading.Event()

        def _finalize() -> None:
            try:
                server.workspace_manager.shutdown(wait=True)
                server.server_close()
            finally:
                finalized.set()

        threading.Thread(target=_finalize, daemon=True, name="runtime-finalize").start()
        if not finalized.wait(FINALIZE_TIMEOUT_SECONDS):
            sys.stderr.write(
                f"写作后端收尾超时（{FINALIZE_TIMEOUT_SECONDS} 秒），强制退出\n"
            )
            sys.stderr.flush()
            os._exit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
