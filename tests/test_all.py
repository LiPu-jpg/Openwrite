"""Smoke tests for core OpenWrite capabilities."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))


def test_markdown_parser():
    from parsers.markdown_parser import MarkdownAnnotationParser

    sample = """
# 第一章

<!--伏笔 weight=9 id=f001 layer=主线-->
主角发现了神秘玉佩
<!--/伏笔-->
"""

    parser = MarkdownAnnotationParser()
    result = parser.parse_all(sample)
    assert len(result["foreshadowings"]) == 1
    attrs = parser.parse_attributes("weight=9 id=f001 layer=主线")
    assert attrs.get("id") == "f001"


def test_foreshadowing_dag():
    from graph.foreshadowing_dag import ForeshadowingDAGManager

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ForeshadowingDAGManager(Path(tmpdir))
        created = manager.create_node(
            node_id="test_fs_001",
            content="测试伏笔",
            weight=8,
            layer="支线",
        )
        assert created
        dag = manager._load_dag()
        assert "test_fs_001" in dag.nodes
        assert manager.update_node_status("test_fs_001", "待收")
        stats = manager.get_statistics()
        assert stats["total_nodes"] == 1


def test_foreshadowing_checker():
    from checks.foreshadowing_checker import ForeshadowingChecker

    with tempfile.TemporaryDirectory() as tmpdir:
        checker = ForeshadowingChecker(Path(tmpdir))
        results = checker.check_all()
        assert "errors" in results
        assert "warnings" in results
        assert "statistics" in results


def test_character_state_manager():
    from character_state_manager import CharacterStateManager

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        manager = CharacterStateManager(project_dir=project_dir, novel_id="my_novel")
        card = manager.create_character("李逍遥", tier="主角")
        assert card.static.id == "char_001"

        manager.apply_mutation(
            name="李逍遥",
            chapter_id="ch_001",
            mutation_expr="acquire:神秘玉佩",
            reason="山洞探险所得",
        )
        manager.apply_mutation(
            name="李逍遥",
            chapter_id="ch_002",
            mutation_expr="move:青云镇",
            reason="剧情推进",
        )

        rebuilt = manager.rebuild_state(name="李逍遥", until_chapter="ch_001")
        assert rebuilt.inventory["神秘玉佩"] == 1
        assert rebuilt.location == "未知"

        current = manager.rebuild_state(name="李逍遥")
        assert current.location == "青云镇"


def test_cli_help():
    result = subprocess.run(
        ["python3", "-m", "tools.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "OpenWrite" in result.stdout


def test_agent_simulator():
    from agents.simulator import AgentSimulator

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT)
        subprocess.run(
            ["python3", "-m", "tools.cli", "init", "my_novel"],
            cwd=str(project_dir),
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        novel_root = project_dir / "my_novel"

        subprocess.run(
            [
                "python3",
                "-m",
                "tools.cli",
                "character-create",
                "李逍遥",
                "--novel-id",
                "my_novel",
            ],
            cwd=str(novel_root),
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

        simulator = AgentSimulator(project_dir=novel_root, novel_id="my_novel")
        result = simulator.simulate_chapter(
            chapter_id="ch_001",
            objective="推进主线",
            forbidden=["死人复活"],
            required=["冲突"],
            use_stylist=False,
        )
        assert result.draft_file.exists()
        assert result.report_file.exists()
        assert result.passed is True


def run_all_tests() -> bool:
    test_markdown_parser()
    test_foreshadowing_dag()
    test_foreshadowing_checker()
    test_character_state_manager()
    test_cli_help()
    test_agent_simulator()
    return True


if __name__ == "__main__":
    ok = run_all_tests()
    print("✅ 所有测试通过!" if ok else "❌ 测试失败")
    sys.exit(0 if ok else 1)
