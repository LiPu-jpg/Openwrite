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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

import yaml

from models.outline import OutlineHierarchy, OutlineNode, OutlineNodeType
from tools.agent_policy import get_default_agent_specs, get_redundant_agent_specs
from tools.frontmatter import parse_toml_front_matter
from tools.outline_cache import deserialize_outline_hierarchy
from tools.outline_parser import OutlineMdParser
from tools.shared_documents import render_indexed_document, resolve_shared_document_path
from tools.source_sync import ensure_runtime_fresh
from tools.style_synthesizer import render_style_manifest_summary
from tools.story_planning import StoryPlanningStore
from tools.truth_manager import TruthFilesManager


ROLE_SYSTEM_PROMPTS: Dict[str, str] = {
    "director": (
        "你是写作总导演 Agent。职责：分解目标、分配子任务、检查章节是否符合篇/节弧线，"
        "并对最终文本做一致性裁决。"
    ),
    "context_engineer": (
        "你是上下文工程 Agent。职责：仅基于项目文档组装事实，不虚构设定；"
        "优先保证人物状态、概念定义、前后章节衔接准确。"
    ),
    "writer": (
        "你是创作 Agent。职责：在既定设定内完成章节初稿；遵守戏剧位置与内容焦点，"
        "不越权改动世界规则，不提前泄露未来篇关键真相。"
    ),
    "continuity_reviewer": (
        "你是连续性审查 Agent。职责：检查人物动机、时间线、力量体系、关系演化、伏笔回收，"
        "输出具体问题与修复建议。"
    ),
    "state_settler": (
        "你是状态结算 Agent。职责：从本章提取客观事实并更新状态文件，"
        "禁止新增未发生事件。"
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
    concept_documents: Dict[str, str] = field(default_factory=dict)
    agent_specs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    redundant_agents: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_markdown(self) -> str:
        parts: List[str] = []

        parts.append("## 系统提示词（按职责）")
        for role, prompt in self.system_prompts.items():
            parts.append(f"### {role}\n{prompt}")

        parts.append("## 作者意图")
        parts.append(self.author_intent or "（暂无）")

        parts.append("## 创作罗盘（当前最高优先级）")
        parts.append(self.creative_focus or "（暂无）")

        parts.append("## 故事背景")
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
        parts.append(f"### current_state.md\n{self.current_state or '（暂无）'}")
        parts.append(f"### ledger.md\n{self.ledger or '（暂无）'}")
        parts.append(f"### relationships.md\n{self.relationships or '（暂无）'}")

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

        parts.append("## 概念文档")
        if self.concept_documents:
            for key, content in self.concept_documents.items():
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

        return "\n\n".join(parts)


class ChapterAssemblerV2:
    """章节组装器 V2。"""

    def __init__(self, project_root: Path, novel_id: str, style_id: str = ""):
        self.project_root = project_root.resolve()
        self.novel_id = novel_id
        self.style_id = style_id

        self.novel_root = self.project_root / "data" / "novels" / novel_id
        self.src_root = self.novel_root / "src"
        self.runtime_root = self.novel_root / "data"
        self.story_planning_store = StoryPlanningStore(self.project_root, self.novel_id)
        self.truth_manager = TruthFilesManager(self.project_root, self.novel_id)

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
            current_state=truth.current_state,
            ledger=truth.ledger,
            relationships=truth.relationships,
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
            packet.concept_documents = self._load_concept_documents(concepts)
        else:
            packet.historical_arc_summaries = self._build_historical_arc_summaries(hierarchy, current_arc_id="")

        packet.style_documents = self._load_all_style_documents()
        return packet

    def _load_story_control(self, filename: str, *, max_chars: int) -> str:
        path = self.src_root / "story" / filename
        text = self._load_text(path).strip() if path.exists() else ""
        return text[:max_chars]

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
        section = hierarchy.get_parent_section(chapter_id)
        candidates: List[str] = []
        if section:
            for ch_id in section.children_ids:
                node = hierarchy.get_node(ch_id)
                if node:
                    candidates.extend(node.involved_characters)
        candidates = self._dedupe(candidates)
        for cid in candidates:
            doc = self._load_character_documents([cid]).get(cid, "")
            if "主角" in doc:
                return cid
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
            arc_lines.append(f"{arc.title}：{arc.arc_structure or arc.summary}")
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
                    f"篇弧线：{arc.arc_structure}",
                    f"篇情感：{arc.arc_emotional_arc}",
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
                    f"节结构：{sec.section_structure}",
                    f"节情感：{sec.section_emotional_arc}",
                    f"节张力：{sec.section_tension}",
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

        section = hierarchy.get_parent_section(chapter_id)
        if section is None:
            return list(chapter.involved_characters)

        all_ids = [ch_id for ch_id in section.children_ids]
        current_idx = all_ids.index(chapter_id) if chapter_id in all_ids else len(all_ids)

        appeared: List[str] = []
        future: List[str] = []
        for idx, ch_id in enumerate(all_ids):
            node = hierarchy.get_node(ch_id)
            if not node:
                continue
            if idx <= current_idx:
                appeared.extend(node.involved_characters)
            else:
                future.extend(node.involved_characters)

        main = chapter.involved_characters
        merged = main + appeared + future
        merged = self._dedupe(merged)
        if merged:
            return merged

        chapter_text = "\n".join(
            [
                chapter.title,
                chapter.summary,
                chapter.content_focus,
                *chapter.goals,
                *chapter.beats,
                *chapter.hooks,
            ]
        )
        character_root = self.src_root / "characters"
        inferred: List[str] = []
        for path in sorted(character_root.glob("*.md")):
            meta, body = parse_toml_front_matter(self._load_text(path))
            heading = ""
            for line in body.splitlines():
                if line.startswith("# "):
                    heading = line[2:].strip()
                    break
            identifiers = {
                path.stem,
                str(meta.get("id") or "").strip(),
                str(meta.get("name") or "").strip(),
                heading,
            }
            if any(
                identifier and identifier in chapter_text
                for identifier in identifiers
            ):
                inferred.append(
                    str(meta.get("name") or heading or path.stem).strip()
                )
        return self._dedupe(inferred)

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
                return text
        return ""

    def _load_character_documents(self, character_ids: List[str]) -> Dict[str, str]:
        docs: Dict[str, str] = {}
        character_root = self.src_root / "characters"
        for char_id in character_ids:
            src_path = resolve_shared_document_path(character_root, char_id) or (
                character_root / f"{char_id}.md"
            )
            if src_path.exists():
                docs[char_id] = self._fit_text(
                    render_indexed_document(
                        self._load_text(src_path),
                        default_meta={"name": char_id},
                        max_chars=2200,
                        max_sections=5,
                    ),
                    min_chars=500,
                    max_chars=2200,
                )
                continue

            profile_path = self.runtime_root / "characters" / "profiles" / f"{char_id}.md"
            if profile_path.exists():
                docs[char_id] = self._fit_text(
                    render_indexed_document(
                        self._load_text(profile_path),
                        default_meta={"name": char_id},
                        max_chars=2200,
                        max_sections=5,
                    ),
                    min_chars=500,
                    max_chars=2200,
                )
                continue

            card_path = self.runtime_root / "characters" / "cards" / f"{char_id}.yaml"
            if card_path.exists():
                card = self._load_yaml(card_path)
                docs[char_id] = yaml.safe_dump(card, allow_unicode=True, sort_keys=False)

        return docs

    def _load_all_style_documents(self) -> Dict[str, str]:
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

        craft_dir = self.project_root / "craft"
        if craft_dir.exists():
            for p in sorted(craft_dir.glob("*")):
                if p.suffix in {".md", ".yaml", ".yml"}:
                    docs[f"craft.{p.stem}"] = self._load_text(p)

        style_name = self.style_id or self.novel_id
        source_dir = self.runtime_root / "sources" / style_name / "style"
        if source_dir.exists():
            for p in sorted(source_dir.glob("*")):
                if p.suffix in {".md", ".yaml", ".yml"}:
                    docs[f"source.{p.stem}"] = self._load_text(p)

        return docs

    def _load_concept_documents(self, concept_names: List[str]) -> Dict[str, str]:
        docs: Dict[str, str] = {}

        world_root = self.src_root / "world"
        if not world_root.exists():
            return docs

        world_defaults = {
            "rules.md": {
                "name": "世界规则",
                "summary": "作品的底层规则、限制与未知项。",
                "detail_refs": ["力量体系", "社会规则", "物理法则", "禁忌与未知"],
            },
            "terminology.md": {
                "name": "术语表",
                "summary": "作品内高频术语与概念定义。",
                "detail_refs": ["术语表"],
            },
            "timeline.md": {
                "name": "时间线",
                "summary": "作品当前已知的重要事件顺序。",
                "detail_refs": [],
            },
        }
        for base_name in ["rules.md", "terminology.md", "timeline.md"]:
            p = world_root / base_name
            if p.exists():
                docs[f"world.{p.stem}"] = render_indexed_document(
                    self._load_text(p),
                    default_meta=world_defaults.get(base_name, {"name": p.stem}),
                    max_chars=1800,
                )

        entities = world_root / "entities"
        if entities.exists():
            concept_set = {c.lower() for c in concept_names}
            for p in sorted(entities.glob("*.md")):
                text = self._load_text(p)
                if not concept_set:
                    docs[f"entity.{p.stem}"] = render_indexed_document(
                        text,
                        default_meta={
                            "name": p.stem,
                            "detail_refs": ["规则", "特征", "关联"],
                        },
                        max_chars=1800,
                    )
                    continue
                stem = p.stem.lower()
                if stem in concept_set or any(c in text.lower() for c in concept_set):
                    docs[f"entity.{p.stem}"] = render_indexed_document(
                        text,
                        default_meta={
                            "name": p.stem,
                            "detail_refs": ["规则", "特征", "关联"],
                        },
                        max_chars=1800,
                    )

        return docs

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
