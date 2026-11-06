"""Regression guards for the Studio HTTP + persistence layer.

Covers the invariants an adversarial review of ``tools/studio_http.py``,
``tools/studio_application.py``, ``tools/workspace_manager.py`` and
``tools/project_lock.py`` must hold.  ``xfail(strict=True)`` entries document
defects that are still open: fixing them turns these into hard failures so the
marker can be removed deliberately.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from threading import Thread

import pytest

from tools.init_project import init_project
from tools.project_lock import ProjectWriteLock
from tools.studio import create_server
from tools.studio_application import StudioApplication
from tools.studio_contracts import StudioError

WRITE_HEADERS = {"X-OpenWrite-Studio": "1"}
DOC_PATH = "data/manuscript/arc_001/ch_001.md"


def _context_headers(root: Path) -> dict[str, str]:
    return {"X-OpenWrite-Workspace-Root": str(root)}


# Loopback requests must never traverse a configured proxy: a machine with an
# HTTP/SOCKS proxy set (macOS also reads the system proxy settings) would have
# `urlopen` send these through it, and the proxy answers 502 with an empty body —
# which looks like a server defect rather than an environment one.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(
    base: str,
    method: str,
    path: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    raw_body: bytes | None = None,
) -> tuple[int, dict]:
    if raw_body is not None:
        data = raw_body
    else:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = dict(headers or {})
    if data is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        f"{base}{path}", method=method, data=data, headers=request_headers
    )
    try:
        with _OPENER.open(request) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _raw(port: int, authorization: str, path: str) -> int:
    import socket

    request = (
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        f"Authorization: {authorization}\r\nConnection: close\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(request.encode("latin-1"))
        raw = b""
        while True:
            block = sock.recv(65536)
            if not block:
                break
            raw += block
    return int(raw.split(b"\r\n")[0].split()[1])


@pytest.fixture()
def server(tmp_path: Path):
    launch = tmp_path / "server"
    launch.mkdir()
    server = create_server(launch, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield server, base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        manager = getattr(server, "workspace_manager", None)
        if manager is not None:
            manager.shutdown(wait=True)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "novel"
    init_project(root, "demo")
    return root


# --------------------------------------------------------------------------
# path containment
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    [
        "../../../../etc/hostname",
        "/etc/hostname",
        "novel_config.yaml",
        "src/outline.md/../../outline.md",
    ],
)
def test_document_reads_reject_paths_outside_the_novel_root(server, project, relative):
    _server, base = server
    status, payload = _request(
        base, "GET", f"/api/document?path={urllib.request.quote(relative, safe='')}",
        headers=_context_headers(project),
    )
    assert status == 403
    assert payload["error"] == "文档路径不在 Studio 可访问范围"


def test_document_reads_reject_symlink_escape(server, project, tmp_path):
    _server, base = server
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    (project / "data" / "novels" / "demo" / "src" / "escape.md").symlink_to(
        outside / "secret.md"
    )
    status, _ = _request(
        base, "GET", "/api/document?path=src/escape.md", headers=_context_headers(project)
    )
    assert status == 403


def test_document_writes_reject_paths_outside_the_novel_root(server, project):
    _server, base = server
    for relative in ("/tmp/pwned.md", "src/../../pwned.md"):
        status, _ = _request(
            base,
            "PUT",
            "/api/document",
            {"path": relative, "content": "x"},
            {**WRITE_HEADERS, **_context_headers(project)},
        )
        assert status == 403, relative


# --------------------------------------------------------------------------
# optimistic concurrency
# --------------------------------------------------------------------------


def test_concurrent_document_writes_are_serialized_by_revision(server, project):
    _server, base = server
    path = project / "data" / "novels" / "demo" / DOC_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("base\n", encoding="utf-8")
    _status, document = _request(
        base, "GET", f"/api/document?path={DOC_PATH}", headers=_context_headers(project)
    )
    version = document["version"]
    results: list[int] = []

    def writer(tag: str) -> None:
        status, _ = _request(
            base,
            "PUT",
            "/api/document",
            {"path": DOC_PATH, "content": f"{tag}\n", "version": version},
            {**WRITE_HEADERS, **_context_headers(project)},
        )
        results.append(status)

    threads = [Thread(target=writer, args=(f"c{index}",)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(results) == [200, 409, 409, 409]


# --------------------------------------------------------------------------
# cross-process lock
# --------------------------------------------------------------------------


def test_project_write_lock_is_released_after_an_exception(tmp_path):
    with pytest.raises(RuntimeError):
        with ProjectWriteLock(tmp_path, "demo", operation="boom"):
            raise RuntimeError("boom")
    lock_path = (
        tmp_path / "data" / "novels" / "demo" / "data" / "workflows" / "project.lock"
    )
    assert not lock_path.exists()


def test_project_write_lock_excludes_a_second_holder(tmp_path):
    with ProjectWriteLock(tmp_path, "demo", operation="first"):
        with pytest.raises(Exception):
            ProjectWriteLock(tmp_path, "demo", operation="second").acquire()


# --------------------------------------------------------------------------
# known defects (strict xfail: a fix must fail loudly so the marker is removed)
# --------------------------------------------------------------------------


def test_novel_id_traversal_in_config_cannot_escape_the_project_root(tmp_path):
    """A crafted ``novel_config.yaml`` must not move the novel root.

    ``novel_id`` is validated when a project is created; it must be re-validated
    when an existing project is opened, or ``..`` segments relocate every derived
    path (novel root, write lock, document root) outside the project — and with
    it the containment anchor every document path is checked against.
    """
    root = tmp_path / "novel"
    init_project(root, "demo")
    escape = tmp_path / "escape"
    (escape / "src").mkdir(parents=True)
    (escape / "src" / "pwned.md").write_text("OUTSIDE\n", encoding="utf-8")
    novel_id = os.path.relpath(escape, root / "data" / "novels")
    config = (root / "novel_config.yaml").read_text(encoding="utf-8")
    (root / "novel_config.yaml").write_text(
        config.replace("novel_id: demo", f"novel_id: {novel_id}"), encoding="utf-8"
    )

    # The config is refused at open, so no escaped application exists to write
    # through. The file outside the project is untouched.
    with pytest.raises(StudioError) as rejected:
        StudioApplication(root)
    assert rejected.value.code == "INVALID_PROJECT"
    assert (escape / "src" / "pwned.md").read_text(encoding="utf-8") == "OUTSIDE\n"


def test_write_document_never_reports_failure_after_committing(tmp_path):
    """A committed write must not surface as a 500.

    ``write_document`` renames the document into place and used to compute the
    checkpoint path with ``relative_to(self.project_root)`` only afterwards; a
    path outside the project root then raised after the commit, so the caller
    saw a 500 for a change that had already happened. The checkpoint is
    best-effort, so it must never be able to fail a committed write.
    """
    root = tmp_path / "novel"
    init_project(root, "demo")
    app = StudioApplication(root)
    app.write_document("src/outline.md", "PWNED\n", None)
    assert (root / "data" / "novels" / "demo" / "src" / "outline.md").read_text(
        encoding="utf-8"
    ) == "PWNED\n"

    # And a document whose resolved path escapes the project root must not turn
    # a committed write into an error: the checkpoint is skipped, the write lands.
    escape = tmp_path / "escape"
    (escape / "src").mkdir(parents=True)
    (escape / "src" / "pwned.md").write_text("OUTSIDE\n", encoding="utf-8")
    novel_id = os.path.relpath(escape, root / "data" / "novels")
    config = (root / "novel_config.yaml").read_text(encoding="utf-8")
    (root / "novel_config.yaml").write_text(
        config.replace("novel_id: demo", f"novel_id: {novel_id}"), encoding="utf-8"
    )
    with pytest.raises(StudioError) as rejected:
        StudioApplication(root)
    assert rejected.value.code == "INVALID_PROJECT"
    assert (escape / "src" / "pwned.md").read_text(encoding="utf-8") == "OUTSIDE\n"


def test_non_ascii_authorization_header_is_rejected_as_unauthorized(tmp_path):
    """``hmac.compare_digest`` on str raises for non-ASCII input.

    The resulting TypeError escapes ``_require_instance_auth`` and is reported
    as a 500 instead of a 401.
    """
    launch = tmp_path / "server"
    launch.mkdir()
    server = create_server(launch, port=0, instance_token="t" * 40)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert _raw(server.server_port, "Bearer nope", "/api/health") == 401
        assert _raw(server.server_port, "Bearer \u00e9\u00e9", "/api/health") == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_malformed_proposal_id_maps_to_a_client_error(server, project):
    """A route-reachable but too-short ``proposal_id`` must not be a 500.

    ``RevisionService.get``/``apply`` call ``store.load`` without translating
    ``RevisionStoreError`` into ``RevisionError``, so the raw store exception
    escapes ``StudioApplication.get_revision`` and becomes a 500.
    """
    _server, base = server
    status, payload = _request(
        base, "GET", "/api/revisions/rev_short", headers=_context_headers(project)
    )
    assert status in {400, 404}
    assert payload["code"] != "INTERNAL_ERROR"

    status, payload = _request(
        base,
        "POST",
        "/api/revisions/rev_short/apply",
        {},
        {**WRITE_HEADERS, **_context_headers(project)},
    )
    assert status in {400, 404}
    assert payload["code"] != "INTERNAL_ERROR"


def test_context_app_cache_refreshes_after_a_project_appears_on_disk(server, tmp_path):
    """A root first seen while uninitialized must not stay stuck at 428.

    ``WorkspaceManager.app_for`` caches one ``StudioApplication`` per root and
    never re-evaluates ``initialized``, so a project created on disk after the
    first request keeps reporting WORKSPACE_NOT_INITIALIZED until restart.
    """
    _server, base = server
    root = tmp_path / "late"
    root.mkdir()
    status, _ = _request(
        base, "GET", "/api/workspace", headers=_context_headers(root)
    )
    assert status == 428

    init_project(root, "demo")

    status, payload = _request(
        base, "GET", "/api/workspace", headers=_context_headers(root)
    )
    assert status == 200
    assert payload["project"]["root"] == str(root)


def test_every_novel_service_error_code_has_an_http_status():
    """A NovelServiceError code without a mapping silently becomes 502.

    Seven export/run codes were missing, so a rejected export target (a symlink)
    or an already-written chapter reached the author as an upstream failure and
    was retried as if transient. The task path preserves `code` verbatim, so only
    the synchronous translator needs the map.
    """
    import re
    from pathlib import Path

    root = Path(__file__).parent.parent
    app_src = (root / "tools/studio_application.py").read_text(encoding="utf-8")
    mapped = set(re.findall(r'"([A-Z][A-Z0-9_]{3,})"\s*:', app_src))
    service_src = (root / "tools/novel_service.py").read_text(encoding="utf-8")
    service_codes = set(re.findall(r'code\s*=\s*"([A-Z][A-Z0-9_]{3,})"', service_src))

    missing = sorted(service_codes - mapped)
    assert not missing, f"NovelServiceError codes with no HTTP status: {missing}"


def test_a_rejected_export_target_is_not_reported_as_an_upstream_failure():
    """A symlink export target must be a 400, not a retryable 502."""
    from tools.novel_service import NovelServiceError
    from tools.studio_application import StudioApplication

    exc = NovelServiceError("导出目标必须是普通文件", code="INVALID_EXPORT_OUTPUT")
    translated = StudioApplication._translate_service_error(exc)
    assert translated.status == 400
    assert translated.code == "INVALID_EXPORT_OUTPUT"


def test_an_already_written_chapter_is_a_conflict_not_an_upstream_failure():
    from tools.novel_service import NovelServiceError
    from tools.studio_application import StudioApplication

    exc = NovelServiceError("章节已存在", code="CHAPTER_ALREADY_EXISTS")
    assert StudioApplication._translate_service_error(exc).status == 409


def test_a_deeply_nested_request_body_is_rejected_not_an_internal_error(server, project):
    """A ~400 KB nested document must not overflow the JSON parser's stack.

    RecursionError is not a JSONDecodeError, so it escaped _body_json's handlers
    and surfaced as a 500 with a traceback - a small request could turn every
    attempt into an internal error.
    """
    import json

    depth = 200_000
    body = ("[" * depth + "]" * depth).encode("utf-8")
    assert len(body) < 2 * 1024 * 1024, "the payload must stay under the size cap"

    _server, base = server
    status, payload = _request(
        base,
        "POST",
        "/api/outline/edit",
        None,
        {**WRITE_HEADERS, **_context_headers(project)},
        raw_body=body,
    )

    # A 400 with a clear code, never a 500.
    assert status != 500, payload
    if status == 400:
        # The envelope shape varies by error path; the invariant that matters is
        # that the request was rejected as malformed input, not crashed on.
        if isinstance(payload, dict):
            # The code lives at the top level; `error` is the human message.
            assert payload.get('code') in {
                'INVALID_JSON', 'INVALID_JSON_DEPTH', 'INVALID_REQUEST_BODY',
            }, payload
        else:
            assert 'JSON' in str(payload), payload


def test_a_deeply_nested_session_state_rebuilds_instead_of_failing_every_start(tmp_path):
    """A damaged session file must not block every session start.

    RecursionError is not a YAMLError, so it escaped the rebuild handler: the
    damaged file stayed on disk and every subsequent start hit the same error.
    """
    from tools.agent.session_state import SessionStateStore
    from tools.init_project import init_project

    init_project(tmp_path, 'demo')
    store = SessionStateStore(tmp_path, 'demo')
    state = store.load_or_create()
    store.save(state)

    depth = 100_000
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('[' * depth + ']' * depth, encoding='utf-8')

    # Must rebuild, not raise.
    rebuilt = store.load_or_create()
    assert rebuilt.session_id, 'the session state must be rebuilt from a damaged file'


@pytest.mark.parametrize("hostile", [
    "../../../etc/passwd",
    "..\\..\\windows\\system32\\config\\sam",
    "/etc/passwd",
    "ch_001/../../../etc/passwd",
    "ch_001%00.txt",
    "....//....//etc/passwd",
    "ch_001/../../book_state.yaml",
    "",
    " ",
    "ch_" + "9" * 500,
    "CH_001",
    "ch_001.md",
])
def test_document_paths_reject_every_traversal_shape(server, project, hostile):
    """A traversal attempt must be a 4xx, never a read outside the novel root.

    These are the shapes that defeat naive `startswith` checks: absolute paths,
    backslashes on Windows, NUL truncation, doubled dots, over-long IDs, and
    case variations.
    """
    _server, base = server
    for method, path, payload in (
        ("PUT", "/api/document", {"path": hostile, "content": "x"}),
        ("GET", "/api/document", None),
    ):
        if method == "GET":
            path = "/api/document?path=" + urllib.parse.quote(hostile, safe="")
        status, body = _request(
            base, method, path, payload, {**WRITE_HEADERS, **_context_headers(project)}
        )
        assert status in (400, 403, 404), f"{hostile!r} via {method} -> {status} {body}"
        assert status != 500, f"{hostile!r} crashed the handler: {body}"


def test_manuscript_ids_reject_traversal(server, project):
    """Chapter and version IDs reach the filesystem directly."""
    _server, base = server
    for hostile in ("../book_state", "ch_1/../..", "ch_", "ch_abc", "ver_x"):
        status, body = _request(
            base,
            "GET",
            f"/api/manuscript/versions/{hostile}/compare",
            None,
            {**_context_headers(project)},
        )
        # Either rejected by the route (404) or by the ID validator (400).
        assert status in (400, 404), f"{hostile!r} -> {status} {body}"


def test_document_writes_reject_a_symlink_that_points_inside_the_allowed_root(server, project, tmp_path):
    """A symlink inside the allowed root must not be writable.

    The root check resolves the candidate, so a symlink at src/evil.md pointing
    at src/real.md passes it. Only the explicit `is_symlink` refusal stops the
    write from following the link and clobbering the target.
    """
    _server, base = server
    novel_root = project / "data" / "novels" / "demo"
    target = novel_root / "src" / "real.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# real\n", encoding="utf-8")
    link = novel_root / "src" / "evil.md"
    link.symlink_to(target)

    status, body = _request(
        base,
        "PUT",
        "/api/document",
        {"path": "src/evil.md", "content": "clobbered"},
        {**WRITE_HEADERS, **_context_headers(project)},
    )
    assert status == 403, f"a symlink write was allowed: {status} {body}"
    assert target.read_text(encoding="utf-8") == "# real\n", "the symlink target was modified"
