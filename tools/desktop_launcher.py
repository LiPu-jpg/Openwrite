"""Cross-platform dependency bootstrap and one-click Studio launcher."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

MIN_PYTHON = (3, 10)
DEFAULT_PORT = 4567
PORT_SCAN_LIMIT = 20
LAUNCHER_VERSION = 1
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_TIMEOUT_SECONDS = 12
REQUIRED_IMPORTS = (
    "pydantic",
    "yaml",
    "openai",
    "anthropic",
    "markdown_it",
    "prompt_toolkit",
)


class LauncherError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceUpdateResult:
    status: str
    message: str = ""


def repository_root() -> Path:
    source_root = Path(__file__).resolve().parents[1]
    if (source_root / "pyproject.toml").is_file():
        return source_root
    return Path(sys.prefix).resolve()


def runtime_directory(
    root: Path,
    *,
    platform_name: str | None = None,
    version_info: tuple[int, int] | None = None,
) -> Path:
    platform_name = platform_name or sys.platform
    version_info = version_info or (sys.version_info.major, sys.version_info.minor)
    if platform_name == "darwin":
        system = "macos"
    elif platform_name.startswith("win"):
        system = "windows"
    else:
        system = "unix"
    return root / ".openwrite-runtime" / f"{system}-py{version_info[0]}.{version_info[1]}"


def runtime_python(runtime: Path, *, platform_name: str | None = None) -> Path:
    platform_name = platform_name or sys.platform
    if platform_name.startswith("win"):
        return runtime / "Scripts" / "python.exe"
    return runtime / "bin" / "python"


def dependency_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(f"launcher:{LAUNCHER_VERSION}\n".encode())
    digest.update(f"python:{sys.version_info.major}.{sys.version_info.minor}\n".encode())
    digest.update(f"platform:{sys.platform}\n".encode())
    for name in ("pyproject.toml", "requirements.txt"):
        path = root / name
        digest.update(f"file:{name}\n".encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _run(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [os.fspath(item) for item in command],
        cwd=cwd,
        check=check,
        text=True,
        env={**os.environ, "PYTHONUTF8": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
    )


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=UPDATE_TIMEOUT_SECONDS,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _source_update_stamp(root: Path) -> Path:
    return root / ".openwrite-runtime" / ".source-update.json"


def _record_source_update_check(root: Path, revision: str, checked_at: float) -> None:
    stamp = _source_update_stamp(root)
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(
            json.dumps(
                {"checked_at": checked_at, "revision": revision},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        # A read-only source checkout should still be launchable.
        pass


def _source_update_check_is_recent(root: Path, revision: str, now: float) -> bool:
    stamp = _read_stamp(_source_update_stamp(root))
    raw_checked_at = stamp.get("checked_at")
    if not isinstance(raw_checked_at, (int, float, str)):
        return False
    try:
        checked_at = float(raw_checked_at)
    except (TypeError, ValueError):
        return False
    return (
        stamp.get("revision") == revision and 0 <= now - checked_at < UPDATE_CHECK_INTERVAL_SECONDS
    )


def check_for_source_update(
    root: Path,
    *,
    force: bool = False,
    now: float | None = None,
) -> SourceUpdateResult:
    """Fast-forward a clean Git checkout without making startup depend on the network."""
    if not (root / ".git").exists() or shutil.which("git") is None:
        message = "当前不是 Git 源码副本，无法自动更新。" if force else ""
        return SourceUpdateResult("unavailable", message)

    try:
        inside_worktree = _git(root, "rev-parse", "--is-inside-work-tree").stdout.strip()
        if inside_worktree != "true":
            return SourceUpdateResult("unavailable")
        revision = _git(root, "rev-parse", "HEAD").stdout.strip()
        timestamp = time.time() if now is None else now
        if not force and _source_update_check_is_recent(root, revision, timestamp):
            return SourceUpdateResult("recent")

        if _git(root, "status", "--porcelain", "--untracked-files=normal").stdout.strip():
            return SourceUpdateResult(
                "skipped",
                "检测到源码目录有本地修改，已保留修改并跳过自动更新。",
            )

        try:
            upstream = _git(
                root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
            ).stdout.strip()
        except subprocess.CalledProcessError:
            return SourceUpdateResult(
                "skipped",
                "当前分支没有上游分支，已跳过自动更新。",
            )
        if not upstream:
            return SourceUpdateResult("skipped", "当前分支没有上游分支，已跳过自动更新。")

        print("[OpenWrite] 正在检查源码更新……")
        _git(root, "fetch", "--quiet", "--no-tags")
        local_revision = _git(root, "rev-parse", "HEAD").stdout.strip()
        upstream_revision = _git(root, "rev-parse", "@{upstream}").stdout.strip()
        if local_revision == upstream_revision:
            _record_source_update_check(root, local_revision, timestamp)
            return SourceUpdateResult("current", "当前已是最新版本。")

        merge_base = _git(root, "merge-base", "HEAD", "@{upstream}").stdout.strip()
        if merge_base != local_revision:
            _record_source_update_check(root, local_revision, timestamp)
            if merge_base == upstream_revision:
                return SourceUpdateResult(
                    "skipped",
                    "当前分支包含尚未推送的提交，已跳过自动更新。",
                )
            return SourceUpdateResult(
                "skipped",
                "本地分支与上游已经分叉，已跳过自动更新。",
            )

        # Recheck immediately before changing the checkout to avoid overwriting a concurrent edit.
        if _git(root, "status", "--porcelain", "--untracked-files=normal").stdout.strip():
            return SourceUpdateResult(
                "skipped",
                "检查更新期间源码发生了变化，已跳过自动更新。",
            )
        _git(root, "merge", "--ff-only", "--quiet", "@{upstream}")
        new_revision = _git(root, "rev-parse", "HEAD").stdout.strip()
        _record_source_update_check(root, new_revision, timestamp)
        return SourceUpdateResult(
            "updated",
            f"已更新源码：{local_revision[:7]} -> {new_revision[:7]}。",
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return SourceUpdateResult("failed", "暂时无法检查更新，将继续启动当前版本。")


def _installation_healthy(
    python: Path,
    root: Path,
    *,
    check_dependencies: bool = True,
) -> bool:
    if not python.is_file():
        return False
    imports = ", ".join(REQUIRED_IMPORTS)
    try:
        _run(
            [python, "-c", f"import {imports}; import tools.cli"],
            cwd=root,
        )
        if check_dependencies:
            _run([python, "-m", "pip", "check"], cwd=root)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def ensure_runtime(root: Path) -> Path:
    installed_root = Path(sys.prefix).resolve()
    if root.resolve() == installed_root and not (root / "pyproject.toml").is_file():
        installed_python = Path(sys.executable).absolute()
        if _installation_healthy(installed_python, root, check_dependencies=False):
            print("[OpenWrite] 已安装环境与依赖已就绪。")
            return installed_python
        raise LauncherError("当前 OpenWrite 安装不完整，请重新安装后再启动。")

    runtime = runtime_directory(root)
    python = runtime_python(runtime)
    stamp_path = runtime / ".openwrite-dependencies.json"
    fingerprint = dependency_fingerprint(root)
    stamp = _read_stamp(stamp_path)
    if stamp.get("fingerprint") == fingerprint and _installation_healthy(python, root):
        print("[OpenWrite] 运行环境与依赖已就绪。")
        return python

    if not python.is_file() or not _installation_healthy(
        python, root, check_dependencies=False
    ):
        print(f"[OpenWrite] 正在创建独立运行环境：{runtime}")
        runtime.parent.mkdir(parents=True, exist_ok=True)
        if runtime.exists():
            shutil.rmtree(runtime)
        try:
            _run([sys.executable, "-m", "venv", runtime], cwd=root)
        except (OSError, subprocess.CalledProcessError) as exc:
            shutil.rmtree(runtime, ignore_errors=True)
            raise LauncherError("无法创建 Python 虚拟环境，请确认当前 Python 包含 venv。") from exc

    print("[OpenWrite] 正在检查并下载所需依赖，首次运行可能需要几分钟……")
    try:
        _run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip>=23",
                "setuptools",
                "wheel",
            ],
            cwd=root,
        )
        _run([python, "-m", "pip", "install", "--editable", root], cwd=root)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LauncherError(
            "依赖下载或安装失败。请检查网络、代理和磁盘空间后重新双击启动。"
        ) from exc
    if not _installation_healthy(python, root):
        raise LauncherError("依赖安装完成但环境自检未通过，请重新运行启动器。")
    stamp_path.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("[OpenWrite] 依赖安装与自检完成。")
    return python


def _read_stamp(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_openwrite_server(port: int) -> bool:
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/health")
    try:
        with urllib.request.urlopen(request, timeout=0.35) as response:
            server = str(response.headers.get("Server") or "")
            payload = json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ):
        return False
    return server.startswith("OpenWriteStudio/") and payload == {"ok": True}


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def select_port(preferred: int) -> tuple[int, bool]:
    if _is_openwrite_server(preferred):
        return preferred, True
    for port in range(preferred, preferred + PORT_SCAN_LIMIT):
        if _port_available(port):
            return port, False
    raise LauncherError(
        f"端口 {preferred}-{preferred + PORT_SCAN_LIMIT - 1} 均被占用，请关闭相关程序后重试。"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenWrite 一键启动器")
    parser.add_argument("--check-only", action="store_true", help="只检查环境，不启动 Studio")
    parser.add_argument("--debug", action="store_true", help="启用 Studio debug 日志")
    parser.add_argument("--project", help="直接打开指定作品目录")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="首选端口")
    update_group = parser.add_mutually_exclusive_group()
    update_group.add_argument(
        "--update",
        action="store_true",
        help="忽略检查间隔，立即检查源码更新",
    )
    update_group.add_argument(
        "--no-update",
        action="store_true",
        help="本次启动不检查源码更新",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if sys.version_info < MIN_PYTHON:
        print("[OpenWrite] 需要 Python 3.10 或更高版本。")
        return 2
    root = repository_root()
    try:
        if not args.no_update:
            update = check_for_source_update(root, force=args.update)
            if update.message:
                print(f"[OpenWrite] {update.message}")
        python = ensure_runtime(root)
        if args.check_only:
            print(f"[OpenWrite] 环境检查通过：{python}")
            return 0
        port, already_running = select_port(args.port)
        url = f"http://127.0.0.1:{port}/"
        if already_running:
            print(f"[OpenWrite] Studio 已在运行：{url}")
            webbrowser.open(url)
            return 0
        command: list[str | os.PathLike[str]] = [
            python,
            "-m",
            "tools.cli",
            "studio",
            "--port",
            str(port),
        ]
        if args.project:
            command.extend(["--project", str(Path(args.project).expanduser())])
        if args.debug:
            command.append("--debug")
        print(f"[OpenWrite] 正在启动 Studio：{url}")
        return _run(command, cwd=root, check=False).returncode
    except LauncherError as exc:
        print(f"\n[OpenWrite] 启动失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
