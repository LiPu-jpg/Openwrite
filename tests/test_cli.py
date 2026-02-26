"""CLI integration tests."""

import os
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        ["python3", "-m", "tools.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


def test_cli_help():
    result = run_cli(["--help"], REPO_ROOT)
    assert result.returncode == 0
    assert "OpenWrite" in result.stdout


def test_init_command():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        result = run_cli(["init", "test_novel"], tmpdir_path)
        assert result.returncode == 0

        novel_dir = tmpdir_path / "test_novel"
        assert novel_dir.exists()
        assert (novel_dir / "data" / "novels" / "test_novel").exists()


def test_character_commands():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        init_result = run_cli(["init", "test_novel"], tmpdir_path)
        assert init_result.returncode == 0

        project_dir = tmpdir_path / "test_novel"
        create_result = run_cli(
            ["character-create", "李逍遥", "--tier", "主角", "--novel-id", "test_novel"],
            project_dir,
        )
        assert create_result.returncode == 0

        mutate_result = run_cli(
            [
                "character-mutate",
                "李逍遥",
                "--chapter",
                "ch_001",
                "--change",
                "acquire:神秘玉佩",
                "--reason",
                "山洞探险所得",
                "--novel-id",
                "test_novel",
            ],
            project_dir,
        )
        assert mutate_result.returncode == 0

        query_result = run_cli(
            ["character-query", "李逍遥", "--novel-id", "test_novel"], project_dir
        )
        assert query_result.returncode == 0
        assert "李逍遥" in query_result.stdout
        assert "神秘玉佩" in query_result.stdout

        snapshot_result = run_cli(
            [
                "character-snapshot",
                "李逍遥",
                "--volume-id",
                "vol_001",
                "--chapter-range",
                "ch_001-ch_010",
                "--novel-id",
                "test_novel",
            ],
            project_dir,
        )
        assert snapshot_result.returncode == 0

        snapshot_file = (
            project_dir
            / "data"
            / "novels"
            / "test_novel"
            / "characters"
            / "timeline"
            / "snapshots"
            / "char_001_vol_001.md"
        )
        assert snapshot_file.exists()


def test_simulate_chapter_command():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        init_result = run_cli(["init", "test_novel"], tmpdir_path)
        assert init_result.returncode == 0

        project_dir = tmpdir_path / "test_novel"
        create_result = run_cli(
            ["character-create", "李逍遥", "--tier", "主角", "--novel-id", "test_novel"],
            project_dir,
        )
        assert create_result.returncode == 0

        simulate_result = run_cli(
            [
                "simulate-chapter",
                "--id",
                "ch_003",
                "--objective",
                "推进主线并保持角色一致性",
                "--novel-id",
                "test_novel",
            ],
            project_dir,
        )
        assert simulate_result.returncode == 0
        assert "模拟完成" in simulate_result.stdout

        draft_file = (
            project_dir
            / "data"
            / "novels"
            / "test_novel"
            / "manuscript"
            / "drafts"
            / "ch_003_draft.md"
        )
        assert draft_file.exists()

        simulation_log_dir = project_dir / "logs" / "simulations"
        assert simulation_log_dir.exists()
        assert any(simulation_log_dir.glob("*_ch_003.yaml"))


if __name__ == "__main__":
    test_cli_help()
    test_init_command()
    test_character_commands()
    test_simulate_chapter_command()
    print("\n所有 CLI 测试通过")
