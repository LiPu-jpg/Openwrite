"""Tests for Writing Skill Tools.

测试节拍生成器和草稿生成器的核心功能。
"""

import pytest

from skills.writing.tools import (
    BeatGenerator,
    BeatTemplates,
    DraftGenerator,
    DraftOutput,
    SectionMarkers,
    load_beat_generator,
    load_draft_generator,
)


class TestBeatTemplates:
    """测试节拍模板。"""

    def test_default_templates(self):
        """测试默认模板。"""
        templates = BeatTemplates.default()

        assert len(templates.opening) == 3
        assert len(templates.development) == 4
        assert len(templates.climax) == 2
        assert len(templates.closing) == 2

        # 检查模板包含变量
        assert "{protagonist}" in templates.opening[0]
        assert "{situation}" in templates.opening[0]

    def test_from_yaml(self, tmp_path):
        """测试从 YAML 加载模板。"""
        yaml_content = """
opening:
  - "测试开场模板 {protagonist}"
development:
  - "测试发展模板"
climax:
  - "测试高潮模板"
closing:
  - "测试收束模板"
"""
        yaml_path = tmp_path / "beat_templates.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        templates = BeatTemplates.from_yaml(yaml_path)

        assert len(templates.opening) == 1
        assert templates.opening[0] == "测试开场模板 {protagonist}"
        assert len(templates.development) == 1


class TestSectionMarkers:
    """测试段落标记。"""

    def test_default_markers(self):
        """测试默认标记。"""
        markers = SectionMarkers.default()

        assert markers.scene == "【场景】"
        assert markers.dialogue == "【对话】"
        assert markers.narration == "【叙述】"
        assert markers.internal == "【内心】"
        assert markers.action == "【动作】"
        assert markers.transition == "【转场】"

    def test_from_yaml(self, tmp_path):
        """测试从 YAML 加载标记。"""
        yaml_content = """
scene: "[SCENE]"
dialogue: "[DIALOGUE]"
narration: "[NARRATION]"
internal: "[INTERNAL]"
action: "[ACTION]"
transition: "[TRANSITION]"
"""
        yaml_path = tmp_path / "section_markers.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        markers = SectionMarkers.from_yaml(yaml_path)

        assert markers.scene == "[SCENE]"
        assert markers.dialogue == "[DIALOGUE]"


class TestBeatGenerator:
    """测试节拍生成器。"""

    def test_generate_beats_basic(self):
        """测试基础节拍生成。"""
        generator = BeatGenerator()
        context = {
            "seed": "测试种子",
            "outline": "测试大纲内容",
            "characters": "主角(境界=筑基)",
            "foreshadowing": "暂无",
        }

        beats = generator.generate_beats("ch_001", context)

        # 应该有开场 + 发展(2-4) + 高潮 + 收束
        assert len(beats) >= 5
        assert len(beats) <= 8

        # 检查节拍格式
        assert beats[0].startswith("ch_001 开场：")
        assert any("发展" in beat for beat in beats)
        assert any("高潮" in beat for beat in beats)
        assert any("收束" in beat for beat in beats)

    def test_generate_beats_with_protagonist(self):
        """测试主角名称提取。"""
        generator = BeatGenerator()
        context = {
            "seed": "测试",
            "outline": "",
            "characters": "李逍遥(境界=金丹,位置=蜀山)",
            "foreshadowing": "暂无",
        }

        beats = generator.generate_beats("ch_001", context)

        # 主角名称应该被提取并填入模板
        assert any("李逍遥" in beat for beat in beats)

    def test_generate_beats_with_foreshadowing(self):
        """测试带伏笔的节拍生成。"""
        generator = BeatGenerator()
        context = {
            "seed": "测试",
            "outline": "",
            "characters": "主角(境界=筑基)",
            "foreshadowing": "fs_001(权重=8), fs_002(权重=5)",
        }

        beats = generator.generate_beats("ch_001", context)

        # 应该包含伏笔节拍
        assert any("伏笔" in beat for beat in beats)

    def test_generate_beats_context_richness(self):
        """测试上下文丰富度影响节拍数量。"""
        generator = BeatGenerator()

        # 贫乏上下文
        poor_context = {
            "seed": "测试",
            "outline": "",
            "characters": "暂无",
            "foreshadowing": "暂无",
            "scenes": "未标注",
        }

        # 丰富上下文
        rich_context = {
            "seed": "测试种子悬念",
            "outline": "详细的章节大纲内容",
            "characters": "主角(境界=筑基), 配角(境界=练气)",
            "foreshadowing": "fs_001(权重=7)",
            "scenes": "场景1, 场景2",
            "world": "世界观设定",
        }

        poor_beats = generator.generate_beats("ch_001", poor_context)
        rich_beats = generator.generate_beats("ch_002", rich_context)

        # 丰富上下文应该产生更多发展节拍
        poor_dev = sum(1 for b in poor_beats if "发展" in b)
        rich_dev = sum(1 for b in rich_beats if "发展" in b)

        assert rich_dev >= poor_dev

    def test_extract_setting_from_characters(self):
        """测试从角色提取场景。"""
        generator = BeatGenerator()
        context = {
            "characters": "主角(境界=筑基,位置=蜀山剑阁)",
        }

        setting = generator._extract_setting(context)
        assert setting == "蜀山剑阁"

    def test_extract_obstacle_from_outline(self):
        """测试从大纲提取障碍。"""
        generator = BeatGenerator()

        outline_with_conflict = "本章讲述主角遭遇敌人围攻"
        obstacle = generator._extract_obstacle(outline_with_conflict, "")
        assert "敌人" in obstacle


class TestDraftGenerator:
    """测试草稿生成器。"""

    def test_generate_chapter_rule_based(self):
        """测试规则引擎草稿生成。"""
        beat_gen = BeatGenerator()
        draft_gen = DraftGenerator(beat_generator=beat_gen)

        context = {
            "seed": "测试种子",
            "outline": "测试大纲",
            "characters": "主角(境界=筑基)",
            "foreshadowing": "暂无",
            "scenes": "测试场景",
            "world": "测试世界",
        }

        result = draft_gen.generate_chapter(
            chapter_id="ch_001",
            objective="测试写作目标",
            context=context,
        )

        assert isinstance(result, DraftOutput)
        assert result.chapter_id == "ch_001"
        assert len(result.beat_list) >= 5
        assert len(result.draft) > 100

        # 检查草稿结构
        assert "# ch_001 章节草稿" in result.draft
        assert "## 写作目标" in result.draft
        assert "## 剧情节拍" in result.draft
        assert "## 草稿正文" in result.draft
        assert "【场景】" in result.draft

    def test_generate_draft_with_multiple_characters(self):
        """测试多角色草稿生成。"""
        beat_gen = BeatGenerator()
        draft_gen = DraftGenerator(beat_generator=beat_gen)

        context = {
            "seed": "测试",
            "outline": "",
            "characters": "李逍遥(境界=金丹), 林月如(境界=元婴)",
            "foreshadowing": "暂无",
        }

        result = draft_gen.generate_chapter(
            chapter_id="ch_001",
            objective="测试",
            context=context,
        )

        # 多角色应该产生对话
        assert "【对话】" in result.draft
        assert "李逍遥" in result.draft or "林月如" in result.draft

    def test_rewrite_chapter_rule_based(self):
        """测试规则引擎重写。"""
        beat_gen = BeatGenerator()
        draft_gen = DraftGenerator(beat_generator=beat_gen)

        previous_draft = """# ch_001 章节草稿

## 草稿正文

主角使用了神器，但神器还没获得。
"""

        result = draft_gen.rewrite_chapter(
            chapter_id="ch_001",
            objective="重写测试",
            context={"characters": "主角(境界=筑基)"},
            previous_draft=previous_draft,
            forbidden=["神器"],
            required=["重要道具"],
            errors=["禁用设定: 神器"],
            warnings=["张力均低于阈值"],
            attempt=1,
        )

        assert isinstance(result, DraftOutput)
        assert result.chapter_id == "ch_001"

        # 禁止词应该被替换
        assert "[已规避词]" in result.draft

        # 修订记录应该被添加
        assert "修订记录" in result.draft

    def test_draft_output_metadata(self):
        """测试草稿输出元数据。"""
        beat_gen = BeatGenerator()
        draft_gen = DraftGenerator(beat_generator=beat_gen)

        context = {
            "seed": "测试",
            "characters": "主角(境界=筑基)",
        }

        result = draft_gen.generate_chapter(
            chapter_id="ch_001",
            objective="测试",
            context=context,
        )

        assert "beat_count" in result.metadata
        assert result.metadata["beat_count"] == str(len(result.beat_list))


class TestLoadFunctions:
    """测试加载函数。"""

    def test_load_beat_generator_default(self):
        """测试加载默认节拍生成器。"""
        generator = load_beat_generator()

        assert isinstance(generator, BeatGenerator)
        assert generator.templates is not None

    def test_load_beat_generator_from_yaml(self, tmp_path):
        """测试从 YAML 加载节拍生成器。"""
        yaml_content = """
opening:
  - "自定义开场 {protagonist}"
development:
  - "自定义发展"
climax:
  - "自定义高潮"
closing:
  - "自定义收束"
"""
        templates_path = tmp_path / "beat_templates.yaml"
        templates_path.write_text(yaml_content, encoding="utf-8")

        generator = load_beat_generator(templates_path=templates_path)

        assert generator.templates.opening[0] == "自定义开场 {protagonist}"

    def test_load_draft_generator_default(self):
        """测试加载默认草稿生成器。"""
        generator = load_draft_generator()

        assert isinstance(generator, DraftGenerator)
        assert generator.beat_generator is not None

    def test_load_draft_generator_with_templates(self, tmp_path):
        """测试带自定义模板加载草稿生成器。"""
        templates_content = """
opening: ["测试开场"]
development: ["测试发展"]
climax: ["测试高潮"]
closing: ["测试收束"]
"""
        markers_content = """
scene: "[S]"
dialogue: "[D]"
narration: "[N]"
internal: "[I]"
action: "[A]"
transition: "[T]"
"""
        templates_path = tmp_path / "beat_templates.yaml"
        markers_path = tmp_path / "section_markers.yaml"
        templates_path.write_text(templates_content, encoding="utf-8")
        markers_path.write_text(markers_content, encoding="utf-8")

        generator = load_draft_generator(
            templates_path=str(templates_path),
            markers_path=str(markers_path),
        )

        assert generator.beat_generator.templates.opening[0] == "测试开场"
        assert generator.markers.scene == "[S]"


class TestEdgeCases:
    """测试边界情况。"""

    def test_empty_context(self):
        """测试空上下文。"""
        generator = BeatGenerator()
        beats = generator.generate_beats("ch_001", {})
        # 应该使用默认值生成节拍
        assert len(beats) >= 5
        # 检查任意节拍中包含默认主角名（hash 可能随机选择不同模板）
        assert any("主角" in beat for beat in beats)

    def test_missing_optional_fields(self):
        """测试缺失可选字段。"""
        generator = BeatGenerator()
        context = {
            "seed": "测试",
            # 缺少 outline, characters, foreshadowing
        }

        beats = generator.generate_beats("ch_001", context)

        assert len(beats) >= 5

    def test_chapter_id_deterministic(self):
        """测试相同章节 ID 生成相同节拍。"""
        generator = BeatGenerator()
        context = {
            "seed": "测试",
            "characters": "主角(境界=筑基)",
        }

        beats1 = generator.generate_beats("ch_001", context)
        beats2 = generator.generate_beats("ch_001", context)

        assert beats1 == beats2

    def test_different_chapter_ids_different_beats(self):
        """测试不同章节 ID 生成不同节拍。"""
        generator = BeatGenerator()
        context = {
            "seed": "测试",
            "characters": "主角(境界=筑基)",
        }

        beats1 = generator.generate_beats("ch_001", context)
        beats2 = generator.generate_beats("ch_002", context)

        # 节拍内容应该不同（因为 hash 不同）
        # 但结构相同
        assert len(beats1) == len(beats2)
        assert beats1 != beats2
