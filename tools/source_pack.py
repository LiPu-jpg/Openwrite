"""Novel-only source extraction, review and promotion service."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from tools.frontmatter import (
    compose_toml_document,
    parse_toml_front_matter,
    strip_front_matter_padding,
)
from tools.shared_documents import normalize_world_entity_document, render_indexed_document
from tools.utils import generate_id

logger = logging.getLogger(__name__)


class SourcePackService:
    """Own the source-pack lifecycle independently from CLI and UI adapters."""

    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id

    def source_root(self, source_id: str) -> Path:
        return (
            self.project_root
            / "data"
            / "novels"
            / self.novel_id
            / "data"
            / "sources"
            / source_id
        )

    def extract(
        self,
        source_id: str,
        source_file: Path,
        *,
        focus: str,
        chunk_size: int = 30000,
    ) -> dict[str, Any]:
        from tools.llm import LLMClient, LLMConfig, Message
        from tools.style_extraction_pipeline import StyleExtractionPipeline

        pipeline = StyleExtractionPipeline(
            project_root=self.project_root,
            novel_id=self.novel_id,
            source_name=source_id,
            chunk_size=chunk_size,
        )
        try:
            progress = pipeline.prepare(source_file=source_file)
        except Exception as exc:
            return {
                "ok": False,
                "blocked": True,
                "error": "prepare_failed",
                "message": str(exc),
                "source_id": source_id,
                "source_file": str(source_file),
            }

        client = LLMClient(LLMConfig.from_env())
        prompt = self._analysis_prompt(focus)
        processed = 0
        for batch in progress.batches:
            if batch.status != "pending":
                continue
            try:
                context = pipeline.get_batch_context(batch.chunk_index)
                chunk_text = str(context["chunk_text"])
                if len(chunk_text) > 8000:
                    chunk_text = chunk_text[:8000] + "..."
                response = client.chat(
                    [
                        Message("system", prompt),
                        Message("user", f"请分析以下文本片段：\n\n{chunk_text}"),
                    ],
                    temperature=0.3,
                    stream=False,
                )
                findings = self._parse_findings(response.content)
            except Exception as exc:
                logger.warning("source chunk %s failed: %s", batch.chunk_index, exc)
                findings = {
                    "craft": [],
                    "author": [],
                    "novel": [],
                    "summary": f"错误: {exc}",
                }
            try:
                pipeline.save_batch_result(batch.chunk_index, findings)
                processed += 1
            except Exception as exc:
                logger.warning("source chunk %s could not be saved: %s", batch.chunk_index, exc)

        if processed == 0:
            return {
                "ok": True,
                "blocked": False,
                "next_action": "review_source_pack",
                "source_id": source_id,
                "source_root": str(pipeline.source_dir),
                "processed_batches": 0,
                "message": "没有处理任何chunk（可能都已完成）",
            }
        try:
            merged = pipeline.merge_all()
        except Exception as exc:
            return {
                "ok": False,
                "blocked": True,
                "error": "merge_failed",
                "message": str(exc),
                "source_id": source_id,
                "source_root": str(pipeline.source_dir),
            }
        self.refresh_documents(source_id)
        return {
            "ok": True,
            "blocked": False,
            "next_action": "review_source_pack",
            "source_id": source_id,
            "source_root": str(pipeline.source_dir),
            "processed_batches": processed,
            "total_batches": merged.get("total_batches", processed),
            "focus": focus,
        }

    def render_review(self, source_id: str) -> str:
        root = self.source_root(source_id)
        source_path = root / "source.md"
        setting_path = root / "setting_profile.md"
        progress_path = root / "extraction" / "progress.json"
        style_dir = root / "style"
        progress: dict[str, Any] = {}
        if progress_path.exists():
            try:
                loaded = json.loads(progress_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    progress = loaded
            except (OSError, json.JSONDecodeError):
                progress = {}
        parts = [f"# 来源审阅：{source_id}", ""]
        if progress:
            parts.extend(
                [
                    f"- 状态: {progress.get('current_phase', 'unknown')}",
                    f"- 已完成: {progress.get('completed_count', 0)}",
                    f"- 待处理: {progress.get('pending_count', 0)}",
                    f"- 进度: {progress.get('progress_pct', 0)}%",
                    "",
                ]
            )
        if source_path.exists():
            parts.extend(
                [
                    "## 来源说明",
                    render_indexed_document(
                        source_path.read_text(encoding="utf-8"), max_chars=1200
                    ),
                    "",
                ]
            )
        if setting_path.exists():
            parts.extend(
                [
                    "## 设定提要",
                    render_indexed_document(
                        setting_path.read_text(encoding="utf-8"), max_chars=1400
                    ),
                    "",
                ]
            )
        style_files = sorted(path.name for path in style_dir.glob("*.md"))
        if style_files:
            parts.append("## 已生成风格文档")
            parts.extend(f"- {name}" for name in style_files)
        return "\n".join(parts).strip() + "\n"

    def promote(self, source_id: str, target: str) -> list[str]:
        promoted: list[str] = []
        if target in {"style", "all"}:
            self._promote_style(source_id)
            promoted.append("style")
        if target in {"setting", "all"}:
            self._promote_setting(source_id)
            promoted.append("setting")
        if target in {"world", "all"}:
            self._promote_world(source_id)
            promoted.append("world")
        return promoted

    def refresh_documents(self, source_id: str) -> None:
        root = self.source_root(source_id)
        findings = self._collect_findings(root)
        craft = findings["craft"]
        author = findings["author"]
        novel = findings["novel"]
        summaries = findings["summaries"]
        source_summary = summaries[0] if summaries else f"{source_id} 的提取来源说明。"
        root.mkdir(parents=True, exist_ok=True)
        source_meta = {
            "id": source_id,
            "kind": "source",
            "source_type": "user_supplied_text",
            "legal": "user_provided",
            "usage": "style_and_setting_reference",
            "status": "extracted",
            "detail_refs": ["summary", "usage_notes", "promotion_notes"],
            "summary": source_summary,
        }
        source_body = (
            "# 来源说明\n\n## summary\n\n"
            f"{source_summary}\n\n## usage_notes\n\n"
            "- 只提取可复用的风格和设定组织方式。\n"
            "- 不直接照搬来源专名、桥段、角色口头禅或签名式表达。\n\n"
            "## promotion_notes\n\n"
            "- 可把 style 侧晋升为当前项目的 style_id。\n"
            "- 可把 setting_profile 中经人工确认的内容晋升到 foundation。\n"
        )
        (root / "source.md").write_text(
            compose_toml_document(source_meta, source_body), encoding="utf-8"
        )
        premise = summaries[:3] or novel[:3]
        rules = self._pick(novel, ("规则", "限制", "代价", "必须", "体系", "机制"), 8)
        factions = self._pick(novel, ("组织", "公司", "部门", "门派", "势力", "阵营"), 6, [])
        characters = self._pick(novel, ("角色", "主角", "人物", "同事", "伙伴", "敌人"), 6, [])
        timeline = self._pick(novel, ("过去", "曾经", "后来", "之前", "时间", "事件"), 6, [])
        setting_meta = {
            "id": source_id,
            "kind": "setting_profile",
            "status": "extracted",
            "detail_refs": [
                "premise",
                "rules",
                "factions",
                "characters",
                "timeline",
                "promotion_notes",
            ],
            "summary": premise[0] if premise else f"{source_id} 的设定提要。",
        }
        setting_body = self._render_setting_body(
            premise, rules, factions, characters, timeline
        )
        (root / "setting_profile.md").write_text(
            compose_toml_document(setting_meta, setting_body), encoding="utf-8"
        )
        self._write_style_documents(
            root,
            source_id,
            source_summary,
            craft,
            author,
            novel,
            int(findings["batch_count"]),
        )

    @staticmethod
    def _analysis_prompt(focus: str) -> str:
        specialty = (
            "重点识别世界前提、规则、组织、角色关系、时间线与约束条件。"
            if focus == "setting"
            else "重点识别叙述方式、句式、节奏、对话与可复用写作技法。"
        )
        return (
            "你是专业的长篇小说风格与设定分析师。"
            f"{specialty}\n"
            "区分跨作品技法、作者风格和来源作品专属设定；禁止建议直接仿写。\n"
            "只返回 JSON："
            '{"craft":[],"author":[],"novel":[],"summary":"50字内摘要"}'
        )

    @staticmethod
    def _parse_findings(content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("source findings must be a JSON object")
        return parsed

    @staticmethod
    def _normalize_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        return list(dict.fromkeys(items))

    def _collect_findings(self, root: Path) -> dict[str, Any]:
        craft: list[str] = []
        author: list[str] = []
        novel: list[str] = []
        summaries: list[str] = []
        batch_count = 0
        for path in sorted((root / "extraction" / "batch_results").glob("batch_*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            findings = data.get("findings", {}) or {}
            batch_count += 1
            craft.extend(self._normalize_list(findings.get("craft")))
            author.extend(self._normalize_list(findings.get("author")))
            novel.extend(self._normalize_list(findings.get("novel")))
            summary = str(findings.get("summary") or "").strip()
            if summary:
                summaries.append(summary)
        return {
            "craft": self._dedupe(craft),
            "author": self._dedupe(author),
            "novel": self._dedupe(novel),
            "summaries": self._dedupe(summaries),
            "batch_count": batch_count,
        }

    @staticmethod
    def _pick(
        items: list[str],
        keywords: tuple[str, ...],
        limit: int,
        fallback: list[str] | None = None,
    ) -> list[str]:
        matched = [item for item in items if any(key in item for key in keywords)]
        return (matched or (items if fallback is None else fallback))[:limit]

    @staticmethod
    def _bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- （待补充）"

    def _render_setting_body(
        self,
        premise: list[str],
        rules: list[str],
        factions: list[str],
        characters: list[str],
        timeline: list[str],
    ) -> str:
        return (
            "# 设定提要\n\n## premise\n\n"
            f"{self._bullets(premise)}\n\n## rules\n\n{self._bullets(rules)}\n\n"
            f"## factions\n\n{self._bullets(factions)}\n\n"
            f"## characters\n\n{self._bullets(characters)}\n\n"
            f"## timeline\n\n{self._bullets(timeline)}\n\n"
            "## promotion_notes\n\n"
            "- 先人工审阅，再决定是否晋升到 foundation 或 world 文档。\n"
            "- 专有名词和来源绑定内容默认只保留为灵感记录。\n"
        )

    def _write_style_documents(
        self,
        root: Path,
        source_id: str,
        summary: str,
        craft: list[str],
        author: list[str],
        novel: list[str],
        batch_count: int,
    ) -> None:
        style_dir = root / "style"
        style_dir.mkdir(parents=True, exist_ok=True)
        reusable = self._dedupe(author + craft)
        bound = novel[:10]
        documents = {
            "summary.md": (
                f"# 风格总结\n\n> 来源 ID: {source_id}\n\n## summary\n\n{summary}\n\n"
                f"## reusable_signals\n\n{self._bullets(reusable[:12])}\n\n"
                f"## source_bound_signals\n\n{self._bullets(bound)}\n\n"
                f"## extraction_notes\n\n- 已处理批次：{batch_count}\n"
            ),
            "voice.md": "# 叙述声音 (Voice)\n\n## 候选信号\n\n"
            + self._bullets(self._pick(author, ("视角", "叙述", "旁白", "口吻"), 8)),
            "language.md": "# 语言风格 (Language)\n\n## 候选信号\n\n"
            + self._bullets(self._pick(reusable, ("句", "词", "比喻", "语言", "口语"), 10)),
            "rhythm.md": "# 节奏风格 (Rhythm)\n\n## 候选信号\n\n"
            + self._bullets(self._pick(reusable, ("节奏", "段落", "推进", "切换"), 10)),
            "dialogue.md": "# 对话风格 (Dialogue)\n\n## 候选信号\n\n"
            + self._bullets(self._pick(reusable, ("对话", "角色声音", "口头禅", "台词"), 10)),
            "consistency.md": (
                "# 一致性规则 (Consistency)\n\n## 禁止直接搬运\n\n"
                "- 不直接照搬来源中的专有名词、招牌桥段和签名式句法。\n\n"
                f"## 来源绑定内容\n\n{self._bullets(bound)}\n"
            ),
        }
        for filename, content in documents.items():
            (style_dir / filename).write_text(content.rstrip() + "\n", encoding="utf-8")

    def _promote_style(self, source_id: str) -> None:
        from tools.style_synthesizer import synthesize_style_document

        config_path = self.project_root / "novel_config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        config["style_id"] = source_id
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        synthesize_style_document(self.project_root, self.novel_id, source_id)

    def _promote_setting(self, source_id: str) -> None:
        from tools.story_planning import StoryPlanningStore

        path = self.source_root(source_id) / "setting_profile.md"
        if not path.exists():
            raise RuntimeError(f"未找到 setting_profile.md: {path}")
        text = path.read_text(encoding="utf-8")
        meta, body = parse_toml_front_matter(text)
        source_body = strip_front_matter_padding(body if meta else text)
        promoted = self._demote(self._strip_heading(source_body))
        store = StoryPlanningStore(self.project_root, self.novel_id)
        foundation = str(store.load_story_document("foundation").get("body") or "").strip()
        background = str(store.load_story_document("background").get("body") or "").strip()
        merged = self._upsert(
            foundation or "# 基础设定\n\n（待补充）\n",
            f"## 来源提取：{source_id}",
            promoted or "（待补充）",
        )
        store.save_foundation_draft(
            background or "# 故事背景\n\n（待补充）\n", merged
        )

    def _promote_world(self, source_id: str) -> None:
        path = self.source_root(source_id) / "setting_profile.md"
        if not path.exists():
            raise RuntimeError(f"未找到 setting_profile.md: {path}")
        text = path.read_text(encoding="utf-8")
        meta, body = parse_toml_front_matter(text)
        source_body = strip_front_matter_padding(body if meta else text)
        premise = self._section(source_body, "premise")
        rules = self._list(source_body, "rules")
        factions = self._list(source_body, "factions")
        timeline = self._list(source_body, "timeline")
        world_root = self.project_root / "data" / "novels" / self.novel_id / "src" / "world"
        rules_content = "\n\n".join(
            part
            for part in (
                f"### premise\n\n{premise}" if premise else "",
                "### rules\n\n" + "\n".join(f"- {item}" for item in rules) if rules else "",
            )
            if part
        )
        if rules_content:
            self._update_world_document(
                world_root / "rules.md",
                f"## 来源提取：{source_id}",
                rules_content,
                "世界规则",
            )
        if timeline:
            self._update_world_document(
                world_root / "timeline.md",
                f"## 来源提取：{source_id}",
                "\n".join(f"- {item}" for item in timeline),
                "时间线",
            )
        self._promote_entities(source_id, factions)

    def _promote_entities(self, source_id: str, factions: list[str]) -> None:
        root = (
            self.project_root
            / "data"
            / "novels"
            / self.novel_id
            / "src"
            / "world"
            / "entities"
        )
        root.mkdir(parents=True, exist_ok=True)
        for item in factions:
            name, description = self._named_item(item)
            if not name:
                continue
            entity_id = generate_id(name, "organization")
            target = root / f"{entity_id}.md"
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            base = existing.strip() or f"# {name}\n\n{description or '（待补充）'}\n"
            updated = self._upsert(
                base, f"## 来源提取：{source_id}", description or "（待补充）"
            )
            target.write_text(
                normalize_world_entity_document(
                    updated,
                    fallback_id=entity_id,
                    fallback_name=name,
                    fallback_summary=description or f"{name}相关设定来源于 {source_id}。",
                    default_type="组织",
                    default_subtype="阵营",
                ),
                encoding="utf-8",
            )

    def _update_world_document(
        self, path: Path, heading: str, content: str, default_heading: str
    ) -> None:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            meta, body = parse_toml_front_matter(text)
            document_meta = meta or {
                "id": path.stem,
                "type": "world_document",
                "summary": default_heading,
                "detail_refs": [default_heading],
            }
            document_body = strip_front_matter_padding(body if meta else text)
        else:
            document_meta = {
                "id": path.stem,
                "type": "world_document",
                "summary": default_heading,
                "detail_refs": [default_heading],
            }
            document_body = f"# {default_heading}\n\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            compose_toml_document(
                document_meta, self._upsert(document_body, heading, content)
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _strip_heading(text: str) -> str:
        lines = text.strip().splitlines()
        if lines and lines[0].lstrip().startswith("#"):
            lines = lines[1:]
        return "\n".join(lines).strip()

    @staticmethod
    def _demote(text: str) -> str:
        return "\n".join("#" + line if line.startswith("#") else line for line in text.splitlines())

    @staticmethod
    def _upsert(body: str, heading: str, content: str) -> str:
        block = f"{heading}\n\n{content.strip()}"
        normalized = body.strip()
        pattern = re.compile(rf"(?ms)^{re.escape(heading)}\n.*?(?=^##\s+|\Z)")
        if pattern.search(normalized):
            return pattern.sub(block + "\n\n", normalized).strip() + "\n"
        return (normalized.rstrip() + "\n\n" + block).strip() + "\n"

    @staticmethod
    def _section(text: str, heading: str) -> str:
        match = re.search(
            rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^\s*##\s+|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        return match.group(1).strip() if match else ""

    @classmethod
    def _list(cls, text: str, heading: str) -> list[str]:
        return [
            line.strip()[2:].strip()
            for line in cls._section(text, heading).splitlines()
            if line.strip().startswith(("- ", "* "))
        ]

    @staticmethod
    def _named_item(item: str) -> tuple[str, str]:
        text = item.strip()
        for separator in ("：", ":", "——", "—", "-", "–"):
            if separator in text:
                left, right = text.split(separator, 1)
                if left.strip():
                    return left.strip(), right.strip()
        return text, ""
