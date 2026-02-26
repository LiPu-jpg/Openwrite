"""CLI integration tests."""

import os
import subprocess
import tempfile
from pathlib import Path

import yaml


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
        profile_file = (
            project_dir
            / "data"
            / "novels"
            / "test_novel"
            / "characters"
            / "profiles"
            / "char_001.md"
        )
        assert profile_file.exists()

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

        note_result = run_cli(
            [
                "character-mutate",
                "李逍遥",
                "--chapter",
                "ch_001",
                "--note",
                "在城门口与守卫短暂对话",
                "--novel-id",
                "test_novel",
            ],
            project_dir,
        )
        assert note_result.returncode == 0

        query_result = run_cli(
            ["character-query", "李逍遥", "--novel-id", "test_novel"], project_dir
        )
        assert query_result.returncode == 0
        assert "李逍遥" in query_result.stdout
        assert "神秘玉佩" in query_result.stdout
        assert "动态档案" in query_result.stdout

        profile_result = run_cli(
            [
                "character-profile",
                "李逍遥",
                "--preview-lines",
                "2",
                "--novel-id",
                "test_novel",
            ],
            project_dir,
        )
        assert profile_result.returncode == 0
        assert "char_001.md" in profile_result.stdout

        timeline_result = run_cli(
            ["character-query", "李逍遥", "--timeline", "--novel-id", "test_novel"],
            project_dir,
        )
        assert timeline_result.returncode == 0
        assert "在城门口与守卫短暂对话" in timeline_result.stdout

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

        chapter_file = (
            project_dir
            / "data"
            / "novels"
            / "test_novel"
            / "outline"
            / "chapters"
            / "ch_003.md"
        )
        chapter_file.write_text(
            "# ch_003\n\n"
            "<!--fs id=f001 weight=9 layer=主线 target=ch_010-->\n"
            "主角得到玉佩线索\n"
            "<!--/fs-->\n"
            "<!--char id=char_001 mutation=\"acquire:神秘玉佩\"-->\n"
            "主角收下玉佩\n"
            "<!--/char-->\n"
            "<!--scene id=s_003 tension=7 emotion=紧张-->\n"
            "战斗一触即发\n"
            "<!--/scene-->\n",
            encoding="utf-8",
        )

        fs_result = run_cli(
            [
                "foreshadowing-add",
                "f001",
                "--content",
                "玉佩线索",
                "--weight",
                "9",
                "--layer",
                "主线",
                "--target-chapter",
                "ch_010",
                "--novel-id",
                "test_novel",
            ],
            project_dir,
        )
        assert fs_result.returncode == 0

        world_entity_result = run_cli(
            [
                "world-entity-add",
                "loc_qingyun",
                "青云镇",
                "--type",
                "location",
                "--novel-id",
                "test_novel",
            ],
            project_dir,
        )
        assert world_entity_result.returncode == 0

        world_entity_result_2 = run_cli(
            [
                "world-entity-add",
                "faction_shushan",
                "蜀山派",
                "--type",
                "faction",
                "--novel-id",
                "test_novel",
            ],
            project_dir,
        )
        assert world_entity_result_2.returncode == 0

        world_relation_result = run_cli(
            [
                "world-relation-add",
                "--source",
                "faction_shushan",
                "--target",
                "loc_qingyun",
                "--relation",
                "protects",
                "--novel-id",
                "test_novel",
            ],
            project_dir,
        )
        assert world_relation_result.returncode == 0

        world_list_result = run_cli(["world-list", "--novel-id", "test_novel"], project_dir)
        assert world_list_result.returncode == 0
        assert "青云镇" in world_list_result.stdout

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
        assert "逻辑检查通过" in simulate_result.stdout

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
        report_files = list(simulation_log_dir.glob("*_ch_003.yaml"))
        assert report_files
        report_data = yaml.safe_load(report_files[0].read_text(encoding="utf-8"))
        assert "f001" in report_data["context"]["foreshadowing"]
        assert "主角得到玉佩线索" in report_data["context"]["outline"]
        assert "场景数=1" in report_data["context"]["scenes"]
        assert "青云镇" in report_data["context"]["world"]


if __name__ == "__main__":
    test_cli_help()
    test_init_command()
    test_character_commands()
    test_simulate_chapter_command()
    print("\n所有 CLI 测试通过")
