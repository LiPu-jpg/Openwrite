"""ReviewerAgent - 审核 Agent

能力：
- 33维度审计
- AI痕迹检测
- 连续性检查

扩展：
- 风格检查
- 逻辑检查
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from .base import BaseAgent, AgentContext
from ..llm import Message, LLMResponse

logger = logging.getLogger(__name__)


@dataclass
class ReviewIssue:
    """审核问题"""

    severity: str  # critical, warning, info
    category: str
    description: str
    suggestion: str
    dimension: Optional[int] = None  # 维度编号


@dataclass
class ReviewResult:
    """审核结果"""

    passed: bool
    issues: list[ReviewIssue]
    summary: str
    score: float = 0.0  # 0-100
    token_usage: dict = field(default_factory=dict)


class ReviewerAgent(BaseAgent):
    """审核 Agent

    支持：
    - 33维度审计（逻辑、连续性）
    - AI痕迹检测（段落等长、套话密度等）
    - 敏感词检测

    用法:
        reviewer = ReviewerAgent(ctx)
        result = await reviewer.review(
            content=chapter_content,
            context=writing_context,
        )
    """

    # 33维度映射
    DIMENSION_MAP = {
        1: "OOC检查",
        2: "时间线检查",
        3: "设定冲突",
        4: "战力崩坏",
        5: "数值检查",
        6: "伏笔检查",
        7: "节奏检查",
        8: "文风检查",
        9: "信息越界",
        10: "词汇疲劳",
        11: "利益链断裂",
        12: "年代考据",
        13: "配角降智",
        14: "配角工具人化",
        15: "爽点虚化",
        16: "台词失真",
        17: "流水账",
        18: "知识库污染",
        19: "视角一致性",
        20: "段落等长",
        21: "套话密度",
        22: "公式化转折",
        23: "列表式结构",
        24: "支线停滞",
        25: "弧线平坦",
        26: "节奏单调",
        27: "敏感词检查",
        28: "正传事件冲突",
        29: "未来信息泄露",
        30: "世界规则跨书一致性",
        31: "番外伏笔隔离",
        32: "读者期待管理",
        33: "大纲偏离检测",
        34: "角色还原度",
        35: "世界规则遵守",
        36: "关系动态",
        37: "正典事件一致性",
    }

    def get_name(self) -> str:
        return "reviewer"

    async def review(
        self,
        content: str,
        context: dict,
        dimensions: Optional[list[int]] = None,
    ) -> ReviewResult:
        """审核章节内容

        Args:
            content: 章节内容
            context: 写作上下文
            dimensions: 要检查的维度列表，默认检查全部

        Returns:
            ReviewResult 审核结果
        """
        all_issues = []

        # ── 规则类检查（零 LLM 成本）─
        rule_issues = self._rule_based_check(
            content,
            target_words=int(context.get("target_words") or 0),
        )
        all_issues.extend(rule_issues)

        # ── AI 痕迹检测（统计方法）─
        ai_issues = self._detect_ai_tells(content)
        all_issues.extend(ai_issues)

        # ── LLM 驱动的深度审计 ─
        llm_issues = await self._llm_audit(content, context, dimensions)
        all_issues.extend(llm_issues)

        # ── 敏感词检查 ─
        sensitive_issues = self._check_sensitive_words(content)
        all_issues.extend(sensitive_issues)

        # 计算总分
        critical_count = sum(1 for i in all_issues if i.severity == "critical")
        warning_count = sum(1 for i in all_issues if i.severity == "warning")

        passed = critical_count == 0
        score = max(0, 100 - critical_count * 20 - warning_count * 5)

        return ReviewResult(
            passed=passed,
            issues=all_issues,
            summary=self._generate_summary(all_issues, score),
            score=score,
        )

    def _rule_based_check(
        self, content: str, target_words: int = 0
    ) -> list[ReviewIssue]:
        """基于规则的检查（零 LLM 成本）"""
        issues = []

        if target_words > 0:
            actual_words = len(re.findall(r"[\u4e00-\u9fff]", content))
            minimum_words = int(target_words * 0.7)
            maximum_words = int(target_words * 1.3)
            if actual_words < minimum_words or actual_words > maximum_words:
                issues.append(
                    ReviewIssue(
                        severity="warning",
                        category="目标字数偏差",
                        description=(
                            f"正文约{actual_words}个中文字符，目标为{target_words}，"
                            "偏差超过30%"
                        ),
                        suggestion="删减重复动作与支线，或补足关键场景，使篇幅回到目标区间",
                        dimension=7,
                    )
                )

        # 检查段落长度均匀度（dim 20）
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if len(paragraphs) >= 3:
            lengths = [len(p) for p in paragraphs]
            mean = sum(lengths) / len(lengths)
            if mean > 0:
                variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
                std_dev = variance**0.5
                cv = std_dev / mean
                if cv < 0.15:
                    issues.append(
                        ReviewIssue(
                            severity="warning",
                            category="段落等长",
                            description=f"段落长度变异系数仅{cv:.3f}（阈值<0.15），段落长度过于均匀，呈现AI生成特征",
                            suggestion="增加段落长度差异：短段落用于节奏加速或冲击，长段落用于沉浸描写",
                            dimension=20,
                        )
                    )

        # 检查列表式结构（dim 23）
        lines = content.split("\n")
        list_pattern = re.compile(r"^[一二三四五六七八九十\d+][、.].+")
        consecutive_lists = 0
        max_list_seq = 0
        for line in lines:
            if list_pattern.match(line.strip()):
                consecutive_lists += 1
                max_list_seq = max(max_list_seq, consecutive_lists)
            else:
                consecutive_lists = 0
        if max_list_seq >= 3:
            issues.append(
                ReviewIssue(
                    severity="warning",
                    category="列表式结构",
                    description=f"发现{max_list_seq}行连续列表式内容",
                    suggestion="改用自然叙述，避免连续使用编号列表",
                    dimension=23,
                )
            )

        return issues

    def _detect_ai_tells(self, content: str) -> list[ReviewIssue]:
        """AI痕迹检测"""
        issues = []

        # ── 套话词密度检测（dim 21）─
        hedge_words = ["似乎", "可能", "或许", "大概", "某种程度上", "一定程度上", "在某种意义上"]
        total_chars = len(content)
        if total_chars > 0:
            hedge_count = sum(content.count(w) for w in hedge_words)
            hedge_density = hedge_count / (total_chars / 1000)
            if hedge_density > 3:
                issues.append(
                    ReviewIssue(
                        severity="warning",
                        category="套话密度",
                        description=f"套话词密度为{hedge_density:.1f}次/千字（阈值>3），语气过于模糊犹豫",
                        suggestion="用确定性叙述替代模糊表达",
                        dimension=21,
                    )
                )

        # ── 公式化转折词检测（dim 22）─
        transition_words = [
            "然而",
            "不过",
            "与此同时",
            "另一方面",
            "尽管如此",
            "话虽如此",
            "但值得注意的是",
        ]
        transition_counts = {w: content.count(w) for w in transition_words}
        repeated = [(w, c) for w, c in transition_counts.items() if c >= 3]
        if repeated:
            detail = "、".join(f'"{w}"×{c}' for w, c in repeated)
            issues.append(
                ReviewIssue(
                    severity="warning",
                    category="公式化转折",
                    description=f"转折词重复使用：{detail}",
                    suggestion="用情节自然转折替代，或换用不同过渡手法",
                    dimension=22,
                )
            )

        # ── 检查 craft/ai_patterns.yaml 中的禁用词 ─
        yaml_issues = self._check_yaml_patterns(content)
        issues.extend(yaml_issues)

        return issues

    def _check_yaml_patterns(self, content: str) -> list[ReviewIssue]:
        """检查 ai_patterns.yaml 中的模式"""
        issues = []

        try:
            import yaml
            from pathlib import Path

            yaml_path = Path(__file__).parent.parent.parent / "craft" / "ai_patterns.yaml"
            if yaml_path.exists():
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                # 检查禁用词
                banned = data.get("banned_patterns", [])
                for item in banned:
                    pattern = item.get("pattern", "")
                    if pattern in content:
                        severity = "critical" if item.get("severity") == "high" else "warning"
                        issues.append(
                            ReviewIssue(
                                severity=severity,
                                category=item.get("category", "AI套路"),
                                description=f"发现禁用表达：{pattern}",
                                suggestion=f"建议替换为：{' / '.join(item.get('replacements', [])[:3])}",
                                dimension=None,
                            )
                        )

                # 检查套话模式
                cliched = data.get("cliched_patterns", [])
                for item in cliched:
                    pattern = item.get("pattern", "")
                    if pattern in content:
                        issues.append(
                            ReviewIssue(
                                severity="warning",
                                category=item.get("category", "AI套路"),
                                description=f"发现AI套话：{pattern}",
                                suggestion=f"建议：{item.get('replacements', ['直接删除'])[0]}",
                                dimension=None,
                            )
                        )
        except Exception as e:
            logger.warning(f"Failed to load ai_patterns.yaml: {e}")

        return issues

    async def _llm_audit(
        self,
        content: str,
        context: dict,
        dimensions: Optional[list[int]] = None,
    ) -> list[ReviewIssue]:
        """LLM 驱动的深度审计"""
        issues = []

        system_prompt = """你是一位专业的小说编辑，负责审核章节内容的质量。

核心审核维度：
1. OOC检查 - 角色行为是否符合性格设定
2. 时间线检查 - 事件顺序是否合理
3. 设定冲突 - 是否与世界观设定矛盾
4. 战力崩坏 - 角色能力是否忽强忽弱
5. 伏笔检查 - 伏笔是否合理埋设/回收
6. 节奏检查 - 节奏是否拖沓或过快
7. 文风检查 - 文风是否一致
8. 视角一致性 - 是否保持叙事视角统一
9. 配角降智 - 配角是否被强行降智
10. 台词失真 - 对话是否不符合角色性格
11. 大纲偏离 - 是否完成本章目标与戏剧位置
12. 作者意图 - 是否违背整本书的长期承诺
13. 创作罗盘 - 是否违反当前阶段必须保留/必须避免项
14. 关系连续性 - 人物关系变化是否有铺垫
15. AI痕迹 - 是否存在过度总结、均匀段落或公式化转折

输出格式：
```json
[
  {
    "severity": "warning",
    "category": "维度名称",
    "description": "问题描述",
    "suggestion": "修改建议"
  }
]
```

如果没有问题，返回空数组 []。"""

        user_prompt = f"""请审核以下章节：

章节内容：
{content[:4000]}

作者意图：
{context.get("author_intent", "无")[:1200]}

当前创作罗盘：
{context.get("creative_focus", "无")[:1200]}

本章大纲与目标：
{context.get("outline", "无")[:2500]}

目标字数：
{context.get("target_words", "未指定")}

角色设定：
{context.get("character_profiles", "无")[:2500]}

当前世界状态：
{context.get("current_state", "无")[:500]}

当前人物关系：
{context.get("relationships", "无")[:800]}

风格约束：
{context.get("style_profile", "无")[:1000]}

上一章衔接：
{context.get("recent_chapters", "无")[:1000]}

请进行审核："""

        response = self.chat(
            messages=[
                Message("system", system_prompt),
                Message("user", user_prompt),
            ],
            temperature=0.3,
            max_tokens=4096,
        )

        # 解析 JSON 输出
        try:
            json_match = re.search(r"\[.*\]", response.content, re.DOTALL)
            if json_match:
                import json

                items = json.loads(json_match.group(0))
                for item in items:
                    issues.append(
                        ReviewIssue(
                            severity=item.get("severity", "warning"),
                            category=item.get("category", "未知"),
                            description=item.get("description", ""),
                            suggestion=item.get("suggestion", ""),
                            dimension=None,
                        )
                    )
        except Exception as e:
            logger.warning(f"Failed to parse LLM audit response: {e}")

        return issues

    def _check_sensitive_words(self, content: str) -> list[ReviewIssue]:
        """敏感词检查（简化版）"""
        issues = []

        # 常见敏感词模式
        sensitive_patterns = [
            (r"赌博", "涉赌内容"),
            (r"毒品|吸毒|贩毒", "涉毒内容"),
            (r"自杀|自残", "自残/自杀相关"),
        ]

        for pattern, category in sensitive_patterns:
            if re.search(pattern, content):
                issues.append(
                    ReviewIssue(
                        severity="critical",
                        category="敏感词检查",
                        description=f"发现敏感内容：{category}",
                        suggestion="请修改相关内容",
                        dimension=27,
                    )
                )

        return issues

    def _generate_summary(self, issues: list[ReviewIssue], score: float) -> str:
        """生成审核摘要"""
        if not issues:
            return f"审核通过（得分：{score:.0f}）"

        critical = [i for i in issues if i.severity == "critical"]
        warnings = [i for i in issues if i.severity == "warning"]

        parts = []
        if critical:
            parts.append(f"严重问题 {len(critical)} 个")
        if warnings:
            parts.append(f"警告 {len(warnings)} 项")

        return f"发现问题：{'，'.join(parts)}（得分：{score:.0f}）"
