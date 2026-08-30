"""章节上下文组装 V2。

目标：为多 Agent 写作流水线提供结构化上下文包，覆盖以下信息：
1) Agent 职责系统提示词
2) 故事背景（500-1000字目标）
3) 历史篇梗概（每篇 1000-2000字目标）
4) 当前篇各节梗概（每节 500-1000字目标）
5) 上一章正文
6) 各节涉及人物/概念（主角、已出现、将出现）
7) 涉及人物文档
8) 全部风格文档
9) 涉及概念文档
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

from models.context_package import estimate_text_tokens
from models.outline import OutlineHierarchy
from tools.agent_policy import get_default_agent_specs, get_redundant_agent_specs
from tools.character_state_index import strip_character_state_annotations
from tools.frontmatter import parse_toml_front_matter
from tools.llm.context import ContextBudgetPlan, ContextBudgetPolicy
from tools.outline_cache import deserialize_outline_hierarchy
from tools.outline_parser import OutlineMdParser
from tools.resources import resolve_craft_dir
from tools.shared_documents import (
    resolve_shared_document_path,
    shared_document_lookup_keys,
)
from tools.source_sync import ensure_runtime_fresh
from tools.story_planning import StoryPlanningStore
from tools.style_synthesizer import render_style_manifest_summary
from tools.truth_manager import TruthFilesManager

ROLE_SYSTEM_PROMPTS: Dict[str, str] = {
    "director": (
        "你是写作总导演 Agent。只以 parser-backed 当前章的戏剧位置、内容焦点、目标、节拍、"
        "悬念、情感弧线和目标字数分配任务；不得用整节摘要替代本章大纲。"
    ),
    "context_engineer": (
        "你是上下文工程 Agent。职责：仅基于项目文档组装事实，不虚构设定；"
        "角色只来自本章 involved_characters 或本章文本明确提名，禁止借用整节角色并集；"
        "优先保证人物状态、概念定义、前后章节衔接准确。"
    ),
    "writer": (
        "你是创作 Agent。按当前章的目标、节拍、悬念、情感弧线和目标字数完成正文；"
        "遵守角色与世界正典，不越权修改设定，不提前泄露未来篇关键真相。"
    ),
    "continuity_reviewer": (
        "你是连续性审查 Agent。以完整正文和当前章上下文检查人物、时间线、力量体系、关系、"
        "伏笔与大纲偏离；每个问题输出 dimension、severity、category、description、suggestion、evidence。"
    ),
    "state_settler": (
        "你是状态结算 Agent。只从本章提取客观事实，输出 runtime-delta-v1 和追加式 state_updates 回退；"
        "未知实体写入 proposed_entities，禁止覆盖整份真相文件或直接创建正典资产。"
    ),
}


@dataclass
class ArcSummary:
    arc_id: str
    title: str
    summary: str


@dataclass
class SectionSummary:
    section_id: str
    title: str
    summary: str
    involved_characters: List[str] = field(default_factory=list)
    involved_concepts: List[str] = field(default_factory=list)


@dataclass
class ChapterAssemblyPacket:
    novel_id: str
    chapter_id: str
    target_words: int = 0
    system_prompts: Dict[str, str] = field(default_factory=dict)
    author_intent: str = ""
    creative_focus: str = ""
    core_documents: Dict[str, str] = field(default_factory=dict)
    story_background: str = ""
    historical_arc_summaries: List[ArcSummary] = field(default_factory=list)
    current_arc_sections: List[SectionSummary] = field(default_factory=list)
    previous_chapter_content: str = ""
    protagonist_state: str = ""
    current_state: str = ""
    ledger: str = ""
    relationships: str = ""
    character_documents: Dict[str, str] = field(default_factory=dict)
    style_documents: Dict[str, str] = field(default_factory=dict)
    setting_documents: Dict[str, str] = field(default_factory=dict)
    concept_documents: Dict[str, str] = field(default_factory=dict)
    continuity_documents: Dict[str, str] = field(default_factory=dict)
    agent_specs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    redundant_agents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    compression: Dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:
        parts: List[str] = []

        parts.append("## 系统提示词（按职责）")
        for role, prompt in self.system_prompts.items():
            parts.append(f"### {role}\n{prompt}")

        parts.append("## 作者意图")
        parts.append(self.author_intent or "（暂无）")

        parts.append("## 创作罗盘（当前最高优先级）")
        parts.append(self.creative_focus or "（暂无）")

        parts.append("## 作品核心")
        if self.core_documents:
            labels = {"background": "故事背景", "foundation": "基础设定"}
            for key, content in self.core_documents.items():
                parts.append(f"### {labels.get(key, key)}\n{content}")
        else:
            parts.append(self.story_background or "（暂无）")

        parts.append("## 历史篇梗概")
        if self.historical_arc_summaries:
            for arc in self.historical_arc_summaries:
                parts.append(f"### {arc.title} ({arc.arc_id})\n{arc.summary}")
        else:
            parts.append("（暂无）")

        parts.append("## 当前篇各节梗概")
        if self.current_arc_sections:
            for sec in self.current_arc_sections:
                chars = "、".join(sec.involved_characters) if sec.involved_characters else "无"
                concepts = "、".join(sec.involved_concepts) if sec.involved_concepts else "无"
                parts.append(
                    f"### {sec.title} ({sec.section_id})\n"
                    f"涉及人物：{chars}\n"
                    f"涉及概念：{concepts}\n\n"
                    f"{sec.summary}"
                )
        else:
            parts.append("（暂无）")

        parts.append("## 上一章正文")
        parts.append(self.previous_chapter_content or "（暂无）")

        parts.append("## 主角状态")
        parts.append(self.protagonist_state or "（暂无）")

        parts.append("## 运行态真相文件")
        continuity = self.continuity_documents or {
            "current_state": self.current_state,
            "ledger": self.ledger,
            "relationships": self.relationships,
        }
        parts.append(f"### current_state.md\n{continuity.get('current_state') or '（暂无）'}")
        parts.append(f"### ledger.md\n{continuity.get('ledger') or '（暂无）'}")
        parts.append(f"### relationships.md\n{continuity.get('relationships') or '（暂无）'}")

        parts.append("## 人物文档")
        if self.character_documents:
            for name, content in self.character_documents.items():
                parts.append(f"### {name}\n{content}")
        else:
            parts.append("（暂无）")

        parts.append("## 风格文档")
        if self.style_documents:
            for key, content in self.style_documents.items():
                parts.append(f"### {key}\n{content}")
        else:
            parts.append("（暂无）")

        parts.append("## 设定文档")
        setting_documents = self.setting_documents or self.concept_documents
        if setting_documents:
            for key, content in setting_documents.items():
                parts.append(f"### {key}\n{content}")
        else:
            parts.append("（暂无）")

        parts.append("## Agent 权限矩阵")
        for name, spec in self.agent_specs.items():
            parts.append(
                f"### {name}\n"
                f"职责：{spec.get('role', '')}\n"
                f"必需：{spec.get('required', False)}\n"
                f"可读：{', '.join(spec.get('can_read', [])) or '无'}\n"
                f"可写：{', '.join(spec.get('can_write', [])) or '无'}\n"
                f"禁止：{', '.join(spec.get('forbidden', [])) or '无'}"
            )

        if self.redundant_agents:
            parts.append("## 冗余 Agent（默认不启用）")
            for name, spec in self.redundant_agents.items():
                parts.append(f"### {name}\n{spec.get('role', '')}")

        if self.compression:
            parts.append("## 上下文预算")
            parts.append(
                f"策略：{self.compression.get('strategy', '')}\n"
                f"压缩前：{self.compression.get('original_characters', 0)} 字符\n"
                f"压缩后：{self.compression.get('final_characters', 0)} 字符\n"
                f"截短文档：{', '.join(self.compression.get('truncated_documents', [])) or '无'}\n"
                f"省略文档：{', '.join(self.compression.get('dropped_documents', [])) or '无'}"
            )

        return "\n\n".join(parts)


class ChapterAssemblerV2:
    """章节组装器 V2。"""

    COMPRESSION_STRATEGY = "staircase-proportional-v3"

    def __init__(self, project_root: Path, novel_id: str, style_id: str = ""):
        self.project_root = project_root.resolve()
        self.novel_id = novel_id
        self.style_id = style_id

        self.novel_root = self.project_root / "data" / "novels" / novel_id
        self.src_root = self.novel_root / "src"
        self.runtime_root = self.novel_root / "data"
        self.story_planning_store = StoryPlanningStore(self.project_root, self.novel_id)
        self.truth_manager = TruthFilesManager(self.project_root, self.novel_id)
        try:
            from tools.model_profiles import active_model_profile

            profile = active_model_profile() or {}
            context_tokens = int(
                profile.get("context_tokens")
                or os.getenv("OPENWRITE_CONTEXT_TOKENS", "64000")
            )
            output_tokens = int(
                profile.get("max_output_tokens")
                or os.getenv("LLM_MAX_TOKENS", "24000")
            )
        except (TypeError, ValueError):
            context_tokens = 64000
            output_tokens = 24000
        self._context_policy = ContextBudgetPolicy(context_tokens, output_tokens)

    def assemble(self, chapter_id: str) -> ChapterAssemblyPacket:
        ensure_runtime_fresh(self.project_root, self.novel_id)
        hierarchy = self._load_hierarchy()
        chapter = hierarchy.get_node(chapter_id)
        truth = self.truth_manager.load_truth_files()

        packet = ChapterAssemblyPacket(
            novel_id=self.novel_id,
            chapter_id=chapter_id,
            system_prompts=dict(ROLE_SYSTEM_PROMPTS),
            author_intent=self._load_story_control("author_intent.md", max_chars=3000),
            creative_focus=self._load_story_control("current_focus.md", max_chars=2400),
            core_documents=self._load_core_documents(),
            current_state=truth.current_state,
            ledger=truth.ledger,
            relationships=truth.relationships,
            continuity_documents={
                "current_state": truth.current_state,
                "ledger": truth.ledger,
                "relationships": truth.relationships,
            },
        )

        packet.agent_specs = {
            name: {
                "role": spec.role,
                "required": spec.required,
                "can_read": list(spec.can_read),
                "can_write": list(spec.can_write),
                "forbidden": list(spec.forbidden),
            }
            for name, spec in get_default_agent_specs().items()
        }
        packet.redundant_agents = {
            name: {
                "role": spec.role,
                "required": spec.required,
            }
            for name, spec in get_redundant_agent_specs().items()
        }

        packet.story_background = self._build_story_background(hierarchy)

        if chapter is not None:
            packet.target_words = (
                chapter.word_count_target or chapter.estimated_words or 0
            )
            current_arc = hierarchy.get_parent_arc(chapter_id)
            packet.historical_arc_summaries = self._build_historical_arc_summaries(
                hierarchy,
                current_arc_id=current_arc.node_id if current_arc else "",
            )
            packet.current_arc_sections = self._build_current_arc_section_summaries(
                hierarchy,
                chapter_id=chapter_id,
            )
            packet.previous_chapter_content = self._load_previous_chapter_content(chapter_id)
            packet.protagonist_state = self._load_protagonist_state(hierarchy, chapter_id)

            chars = self._collect_relevant_characters(hierarchy, chapter_id)
            concepts = self._collect_relevant_concepts(hierarchy, chapter_id)
            packet.character_documents = self._load_character_documents(chars)
            packet.setting_documents = self._load_setting_documents(concepts)
            packet.concept_documents = dict(packet.setting_documents)
        else:
            packet.historical_arc_summaries = self._build_historical_arc_summaries(hierarchy, current_arc_id="")

        current_arc = hierarchy.get_parent_arc(chapter_id) if chapter is not None else None
        packet.style_documents = self._load_all_style_documents(
            chapter_id=chapter_id,
            arc_id=current_arc.node_id if current_arc else "",
        )
        self._enforce_context_budget(packet)
        return packet

    def _enforce_context_budget(self, packet: ChapterAssemblyPacket) -> None:
        """Compress only under pressure, using shared tiers and proportional shares."""
        original_characters = self._packet_character_count(packet)
        original_tokens = self._packet_token_count(packet)
        plan = self._context_policy.plan(original_tokens)
        truncated_documents: List[str] = []
        dropped_documents: List[str] = []

        if not plan.requires_compression:
            packet.compression = self._compression_report(
                plan,
                applied=False,
                original_characters=original_characters,
                final_characters=original_characters,
                original_tokens=original_tokens,
                final_tokens=original_tokens,
                truncated_documents=[],
                dropped_documents=[],
                budgets={},
            )
            return

        target_characters = min(
            original_characters,
            max(256, int(plan.target_tokens / 1.5)),
        )
        shares = {
            "controls": 0.11,
            "core": 0.09,
            "historical_outline": 0.08,
            "current_outline": 0.08,
            "previous_chapter": 0.18,
            "protagonist_state": 0.04,
            "continuity": 0.14,
            "characters": 0.13,
            "settings": 0.08,
            "style": 0.07,
        }
        budgets = {
            name: max(1, int(target_characters * share))
            for name, share in shares.items()
        }

        controls, truncated, dropped = self._limit_document_map(
            {
                "author_intent": packet.author_intent,
                "creative_focus": packet.creative_focus,
            },
            total_chars=budgets["controls"],
            per_document=budgets["controls"],
            preferred_prefixes=("author_intent", "creative_focus"),
        )
        packet.author_intent = controls.get("author_intent", "")
        packet.creative_focus = controls.get("creative_focus", "")
        truncated_documents.extend(f"control:{name}" for name in truncated)
        dropped_documents.extend(f"control:{name}" for name in dropped)

        if packet.core_documents:
            packet.core_documents, truncated, dropped = self._limit_document_map(
                packet.core_documents,
                total_chars=budgets["core"],
                per_document=budgets["core"],
                preferred_prefixes=("background", "foundation"),
            )
            truncated_documents.extend(f"core:{name}" for name in truncated)
            dropped_documents.extend(f"core:{name}" for name in dropped)
        else:
            packet.story_background = self._limit_scalar(
                packet.story_background,
                budgets["core"],
                "core:story_background",
                truncated_documents,
            )

        self._limit_summary_items(
            packet.historical_arc_summaries,
            budgets["historical_outline"],
            "outline:arc",
            truncated_documents,
        )
        self._limit_summary_items(
            packet.current_arc_sections,
            budgets["current_outline"],
            "outline:section",
            truncated_documents,
        )
        packet.previous_chapter_content = self._limit_scalar(
            packet.previous_chapter_content,
            budgets["previous_chapter"],
            "recent:previous_chapter",
            truncated_documents,
            prefer_tail=True,
        )
        packet.protagonist_state = self._limit_scalar(
            packet.protagonist_state,
            budgets["protagonist_state"],
            "continuity:protagonist_state",
            truncated_documents,
        )

        continuity, truncated, dropped = self._limit_document_map(
            packet.continuity_documents
            or {
                "current_state": packet.current_state,
                "ledger": packet.ledger,
                "relationships": packet.relationships,
            },
            total_chars=budgets["continuity"],
            per_document=budgets["continuity"],
            preferred_prefixes=("current_state", "relationships", "ledger"),
        )
        packet.continuity_documents = continuity
        packet.current_state = continuity.get("current_state", "")
        packet.ledger = continuity.get("ledger", "")
        packet.relationships = continuity.get("relationships", "")
        truncated_documents.extend(f"continuity:{name}" for name in truncated)
        dropped_documents.extend(f"continuity:{name}" for name in dropped)

        for attribute, label, preferred in (
            ("character_documents", "character", ()),
            ("setting_documents", "setting", ()),
            (
                "style_documents",
                "style",
                ("work.composed", "work.manifest", "work.fingerprint", "craft."),
            ),
        ):
            source = getattr(packet, attribute)
            if attribute == "setting_documents":
                source = source or packet.concept_documents
            limited, truncated, dropped = self._limit_document_map(
                source,
                total_chars=budgets[
                    {
                        "character_documents": "characters",
                        "setting_documents": "settings",
                        "style_documents": "style",
                    }[attribute]
                ],
                per_document=budgets[
                    {
                        "character_documents": "characters",
                        "setting_documents": "settings",
                        "style_documents": "style",
                    }[attribute]
                ],
                preferred_prefixes=preferred,
            )
            setattr(packet, attribute, limited)
            truncated_documents.extend(f"{label}:{name}" for name in truncated)
            dropped_documents.extend(f"{label}:{name}" for name in dropped)
        packet.concept_documents = dict(packet.setting_documents)

        final_tokens = self._packet_token_count(packet)
        final_characters = self._packet_character_count(packet)
        packet.compression = self._compression_report(
            plan,
            applied=True,
            original_characters=original_characters,
            final_characters=final_characters,
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            truncated_documents=truncated_documents,
            dropped_documents=dropped_documents,
            budgets=budgets,
        )

    def _compression_report(
        self,
        plan: ContextBudgetPlan,
        *,
        applied: bool,
        original_characters: int,
        final_characters: int,
        original_tokens: int,
        final_tokens: int,
        truncated_documents: List[str],
        dropped_documents: List[str],
        budgets: Dict[str, int],
    ) -> Dict[str, Any]:
        return {
            "strategy": self.COMPRESSION_STRATEGY,
            "applied": applied,
            "level": plan.level,
            "planned_level": plan.level,
            "context_window_tokens": plan.context_window_tokens,
            "reserved_output_tokens": plan.reserved_output_tokens,
            "safety_tokens": plan.safety_tokens,
            "budget_tokens": plan.input_budget_tokens,
            "target_tokens": plan.target_tokens,
            "target_ratio": plan.target_ratio,
            "usage_ratio": round(plan.usage_ratio, 4),
            "original_characters": original_characters,
            "final_characters": final_characters,
            "original_estimated_tokens": original_tokens,
            "final_estimated_tokens": final_tokens,
            "within_budget": final_tokens <= plan.input_budget_tokens,
            "truncated_documents": truncated_documents,
            "dropped_documents": dropped_documents,
            "budgets": budgets,
        }

    @staticmethod
    def _limit_scalar(
        text: str,
        max_chars: int,
        label: str,
        truncated: List[str],
        *,
        prefer_tail: bool = False,
    ) -> str:
        if len(text) <= max_chars:
            return text
        truncated.append(label)
        return text[-max_chars:] if prefer_tail else text[:max_chars]

    @classmethod
    def _limit_summary_items(
        cls,
        items: List[Any],
        total_chars: int,
        label: str,
        truncated_documents: List[str],
    ) -> None:
        documents = {
            str(index): str(getattr(item, "summary", "") or "")
            for index, item in enumerate(items)
        }
        limited, truncated, _dropped = cls._limit_document_map(
            documents,
            total_chars=total_chars,
            per_document=total_chars,
        )
        for index, item in enumerate(items):
            item.summary = limited.get(str(index), "")
        truncated_documents.extend(f"{label}:{index}" for index in truncated)

    @staticmethod
    def _limit_document_map(
        documents: Dict[str, str],
        *,
        total_chars: int,
        per_document: int,
        preferred_prefixes: tuple[str, ...] = (),
    ) -> tuple[Dict[str, str], List[str], List[str]]:
        def priority(item: tuple[str, str]) -> tuple[int, str]:
            name = item[0]
            rank = next(
                (index for index, prefix in enumerate(preferred_prefixes) if name.startswith(prefix)),
                len(preferred_prefixes),
            )
            return rank, name

        ordered = [
            (name, content)
            for name, content in sorted(documents.items(), key=priority)
            if content
        ]
        kept: Dict[str, str] = {}
        truncated: List[str] = []
        dropped: List[str] = []
        if not ordered or total_chars <= 0:
            return kept, truncated, [name for name, _ in ordered]

        # Give every relevant document a fair base allocation before assigning
        # spare capacity by priority. Filename order must never erase a whole
        # character merely because earlier profiles filled the bucket first.
        base_cap = min(per_document, max(1, total_chars // len(ordered)))
        used = 0
        for name, content in ordered:
            fitted = content[:base_cap]
            if fitted:
                kept[name] = fitted
                used += len(fitted)
            else:
                dropped.append(name)

        remaining = max(0, total_chars - used)
        for name, content in ordered:
            if remaining <= 0 or name not in kept:
                break
            current = kept[name]
            extra = min(per_document - len(current), len(content) - len(current), remaining)
            if extra > 0:
                kept[name] = content[: len(current) + extra]
                remaining -= extra

        for name, content in ordered:
            if name in kept and len(kept[name]) < len(content):
                truncated.append(name)
        return kept, truncated, dropped

    @staticmethod
    def _packet_character_count(packet: ChapterAssemblyPacket) -> int:
        return sum(len(item) for item in ChapterAssemblerV2._packet_text_values(packet))

    @staticmethod
    def _packet_token_count(packet: ChapterAssemblyPacket) -> int:
        return sum(
            estimate_text_tokens(item)
            for item in ChapterAssemblerV2._packet_text_values(packet)
        )

    @staticmethod
    def _packet_text_values(packet: ChapterAssemblyPacket) -> List[str]:
        core_values = (
            list(packet.core_documents.values())
            if packet.core_documents
            else [packet.story_background]
        )
        setting_values = list(
            (packet.setting_documents or packet.concept_documents).values()
        )
        continuity_values = (
            list(packet.continuity_documents.values())
            if packet.continuity_documents
            else [packet.current_state, packet.ledger, packet.relationships]
        )
        values: List[str] = [
            packet.author_intent,
            packet.creative_focus,
            *core_values,
            packet.previous_chapter_content,
            packet.protagonist_state,
            *packet.character_documents.values(),
            *setting_values,
            *continuity_values,
            *packet.style_documents.values(),
        ]
        values.extend(item.summary for item in packet.historical_arc_summaries)
        values.extend(item.summary for item in packet.current_arc_sections)
        return values

    def _load_story_control(self, filename: str, *, max_chars: int) -> str:
        path = self.src_root / "story" / filename
        text = self._load_text(path).strip() if path.exists() else ""
        return text

    def _load_core_documents(self) -> Dict[str, str]:
        documents: Dict[str, str] = {}
        for key in ("background", "foundation"):
            path = self.src_root / "story" / f"{key}.md"
            text = self._load_text(path).strip() if path.exists() else ""
            if text:
                documents[key] = text
        return documents

    def _load_protagonist_state(self, hierarchy: OutlineHierarchy, chapter_id: str) -> str:
        truth = self.truth_manager.load_truth_files()
        current_state = truth.current_state or ""
        if not current_state.strip():
            return ""

        protagonist = self._detect_protagonist_name(hierarchy, chapter_id)
        if not protagonist:
            return current_state[:1200]

        pattern = rf"^##\s*{re.escape(protagonist)}(?:状态)?\s*$"
        lines = current_state.splitlines()
        out: List[str] = []
        in_block = False
        for line in lines:
            if re.match(pattern, line.strip()):
                in_block = True
                out.append(line)
                continue
            if in_block and line.startswith("## "):
                break
            if in_block:
                out.append(line)

        if out:
            return "\n".join(out).strip()
        return current_state[:1200]

    def _detect_protagonist_name(self, hierarchy: OutlineHierarchy, chapter_id: str) -> str:
        candidates = self._collect_relevant_characters(hierarchy, chapter_id)
        for cid in candidates:
            doc = self._load_character_documents([cid]).get(cid, "")
            if "主角" in doc:
                return cid
        for path in sorted((self.src_root / "characters").glob("*.md")):
            text = self._load_text(path)
            meta, body = parse_toml_front_matter(text)
            if str(meta.get("tier") or meta.get("role") or "").strip() == "主角":
                heading = next(
                    (
                        line[2:].strip()
                        for line in body.splitlines()
                        if line.startswith("# ")
                    ),
                    "",
                )
                return str(meta.get("name") or heading or path.stem)
        return candidates[0] if candidates else ""

    def _load_hierarchy(self) -> OutlineHierarchy:
        outline_src = self.src_root / "outline.md"
        if outline_src.exists():
            text = self._load_text(outline_src)
            if text.strip():
                return OutlineMdParser().parse(text, self.novel_id)

        path = self.runtime_root / "hierarchy.yaml"
        if not path.exists():
            return OutlineHierarchy(novel_id=self.novel_id)

        data = self._load_yaml(path)
        return deserialize_outline_hierarchy(data, self.novel_id)

    def _build_story_background(self, hierarchy: OutlineHierarchy) -> str:
        story_background = self.story_planning_store.read_story_document("background", max_chars=1600)
        foundation = self.story_planning_store.read_story_document("foundation", max_chars=1200)
        if story_background or foundation:
            merged = "\n\n".join(part for part in [story_background, foundation] if part)
            return self._fit_text(merged, min_chars=500, max_chars=1000)

        master = hierarchy.master
        chunks: List[str] = []
        if master:
            if master.title:
                chunks.append(f"作品：{master.title}")
            if master.core_theme:
                chunks.append(f"核心主题：{master.core_theme}")
            if master.world_premise:
                chunks.append(f"世界前提：{master.world_premise}")

        arc_lines: List[str] = []
        for arc in hierarchy.arcs[:3]:
            arc_lines.append(f"{arc.title}：{arc.summary}")
        if arc_lines:
            chunks.append("当前主线推进：" + "；".join(arc_lines))

        text = "\n".join(chunks)
        return self._fit_text(text, min_chars=500, max_chars=1000)

    def _build_historical_arc_summaries(self, hierarchy: OutlineHierarchy, current_arc_id: str) -> List[ArcSummary]:
        result: List[ArcSummary] = []
        current_index = next((i for i, a in enumerate(hierarchy.arcs) if a.node_id == current_arc_id), len(hierarchy.arcs))

        for i, arc in enumerate(hierarchy.arcs):
            if i > current_index:
                break
            chapter_summaries = self._collect_chapter_summaries(
                hierarchy,
                [chapter.node_id for chapter in hierarchy.get_chapters_by_arc(arc.node_id)],
            )
            seed = "\n".join(
                [
                    f"篇标题：{arc.title}",
                    f"篇梗概：{arc.summary}",
                    f"章节推进：{chapter_summaries}",
                ]
            )
            result.append(
                ArcSummary(
                    arc_id=arc.node_id,
                    title=arc.title,
                    summary=self._fit_text(seed, min_chars=1000, max_chars=2000),
                )
            )
        return result

    def _build_current_arc_section_summaries(self, hierarchy: OutlineHierarchy, chapter_id: str) -> List[SectionSummary]:
        current_arc = hierarchy.get_parent_arc(chapter_id)
        if not current_arc:
            return []

        sections = [s for s in hierarchy.sections if s.parent_id == current_arc.node_id]
        result: List[SectionSummary] = []

        for sec in sections:
            sec_chapters = [ch for ch in hierarchy.chapters if ch.node_id in sec.children_ids]
            sec_text = self._collect_chapter_summaries(hierarchy, sec.children_ids)
            summary_seed = "\n".join(
                [
                    f"节标题：{sec.title}",
                    f"节梗概：{sec.summary}",
                    f"章节推进：{sec_text}",
                ]
            )

            involved_chars: List[str] = []
            involved_concepts: List[str] = []
            for ch in sec_chapters:
                involved_chars.extend(ch.involved_characters)
                involved_concepts.extend(ch.involved_settings)

            result.append(
                SectionSummary(
                    section_id=sec.node_id,
                    title=sec.title,
                    summary=self._fit_text(summary_seed, min_chars=500, max_chars=1000),
                    involved_characters=self._dedupe(involved_chars),
                    involved_concepts=self._dedupe(involved_concepts),
                )
            )

        return result

    def _collect_relevant_characters(self, hierarchy: OutlineHierarchy, chapter_id: str) -> List[str]:
        chapter = hierarchy.get_node(chapter_id)
        if chapter is None:
            return []

        chapter_text = "\n".join(
            [
                chapter.title,
                chapter.summary,
                chapter.content_focus,
                *chapter.goals,
                *chapter.beats,
                *chapter.hooks,
                self._load_current_chapter_content(chapter_id),
            ]
        )
        character_root = self.src_root / "characters"
        inferred: list[tuple[int, str]] = []
        for path in sorted(character_root.glob("*.md")):
            text = self._load_text(path)
            meta, body = parse_toml_front_matter(text)
            heading = ""
            for line in body.splitlines():
                if line.startswith("# "):
                    heading = line[2:].strip()
                    break
            positions = [
                chapter_text.find(identifier)
                for identifier in shared_document_lookup_keys(path, content=text)
                if identifier and identifier in chapter_text
            ]
            if positions:
                inferred.append(
                    (
                        min(positions),
                        str(meta.get("name") or heading or path.stem).strip(),
                    )
                )
        return self._dedupe(
            list(chapter.involved_characters)
            + [name for _, name in sorted(inferred)]
        )

    def _collect_relevant_concepts(self, hierarchy: OutlineHierarchy, chapter_id: str) -> List[str]:
        chapter = hierarchy.get_node(chapter_id)
        if chapter is None:
            return []

        section = hierarchy.get_parent_section(chapter_id)
        if section is None:
            return list(chapter.involved_settings)

        concepts: List[str] = []
        for ch_id in section.children_ids:
            node = hierarchy.get_node(ch_id)
            if node:
                concepts.extend(node.involved_settings)
        return self._dedupe(concepts)

    def _load_previous_chapter_content(self, chapter_id: str) -> str:
        idx = self._parse_chapter_index(chapter_id)
        if idx <= 1:
            return ""

        prev = f"ch_{idx - 1:03d}"
        manuscript_root = self.runtime_root / "manuscript"
        for path in sorted(manuscript_root.glob("arc_*/" + prev + "*.md")):
            text = self._load_text(path)
            if text:
                return strip_character_state_annotations(text)
        return ""

    def _load_current_chapter_content(self, chapter_id: str) -> str:
        manuscript_root = self.runtime_root / "manuscript"
        for pattern in (f"{chapter_id}.md", f"{chapter_id}_*.md"):
            matches = sorted(manuscript_root.rglob(pattern))
            if matches:
                return strip_character_state_annotations(
                    self._load_text(matches[0])
                )
        return ""

    def _load_character_documents(self, character_ids: List[str]) -> Dict[str, str]:
        docs: Dict[str, str] = {}
        character_root = self.src_root / "characters"
        for char_id in character_ids:
            src_path = resolve_shared_document_path(character_root, char_id) or (
                character_root / f"{char_id}.md"
            )
            if src_path.exists():
                docs[char_id] = self._load_text(src_path).strip()
                continue

            profile_path = self.runtime_root / "characters" / "profiles" / f"{char_id}.md"
            if profile_path.exists():
                docs[char_id] = self._load_text(profile_path).strip()
                continue

            card_path = self.runtime_root / "characters" / "cards" / f"{char_id}.yaml"
            if card_path.exists():
                card = self._load_yaml(card_path)
                docs[char_id] = yaml.safe_dump(card, allow_unicode=True, sort_keys=False)

        return docs

    def _load_all_style_documents(
        self,
        *,
        chapter_id: str = "",
        arc_id: str = "",
    ) -> Dict[str, str]:
        docs: Dict[str, str] = {}

        composed = self.runtime_root / "style" / "composed.md"
        if composed.exists():
            docs["work.composed"] = self._load_text(composed)

        manifest = self.runtime_root / "style" / "manifest.toml"
        if manifest.exists():
            docs["work.manifest"] = render_style_manifest_summary(self._load_text(manifest))

        fingerprint = self.runtime_root / "style" / "fingerprint.yaml"
        if fingerprint.exists():
            docs["work.fingerprint"] = self._load_text(fingerprint)

        scoped = self._load_scoped_style_rules(chapter_id=chapter_id, arc_id=arc_id)
        if scoped:
            docs["work.scoped"] = scoped

        craft_dir = resolve_craft_dir(self.project_root)
        if craft_dir.exists():
            for p in sorted(craft_dir.glob("*")):
                if p.suffix in {".md", ".yaml", ".yml"}:
                    docs[f"craft.{p.stem}"] = self._load_text(p)

        style_name = self.style_id or self.novel_id
        source_dir = self.runtime_root / "sources" / style_name / "style"
        if not composed.exists() and source_dir.exists():
            for p in sorted(source_dir.glob("*")):
                if p.suffix in {".md", ".yaml", ".yml"}:
                    docs[f"source.{p.stem}"] = self._load_text(p)

        return docs

    def _load_scoped_style_rules(self, *, chapter_id: str, arc_id: str) -> str:
        path = self.runtime_root / "style" / "recipe.yaml"
        if not path.is_file():
            return ""
        data = self._load_yaml(path)
        selections = data.get("selections") if isinstance(data, dict) else []
        if not isinstance(selections, list):
            return ""
        sections: dict[str, list[str]] = {
            "当前范围主风格": [],
            "当前范围辅助技法": [],
            "当前范围禁止": [],
        }
        for item in selections:
            if not isinstance(item, dict):
                continue
            scope = str(item.get("scope") or "project")
            scope_id = str(item.get("scope_id") or "")
            if scope == "project":
                continue
            if scope == "arc" and scope_id != arc_id:
                continue
            if scope == "chapter" and scope_id != chapter_id:
                continue
            role = str(item.get("role") or "auxiliary")
            if role == "validation_only":
                continue
            claim = str(item.get("claim") or "").strip()
            if not claim:
                continue
            if role == "avoid":
                sections["当前范围禁止"].append(claim)
            elif role == "primary":
                sections["当前范围主风格"].append(claim)
            else:
                sections["当前范围辅助技法"].append(claim)
        parts = [
            f"## {title}\n" + "\n".join(f"- {item}" for item in items)
            for title, items in sections.items()
            if items
        ]
        return "\n\n".join(parts)

    def _load_setting_documents(self, concept_names: List[str]) -> Dict[str, str]:
        docs: Dict[str, str] = {}

        world_root = self.src_root / "world"
        if not world_root.exists():
            return docs

        for base_name in ["rules.md", "terminology.md", "timeline.md"]:
            p = world_root / base_name
            if p.exists():
                docs[f"world.{p.stem}"] = self._load_text(p).strip()

        entities = world_root / "entities"
        if entities.exists():
            concept_set = {c.lower() for c in concept_names}
            for p in sorted(entities.rglob("*.md")):
                text = self._load_text(p)
                if not concept_set:
                    continue
                stem = p.stem.lower()
                if stem in concept_set or any(c in text.lower() for c in concept_set):
                    docs[f"entity.{p.stem}"] = text.strip()

        return docs

    def _load_concept_documents(self, concept_names: List[str]) -> Dict[str, str]:
        """Compatibility alias for callers that still use the legacy term."""
        return self._load_setting_documents(concept_names)

    def _collect_chapter_summaries(self, hierarchy: OutlineHierarchy, chapter_ids: List[str]) -> str:
        lines: List[str] = []
        chapter_map = {c.node_id: c for c in hierarchy.chapters}
        for ch_id in chapter_ids:
            node = chapter_map.get(ch_id)
            if not node:
                continue
            focus = node.content_focus or node.summary
            lines.append(f"{node.title}（{ch_id}，{node.dramatic_position}）：{focus}")
        return "\n".join(lines)

    def _fit_text(self, text: str, min_chars: int, max_chars: int) -> str:
        cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(cleaned) > max_chars:
            return cleaned[:max_chars] + "..."
        if len(cleaned) < min_chars and cleaned:
            return cleaned
        return cleaned

    def _dedupe(self, values: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for v in values:
            vv = (v or "").strip()
            if not vv or vv in seen:
                continue
            seen.add(vv)
            out.append(vv)
        return out

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _load_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _parse_chapter_index(self, chapter_id: str) -> int:
        m = re.search(r"(\d+)", chapter_id)
        return int(m.group(1)) if m else 0
