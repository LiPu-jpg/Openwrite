"""HTTP transport for the local OpenWrite Studio application."""

from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, quote, urlparse

from tools.studio_contracts import (
    MAX_ASSET_PACKAGE_REQUEST_BYTES,
    MAX_DOCUMENT_BYTES,
    STATIC_ROOT,
    WRITE_HEADER,
    StudioError,
    apply_security_headers,
    internal_error_payload,
    new_request_id,
    studio_error_payload,
    studio_success_payload,
)


@dataclass(frozen=True)
class StudioPostRoute:
    method_name: str
    requires_project: bool = True
    accepts_payload: bool = True
    envelope: bool = False
    path_parameter: str = ""


POST_ROUTES = {
    "/api/focus": StudioPostRoute("update_focus", requires_project=False),
    "/api/model": StudioPostRoute("configure_model", requires_project=False),
    "/api/model/test": StudioPostRoute("test_model_connection", requires_project=False),
    "/api/model/embedding/test": StudioPostRoute(
        "test_embedding_connection", requires_project=False
    ),
    "/api/model/profiles": StudioPostRoute("save_model_profile", requires_project=False),
    "/api/model/profiles/delete": StudioPostRoute(
        "delete_model_profile", requires_project=False
    ),
    "/api/model/routes": StudioPostRoute("save_model_routes", requires_project=False),
    "/api/research/settings": StudioPostRoute("save_research_settings"),
    "/api/project/init": StudioPostRoute("initialize_project", requires_project=False),
    "/api/project/open": StudioPostRoute("open_project", requires_project=False),
    "/api/project/delete": StudioPostRoute("delete_project", requires_project=False),
    "/api/project/writing-targets": StudioPostRoute("update_writing_targets"),
    "/api/write": StudioPostRoute("write_next_chapter"),
    "/api/chapter/delete": StudioPostRoute("delete_chapter"),
    "/api/outline/edit": StudioPostRoute("edit_outline_structure"),
    "/api/review": StudioPostRoute("review_chapter"),
    "/api/revisions/selection": StudioPostRoute(
        "create_selection_revision", envelope=True
    ),
    "/api/revisions/from-review": StudioPostRoute(
        "create_review_revision", envelope=True
    ),
    "/api/assets": StudioPostRoute("create_asset", envelope=True),
    "/api/assets/update": StudioPostRoute("update_asset", envelope=True),
    "/api/assets/package/preview": StudioPostRoute(
        "asset_package_preview", envelope=True
    ),
    "/api/assets/package/import": StudioPostRoute(
        "import_asset_package", envelope=True
    ),
    "/api/tasks": StudioPostRoute("create_task", envelope=True),
    "/api/benchmarks": StudioPostRoute("create_benchmark", envelope=True),
    "/api/sync": StudioPostRoute("sync_project", accepts_payload=False),
    "/api/document/create": StudioPostRoute("create_document"),
    "/api/import": StudioPostRoute("import_text"),
    "/api/import/preview": StudioPostRoute("preview_import"),
    "/api/foreshadowing": StudioPostRoute("manage_foreshadowing"),
    "/api/chat": StudioPostRoute("chat_turn"),
    "/api/agent/session": StudioPostRoute("create_agent_session"),
    "/api/agent/session/delete": StudioPostRoute("delete_agent_session"),
    "/api/source": StudioPostRoute("source_action"),
    "/api/reference-library": StudioPostRoute("reference_library_action"),
    "/api/runtime-skills": StudioPostRoute("runtime_skill_action"),
    "/api/rules": StudioPostRoute("rule_action"),
    "/api/chapter-runs-v2": StudioPostRoute("chapter_run_v2_action"),
    "/api/diagnostics": StudioPostRoute("runtime_diagnostics"),
    "/api/rolling-plans": StudioPostRoute("rolling_plan_action"),
    "/api/narrative-forecasts": StudioPostRoute("narrative_forecast_action"),
    "/api/manuscript-editing": StudioPostRoute("manuscript_editing_action"),
}

POST_ROUTE_PATTERNS = (
    (
        re.compile(r"^/api/tasks/(?P<task_id>tsk_[A-Za-z0-9_-]+)/cancel$"),
        StudioPostRoute("cancel_task", envelope=True, path_parameter="task_id"),
    ),
    (
        re.compile(r"^/api/tasks/(?P<task_id>tsk_[A-Za-z0-9_-]+)/retry$"),
        StudioPostRoute("retry_task", envelope=True, path_parameter="task_id"),
    ),
    (
        re.compile(r"^/api/tasks/(?P<task_id>tsk_[A-Za-z0-9_-]+)/confirm$"),
        StudioPostRoute("confirm_task", envelope=True, path_parameter="task_id"),
    ),
    (
        re.compile(r"^/api/revisions/(?P<proposal_id>rev_[A-Za-z0-9_-]+)/apply$"),
        StudioPostRoute("apply_revision", envelope=True, path_parameter="proposal_id"),
    ),
    (
        re.compile(r"^/api/revisions/(?P<proposal_id>rev_[A-Za-z0-9_-]+)/reject$"),
        StudioPostRoute("reject_revision", envelope=True, path_parameter="proposal_id"),
    ),
    (
        re.compile(r"^/api/revisions/(?P<proposal_id>rev_[A-Za-z0-9_-]+)/regenerate$"),
        StudioPostRoute("regenerate_revision", envelope=True, path_parameter="proposal_id"),
    ),
)


def resolve_post_route(path: str) -> tuple[StudioPostRoute | None, dict[str, str]]:
    contract = POST_ROUTES.get(path)
    if contract is not None:
        return contract, {}
    for pattern, candidate in POST_ROUTE_PATTERNS:
        match = pattern.fullmatch(path)
        if match:
            return candidate, match.groupdict()
    return None, {}


class StudioRequestHandler(SimpleHTTPRequestHandler):
    server_version = "OpenWriteStudio/5.8"

    @property
    def app(self) -> Any:
        return getattr(self.server, "app")

    @property
    def request_id(self) -> str:
        value = getattr(self, "_request_id", "")
        if not value:
            value = new_request_id()
            self._request_id = value
        return cast(str, value)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._json({"ok": True})
                return
            if parsed.path == "/api/workspace":
                self._json(self.app.workspace())
                return
            if parsed.path == "/api/project/list":
                self._json(self.app.list_projects())
                return
            if parsed.path == "/api/model/profiles":
                self._json(studio_success_payload(self.app.model_profiles(), self.request_id))
                return
            if parsed.path == "/api/continuity":
                self.app.require_project()
                self._json(self.app.continuity())
                return
            if parsed.path == "/api/dog/graphs":
                self.app.require_project()
                chapter_id = parse_qs(parsed.query).get("chapter", [""])[0]
                self._json(self.app.dog_graphs(chapter_id))
                return
            if parsed.path == "/api/benchmarks":
                self.app.require_project()
                raw_limit = parse_qs(parsed.query).get("limit", ["20"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError as exc:
                    raise StudioError(
                        "测试记录数量必须是整数", code="INVALID_INPUT"
                    ) from exc
                self._json(
                    studio_success_payload(
                        self.app.benchmark_surface(limit), self.request_id
                    )
                )
                return
            benchmark_match = re.fullmatch(
                r"/api/benchmarks/(?P<run_id>bench_[A-Za-z0-9_-]+)",
                parsed.path,
            )
            if benchmark_match:
                self.app.require_project()
                result = self.app.benchmark_run(benchmark_match.group("run_id"))
                self._json(studio_success_payload(result, self.request_id))
                return
            if parsed.path == "/api/research":
                self.app.require_project()
                self._json(studio_success_payload(self.app.research_surface(), self.request_id))
                return
            research_report_match = re.fullmatch(
                r"/api/research/reports/(?P<report_id>[A-Za-z0-9][A-Za-z0-9_-]{0,100})",
                parsed.path,
            )
            if research_report_match:
                self.app.require_project()
                result = self.app.research_report(research_report_match.group("report_id"))
                self._json(studio_success_payload(result, self.request_id))
                return
            if parsed.path == "/api/agents":
                params = parse_qs(parsed.query)
                agent_name = params.get("agent", ["goethe"])[0]
                session_id = params.get("session_id", ["default"])[0]
                try:
                    limit = int(params.get("limit", ["200"])[0])
                except ValueError as exc:
                    raise StudioError(
                        "历史消息数量必须是整数", code="INVALID_HISTORY_LIMIT"
                    ) from exc
                self._json(self.app.agent_surface(agent_name, limit, session_id))
                return
            if parsed.path == "/api/agent/activity":
                run_id = parse_qs(parsed.query).get("run_id", [""])[0]
                self._json(self.app.agent_activity(run_id))
                return
            if parsed.path == "/api/context":
                self.app.require_project()
                chapter_id = parse_qs(parsed.query).get("chapter", ["next"])[0]
                self._json(self.app.context_preview(chapter_id))
                return
            if parsed.path == "/api/outline":
                chapter_id = parse_qs(parsed.query).get("chapter", [""])[0]
                self._json(self.app.outline_structure(chapter_id))
                return
            if parsed.path == "/api/search":
                self.app.require_project()
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0]
                scope = params.get("scope", ["all"])[0]
                try:
                    limit = int(params.get("limit", ["20"])[0])
                except ValueError as exc:
                    raise StudioError("搜索数量必须是整数", code="INVALID_SEARCH_LIMIT") from exc
                self._json(self.app.search_project(query, scope, limit))
                return
            if parsed.path == "/api/document":
                self.app.require_project()
                path = parse_qs(parsed.query).get("path", [""])[0]
                self._json(self.app.read_document(path))
                return
            if parsed.path == "/api/assets":
                self.app.require_project()
                kind = parse_qs(parsed.query).get("kind", [""])[0]
                result = self.app.asset_surface(kind)
                self._json(studio_success_payload(result, self.request_id))
                return
            reference_match = re.fullmatch(
                r"/api/reference-library/(?P<source_id>[A-Za-z0-9][A-Za-z0-9_-]{1,63})",
                parsed.path,
            )
            if reference_match:
                self.app.require_project()
                result = self.app.read_reference_library_content(
                    reference_match.group("source_id")
                )
                self._json(studio_success_payload(result, self.request_id))
                return
            asset_match = re.fullmatch(
                r"/api/assets/(?P<kind>character|world|progression)/"
                r"(?P<asset_id>[A-Za-z0-9][A-Za-z0-9_.-]{0,79})",
                parsed.path,
            )
            if asset_match:
                self.app.require_project()
                result = self.app.read_asset(
                    asset_match.group("kind"),
                    asset_match.group("asset_id"),
                )
                self._json(studio_success_payload(result, self.request_id))
                return
            if parsed.path == "/api/revisions":
                self.app.require_project()
                params = parse_qs(parsed.query)
                result = self.app.list_revisions(
                    params.get("chapter", [""])[0],
                    params.get("status", [""])[0],
                )
                self._json(studio_success_payload(result, self.request_id))
                return
            if parsed.path == "/api/tasks":
                self.app.require_project()
                raw_limit = parse_qs(parsed.query).get("limit", ["100"])[0]
                try:
                    limit = int(raw_limit)
                except ValueError as exc:
                    raise StudioError("任务数量必须是整数", code="INVALID_INPUT") from exc
                result = self.app.task_surface(limit)
                self._json(studio_success_payload(result, self.request_id))
                return
            task_match = re.fullmatch(
                r"/api/tasks/(?P<task_id>tsk_[A-Za-z0-9_-]+)",
                parsed.path,
            )
            if task_match:
                self.app.require_project()
                result = self.app.get_task(task_match.group("task_id"))
                self._json(studio_success_payload(result, self.request_id))
                return
            revision_match = re.fullmatch(
                r"/api/revisions/(?P<proposal_id>rev_[A-Za-z0-9_-]+)",
                parsed.path,
            )
            if revision_match:
                self.app.require_project()
                result = self.app.get_revision(revision_match.group("proposal_id"))
                self._json(studio_success_payload(result, self.request_id))
                return
            if parsed.path == "/api/export":
                self.app.require_project()
                format_name = parse_qs(parsed.query).get("format", ["md"])[0]
                filename, content, mime = self.app.export_download(format_name)
                self.send_response(HTTPStatus.OK)
                self._security_headers()
                self.send_header("Content-Type", mime)
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename*=UTF-8''{quote(filename)}",
                )
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            if parsed.path == "/api/assets/package/export":
                self.app.require_project()
                selections: list[dict[str, str]] = []
                for value in parse_qs(parsed.query).get("select", []):
                    kind, separator, asset_id = value.partition(":")
                    if not separator:
                        raise StudioError(
                            "资产选择格式无效",
                            code="INVALID_ASSET_SELECTION",
                        )
                    selections.append({"kind": kind, "id": asset_id})
                filename, content, mime = self.app.asset_package_download(selections)
                self.send_response(HTTPStatus.OK)
                self._security_headers()
                self.send_header("Content-Type", mime)
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename*=UTF-8''{quote(filename)}",
                )
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            if parsed.path in {"/brand/logo.svg", "/brand/logo-dark.svg"}:
                self._serve_brand_logo(parsed.path.endswith("dark.svg"))
                return
            self._serve_static(parsed.path)
        except StudioError as exc:
            self._handle_studio_error(exc)
        except Exception as exc:
            self._handle_internal_error(exc)

    def do_PUT(self) -> None:
        try:
            self._require_write_header()
            if urlparse(self.path).path != "/api/document":
                raise StudioError("接口不存在", HTTPStatus.NOT_FOUND, code="ROUTE_NOT_FOUND")
            self.app.require_project()
            payload = self._body_json()
            result = self.app.write_document(
                str(payload.get("path") or ""),
                str(payload.get("content") or ""),
                (
                    payload.get("version")
                    if isinstance(payload.get("version"), (str, int))
                    else None
                ),
                force=bool(payload.get("force")),
            )
            self._json(result)
        except StudioError as exc:
            self._handle_studio_error(exc)
        except Exception as exc:
            self._handle_internal_error(exc)

    def do_POST(self) -> None:
        try:
            self._require_write_header()
            route = urlparse(self.path).path
            payload = self._body_json()
            route_contract, path_parameters = resolve_post_route(route)
            if route_contract is None:
                raise StudioError("接口不存在", HTTPStatus.NOT_FOUND, code="ROUTE_NOT_FOUND")
            if route_contract.requires_project:
                self.app.require_project()
            method = getattr(self.app, route_contract.method_name)
            if route_contract.path_parameter:
                result = method(
                    path_parameters[route_contract.path_parameter],
                    payload,
                )
            else:
                result = method(payload) if route_contract.accepts_payload else method()
            if route_contract.envelope:
                result = studio_success_payload(result, self.request_id)
            self._json(result)
        except StudioError as exc:
            self._handle_studio_error(exc)
        except Exception as exc:
            self._handle_internal_error(exc)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self._security_headers()
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        if self.path.startswith("/api/") and not self.path.startswith("/api/health"):
            super().log_message(format, *args)

    def _handle_studio_error(self, error: StudioError) -> None:
        self._debug_http_error(error.status, str(error))
        self._json(studio_error_payload(error, self.request_id), status=error.status)

    def _handle_internal_error(self, error: Exception) -> None:
        self._debug_http_error(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            error.__class__.__name__,
        )
        self._json(
            internal_error_payload(self.request_id),
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    def _debug_http_error(self, status: HTTPStatus | int, message: str) -> None:
        if not self.app.debug_enabled:
            return
        self.app._debug_event(
            "http_error",
            request_id=self.request_id,
            method=self.command,
            path=urlparse(self.path).path,
            status=int(status),
            message=message,
        )

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        path = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in path.parents and path != STATIC_ROOT.resolve():
            raise StudioError("资源不存在", HTTPStatus.NOT_FOUND, code="STATIC_ASSET_NOT_FOUND")
        if not path.is_file():
            raise StudioError(
                f"Studio 资源不存在: {relative}",
                HTTPStatus.NOT_FOUND,
                code="STATIC_ASSET_NOT_FOUND",
                details={"path": relative},
            )
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_brand_logo(self, dark: bool) -> None:
        path = STATIC_ROOT / ("logo-dark.svg" if dark else "logo.svg")
        if not path.is_file():
            raise StudioError("品牌资源不存在", HTTPStatus.NOT_FOUND, code="BRAND_ASSET_NOT_FOUND")
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _body_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise StudioError("无效请求长度", code="INVALID_CONTENT_LENGTH") from exc
        max_length = (
            MAX_ASSET_PACKAGE_REQUEST_BYTES
            if urlparse(self.path).path == "/api/assets/package/preview"
            else MAX_DOCUMENT_BYTES + 65536
        )
        if length <= 0 or length > max_length:
            raise StudioError(
                "无效请求体",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                code="INVALID_REQUEST_BODY",
            )
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StudioError("请求 JSON 无效", code="INVALID_JSON") from exc
        if not isinstance(payload, dict):
            raise StudioError("请求必须是 JSON 对象", code="INVALID_JSON_OBJECT")
        return payload

    def _require_write_header(self) -> None:
        if self.headers.get(WRITE_HEADER) != "1":
            raise StudioError(
                "缺少 Studio 写入凭证",
                HTTPStatus.FORBIDDEN,
                code="WRITE_CREDENTIAL_REQUIRED",
            )

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Request-ID", self.request_id)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        apply_security_headers(self.send_header)


class OpenWriteStudioServer(ThreadingHTTPServer):
    app: Any
