"""Smoke tests for core OpenWrite capabilities."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

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
<!--fs-recover ref=f001-->
玉佩真相揭开
<!--/fs-recover-->
<!--char id=char_001 mutation="acquire:神秘玉佩"-->
主角收下玉佩
<!--/char-->
<!--scene id=s_001 tension=8 emotion=紧张-->
夜战爆发
<!--/scene-->
"""

    parser = MarkdownAnnotationParser()
    result = parser.parse_all(sample)
    assert len(result["foreshadowings"]) == 1
    assert len(result["recovers"]) == 1
    assert len(result["characters"]) == 1
    assert len(result["scenes"]) == 1
    assert result["recovers"][0]["attributes"]["ref"] == "f001"
    assert result["characters"][0]["attributes"]["mutation"] == "acquire:神秘玉佩"
    assert result["scenes"][0]["attributes"]["tension"] == "8"
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


def test_world_graph_manager():
    from world_graph_manager import WorldGraphManager

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = WorldGraphManager(project_dir=Path(tmpdir), novel_id="my_novel")
        manager.upsert_entity(
            entity_id="faction_han",
            name="雨城韩氏",
            entity_type="faction",
            tags=["主角方"],
        )
        manager.upsert_entity(
            entity_id="city_rain",
            name="雨城",
            entity_type="location",
        )
        manager.add_relation(
            source_id="faction_han",
            target_id="city_rain",
            relation="located_in",
            weight=5,
        )
        summary = manager.summary()
        assert "雨城韩氏" in summary
        check = manager.check_conflicts()
        assert check["is_valid"] is True


def test_character_state_manager():
    from character_state_manager import CharacterStateManager

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        manager = CharacterStateManager(project_dir=project_dir, novel_id="my_novel")
        card = manager.create_character("李逍遥", tier="主角")
        assert card.static.id == "char_001"
        profile_file = (
            project_dir
            / "data"
            / "novels"
            / "my_novel"
            / "characters"
            / "profiles"
            / "char_001.md"
        )
        assert profile_file.exists()
        excerpt = manager.get_profile_excerpt(name="李逍遥", max_chars=60)
        assert "【姓名" in excerpt

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
        manager.apply_mutation(
            name="李逍遥",
            chapter_id="ch_002",
            note="与旧友在茶馆交换情报",
        )

        rebuilt = manager.rebuild_state(name="李逍遥", until_chapter="ch_001")
        assert "神秘玉佩" in rebuilt.items
        assert rebuilt.location == "未知"

        current = manager.rebuild_state(name="李逍遥")
        assert current.location == "青云镇"
        assert current.realm == "凡人"
        timeline = manager.get_timeline(name="李逍遥")
        assert timeline[-1].action is None
        assert timeline[-1].note == "与旧友在茶馆交换情报"


def test_cli_help():
    result = subprocess.run(
        ["python3", "-m", "tools.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "OpenWrite" in result.stdout


def test_lore_checker_structured_rules():
    from agents.lore_checker import LoreCheckerAgent
    from character_state_manager import CharacterStateManager

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        manager = CharacterStateManager(project_dir=project_dir, novel_id="my_novel")
        manager.create_character("李逍遥", tier="主角")
        checker = LoreCheckerAgent()

        chapter_annotations = {
            "foreshadowings": [],
            "recovers": [],
            "characters": [
                {"attributes": {"id": "char_001", "mutation": "use:回气丹"}, "content": ""}
            ],
            "scenes": [{"attributes": {"id": "s_001", "tension": "11", "emotion": "紧张"}}],
        }
        result = checker.check_draft(
            draft="这一段里有冲突",
            forbidden=[],
            required=["冲突"],
            chapter_annotations=chapter_annotations,
            character_state_manager=manager,
            strict=True,
        )
        assert any("tension 超出范围" in msg for msg in result.errors)
        assert any("尝试使用不存在/不足物品" in msg for msg in result.errors)

        non_strict = checker.check_draft(
            draft="这一段里有冲突",
            forbidden=[],
            required=["冲突"],
            chapter_annotations=chapter_annotations,
            character_state_manager=manager,
            strict=False,
        )
        assert not non_strict.errors
        assert any("tension 超出范围" in msg for msg in non_strict.warnings)


def test_agent_simulator():
    from agents.simulator import AgentSimulator
    from graph.foreshadowing_dag import ForeshadowingDAGManager
    from world_graph_manager import WorldGraphManager

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

        profile_file = (
            novel_root
            / "data"
            / "novels"
            / "my_novel"
            / "characters"
            / "profiles"
            / "char_001.md"
        )
        profile_file.write_text(
            "# 李逍遥 动态档案\n【特质：九阴凝幽气】\n",
            encoding="utf-8",
        )

        chapter_file = (
            novel_root
            / "data"
            / "novels"
            / "my_novel"
            / "outline"
            / "chapters"
            / "ch_001.md"
        )
        chapter_file.write_text(
            "# ch_001\n\n"
            "<!--fs id=f001 weight=9 layer=主线 target=ch_010-->\n"
            "玉佩线索出现\n"
            "<!--/fs-->\n"
            "<!--char id=char_001 mutation=\"acquire:神秘玉佩\"-->\n"
            "主角获得新道具\n"
            "<!--/char-->\n"
            "<!--scene id=s_001 tension=8 emotion=紧张-->\n"
            "夜战爆发\n"
            "<!--/scene-->\n",
            encoding="utf-8",
        )

        dag_manager = ForeshadowingDAGManager(project_dir=novel_root, novel_id="my_novel")
        dag_manager.create_node(
            node_id="f001",
            content="玉佩线索",
            weight=9,
            layer="主线",
            created_at="ch_001",
            target_chapter="ch_010",
        )
        world_manager = WorldGraphManager(project_dir=novel_root, novel_id="my_novel")
        world_manager.upsert_entity(
            entity_id="loc_qingyun",
            name="青云镇",
            entity_type="location",
            description="主角早期重要据点",
        )
        world_manager.upsert_entity(
            entity_id="faction_shushan",
            name="蜀山派",
            entity_type="faction",
        )
        world_manager.add_relation(
            source_id="faction_shushan",
            target_id="loc_qingyun",
            relation="protects",
            weight=6,
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
        assert result.rewrite_attempts == 0

        report = yaml.safe_load(result.report_file.read_text(encoding="utf-8"))
        assert "f001" in report["context"]["foreshadowing"]
        assert "玉佩线索出现" in report["context"]["outline"]
        assert "场景数=1" in report["context"]["scenes"]
        assert "九阴凝幽气" in report["context"]["characters"]
        assert "青云镇" in report["context"]["world"]
        assert len(report["chapter_annotations"]["scenes"]) == 1
        assert report["lore_checker"]["attempts"][0]["passed"] is True

        rewrite_result = simulator.simulate_chapter(
            chapter_id="ch_001",
            objective="推进主线",
            forbidden=["冲突"],
            required=[],
            use_stylist=False,
            max_rewrites=1,
        )
        assert rewrite_result.passed is True
        assert rewrite_result.rewrite_attempts == 1
        rewrite_report = yaml.safe_load(
            rewrite_result.report_file.read_text(encoding="utf-8")
        )
        assert len(rewrite_report["lore_checker"]["attempts"]) >= 2
        assert rewrite_report["lore_checker"]["attempts"][0]["passed"] is False
        assert rewrite_report["lore_checker"]["attempts"][-1]["passed"] is True


def run_all_tests() -> bool:
    test_markdown_parser()
    test_foreshadowing_dag()
    test_foreshadowing_checker()
    test_world_graph_manager()
    test_character_state_manager()
    test_cli_help()
    test_lore_checker_structured_rules()
    test_agent_simulator()
    return True


if __name__ == "__main__":
    ok = run_all_tests()
    print("✅ 所有测试通过!" if ok else "❌ 测试失败")
    sys.exit(0 if ok else 1)
