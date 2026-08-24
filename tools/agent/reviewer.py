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

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from models.context_package import estimate_text_tokens

from ..llm import Message
from ..llm.context import ContextBudgetPolicy
from .base import BaseAgent

logger = logging.getLogger(__name__)


@dataclass
class ReviewIssue:
    """审核问题"""

    severity: str  # critical, warning, info
    category: str
    description: str
    suggestion: str
    dimension: int | None = None  # 维度编号
    evidence: str = ""


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
    # 8 维/批在推理模型上会因思维链挤占输出预算而截断（实测 37 维全量时
    # reasoning_content 可达 13K+ 字符），降到 4 维/批给 JSON 输出留足空间。
    LLM_AUDIT_BATCH_SIZE = 4
    LLM_AUDIT_INPUT_CEILING = 32_000
    LLM_AUDIT_OUTPUT_TOKENS_PER_DIMENSION = 1024
    _AUDIT_CONTEXT_SPECS = (
        ("author_intent", "作者意图", 6.0, None),
        ("creative_focus", "当前创作罗盘", 6.0, None),
        ("outline", "本章大纲与目标", 7.0, None),
        ("target_words", "目标字数", 2.0, None),
        (
            "character_profiles",
            "角色设定",
            6.0,
            frozenset({1, 3, 9, 13, 14, 16, 18, 28, 29, 30, 31, 33, 34, 35, 36, 37}),
        ),
        (
            "current_state",
            "当前世界状态",
            6.0,
            frozenset({2, 3, 4, 5, 6, 9, 11, 18, 28, 29, 30, 31, 33, 35, 37}),
        ),
        (
            "relationships",
            "当前人物关系",
            5.0,
            frozenset({1, 9, 11, 13, 14, 16, 18, 28, 29, 30, 31, 34, 36, 37}),
        ),
        (
            "ledger",
            "当前资源账本",
            4.0,
            frozenset({4, 5, 11, 18, 28, 30, 35, 37}),
        ),
        (
            "foreshadowing_summary",
            "本章相关伏笔",
            5.0,
            frozenset({6, 9, 15, 24, 25, 28, 29, 31, 32, 33, 37}),
        ),
        (
            "emotion_arc",
            "章内情感弧线",
            4.0,
            frozenset({7, 15, 24, 25, 26, 32, 33}),
        ),
        (
            "style_profile",
            "风格约束",
            5.0,
            frozenset({7, 8, 10, 12, 16, 17, 19, 20, 21, 22, 23, 26, 27, 32, 34}),
        ),
        (
            "recent_chapters",
            "上一章衔接",
            5.0,
            frozenset(
                {1, 2, 3, 4, 5, 6, 9, 11, 13, 14, 15, 16, 18, 19, 24, 25} | set(range(28, 38))
            ),
        ),
    )

    def get_name(self) -> str:
        return "reviewer"

    async def review(
        self,
        content: str,
        context: dict,
        dimensions: list[int] | None = None,
        strict: bool = False,
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

        if dimensions is not None:
            selected = {
                int(item)
                for item in dimensions
                if isinstance(item, int) and item in self.DIMENSION_MAP
            }
            all_issues = [issue for issue in all_issues if issue.dimension in selected]

        # 计算总分
        critical_count = sum(1 for i in all_issues if i.severity == "critical")
        warning_count = sum(1 for i in all_issues if i.severity == "warning")

        passed = critical_count == 0 and (not strict or warning_count == 0)
        score = max(0, 100 - critical_count * 20 - warning_count * 5)

        return ReviewResult(
            passed=passed,
            issues=all_issues,
            summary=self._generate_summary(all_issues, score),
            score=score,
            token_usage=self._audit_usage_summary(),
        )

    def _rule_based_check(self, content: str, target_words: int = 0) -> list[ReviewIssue]:
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
                            f"正文约{actual_words}个中文字符，目标为{target_words}，偏差超过30%"
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
                variance = sum((length - mean) ** 2 for length in lengths) / len(lengths)
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
            yaml_path = Path(__file__).parent.parent.parent / "craft" / "ai_patterns.yaml"
            if yaml_path.exists():
                with yaml_path.open(encoding="utf-8") as f:
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
                                suggestion=(
                                    "建议替换为：" + " / ".join(item.get("replacements", [])[:3])
                                ),
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
        dimensions: list[int] | None = None,
    ) -> list[ReviewIssue]:
        """Run deep review in bounded batches so one report cannot be truncated."""

        requested = [
            item
            for item in (dimensions or self.DIMENSION_MAP.keys())
            if isinstance(item, int) and item in self.DIMENSION_MAP
        ]
        self._audit_context_reports: list[dict] = []
        issues: list[ReviewIssue] = []
        for start in range(0, len(requested), self.LLM_AUDIT_BATCH_SIZE):
            batch = requested[start : start + self.LLM_AUDIT_BATCH_SIZE]
            issues.extend(self._llm_audit_batch(content, context, batch))
        return issues

    def _llm_audit_batch(
        self,
        content: str,
        context: dict,
        requested: list[int],
        *,
        output_budget: int | None = None,
    ) -> list[ReviewIssue]:
        """Review one dimension batch, bisecting it if the provider truncates output."""

        from ..llm.response import ProviderResponseError

        dimension_contract = "\n".join(
            f"{number}. {self.DIMENSION_MAP[number]}" for number in requested
        )

        system_prompt = f"""你是一位专业的小说编辑，负责审核章节内容的质量。

只审核以下维度，不要返回范围之外的问题：
{dimension_contract}

严重度定义：
- critical：明确的事实矛盾、连续性破坏、敏感内容或导致本章不可用的问题。
- warning：有正文证据的实质质量问题，需要修改才能达到交付标准。
- info：不影响正确性的可选优化建议。

输出格式：
```json
[
  {{
    "dimension": 1,
    "severity": "warning",
    "category": "维度名称",
    "description": "问题描述",
    "suggestion": "修改建议",
    "evidence": "正文中的短引用或明确位置；无法引用时为空字符串"
  }}
]
```

每个对象必须包含全部六个字段；severity 只能是 critical/warning/info；dimension 必须来自上述列表。
不要逐维复述“通过”结论，只返回有正文证据的问题；每个维度最多返回 2 个最重要问题。
description 和 suggestion 各不超过 80 字，evidence 不超过 60 字。
如果没有问题，返回空数组 []。只输出 JSON 数组。"""

        effective_output_budget = output_budget or self._audit_output_budget(requested)
        user_prompt, context_report = self._build_audit_user_prompt(
            content,
            context,
            requested,
            system_prompt=system_prompt,
            output_budget=effective_output_budget,
        )
        if not hasattr(self, "_audit_context_reports"):
            self._audit_context_reports = []
        self._audit_context_reports.append(context_report)

        try:
            response = self.chat(
                messages=[
                    Message("system", system_prompt),
                    Message("user", user_prompt),
                ],
                temperature=0.3,
                max_tokens=effective_output_budget,
            )
        except ProviderResponseError as exc:
            if exc.code != "MODEL_OUTPUT_TRUNCATED" or len(requested) <= 1:
                raise
            midpoint = len(requested) // 2
            return self._llm_audit_batch(
                content,
                context,
                requested[:midpoint],
                output_budget=effective_output_budget,
            ) + self._llm_audit_batch(
                content,
                context,
                requested[midpoint:],
                output_budget=effective_output_budget,
            )

        usage = dict(getattr(response, "usage", {}) or {})
        if usage:
            context_report["provider_usage"] = usage
        return self._parse_llm_issues(response.content, allowed_dimensions=set(requested))

    def _audit_output_budget(self, requested: list[int]) -> int:
        config = getattr(getattr(getattr(self, "ctx", None), "client", None), "config", None)
        configured = self._positive_int(getattr(config, "max_tokens", None), 4096)
        context_window = self._positive_int(getattr(config, "context_tokens", None), 64_000)
        desired = max(
            4096,
            len(requested) * self.LLM_AUDIT_OUTPUT_TOKENS_PER_DIMENSION,
        )
        return max(256, min(configured, desired, max(256, context_window - 1024)))

    @staticmethod
    def _positive_int(value: object, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            parsed = default
        return max(1, parsed)

    def _build_audit_user_prompt(
        self,
        content: str,
        context: dict,
        requested: list[int],
        *,
        system_prompt: str,
        output_budget: int,
    ) -> tuple[str, dict]:
        selected = set(requested)
        all_entries: list[tuple[str, str, float]] = []
        entries: list[tuple[str, str, float]] = []
        omitted_fields: list[str] = []
        for key, label, priority, dimensions in self._AUDIT_CONTEXT_SPECS:
            value = str(context.get(key) or "").strip()
            if not value:
                continue
            entry = (key, f"{label}：\n{value}", priority)
            all_entries.append(entry)
            if dimensions is not None and not selected.intersection(dimensions):
                omitted_fields.append(key)
                continue
            entries.append(entry)

        full_user_prompt = self._render_audit_user_prompt(content, all_entries)
        original_user_prompt = self._render_audit_user_prompt(content, entries)
        original_tokens = estimate_text_tokens(system_prompt) + estimate_text_tokens(
            full_user_prompt
        )
        selected_tokens = estimate_text_tokens(system_prompt) + estimate_text_tokens(
            original_user_prompt
        )
        config = getattr(getattr(getattr(self, "ctx", None), "client", None), "config", None)
        context_window = self._positive_int(getattr(config, "context_tokens", None), 64_000)
        policy = ContextBudgetPolicy(context_window, output_budget)
        proactive_target = min(
            self.LLM_AUDIT_INPUT_CEILING,
            max(1024, int(policy.input_budget_tokens * 0.70)),
        )
        if selected_tokens <= proactive_target:
            return original_user_prompt, {
                "dimensions": list(requested),
                "context_window_tokens": context_window,
                "max_output_tokens": output_budget,
                "input_budget_tokens": policy.input_budget_tokens,
                "target_input_tokens": proactive_target,
                "original_estimated_tokens": original_tokens,
                "selection_estimated_tokens": selected_tokens,
                "final_estimated_tokens": selected_tokens,
                "compressed": bool(omitted_fields),
                "omitted_fields": omitted_fields,
                "truncated_fields": [],
            }

        system_tokens = estimate_text_tokens(system_prompt)
        available = max(256, proactive_target - system_tokens - 1024)
        content_tokens = estimate_text_tokens(content)
        context_tokens = sum(estimate_text_tokens(value) for _, value, _ in entries)
        reserved_context = min(context_tokens, max(256, int(available * 0.45))) if entries else 0
        content_budget = min(content_tokens, max(0, available - reserved_context))
        context_budget = min(context_tokens, max(0, available - content_budget))
        remaining = max(0, available - content_budget - context_budget)
        if remaining and content_budget < content_tokens:
            added = min(remaining, content_tokens - content_budget)
            content_budget += added
            remaining -= added
        if remaining:
            context_budget += remaining

        fitted_content = self._fit_audit_text(content, content_budget)
        allocations = self._weighted_context_allocations(entries, context_budget)
        fitted_entries: list[tuple[str, str, float]] = []
        truncated_fields: list[str] = []
        for (key, value, priority), allocation in zip(entries, allocations, strict=True):
            fitted = self._fit_audit_text(value, allocation)
            if fitted != value:
                truncated_fields.append(key)
            if fitted:
                fitted_entries.append((key, fitted, priority))

        user_prompt = self._render_audit_user_prompt(fitted_content, fitted_entries)
        final_tokens = estimate_text_tokens(system_prompt) + estimate_text_tokens(user_prompt)
        return user_prompt, {
            "dimensions": list(requested),
            "context_window_tokens": context_window,
            "max_output_tokens": output_budget,
            "input_budget_tokens": policy.input_budget_tokens,
            "target_input_tokens": proactive_target,
            "original_estimated_tokens": original_tokens,
            "selection_estimated_tokens": selected_tokens,
            "final_estimated_tokens": final_tokens,
            "compressed": True,
            "content_truncated": fitted_content != content,
            "omitted_fields": omitted_fields,
            "truncated_fields": truncated_fields,
        }

    @staticmethod
    def _render_audit_user_prompt(
        content: str,
        entries: list[tuple[str, str, float]],
    ) -> str:
        parts = ["请审核以下章节：", f"章节内容：\n{content}"]
        parts.extend(value for _, value, _ in entries)
        parts.append("请进行审核：")
        return "\n\n".join(parts)

    @classmethod
    def _weighted_context_allocations(
        cls,
        entries: list[tuple[str, str, float]],
        budget: int,
    ) -> list[int]:
        counts = [estimate_text_tokens(value) for _, value, _ in entries]
        if sum(counts) <= budget:
            return counts
        allocations = [0] * len(entries)
        remaining = max(0, budget)
        active = {index for index, count in enumerate(counts) if count > 0}
        if active and remaining:
            floor = min(96, remaining // len(active))
            for index in active:
                allocations[index] = min(counts[index], floor)
            remaining -= sum(allocations)
            active = {index for index in active if allocations[index] < counts[index]}
        while active and remaining > 0:
            denominator = sum(entries[index][2] for index in active)
            if denominator <= 0:
                break
            shares = {
                index: max(1, int(remaining * entries[index][2] / denominator)) for index in active
            }
            progressed = 0
            for index in list(active):
                added = min(shares[index], counts[index] - allocations[index], remaining)
                allocations[index] += added
                remaining -= added
                progressed += added
                if allocations[index] >= counts[index]:
                    active.remove(index)
                if remaining <= 0:
                    break
            if progressed == 0:
                break
        return allocations

    @staticmethod
    def _fit_audit_text(text: str, max_tokens: int) -> str:
        value = str(text or "")
        current = estimate_text_tokens(value)
        if not value or current <= max_tokens:
            return value
        if max_tokens <= 0:
            return ""
        marker = "\n...[审稿上下文已按 Token 预算压缩]...\n"
        max_chars = max(1, int(len(value) * max_tokens / max(1, current)))
        fitted = value
        for _ in range(8):
            head = max(1, int(max_chars * 0.55))
            tail = max(0, max_chars - head)
            fitted = value[:head] + marker + (value[-tail:] if tail else "")
            actual = estimate_text_tokens(fitted)
            if actual <= max_tokens:
                return fitted
            max_chars = max(1, int(max_chars * max_tokens / actual * 0.95))
        return fitted

    def _audit_usage_summary(self) -> dict:
        reports = list(getattr(self, "_audit_context_reports", []) or [])
        if not reports:
            return {}
        provider_usage = [dict(report.get("provider_usage") or {}) for report in reports]
        prompt_tokens = sum(
            int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            for usage in provider_usage
        )
        completion_tokens = sum(
            int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            for usage in provider_usage
        )
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "audit_calls": len(reports),
            "compressed_calls": sum(bool(report.get("compressed")) for report in reports),
            "original_estimated_tokens": sum(
                int(report.get("original_estimated_tokens") or 0) for report in reports
            ),
            "final_estimated_tokens": sum(
                int(report.get("final_estimated_tokens") or 0) for report in reports
            ),
        }

    @staticmethod
    def _parse_llm_issues(
        content: str,
        *,
        allowed_dimensions: set[int],
    ) -> list[ReviewIssue]:
        from ..llm.response import ProviderResponseError

        match = re.search(r"\[.*\]", str(content or ""), re.DOTALL)
        if match is None:
            raise ProviderResponseError(
                "MALFORMED_STRUCTURED_OUTPUT",
                "审稿模型没有返回 JSON 数组",
            )
        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "MALFORMED_STRUCTURED_OUTPUT",
                "审稿模型返回的 JSON 无法解析",
            ) from exc
        if not isinstance(items, list):
            raise ProviderResponseError(
                "MALFORMED_STRUCTURED_OUTPUT",
                "审稿结果必须是 JSON 数组",
            )

        issues: list[ReviewIssue] = []
        required = {
            "dimension",
            "severity",
            "category",
            "description",
            "suggestion",
            "evidence",
        }
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict) or not required.issubset(item):
                raise ProviderResponseError(
                    "MALFORMED_STRUCTURED_OUTPUT",
                    f"第 {index} 个审稿问题缺少必需字段",
                )
            severity = str(item["severity"]).strip().lower()
            dimension = item["dimension"]
            if severity not in {"critical", "warning", "info"}:
                raise ProviderResponseError(
                    "MALFORMED_STRUCTURED_OUTPUT",
                    f"第 {index} 个审稿问题 severity 无效",
                )
            if not isinstance(dimension, int) or dimension not in allowed_dimensions:
                # 模型偶发把问题标到请求批次之外。整批失败会让章节评审随机翻车
                # （dsh-novel conductor 实测：同章多次重试均命中），改为丢弃该条，
                # 其余问题照常进入报告。
                continue
            issues.append(
                ReviewIssue(
                    severity=severity,
                    category=str(item["category"]).strip(),
                    description=str(item["description"]).strip(),
                    suggestion=str(item["suggestion"]).strip(),
                    dimension=dimension,
                    evidence=str(item["evidence"]).strip(),
                )
            )
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
