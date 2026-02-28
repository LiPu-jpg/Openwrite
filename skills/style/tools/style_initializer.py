"""Style Initializer — 通过问询生成作品专属风格指纹。

核心流程：
1. 加载问询问题配置
2. 收集用户答案
3. 合并 style_hints
4. 如有参考作品，提取风格特征
5. 生成 fingerprint.yaml
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class StyleInitializer:
    """风格初始化器，通过问询生成专属风格。"""

    def __init__(self, project_root: Path):
        """初始化风格初始化器。

        Args:
            project_root: 项目根目录
        """
        self.project_root = project_root
        self.config_dir = project_root / "config"
        self.novels_dir = project_root / "novels"
        self.styles_dir = project_root / "styles"
        self.craft_dir = project_root / "craft"

        # 问询问题配置
        self.questions_config: Optional[Dict[str, Any]] = None

    def load_questions_config(self) -> Dict[str, Any]:
        """加载问询问题配置。

        Returns:
            问询问题配置字典
        """
        config_path = self.config_dir / "style_questions.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"问询配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            self.questions_config = yaml.safe_load(f)

        return self.questions_config

    def get_questions(self) -> List[Dict[str, Any]]:
        """获取问询问题列表。

        Returns:
            问题列表，每个问题包含 id, question, description, options
        """
        if not self.questions_config:
            self.load_questions_config()

        return self.questions_config.get("questions", [])

    def process_answers(self, answers: Dict[str, Any]) -> Dict[str, Any]:
        """处理用户答案，生成合并后的 style_hints。

        Args:
            answers: 用户答案字典，key 为问题 id，value 为选项 value

        Returns:
            合并后的 style_hints 字典
        """
        if not self.questions_config:
            self.load_questions_config()

        merged_hints: Dict[str, Any] = {}

        for question in self.questions_config.get("questions", []):
            question_id = question.get("id")
            user_answer = answers.get(question_id)

            if not user_answer:
                continue

            # 查找用户选择的选项
            for option in question.get("options", []):
                if option.get("value") == user_answer:
                    # 合并该选项的 style_hints
                    option_hints = option.get("style_hints", {})
                    merged_hints.update(option_hints)
                    break

        return merged_hints

    def load_reference_style(self, style_id: str) -> Optional[Dict[str, Any]]:
        """加载参考作品的风格特征。

        Args:
            style_id: 参考作品风格 ID

        Returns:
            参考风格特征，如不存在返回 None
        """
        # 尝试加载 fingerprint.yaml
        fingerprint_path = self.styles_dir / style_id / "fingerprint.yaml"
        if fingerprint_path.exists():
            with open(fingerprint_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)

        # 尝试加载 fingerprint.md
        fingerprint_md_path = self.styles_dir / style_id / "fingerprint.md"
        if fingerprint_md_path.exists():
            # 简单解析 MD 文件
            content = fingerprint_md_path.read_text(encoding="utf-8")
            return {"source": style_id, "raw_content": content}

        return None

    def generate_fingerprint(
        self,
        novel_id: str,
        answers: Dict[str, Any],
        special_requirements: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生成作品专属风格指纹。

        Args:
            novel_id: 小说 ID
            answers: 用户问询答案
            special_requirements: 特殊要求（可选）

        Returns:
            完整的风格指纹字典
        """
        # 处理答案，获取合并的 hints
        merged_hints = self.process_answers(answers)

        # 提取核心风格
        core = {
            "tone": answers.get("tone", "中节奏"),
            "pacing": answers.get("pacing", "中节奏"),
            "dialogue_ratio": merged_hints.get("dialogue_ratio", 0.4),
        }

        if special_requirements:
            core["special_requirements"] = special_requirements

        # 构建特征
        features = self._build_features(merged_hints)

        # 处理参考作品
        reference_style = None
        ref_style_id = answers.get("reference")
        if ref_style_id and ref_style_id != "无参考":
            reference_style = self._build_reference_style(ref_style_id)

        # 构建完整的 fingerprint
        fingerprint = {
            "meta": {
                "name": f"{novel_id}专属风格",
                "created_at": datetime.now().strftime("%Y-%m-%d"),
                "source": self._determine_source(answers),
            },
            "core": core,
            "features": features,
            "shared_craft": {
                "humanization": "@craft/humanization.yaml",
                "tropes": "@craft/tropes/",
                "dialogue": "@craft/dialogue_craft.md",
            },
            "banned": {
                "words": [],
                "patterns": [],
                "ai_phrases": self._get_default_ai_phrases(),
            },
        }

        if reference_style:
            fingerprint["reference_style"] = reference_style

        return fingerprint

    def _build_features(self, hints: Dict[str, Any]) -> Dict[str, Any]:
        """根据 hints 构建特征部分。

        Args:
            hints: 合并后的 style_hints

        Returns:
            特征字典
        """
        features: Dict[str, Any] = {
            "tone_features": [],
            "pacing_features": {},
            "dialogue_features": {},
        }

        # 基调特征
        tone = hints.get("tone") or hints.get("humor")
        if tone:
            features["tone_features"].extend(self._get_tone_features(tone))

        # 节奏特征
        pacing = hints.get("pacing")
        if pacing:
            features["pacing_features"] = self._get_pacing_features(pacing)
        elif hints.get("paragraph_length"):
            features["pacing_features"] = {
                "paragraph_length": hints.get("paragraph_length"),
                "scene_transition": hints.get("scene_transition", "normal"),
                "short_paragraph_ratio": hints.get("short_paragraph_ratio", 0.4),
            }

        # 对话特征
        if "dialogue_ratio" in hints:
            features["dialogue_features"] = {
                "ratio": hints["dialogue_ratio"],
                "style": self._infer_dialogue_style(hints["dialogue_ratio"]),
            }

        return features

    def _get_tone_features(self, tone: str) -> List[str]:
        """根据基调获取特征描述。

        Args:
            tone: 基调类型

        Returns:
            特征描述列表
        """
        tone_map = {
            "high": ["适度吐槽", "轻松不轻浮", "现代感语言"],
            "medium": ["偶尔幽默", "张弛有度"],
            "low": ["严肃基调", "深度叙事"],
            "light": ["轻松明快", "日常感"],
            "deep": ["情感深度", "细腻描写"],
            "warm": ["温馨治愈", "人情味"],
        }
        return tone_map.get(tone, ["中性基调"])

    def _get_pacing_features(self, pacing: str) -> Dict[str, Any]:
        """根据节奏获取特征。

        Args:
            pacing: 节奏类型

        Returns:
            节奏特征字典
        """
        pacing_map = {
            "fast": {
                "paragraph_length": "短",
                "scene_transition": "快",
                "short_paragraph_ratio": 0.6,
            },
            "normal": {
                "paragraph_length": "中",
                "scene_transition": "正常",
                "short_paragraph_ratio": 0.4,
            },
            "slow": {
                "paragraph_length": "长",
                "scene_transition": "慢",
                "short_paragraph_ratio": 0.2,
            },
        }
        return pacing_map.get(pacing, pacing_map["normal"])

    def _infer_dialogue_style(self, ratio: float) -> str:
        """根据对话比例推断对话风格。

        Args:
            ratio: 对话比例

        Returns:
            对话风格描述
        """
        if ratio >= 0.5:
            return "活泼自然"
        elif ratio >= 0.35:
            return "平衡"
        else:
            return "含蓄内敛"

    def _build_reference_style(self, style_id: str) -> Dict[str, Any]:
        """构建参考风格部分。

        Args:
            style_id: 参考风格 ID

        Returns:
            参考风格字典
        """
        ref_style = self.load_reference_style(style_id)

        if ref_style:
            return {
                "source": style_id,
                "adopted_features": self._extract_adopted_features(ref_style),
            }

        return {"source": style_id, "adopted_features": []}

    def _extract_adopted_features(self, ref_style: Dict[str, Any]) -> List[str]:
        """从参考风格中提取可借鉴的特征。

        Args:
            ref_style: 参考风格字典

        Returns:
            可借鉴特征列表
        """
        features = []

        # 从已有特征中提取
        if "features" in ref_style:
            tone_features = ref_style["features"].get("tone_features", [])
            features.extend(tone_features[:3])  # 最多取3个

        return features

    def _determine_source(self, answers: Dict[str, Any]) -> str:
        """确定风格来源描述。

        Args:
            answers: 用户答案

        Returns:
            来源描述
        """
        ref = answers.get("reference")
        if ref and ref != "无参考":
            return f"问询生成 + 参考《{ref}》"
        return "问询生成"

    def _get_default_ai_phrases(self) -> List[str]:
        """获取默认的 AI 痕迹短语列表。

        Returns:
            AI 痕迹短语列表
        """
        return [
            "不禁",
            "心中涌起",
            "眼神中闪过",
            "一股暖流",
            "难以言喻",
            "无法形容",
            "仿佛...",
            "这一刻",
        ]

    def save_fingerprint(self, novel_id: str, fingerprint: Dict[str, Any]) -> Path:
        """保存风格指纹到文件。

        Args:
            novel_id: 小说 ID
            fingerprint: 风格指纹字典

        Returns:
            保存的文件路径
        """
        # 确保目录存在
        style_dir = self.novels_dir / novel_id / "style"
        style_dir.mkdir(parents=True, exist_ok=True)

        # 保存文件
        output_path = style_dir / "fingerprint.yaml"
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(fingerprint, f, allow_unicode=True, default_flow_style=False)

        return output_path

    def initialize(
        self,
        novel_id: str,
        answers: Dict[str, Any],
        special_requirements: Optional[str] = None,
    ) -> Path:
        """完整的风格初始化流程。

        Args:
            novel_id: 小说 ID
            answers: 用户问询答案
            special_requirements: 特殊要求（可选）

        Returns:
            保存的 fingerprint.yaml 路径
        """
        # 加载配置
        self.load_questions_config()

        # 生成指纹
        fingerprint = self.generate_fingerprint(novel_id, answers, special_requirements)

        # 保存
        return self.save_fingerprint(novel_id, fingerprint)


def create_default_answers() -> Dict[str, Any]:
    """创建默认的问询答案（用于测试或快速初始化）。

    Returns:
        默认答案字典
    """
    return {
        "tone": "轻松幽默",
        "pacing": "中节奏",
        "dialogue_ratio": "平衡",
        "reference": "无参考",
        "special_requirements": "",
    }
