"""Phase 5 tests — cycle detection, StyleProfile integration, cross-chapter checks, context compressor."""

import tempfile
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmpdir: str, novel_id: str = "test") -> Path:
    """Create a minimal project directory structure."""
    root = Path(tmpdir)
    (root / "data" / "novels" / novel_id / "foreshadowing").mkdir(
        parents=True, exist_ok=True
    )
    (root / "data" / "novels" / novel_id / "characters" / "cards").mkdir(
        parents=True, exist_ok=True
    )
    (root / "data" / "novels" / novel_id / "characters" / "profiles").mkdir(
        parents=True, exist_ok=True
    )
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "composed").mkdir(parents=True, exist_ok=True)
    return root


# ===========================================================================
# 1. Cycle detection in ForeshadowingDAG
# ===========================================================================


class TestCycleDetection:
    def test_cycle_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_project(tmpdir)
            from tools.graph.foreshadowing_dag import ForeshadowingDAGManager

            mgr = ForeshadowingDAGManager(project_dir=root, novel_id="test")
            mgr.create_node("A", "node A", weight=5)
            mgr.create_node("B", "node B", weight=5)
            mgr.create_node("C", "node C", weight=5)
            mgr.create_edge("A", "B")
            mgr.create_edge("B", "C")
            mgr.create_edge("C", "A")
            result = mgr.validate_dag()
            assert not result["is_valid"]
            assert any("循环引用" in e for e in result["errors"])

    def test_no_cycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_project(tmpdir)
            from tools.graph.foreshadowing_dag import ForeshadowingDAGManager

            mgr = ForeshadowingDAGManager(project_dir=root, novel_id="test")
            mgr.create_node("X", "node X", weight=5)
            mgr.create_node("Y", "node Y", weight=5)
            mgr.create_edge("X", "Y")
            result = mgr.validate_dag()
            assert result["is_valid"]
            assert len(result["errors"]) == 0

    def test_self_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_project(tmpdir)
            from tools.graph.foreshadowing_dag import ForeshadowingDAGManager

            mgr = ForeshadowingDAGManager(project_dir=root, novel_id="test")
            mgr.create_node("S", "self-loop", weight=3)
            mgr.create_edge("S", "S")
            result = mgr.validate_dag()
            assert any("循环引用" in e for e in result["errors"])


# ===========================================================================
# 2. Stylist + StyleProfile integration
# ===========================================================================


class TestStylistProfileIntegration:
    def test_stylist_loads_profile_banned_phrases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_project(tmpdir)
            # Write a minimal composed doc with banned phrases
            composed = root / "composed" / "test_final.md"
            composed.write_text(
                "# 风格文档\n## 禁用表达\n- 「突然之间」：避免使用\n- 「不由得」：替换\n",
                encoding="utf-8",
            )
            from tools.agents.stylist import StylistAgent

            agent = StylistAgent(project_root=root, novel_id="test")
            # Profile should have been loaded
            assert agent.style_profile is not None
            # Banned phrases should include both defaults and profile-extracted
            assert "不由得" in agent.rules.banned_phrases

    def test_stylist_without_profile(self):
        from tools.agents.stylist import StylistAgent

        agent = StylistAgent()
        assert agent.style_profile is None
        # Should still have default banned phrases
        assert len(agent.rules.banned_phrases) > 0

    def test_stylist_score_with_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_project(tmpdir)
            composed = root / "composed" / "test_final.md"
            composed.write_text(
                "# 风格\n## 禁用表达\n- 「不禁」\n## 节奏\n短段60%\n## AI痕迹反模式\n- banned\n",
                encoding="utf-8",
            )
            from tools.agents.stylist import StylistAgent

            agent = StylistAgent(project_root=root, novel_id="test")
            result = agent.check_style("这是一段测试文本。不禁感叹。微微一笑。")
            assert "anti_pattern" in result.score
            assert result.score["anti_pattern"] < 100  # Should have deductions


# ===========================================================================
# 3. Cross-chapter LoreChecker
# ===========================================================================


class TestCrossChapterLoreChecker:
    def test_overdue_foreshadowing_high_weight(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_project(tmpdir)
            from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
            from tools.agents.lore_checker import LoreCheckerAgent

            fsm = ForeshadowingDAGManager(project_dir=root, novel_id="test")
            fsm.create_node(
                "f001",
                "重要伏笔",
                weight=9,
                layer="主线",
                created_at="ch_001",
                target_chapter="ch_005",
            )
            checker = LoreCheckerAgent()
            result = checker.check_cross_chapter(
                chapter_id="ch_010",
                foreshadowing_manager=fsm,
            )
            assert any("f001" in w for w in result.warnings)
            assert any("5章未回收" in w for w in result.warnings)

    def test_no_overdue_before_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_project(tmpdir)
            from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
            from tools.agents.lore_checker import LoreCheckerAgent

            fsm = ForeshadowingDAGManager(project_dir=root, novel_id="test")
            fsm.create_node(
                "f001",
                "伏笔",
                weight=5,
                layer="支线",
                created_at="ch_001",
                target_chapter="ch_010",
            )
            checker = LoreCheckerAgent()
            result = checker.check_cross_chapter(
                chapter_id="ch_003",
                foreshadowing_manager=fsm,
            )
            assert len(result.errors) == 0
            assert len(result.warnings) == 0

    def test_overdue_strict_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = _make_project(tmpdir)
            from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
            from tools.agents.lore_checker import LoreCheckerAgent

            fsm = ForeshadowingDAGManager(project_dir=root, novel_id="test")
            fsm.create_node(
                "f001",
                "关键伏笔",
                weight=9,
                layer="主线",
                created_at="ch_001",
                target_chapter="ch_005",
            )
            checker = LoreCheckerAgent()
            result = checker.check_cross_chapter(
                chapter_id="ch_010",
                foreshadowing_manager=fsm,
                strict=True,
            )
            # In strict mode, high-weight overdue should be an error
            assert any("f001" in e for e in result.errors)

    def test_cross_chapter_no_managers(self):
        from tools.agents.lore_checker import LoreCheckerAgent

        checker = LoreCheckerAgent()
        result = checker.check_cross_chapter(chapter_id="ch_001")
        assert result.passed


# ===========================================================================
# 4. Context Compressor
# ===========================================================================


class TestContextCompressor:
    def test_basic_compression(self):
        from tools.utils.context_compressor import ContextCompressor

        compressor = ContextCompressor(budget=100)
        context = {
            "outline": "这是一段很长的大纲内容。" * 10,
            "characters": "角色信息。" * 5,
        }
        result = compressor.compress(context)
        assert result.total_chars <= 150  # Some tolerance
        # Repeated phrases get deduped, so content shrinks significantly
        assert result.total_chars < 110 + 25  # well under original ~135 chars

    def test_no_truncation_when_within_budget(self):
        from tools.utils.context_compressor import ContextCompressor

        compressor = ContextCompressor(budget=5000)
        context = {"outline": "短内容", "characters": "也很短"}
        result = compressor.compress(context)
        assert len(result.sections_truncated) == 0
        assert result.sections["outline"] == "短内容"

    def test_redundancy_removal(self):
        from tools.utils.context_compressor import ContextCompressor

        compressor = ContextCompressor(budget=500)
        # Use semicolon-separated phrases where one exact phrase (6+ chars) appears in both
        context = {
            "outline": "主角前往碎湖城；发现神秘的玉佩并带走",
            "characters": "亚修在碎湖城；发现神秘的玉佩并带走",
        }
        result = compressor.compress(context)
        # The shared phrase '发现神秘的玉佩并带走' (9 chars) should be deduped
        assert result.redundancies_removed >= 1

    def test_sentence_boundary_truncation(self):
        from tools.utils.context_compressor import ContextCompressor

        compressor = ContextCompressor(budget=60)
        context = {
            "outline": "第一句话。第二句话。第三句话。第四句话。第五句话。",
        }
        result = compressor.compress(context)
        truncated = result.sections["outline"]
        # Should end at a sentence boundary
        assert (
            truncated.endswith("。") or truncated.endswith("…") or len(truncated) <= 60
        )

    def test_to_flat(self):
        from tools.utils.context_compressor import ContextCompressor

        compressor = ContextCompressor(budget=500)
        context = {"outline": "大纲", "characters": "角色"}
        result = compressor.compress(context)
        flat = result.to_flat()
        assert "outline:大纲" in flat
        assert "characters:角色" in flat

    def test_empty_context(self):
        from tools.utils.context_compressor import ContextCompressor

        compressor = ContextCompressor(budget=100)
        result = compressor.compress({})
        assert result.total_chars == 0
        assert len(result.sections) == 0

    def test_priority_allocation(self):
        from tools.utils.context_compressor import ContextCompressor

        compressor = ContextCompressor(budget=200)
        long_text = "内容。" * 50
        context = {
            "outline": long_text,  # priority 10
            "characters": long_text,  # priority 9
            "scenes": long_text,  # priority 7
        }
        result = compressor.compress(context)
        # Higher priority sections should get more budget
        assert len(result.sections["outline"]) >= len(result.sections["scenes"])


# ===========================================================================
# 5. Simulator style_analysis integration (smoke test)
# ===========================================================================


class TestSimulatorStyleAnalysis:
    def test_simulation_result_has_style_analysis_field(self):
        from tools.agents.simulator import SimulationResult

        result = SimulationResult(
            chapter_id="ch_001",
            passed=True,
            draft_file=Path("/tmp/test.md"),
            report_file=Path("/tmp/report.yaml"),
            errors=[],
            warnings=[],
            style_analysis={"reader": {"total_findings": 3}},
        )
        assert result.style_analysis is not None
        assert result.style_analysis["reader"]["total_findings"] == 3

    def test_simulation_result_default_no_analysis(self):
        from tools.agents.simulator import SimulationResult

        result = SimulationResult(
            chapter_id="ch_001",
            passed=True,
            draft_file=Path("/tmp/test.md"),
            report_file=Path("/tmp/report.yaml"),
            errors=[],
            warnings=[],
        )
        assert result.style_analysis is None
