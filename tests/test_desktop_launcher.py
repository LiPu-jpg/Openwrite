import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import desktop_launcher


def test_dependency_fingerprint_changes_with_project_metadata(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pyyaml\n", encoding="utf-8")
    before = desktop_launcher.dependency_fingerprint(tmp_path)

    (tmp_path / "requirements.txt").write_text("pyyaml\npydantic\n", encoding="utf-8")

    assert desktop_launcher.dependency_fingerprint(tmp_path) != before


def test_runtime_directory_is_separate_for_macos_and_windows(tmp_path: Path):
    mac = desktop_launcher.runtime_directory(tmp_path, platform_name="darwin", version_info=(3, 12))
    windows = desktop_launcher.runtime_directory(
        tmp_path, platform_name="win32", version_info=(3, 12)
    )

    assert mac.name == "macos-py3.12"
    assert windows.name == "windows-py3.12"
    assert desktop_launcher.runtime_python(mac, platform_name="darwin").name == "python"
    assert desktop_launcher.runtime_python(windows, platform_name="win32").name == "python.exe"


def test_select_port_reuses_openwrite_or_skips_busy_port(monkeypatch):
    monkeypatch.setattr(desktop_launcher, "_is_openwrite_server", lambda port: port == 4567)
    assert desktop_launcher.select_port(4567) == (4567, True)

    monkeypatch.setattr(desktop_launcher, "_is_openwrite_server", lambda port: False)
    monkeypatch.setattr(desktop_launcher, "_port_available", lambda port: port == 4569)
    assert desktop_launcher.select_port(4567) == (4569, False)


def test_ensure_runtime_skips_install_when_stamp_and_environment_are_healthy(
    tmp_path: Path, monkeypatch
):
    runtime = desktop_launcher.runtime_directory(tmp_path)
    python = desktop_launcher.runtime_python(runtime)
    python.parent.mkdir(parents=True)
    python.touch()
    fingerprint = desktop_launcher.dependency_fingerprint(tmp_path)
    (runtime / ".openwrite-dependencies.json").write_text(
        '{"fingerprint": "' + fingerprint + '"}\n', encoding="utf-8"
    )
    commands = []

    monkeypatch.setattr(desktop_launcher, "_installation_healthy", lambda *_: True)
    monkeypatch.setattr(desktop_launcher, "_run", lambda *args, **kwargs: commands.append(args))

    assert desktop_launcher.ensure_runtime(tmp_path) == python
    assert commands == []


def test_ensure_runtime_creates_and_installs_missing_environment(tmp_path: Path, monkeypatch):
    runtime = desktop_launcher.runtime_directory(tmp_path)
    python = desktop_launcher.runtime_python(runtime)
    commands: list[list[str]] = []

    def fake_run(command, *, cwd, check=True):
        rendered = [str(item) for item in command]
        commands.append(rendered)
        if rendered[1:3] == ["-m", "venv"]:
            python.parent.mkdir(parents=True)
            python.touch()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(desktop_launcher, "_run", fake_run)
    monkeypatch.setattr(desktop_launcher, "_installation_healthy", lambda *args, **kwargs: True)

    assert desktop_launcher.ensure_runtime(tmp_path) == python
    assert commands[0][1:3] == ["-m", "venv"]
    assert commands[1][1:4] == ["-m", "pip", "install"]
    assert commands[2][1:4] == ["-m", "pip", "install"]
    assert "--editable" in commands[2]
    assert (runtime / ".openwrite-dependencies.json").is_file()


def test_ensure_runtime_rebuilds_corrupt_existing_environment(tmp_path: Path, monkeypatch):
    runtime = desktop_launcher.runtime_directory(tmp_path)
    python = desktop_launcher.runtime_python(runtime)
    python.parent.mkdir(parents=True)
    python.touch()
    commands: list[list[str]] = []

    def fake_run(command, *, cwd, check=True):
        rendered = [str(item) for item in command]
        commands.append(rendered)
        if rendered[1:3] == ["-m", "venv"]:
            python.parent.mkdir(parents=True)
            python.touch()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(desktop_launcher, "_run", fake_run)
    monkeypatch.setattr(
        desktop_launcher,
        "_installation_healthy",
        lambda _python, _root, *, check_dependencies=True: check_dependencies,
    )

    assert desktop_launcher.ensure_runtime(tmp_path) == python
    assert commands[0][1:3] == ["-m", "venv"]
    assert runtime.is_dir()

def test_double_click_launchers_are_present_and_use_shared_bootstrap():
    root = Path(__file__).parent.parent
    mac = (root / "启动 OpenWrite.command").read_text(encoding="utf-8")
    windows = (root / "启动 OpenWrite.bat").read_text(encoding="utf-8")

    assert "tools/desktop_launcher.py" in mac
    assert "tools\\desktop_launcher.py" in windows
    assert "Python 3.10" in mac
    assert "Python 3.10" in windows
    assert '"%~1" -c' in windows
    assert "launch_status=$?" in mac
    assert " -u " in mac
    assert " -u " in windows
    assert "-m tools.desktop_launcher" in mac
    assert "-m tools.desktop_launcher" in windows


def test_installed_launcher_reuses_the_active_environment(monkeypatch) -> None:
    health_checks = []
    monkeypatch.setattr(
        desktop_launcher,
        "_installation_healthy",
        lambda *args, **kwargs: health_checks.append((args, kwargs)) or True,
    )

    assert (
        desktop_launcher.ensure_runtime(Path(desktop_launcher.sys.prefix))
        == Path(desktop_launcher.sys.executable).absolute()
    )
    assert health_checks[0][1] == {"check_dependencies": False}


def test_installation_health_can_skip_pip_check(tmp_path: Path, monkeypatch) -> None:
    python = tmp_path / "python"
    python.touch()
    commands = []
    monkeypatch.setattr(
        desktop_launcher,
        "_run",
        lambda command, **_: commands.append([str(item) for item in command]),
    )

    assert desktop_launcher._installation_healthy(python, tmp_path, check_dependencies=False)
    assert len(commands) == 1
    assert commands[0][1] == "-c"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_repositories(tmp_path: Path) -> tuple[Path, Path]:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", str(seed))
    _git(seed, "config", "user.name", "OpenWrite Test")
    _git(seed, "config", "user.email", "test@openwrite.local")
    (seed / ".gitignore").write_text(".openwrite-runtime/\n", encoding="utf-8")
    (seed / "pyproject.toml").write_text("[project]\nname='openwrite-test'\n", encoding="utf-8")
    (seed / "version.txt").write_text("one\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "initial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "HEAD")
    _git(tmp_path, "clone", str(remote), str(checkout))
    return seed, checkout


def test_source_update_fast_forwards_clean_checkout(tmp_path: Path) -> None:
    seed, checkout = _source_repositories(tmp_path)
    (seed / "version.txt").write_text("two\n", encoding="utf-8")
    _git(seed, "add", "version.txt")
    _git(seed, "commit", "-m", "update")
    _git(seed, "push")

    result = desktop_launcher.check_for_source_update(checkout, force=True, now=1000)

    assert result.status == "updated"
    assert (checkout / "version.txt").read_text(encoding="utf-8") == "two\n"
    assert (_git(checkout, "status", "--porcelain")) == ""


def test_source_update_preserves_local_changes(tmp_path: Path) -> None:
    _, checkout = _source_repositories(tmp_path)
    (checkout / "version.txt").write_text("local\n", encoding="utf-8")

    result = desktop_launcher.check_for_source_update(checkout, force=True, now=1000)

    assert result.status == "skipped"
    assert "本地修改" in result.message
    assert (checkout / "version.txt").read_text(encoding="utf-8") == "local\n"


def test_source_update_preserves_unpushed_commit(tmp_path: Path) -> None:
    _, checkout = _source_repositories(tmp_path)
    _git(checkout, "config", "user.name", "OpenWrite Test")
    _git(checkout, "config", "user.email", "test@openwrite.local")
    (checkout / "version.txt").write_text("local commit\n", encoding="utf-8")
    _git(checkout, "add", "version.txt")
    _git(checkout, "commit", "-m", "local update")
    local_revision = _git(checkout, "rev-parse", "HEAD")

    result = desktop_launcher.check_for_source_update(checkout, force=True, now=1000)

    assert result.status == "skipped"
    assert "尚未推送" in result.message
    assert _git(checkout, "rev-parse", "HEAD") == local_revision


def test_source_update_ignores_non_git_directory(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='download'\n", encoding="utf-8")

    result = desktop_launcher.check_for_source_update(tmp_path, force=True, now=1000)

    assert result.status == "unavailable"
    assert "Git 源码副本" in result.message
    assert not (tmp_path / ".openwrite-runtime").exists()


def test_source_update_uses_daily_check_stamp(tmp_path: Path, monkeypatch) -> None:
    _, checkout = _source_repositories(tmp_path)
    first = desktop_launcher.check_for_source_update(checkout, force=True, now=1000)
    commands = []
    real_git = desktop_launcher._git

    def recording_git(root, *args):
        commands.append(args)
        return real_git(root, *args)

    monkeypatch.setattr(desktop_launcher, "_git", recording_git)
    second = desktop_launcher.check_for_source_update(checkout, now=1001)

    assert first.status == "current"
    assert second.status == "recent"
    assert not any(args and args[0] == "fetch" for args in commands)


def test_source_update_network_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    _, checkout = _source_repositories(tmp_path)
    real_git = desktop_launcher._git

    def failing_fetch(root, *args):
        if args and args[0] == "fetch":
            raise subprocess.TimeoutExpired(["git", "fetch"], 1)
        return real_git(root, *args)

    monkeypatch.setattr(desktop_launcher, "_git", failing_fetch)

    result = desktop_launcher.check_for_source_update(checkout, force=True, now=1000)

    assert result.status == "failed"
    assert "继续启动" in result.message


def test_update_flags_are_mutually_exclusive() -> None:
    parser = desktop_launcher.build_parser()

    assert parser.parse_args(["--update"]).update is True
    assert parser.parse_args(["--no-update"]).no_update is True
    with pytest.raises(SystemExit):
        parser.parse_args(["--update", "--no-update"])
