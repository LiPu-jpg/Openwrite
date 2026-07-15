"""Local, novel-only web workbench for OpenWrite."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import tempfile
import webbrowser
from collections.abc import Callable
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any, cast
from urllib.parse import parse_qs, quote, urlparse

import yaml

from tools.novel_service import NovelApplicationService, NovelServiceError
from tools.novel_workspace import (
    list_chapters,
    novel_root,
)
from tools.version import __version__

STATIC_ROOT = Path(__file__).parent / "studio_assets"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
WRITE_HEADER = "X-OpenWrite-Studio"


class StudioError(Exception):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


class StudioApplication:
    """Filesystem and writing operations exposed to the local HTTP layer."""

    def __init__(
        self,
        project_root: Path,
        writer_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
        review_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
        chat_executor: Callable[[Path, str, str, str], dict[str, Any]] | None = None,
        source_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.config_path = self.project_root / "novel_config.yaml"
        self.initialized = self.config_path.exists()
        self.config = self._load_config() if self.initialized else {}
        self.novel_id = str(self.config.get("novel_id") or "")
        if self.initialized and not self.novel_id:
            raise StudioError("novel_config.yaml 缺少 novel_id")
        self.novel_root = (
            novel_root(self.project_root, self.novel_id).resolve()
            if self.initialized
            else self.project_root
        )
        self._writer_executor = writer_executor
        self._review_executor = review_executor
        self._chat_executor = chat_executor
        self._source_executor = source_executor
        self._write_lock = Lock()
        self._novel_service = self._build_novel_service() if self.initialized else None

    def workspace(self) -> dict[str, Any]:
        if not self.initialized:
            return {
                "version": __version__,
                "initialized": False,
                "snapshot": {
                    "novel_id": "",
                    "title": "新小说",
                    "current_arc": "arc_001",
                    "current_chapter": "ch_001",
                    "stage": "discovery",
                    "chapters": 0,
                    "writing_units": 0,
                    "target_units": 0,
                    "characters": 0,
                    "world_documents": 0,
                    "pending_foreshadowing": 0,
                    "total_tokens": 0,
                    "reviewed_chapters": 0,
                    "average_review_score": 0,
                    "creative_focus": {
                        "goal": "",
                        "must_keep": [],
                        "must_avoid": [],
                        "notes": [],
                    },
                    "readiness": {
                        "author_intent": False,
                        "background": False,
                        "foundation": False,
                        "characters": False,
                        "outline": False,
                        "creative_focus": False,
                    },
                    "next_actions": ["先创建小说项目"],
                },
                "documents": {
                    "story": [],
                    "characters": [],
                    "world": [],
                    "chapters": [],
                },
                "model": {
                    "configured": bool(os.environ.get("LLM_API_KEY", "").strip()),
                    "name": os.environ.get("LLM_MODEL", "").strip() or "未配置",
                },
                "operations": {
                    "sync": {"needs_sync": False},
                    "source_packs": [],
                    "diagnostics": [
                        {"name": "项目配置", "ok": False, "detail": "尚未创建"}
                    ],
                },
            }
        self.config = self._load_config()
        snapshot = self._service().workspace_snapshot()
        chapters = list_chapters(self.project_root, self.novel_id)
        return {
            "version": __version__,
            "initialized": True,
            "snapshot": snapshot,
            "documents": self._document_groups(chapters),
            "model": {
                "configured": bool(os.environ.get("LLM_API_KEY", "").strip()),
                "name": os.environ.get("LLM_MODEL", "").strip() or "未配置",
            },
            "operations": self.operation_status(),
        }

    def initialize_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.initialized:
            raise StudioError("当前目录已经是小说项目", HTTPStatus.CONFLICT)
        novel_id = str(payload.get("novel_id") or "").strip()
        title = str(payload.get("title") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", novel_id):
            raise StudioError("小说 ID 需为 2-64 位字母、数字、横线或下划线")
        if not title or len(title) > 120:
            raise StudioError("书名不能为空且不能超过 120 字")
        try:
            NovelApplicationService.initialize(self.project_root, novel_id, title)
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        self.config = self._load_config()
        self.novel_id = novel_id
        self.novel_root = novel_root(self.project_root, novel_id).resolve()
        self.initialized = True
        self._novel_service = self._build_novel_service()
        return self.workspace()

    def require_project(self) -> None:
        if not self.initialized:
            raise StudioError("请先创建小说项目", HTTPStatus.PRECONDITION_REQUIRED)

    def _build_novel_service(self) -> NovelApplicationService:
        return NovelApplicationService(
            self.project_root,
            writer_executor=self._writer_executor,
            review_executor=self._review_executor,
            source_executor=self._source_executor,
            task_lock=self._write_lock,
        )

    def _service(self) -> NovelApplicationService:
        self.require_project()
        if self._novel_service is None:
            self._novel_service = self._build_novel_service()
        return self._novel_service

    @staticmethod
    def _translate_service_error(exc: NovelServiceError) -> StudioError:
        status = {
            "PROJECT_BUSY": HTTPStatus.CONFLICT,
            "CONFLICT": HTTPStatus.CONFLICT,
            "NOT_FOUND": HTTPStatus.NOT_FOUND,
            "INVALID_PROJECT": HTTPStatus.PRECONDITION_FAILED,
            "INVALID_INPUT": HTTPStatus.BAD_REQUEST,
        }.get(exc.code, HTTPStatus.BAD_GATEWAY)
        return StudioError(str(exc), status)

    def operation_status(self) -> dict[str, Any]:
        sources_root = self.novel_root / "data" / "sources"
        source_packs = []
        if sources_root.exists():
            for path in sorted(sources_root.iterdir()):
                if not path.is_dir():
                    continue
                source_packs.append(
                    {
                        "source_id": path.name,
                        "review_ready": (path / "source.md").exists(),
                        "style_ready": (path / "style").is_dir(),
                        "setting_ready": (path / "setting_profile.md").exists(),
                    }
                )
        sync = self._service().sync_status()
        diagnostics = [
            {
                "name": "项目配置",
                "ok": self.config_path.is_file() and bool(self.novel_id),
                "detail": self.novel_id,
            },
            {
                "name": "模型连接",
                "ok": bool(os.environ.get("LLM_API_KEY", "").strip()),
                "detail": os.environ.get("LLM_MODEL", "").strip() or "未配置",
            },
            {
                "name": "源文件同步",
                "ok": not bool(sync.get("needs_sync")),
                "detail": "待同步" if sync.get("needs_sync") else "已同步",
            },
            {
                "name": "作品写入",
                "ok": os.access(self.novel_root, os.W_OK),
                "detail": "可写" if os.access(self.novel_root, os.W_OK) else "只读",
            },
        ]
        return {"sync": sync, "source_packs": source_packs, "diagnostics": diagnostics}

    def read_document(self, relative_path: str) -> dict[str, Any]:
        path = self._resolve_document(relative_path, write=False)
        if not path.is_file():
            raise StudioError("文档不存在", HTTPStatus.NOT_FOUND)
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise StudioError(
                "文档超过 2 MB，Studio 不直接打开",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        return {
            "path": self._relative(path),
            "title": self._document_title(path),
            "content": path.read_text(encoding="utf-8"),
            "version": str(path.stat().st_mtime_ns),
        }

    def write_document(
        self,
        relative_path: str,
        content: str,
        version: str | int | None,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        path = self._resolve_document(relative_path, write=True)
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise StudioError("文档超过 2 MB，已拒绝保存", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if "\x00" in content:
            raise StudioError("文档包含无效字符")

        with self._write_lock:
            if path.exists() and version is not None and not force:
                current_version = str(path.stat().st_mtime_ns)
                if current_version != str(version):
                    raise StudioError("文档已在其他位置修改，请重新载入", HTTPStatus.CONFLICT)
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                temp_path = Path(handle.name)
            temp_path.replace(path)
        return self.read_document(self._relative(path))

    def update_focus(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            self._service().update_focus(
                goal=str(payload.get("goal") or ""),
                must_keep=self._string_list(payload.get("must_keep")),
                must_avoid=self._string_list(payload.get("must_avoid")),
                notes=self._string_list(payload.get("notes")),
            )
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return self.workspace()

    def configure_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "openai").strip().lower()
        model = str(payload.get("model") or "").strip()
        base_url = str(payload.get("base_url") or "").strip()
        api_format = str(payload.get("api_format") or "chat").strip().lower()
        api_key = str(payload.get("api_key") or "").strip()
        if provider not in {"openai", "anthropic", "custom"}:
            raise StudioError("模型提供方无效")
        if api_format not in {"chat", "responses"}:
            raise StudioError("API 格式无效")
        if not model or len(model) > 120:
            raise StudioError("模型名称不能为空且不能超过 120 字")
        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise StudioError("Base URL 必须是有效的 HTTP(S) 地址")
        if not api_key and not os.environ.get("LLM_API_KEY", "").strip():
            raise StudioError("API Key 不能为空")
        os.environ["LLM_PROVIDER"] = provider
        os.environ["LLM_MODEL"] = model
        os.environ["LLM_API_FORMAT"] = api_format
        if base_url:
            os.environ["LLM_BASE_URL"] = base_url
        if api_key:
            os.environ["LLM_API_KEY"] = api_key
        return self.workspace()

    def sync_project(self) -> dict[str, Any]:
        try:
            result = self._service().sync()
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {**result, "workspace": self.workspace()}

    def create_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = str(payload.get("kind") or "").strip()
        name = str(payload.get("name") or "").strip()
        description = str(payload.get("description") or "").strip()
        with self._write_lock:
            try:
                path = self._service().create_document(
                    kind=kind,
                    name=name,
                    description=description,
                )
            except NovelServiceError as exc:
                raise self._translate_service_error(exc) from exc
        return {"document": self.read_document(self._relative(path)), "workspace": self.workspace()}

    def import_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        filename = str(payload.get("filename") or "import.md").strip()
        content = str(payload.get("content") or "")
        if not content.strip():
            raise StudioError("导入内容不能为空")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".markdown"}:
            raise StudioError("当前仅支持 TXT 和 Markdown 导入")
        arc_id = str(payload.get("arc_id") or self.config.get("current_arc") or "arc_001")
        if not re.fullmatch(r"arc_\d+", arc_id):
            raise StudioError("篇 ID 必须形如 arc_001")
        start_number = payload.get("start_number")
        if start_number in {None, ""}:
            start = None
        else:
            try:
                start = int(start_number)
            except (TypeError, ValueError) as exc:
                raise StudioError("起始章节必须是整数") from exc
        with self._write_lock, tempfile.TemporaryDirectory(prefix="openwrite-import-") as temp_dir:
            source = Path(temp_dir) / f"source{suffix}"
            source.write_text(content, encoding="utf-8")
            try:
                result = self._service().import_book(
                    source,
                    arc_id=arc_id,
                    start_number=start,
                    force=bool(payload.get("force")),
                )
            except NovelServiceError as exc:
                raise self._translate_service_error(exc) from exc
        return {
            "imported": result["imported"],
            "workspace": self.workspace(),
        }

    def context_preview(self, chapter_id: str) -> dict[str, Any]:
        try:
            result = self._service().context_preview(chapter_id)
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        result.pop("packet", None)
        return result

    def continuity(self) -> dict[str, Any]:
        try:
            return self._service().continuity()
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc

    def manage_foreshadowing(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._service().manage_foreshadowing(payload)
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {**result, "workspace": self.workspace()}

    def chat_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not os.environ.get("LLM_API_KEY", "").strip():
            raise StudioError("未配置 LLM_API_KEY", HTTPStatus.PRECONDITION_FAILED)
        agent_name = str(payload.get("agent") or "dante").strip().lower()
        message = str(payload.get("message") or "").strip()
        if agent_name not in {"goethe", "dante"}:
            raise StudioError("Agent 仅支持 goethe 或 dante")
        if not message or len(message) > 12000:
            raise StudioError("消息不能为空且不能超过 12000 字")
        if not self._write_lock.acquire(blocking=False):
            raise StudioError("已有 AI 任务正在运行", HTTPStatus.CONFLICT)
        try:
            if self._chat_executor is not None:
                result = self._chat_executor(
                    self.project_root, self.novel_id, agent_name, message
                )
            elif agent_name == "goethe":
                from tools.goethe import GoetheChatAgent

                response = GoetheChatAgent(
                    self.project_root, self.novel_id
                ).respond(message)
                result = {"content": response}
            else:
                from tools.agent.dante import DanteChatAgent
                from tools.agent.tool_layers import build_dante_tool_layers

                layers = build_dante_tool_layers(self.project_root)
                agent = DanteChatAgent(
                    self.project_root,
                    self.novel_id,
                    tool_executors=layers.get("direct_tool_executors", {}),
                    action_executors=layers.get("action_tool_executors", {}),
                )
                result = {"content": agent.respond(message)}
        finally:
            self._write_lock.release()
        if result.get("error"):
            raise StudioError(str(result["error"]), HTTPStatus.BAD_GATEWAY)
        return {
            "agent": agent_name,
            "content": str(result.get("content") or ""),
            "workspace": self.workspace(),
        }

    def source_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip()
        source_id = str(payload.get("source_id") or "").strip()
        try:
            if action == "extract":
                if not os.environ.get("LLM_API_KEY", "").strip():
                    raise StudioError("未配置 LLM_API_KEY", HTTPStatus.PRECONDITION_FAILED)
                text = str(payload.get("content") or "")
                if not text.strip():
                    raise StudioError("来源文本不能为空")
                with tempfile.TemporaryDirectory(prefix="openwrite-source-") as temp_dir:
                    source = Path(temp_dir) / "source.txt"
                    source.write_text(text, encoding="utf-8")
                    result = self._service().extract_source(
                        source_id=source_id,
                        source_file=source,
                        focus=str(payload.get("focus") or "style"),
                    )
            elif action == "review":
                result = self._service().review_source(source_id)
            elif action == "promote":
                result = self._service().promote_source(
                    source_id,
                    str(payload.get("target") or "all"),
                )
            elif action == "synthesize":
                result = self._service().synthesize_style(source_id)
            else:
                raise StudioError("未知来源操作")
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {"result": result, "workspace": self.workspace()}

    def write_next_chapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not os.environ.get("LLM_API_KEY", "").strip():
            raise StudioError("未配置 LLM_API_KEY", HTTPStatus.PRECONDITION_FAILED)
        try:
            target_words = int(payload.get("target_words") or 3000)
        except (TypeError, ValueError) as exc:
            raise StudioError("目标字数必须是整数") from exc
        if not 200 <= target_words <= 12000:
            raise StudioError("目标字数必须在 200 到 12000 之间")
        guidance = str(payload.get("guidance") or "").strip()
        try:
            result = self._service().write_chapter(
                {
                    "chapter_id": "next",
                    "guidance": guidance,
                    "target_words": target_words,
                    "temperature": float(payload.get("temperature") or 0.7),
                }
            )
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {"result": result, "workspace": self.workspace()}

    def review_chapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not os.environ.get("LLM_API_KEY", "").strip():
            raise StudioError("未配置 LLM_API_KEY", HTTPStatus.PRECONDITION_FAILED)
        relative_path = str(payload.get("path") or "")
        path = self._resolve_document(relative_path, write=False)
        manuscript_root = (self.novel_root / "data" / "manuscript").resolve()
        if manuscript_root not in path.parents or not re.fullmatch(r"ch_\d+", path.stem):
            raise StudioError("只能审查正文章节")

        try:
            result = self._service().review_chapter(path.stem)
        except NovelServiceError as exc:
            raise self._translate_service_error(exc) from exc
        return {"result": result, "workspace": self.workspace()}

    def export_download(self, format_name: str) -> tuple[str, bytes, str]:
        if format_name not in {"md", "txt"}:
            raise StudioError("导出格式仅支持 md 或 txt")
        title = str(self.config.get("title") or self.novel_id)
        with tempfile.TemporaryDirectory(prefix="openwrite-export-") as temp_dir:
            output = Path(temp_dir) / f"{self.novel_id}.{format_name}"
            try:
                self._service().export_book(
                    output,
                    format_name=format_name,
                    title=title,
                )
            except NovelServiceError as exc:
                raise self._translate_service_error(exc) from exc
            content = output.read_bytes()
        mime = (
            "text/markdown; charset=utf-8"
            if format_name == "md"
            else "text/plain; charset=utf-8"
        )
        return f"{self.novel_id}.{format_name}", content, mime

    def _load_config(self) -> dict[str, Any]:
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise StudioError(f"项目配置无法读取: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def _document_groups(self, chapters: list[Any]) -> dict[str, list[dict[str, Any]]]:
        src = self.novel_root / "src"
        groups = {
            "story": self._collect_documents(src / "story", recursive=False),
            "characters": self._collect_documents(src / "characters", recursive=False),
            "world": self._collect_documents(src / "world", recursive=True),
            "chapters": [self._chapter_summary(item) for item in chapters],
        }
        outline = src / "outline.md"
        if outline.exists():
            groups["story"].insert(0, self._document_summary(outline))
        return groups

    def _chapter_summary(self, item: Any) -> dict[str, Any]:
        review = self._load_review_result(item.chapter_id)
        subtitle = f"{item.chapter_id} · {item.writing_units:,} 字"
        if review:
            subtitle += f" · {float(review.get('score', 0)):.0f} 分"
        return {
            "path": self._relative(item.path),
            "title": item.title,
            "subtitle": subtitle,
            "review": review,
        }

    def _load_review_result(self, chapter_id: str) -> dict[str, Any] | None:
        from tools.review_store import ReviewStore

        data = ReviewStore(self.project_root, self.novel_id).load(chapter_id)
        if data is None:
            return None
        return {
            "score": float(data.get("score") or 0),
            "passed": bool(data.get("passed")),
            "issues": int(data.get("issues") or 0),
            "reviewed_at": str(data.get("reviewed_at") or ""),
        }

    def _collect_documents(self, root: Path, *, recursive: bool) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        iterator = root.rglob("*.md") if recursive else root.glob("*.md")
        return [self._document_summary(path) for path in sorted(iterator) if path.is_file()]

    def _document_summary(self, path: Path) -> dict[str, Any]:
        return {
            "path": self._relative(path),
            "title": self._document_title(path),
            "subtitle": str(path.relative_to(self.novel_root).parent),
        }

    def _document_title(self, path: Path) -> str:
        try:
            head = path.read_text(encoding="utf-8")[:2000]
        except OSError:
            return path.stem
        match = re.search(r"^#\s+(.+?)\s*$", head, re.MULTILINE)
        return match.group(1).strip() if match else path.stem.replace("_", " ")

    def _resolve_document(self, relative_path: str, *, write: bool) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise StudioError("缺少文档路径")
        candidate = (self.novel_root / relative_path).resolve()
        allowed_roots = [
            (self.novel_root / "src").resolve(),
            (self.novel_root / "data" / "manuscript").resolve(),
        ]
        if not any(candidate == root or root in candidate.parents for root in allowed_roots):
            raise StudioError("文档路径不在 Studio 可访问范围", HTTPStatus.FORBIDDEN)
        if candidate.suffix.lower() != ".md":
            raise StudioError("Studio 仅编辑 Markdown 文档")
        if write and candidate.is_symlink():
            raise StudioError("不允许写入符号链接", HTTPStatus.FORBIDDEN)
        return candidate

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.novel_root).as_posix()

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if isinstance(value, str):
            values = value.splitlines()
        elif isinstance(value, list):
            values = value
        else:
            return []
        return [str(item).strip().removeprefix("- ") for item in values if str(item).strip()]


class StudioRequestHandler(SimpleHTTPRequestHandler):
    server_version = "OpenWriteStudio/5.8"

    @property
    def app(self) -> StudioApplication:
        return cast(StudioApplication, getattr(self.server, "app"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._json({"ok": True})
                return
            if parsed.path == "/api/workspace":
                self._json(self.app.workspace())
                return
            if parsed.path == "/api/continuity":
                self.app.require_project()
                self._json(self.app.continuity())
                return
            if parsed.path == "/api/context":
                self.app.require_project()
                chapter_id = parse_qs(parsed.query).get("chapter", ["next"])[0]
                self._json(self.app.context_preview(chapter_id))
                return
            if parsed.path == "/api/document":
                self.app.require_project()
                path = parse_qs(parsed.query).get("path", [""])[0]
                self._json(self.app.read_document(path))
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
            if parsed.path in {"/brand/logo.svg", "/brand/logo-dark.svg"}:
                self._serve_brand_logo(parsed.path.endswith("dark.svg"))
                return
            self._serve_static(parsed.path)
        except StudioError as exc:
            self._json({"error": str(exc)}, status=exc.status)
        except Exception:
            self._json({"error": "Studio 内部错误"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PUT(self) -> None:
        try:
            self._require_write_header()
            if urlparse(self.path).path != "/api/document":
                raise StudioError("接口不存在", HTTPStatus.NOT_FOUND)
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
            self._json({"error": str(exc)}, status=exc.status)

    def do_POST(self) -> None:
        try:
            self._require_write_header()
            route = urlparse(self.path).path
            payload = self._body_json()
            if route == "/api/focus":
                self._json(self.app.update_focus(payload))
                return
            if route == "/api/model":
                self._json(self.app.configure_model(payload))
                return
            if route == "/api/project/init":
                self._json(self.app.initialize_project(payload))
                return
            self.app.require_project()
            if route == "/api/write":
                self._json(self.app.write_next_chapter(payload))
                return
            if route == "/api/review":
                self._json(self.app.review_chapter(payload))
                return
            if route == "/api/sync":
                self._json(self.app.sync_project())
                return
            if route == "/api/document/create":
                self._json(self.app.create_document(payload))
                return
            if route == "/api/import":
                self._json(self.app.import_text(payload))
                return
            if route == "/api/foreshadowing":
                self._json(self.app.manage_foreshadowing(payload))
                return
            if route == "/api/chat":
                self._json(self.app.chat_turn(payload))
                return
            if route == "/api/source":
                self._json(self.app.source_action(payload))
                return
            raise StudioError("接口不存在", HTTPStatus.NOT_FOUND)
        except StudioError as exc:
            self._json({"error": str(exc)}, status=exc.status)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self._security_headers()
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        if self.path.startswith("/api/") and not self.path.startswith("/api/health"):
            super().log_message(format, *args)

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        path = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in path.parents and path != STATIC_ROOT.resolve():
            raise StudioError("资源不存在", HTTPStatus.NOT_FOUND)
        if not path.is_file():
            path = STATIC_ROOT / "index.html"
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
            raise StudioError("品牌资源不存在", HTTPStatus.NOT_FOUND)
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
            raise StudioError("无效请求长度") from exc
        if length <= 0 or length > MAX_DOCUMENT_BYTES + 65536:
            raise StudioError("无效请求体", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StudioError("请求 JSON 无效") from exc
        if not isinstance(payload, dict):
            raise StudioError("请求必须是 JSON 对象")
        return payload

    def _require_write_header(self) -> None:
        if self.headers.get(WRITE_HEADER) != "1":
            raise StudioError("缺少 Studio 写入凭证", HTTPStatus.FORBIDDEN)

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )
        self.send_header("Cache-Control", "no-store")


class OpenWriteStudioServer(ThreadingHTTPServer):
    app: StudioApplication


def create_server(
    project_root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 4567,
    writer_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
    review_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
    chat_executor: Callable[[Path, str, str, str], dict[str, Any]] | None = None,
    source_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
) -> OpenWriteStudioServer:
    if not STATIC_ROOT.is_dir():
        raise StudioError(f"Studio 静态资源缺失: {STATIC_ROOT}")
    app = StudioApplication(
        project_root,
        writer_executor=writer_executor,
        review_executor=review_executor,
        chat_executor=chat_executor,
        source_executor=source_executor,
    )
    handler = partial(StudioRequestHandler, directory=str(STATIC_ROOT))
    server = OpenWriteStudioServer((host, port), handler)
    server.app = app
    return server


def run_studio(
    project_root: Path,
    *,
    port: int = 4567,
    open_browser: bool = True,
) -> int:
    server = create_server(project_root, port=port)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"OpenWrite Studio: {url}")
    print("按 Ctrl+C 停止")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStudio 已停止")
    finally:
        server.server_close()
    return 0
