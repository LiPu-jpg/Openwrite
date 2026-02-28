"""Tests for skills/style/tools/."""

import tempfile
from pathlib import Path

import yaml

from skills.style.tools import (
    StyleComposer,
    StyleExtractor,
    StyleInitializer,
    create_default_answers,
)


class TestStyleInitializer:
    """测试 StyleInitializer。"""

    def test_load_questions_config(self, tmp_path: Path) -> None:
        """测试加载问询配置。"""
        # 创建配置文件
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_content = """
questions:
  - id: tone
    question: "基调？"
    options:
      - value: "轻松"
        style_hints:
          humor: "high"
"""
        (config_dir / "style_questions.yaml").write_text(config_content)

        initializer = StyleInitializer(tmp_path)
        config = initializer.load_questions_config()

        assert "questions" in config
        assert len(config["questions"]) == 1
        assert config["questions"][0]["id"] == "tone"

    def test_process_answers(self, tmp_path: Path) -> None:
        """测试处理答案。"""
        # 创建配置
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_content = """
questions:
  - id: tone
    question: "基调？"
    options:
      - value: "轻松幽默"
        style_hints:
          humor: "high"
          modern_slang: "high"
  - id: pacing
    question: "节奏？"
    options:
      - value: "快节奏"
        style_hints:
          paragraph_length: "short"
          short_paragraph_ratio: 0.6
"""
        (config_dir / "style_questions.yaml").write_text(config_content)

        initializer = StyleInitializer(tmp_path)
        initializer.load_questions_config()

        answers = {"tone": "轻松幽默", "pacing": "快节奏"}
        hints = initializer.process_answers(answers)

        assert hints["humor"] == "high"
        assert hints["modern_slang"] == "high"
        assert hints["paragraph_length"] == "short"
        assert hints["short_paragraph_ratio"] == 0.6

    def test_generate_fingerprint(self, tmp_path: Path) -> None:
        """测试生成风格指纹。"""
        # 创建配置
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "style_questions.yaml").write_text("questions: []")

        initializer = StyleInitializer(tmp_path)
        initializer.load_questions_config()

        answers = {
            "tone": "轻松幽默",
            "pacing": "快节奏",
            "dialogue_ratio": "平衡",
            "reference": "无参考",
        }

        fingerprint = initializer.generate_fingerprint("test_novel", answers)

        assert fingerprint["meta"]["name"] == "test_novel专属风格"
        assert fingerprint["core"]["tone"] == "轻松幽默"
        assert "shared_craft" in fingerprint
        assert "banned" in fingerprint

    def test_save_fingerprint(self, tmp_path: Path) -> None:
        """测试保存风格指纹。"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "style_questions.yaml").write_text("questions: []")

        initializer = StyleInitializer(tmp_path)
        initializer.load_questions_config()

        fingerprint = initializer.generate_fingerprint(
            "test_novel", {"tone": "严肃正剧"}
        )
        path = initializer.save_fingerprint("test_novel", fingerprint)

        assert path.exists()
        assert "test_novel" in str(path)

        # 验证内容
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        assert loaded["meta"]["name"] == "test_novel专属风格"


class TestStyleExtractor:
    """测试 StyleExtractor。"""

    def test_extract_basic(self, tmp_path: Path) -> None:
        """测试基本提取。"""
        extractor = StyleExtractor(tmp_path)

        text = "这是一段测试文本。"
        report = extractor.extract(text, "test_source")

        assert report.source_id == "test_source"
        assert report.word_count > 0

    def test_extract_dialogue(self, tmp_path: Path) -> None:
        """测试对话提取。"""
        extractor = StyleExtractor(tmp_path)

        # 使用直角引号
        text = "「你好，请问怎么走？」我问道。「一直往前走就行了。」他回答。「谢谢！」"
        report = extractor.extract(text)

        # 应该检测到对话
        assert len(report.dialogue_features) > 0

    def test_to_dict(self, tmp_path: Path) -> None:
        """测试转换为字典。"""
        extractor = StyleExtractor(tmp_path)

        text = "测试文本。"
        report = extractor.extract(text)

        result = report.to_dict()

        assert "source" in result
        assert "extraction" in result
        assert result["source"]["text_id"] == "unknown"


class TestStyleComposer:
    """测试 StyleComposer。"""

    def test_load_craft_layer(self, tmp_path: Path) -> None:
        """测试加载通用技法层。"""
        # 创建 humanization.yaml
        craft_dir = tmp_path / "craft"
        craft_dir.mkdir()
        humanization = {
            "banned_words": ["不禁", "心中涌起"],
            "ai_phrases": ["这一刻"],
        }
        with open(craft_dir / "humanization.yaml", "w", encoding="utf-8") as f:
            yaml.dump(humanization, f)

        composer = StyleComposer(tmp_path)
        layer = composer.load_craft_layer()

        assert layer.name == "通用技法"
        assert "humanization" in layer.content
        assert "banned_words" in layer.content["humanization"]

    def test_compose_empty(self, tmp_path: Path) -> None:
        """测试空合成。"""
        composer = StyleComposer(tmp_path)
        composed = composer.compose("test_novel")

        assert composed.novel_id == "test_novel"
        assert composed.style_id == "test_novel"
        assert "craft/" in composed.sources

    def test_to_markdown(self, tmp_path: Path) -> None:
        """测试转换为 Markdown。"""
        composer = StyleComposer(tmp_path)
        composed = composer.compose("test_novel")

        md = composed.to_markdown()

        assert "# 最终风格文档" in md
        assert "test_novel" in md
        assert "硬性约束" in md
        assert "风格约束" in md
        assert "可选技法" in md

    def test_save_composed(self, tmp_path: Path) -> None:
        """测试保存合成结果。"""
        composer = StyleComposer(tmp_path)
        composed = composer.compose("test_novel")
        path = composer.save_composed(composed)

        assert path.exists()
        assert "test_novel_final.md" in str(path)

        # 检查 YAML 版本
        yaml_path = path.parent / "test_novel_final.yaml"
        assert yaml_path.exists()


class TestCreateDefaultAnswers:
    """测试 create_default_answers。"""

    def test_returns_dict(self) -> None:
        """测试返回字典。"""
        answers = create_default_answers()

        assert isinstance(answers, dict)
        assert "tone" in answers
        assert "pacing" in answers
        assert "dialogue_ratio" in answers
