"""Revision-bound, non-canonical multi-branch narrative forecasts for Goethe."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from models.narrative_forecast import ForecastBranchV1, NarrativeForecastV1


class NarrativeForecastError(RuntimeError):
    def __init__(self, message: str, *, code: str = "NARRATIVE_FORECAST_ERROR") -> None:
        super().__init__(message)
        self.code = code


class NarrativeForecastService:
    """Store forecasts under planning without modifying canonical story assets."""

    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.root = self.novel_root / "data" / "planning" / "narrative_forecasts"

    def create(
        self,
        *,
        divergence: str,
        anchor_chapter_id: str,
        branch_count: int = 3,
        horizon: int = 5,
    ) -> NarrativeForecastV1:
        clean_divergence = str(divergence or "").strip()
        if not clean_divergence:
            raise NarrativeForecastError("请先说明需要比较的剧情分歧点", code="EMPTY_DIVERGENCE")
        if len(clean_divergence) > 4000:
            raise NarrativeForecastError("剧情分歧点不能超过 4000 字", code="DIVERGENCE_TOO_LONG")
        clean_anchor_id = str(anchor_chapter_id or "").strip()
        if not clean_anchor_id:
            raise NarrativeForecastError(
                "请先选择分歧点所在的大纲章节",
                code="ANCHOR_CHAPTER_REQUIRED",
            )
        branches = self._bounded_int(branch_count, "branch_count", 2, 5)
        span = self._bounded_int(horizon, "horizon", 1, 10)
        context = self._build_context(span, anchor_chapter_id=clean_anchor_id)
        forecast = NarrativeForecastV1(
            forecast_id=(
                f"forecast_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_"
                f"{uuid4().hex[:8]}"
            ),
            novel_id=self.novel_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            divergence=clean_divergence,
            branch_count=branches,
            horizon=span,
            anchor_chapter_id=context["anchor_chapter_id"],
            anchor_chapter_title=context["anchor_chapter_title"],
            anchor_chapter_status=context["anchor_chapter_status"],
            anchor_chapter_number=context["anchor_chapter_number"],
            anchor_chapter_path=context["anchor_chapter_path"],
            base_chapter=context["base_chapter"],
            outline_revision=context["outline_revision"],
            facts_revision=context["facts_revision"],
            context_fingerprint=context["context_fingerprint"],
            context_brief=context["context_brief"],
        )
        self.save(forecast)
        return forecast

    def list(self, *, limit: int = 20) -> list[NarrativeForecastV1]:
        if not self.root.is_dir():
            return []
        forecasts: list[NarrativeForecastV1] = []
        for path in self.root.glob("forecast_*/forecast.json"):
            forecast = self.load(path.parent.name)
            if forecast is not None:
                forecasts.append(forecast)
        forecasts.sort(key=lambda item: item.created_at, reverse=True)
        return forecasts[: max(1, min(100, int(limit)))]

    def load(self, forecast_id: str) -> NarrativeForecastV1 | None:
        path = self.forecast_path(forecast_id)
        if not path.is_file():
            return None
        try:
            return NarrativeForecastV1.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def get(self, forecast_id: str) -> NarrativeForecastV1:
        forecast = self._require(forecast_id)
        if self.is_stale(forecast) and forecast.state != "stale":
            forecast = forecast.model_copy(update={"state": "stale"})
            self.save(forecast)
        return forecast

    def stage(
        self,
        forecast_id: str,
        branches: Any,
        *,
        forecast_revision: str,
    ) -> NarrativeForecastV1:
        forecast = self._require(forecast_id)
        if forecast_revision != self.revision(forecast):
            raise NarrativeForecastError("剧情推演候选已变化", code="STALE_FORECAST")
        if forecast.state != "candidate":
            raise NarrativeForecastError(
                "只有待生成候选可以写入分支",
                code="FORECAST_NOT_CANDIDATE",
            )
        if self.is_stale(forecast):
            stale = forecast.model_copy(update={"state": "stale"})
            self.save(stale)
            raise NarrativeForecastError(
                "大纲、事实或近期正文已变化，请重新创建剧情推演",
                code="STALE_FORECAST_INPUT",
            )
        if not isinstance(branches, list) or len(branches) != forecast.branch_count:
            raise NarrativeForecastError(
                f"必须提交恰好 {forecast.branch_count} 个剧情分支",
                code="INVALID_BRANCH_COUNT",
            )

        parsed: list[ForecastBranchV1] = []
        try:
            for index, branch in enumerate(branches, start=1):
                if not isinstance(branch, dict):
                    raise ValueError("branch must be an object")
                parsed.append(
                    ForecastBranchV1.model_validate(
                        {**branch, "branch_id": f"branch-{index}"}
                    )
                )
        except (ValidationError, ValueError) as exc:
            raise NarrativeForecastError(
                f"剧情分支结构不符合约定: {exc}",
                code="INVALID_BRANCHES",
            ) from exc

        titles = [branch.title.casefold() for branch in parsed]
        premises = [branch.premise.casefold() for branch in parsed]
        if len(titles) != len(set(titles)) or len(premises) != len(set(premises)):
            raise NarrativeForecastError(
                "各分支必须有不同的标题和前提",
                code="DUPLICATE_BRANCHES",
            )
        try:
            active = NarrativeForecastV1.model_validate(
                {
                    **forecast.model_dump(mode="json"),
                    "state": "active",
                    "branches": [branch.model_dump(mode="json") for branch in parsed],
                }
            )
        except ValidationError as exc:
            raise NarrativeForecastError(
                f"剧情分支结构不符合推演跨度: {exc}",
                code="INVALID_BRANCHES",
            ) from exc
        self.save(active)
        return active

    def select(
        self,
        forecast_id: str,
        branch_id: str,
        *,
        forecast_revision: str,
    ) -> NarrativeForecastV1:
        forecast = self._require(forecast_id)
        if forecast_revision != self.revision(forecast):
            raise NarrativeForecastError("剧情推演已变化，请刷新后重试", code="STALE_FORECAST")
        branch = next(
            (item for item in forecast.branches if item.branch_id == branch_id),
            None,
        )
        if branch is None:
            raise NarrativeForecastError("剧情分支不存在", code="BRANCH_NOT_FOUND")
        stale = self.is_stale(forecast)
        selected_at = datetime.now(timezone.utc).isoformat()
        selected = forecast.model_copy(
            update={
                "state": "stale" if stale else forecast.state,
                "selected_branch_id": branch.branch_id,
                "selected_at": selected_at,
            }
        )
        selected = NarrativeForecastV1.model_validate(selected.model_dump(mode="json"))
        self.save(selected)
        self._atomic_write_text(
            self.selected_plan_path(forecast_id),
            self.render_selected_plan(selected, branch, stale=stale),
        )
        return selected

    def payload(
        self,
        forecast: NarrativeForecastV1,
        *,
        include_context: bool = True,
        current_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        result = forecast.model_dump(mode="json")
        stale = forecast.state == "stale" or (
            (current_fingerprint or self.context_fingerprint())
            != forecast.context_fingerprint
        )
        result["revision"] = self.revision(forecast)
        result["stale"] = stale
        result["effective_state"] = "stale" if stale else forecast.state
        result["comparison_path"] = self._relative(self.comparison_path(forecast.forecast_id))
        result["selected_plan_path"] = (
            self._relative(self.selected_plan_path(forecast.forecast_id))
            if self.selected_plan_path(forecast.forecast_id).is_file()
            else ""
        )
        if include_context:
            result["goethe_brief"] = self.goethe_brief(forecast)
        else:
            result.pop("context_brief", None)
        return result

    def goethe_brief(self, forecast: NarrativeForecastV1) -> str:
        anchor_label = self._forecast_anchor_label(forecast)
        return (
            f"{forecast.context_brief}\n\n"
            "## 本次分歧点\n\n"
            f"- 大纲锚点：{anchor_label}\n"
            f"- 开放决策：{forecast.divergence}\n\n"
            "## 推演要求\n\n"
            f"生成恰好 {forecast.branch_count} 个相互隔离、互斥的候选分支；每个分支覆盖 "
            f"从大纲锚点开始的约 {forecast.horizon} 章。offset 从 1 开始，offset=1 必须对应"
            f"锚点章节 {forecast.anchor_chapter_id or anchor_label}。分支是规划材料，不是正文。\n"
            "每个分支必须包含：title、premise、beats、character_decisions、"
            "projected_changes、risks、uncertainties、intent_alignment。"
            "projected_changes 必须分别给出 characters、relationships、world、"
            "foreshadowing；risk.kind 只能是 continuity、causality、character；"
            "intent_alignment.score 为 0–100 的整数。\n"
            f"完成分析后调用 manage_narrative_forecast(action=stage, forecast_id="
            f"{forecast.forecast_id}, revision={self.revision(forecast)}) 写入结构化 branches。"
            "不要替作者选择分支，也不要修改 canonical 大纲或正文。"
        )

    # Retain only the most recent forecast_* entries. Every `create` writes a new
    # directory and nothing ever deleted one, so a long-lived project
    # accumulated them without bound.
    MAX_RETAINED = 50

    def _prune(self) -> None:
        if not self.root.is_dir():
            return
        entries = sorted(
            (path for path in self.root.glob('forecast_*') if path.is_dir()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for stale in entries[self.MAX_RETAINED:]:
            for child in sorted(stale.rglob('*'), reverse=True):
                try:
                    if child.is_file() or child.is_symlink():
                        child.unlink()
                    else:
                        child.rmdir()
                except OSError:
                    continue
            try:
                stale.rmdir()
            except OSError:
                continue

    def save(self, forecast: NarrativeForecastV1) -> Path:
        directory = self.forecast_dir(forecast.forecast_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = self.forecast_path(forecast.forecast_id)
        self._atomic_write_text(target, forecast.model_dump_json(indent=2))
        if forecast.branches:
            self._atomic_write_text(
                self.comparison_path(forecast.forecast_id),
                self.render_comparison(forecast),
            )
        self._prune()
        return target

    def revision(self, forecast: NarrativeForecastV1) -> str:
        return self._hash(forecast.model_dump(mode="json"))

    def is_stale(self, forecast: NarrativeForecastV1) -> bool:
        return (
            forecast.state == "stale"
            or forecast.context_fingerprint != self.context_fingerprint()
        )

    def context_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in self._canonical_input_paths():
            relative = path.relative_to(self.novel_root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            try:
                digest.update(path.read_bytes())
            except OSError:
                continue
            digest.update(b"\0")
        return "sha256:" + digest.hexdigest()

    def forecast_dir(self, forecast_id: str) -> Path:
        clean = self._clean_forecast_id(forecast_id)
        return self.root / clean

    def forecast_path(self, forecast_id: str) -> Path:
        return self.forecast_dir(forecast_id) / "forecast.json"

    def comparison_path(self, forecast_id: str) -> Path:
        return self.forecast_dir(forecast_id) / "comparison.md"

    def selected_plan_path(self, forecast_id: str) -> Path:
        return self.forecast_dir(forecast_id) / "selected-branch-plan.md"

    def render_comparison(self, forecast: NarrativeForecastV1) -> str:
        lines = [
            f"# 剧情多线推演：{forecast.divergence}",
            "",
            f"- 推演 ID：{forecast.forecast_id}",
            f"- 大纲锚点：{self._forecast_anchor_label(forecast)}",
            f"- 推演跨度：约 {forecast.horizon} 章",
            f"- 生成时间：{forecast.created_at}",
            "",
            "> 本文件是非正史规划材料，不会修改大纲、正文或权威状态。",
            "",
            "| 分支 | 标题 | 意图匹配 | 风险数 | 前提 |",
            "| --- | --- | ---: | ---: | --- |",
        ]
        for branch in forecast.branches:
            lines.append(
                f"| {branch.branch_id} | {self._table_cell(branch.title)} | "
                f"{branch.intent_alignment.score} | {len(branch.risks)} | "
                f"{self._table_cell(branch.premise)} |"
            )
        for branch in forecast.branches:
            lines.extend(["", self._render_branch(branch)])
        return "\n".join(lines).rstrip() + "\n"

    def render_selected_plan(
        self,
        forecast: NarrativeForecastV1,
        branch: ForecastBranchV1,
        *,
        stale: bool,
    ) -> str:
        lines = [
            f"# 已选剧情分支：{branch.title}",
            "",
            f"- 推演 ID：{forecast.forecast_id}",
            f"- 分支：{branch.branch_id}",
            f"- 分歧点：{forecast.divergence}",
            f"- 大纲锚点：{self._forecast_anchor_label(forecast)}",
            f"- 选择时间：{forecast.selected_at}",
        ]
        if stale:
            lines.extend(
                [
                    "",
                    "> [警告] 该推演基于旧的正典上下文，采用前应重新核对。",
                ]
            )
        lines.extend(
            [
                "",
                self._render_branch(branch, include_id=False),
                "",
                "> 选择记录不会修改正典。应用到大纲时仍需单独预览并明确确认。",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _build_context(
        self,
        horizon: int,
        *,
        anchor_chapter_id: str,
    ) -> dict[str, Any]:
        from tools.chapter_memory import ChapterMemoryStore
        from tools.foreshadowing_manager import ForeshadowingDAGManager
        from tools.outline_tree import build_outline_structure
        from tools.story_planning import StoryPlanningStore
        from tools.truth_manager import TruthFilesManager

        outline = build_outline_structure(self.novel_root)
        runtime_state = TruthFilesManager(self.project_root, self.novel_id).load_runtime_state()
        planning = StoryPlanningStore(self.project_root, self.novel_id)
        chapters = self._chapters(outline.get("roots", []))
        anchor_index = next(
            (
                index
                for index, item in enumerate(chapters)
                if str(item.get("id") or "") == anchor_chapter_id
            ),
            -1,
        )
        if anchor_index < 0:
            raise NarrativeForecastError(
                "所选大纲章节不存在，请刷新章节列表后重试",
                code="ANCHOR_CHAPTER_NOT_FOUND",
            )
        anchor = chapters[anchor_index]
        anchor_number = self._chapter_number(anchor_chapter_id) or anchor_index + 1
        base_chapter = max(0, anchor_number - 1)
        chapters_through_anchor = chapters[: anchor_index + 1]
        drafted = [
            item for item in chapters_through_anchor if item.get("status") == "drafted"
        ]

        memory_store = ChapterMemoryStore(self.project_root, self.novel_id)
        summaries: list[str] = []
        for item in drafted[-8:]:
            chapter_id = str(item.get("id") or "")
            memory = memory_store.load(chapter_id) or {}
            summary = str(memory.get("summary") or memory.get("observations") or "").strip()
            if summary:
                summaries.append(f"- {chapter_id}：{summary[:1000]}")

        dag = ForeshadowingDAGManager(self.project_root, self.novel_id)._load_dag()
        unresolved = [
            f"{node.id}：{node.content}"
            for node in dag.nodes.values()
            if dag.status.get(node.id, node.status) in {"埋伏", "待收"}
        ]
        character_state = [
            f"- {item.name}：{item.state or item.location or '状态未记录'}"
            for item in runtime_state.characters.values()
        ]
        relationship_state = [
            f"- {item.source} -> {item.target}：{item.status}"
            for item in runtime_state.relationships.values()
        ]
        preceding_window = chapters[max(0, anchor_index - 5) : anchor_index]
        forecast_window = chapters[anchor_index : anchor_index + horizon]
        anchor_path = tuple(str(item) for item in (anchor.get("path") or []) if item)
        anchor_detail = self._render_outline_chapter(anchor, marker="分歧锚点")
        preceding_outline = [
            self._render_outline_chapter(item) for item in preceding_window
        ]
        forecast_outline = [
            self._render_outline_chapter(
                item,
                marker="offset=1" if index == 0 else f"offset={index + 1}",
            )
            for index, item in enumerate(forecast_window)
        ]

        sections = [
            ("作者意图", planning.read_story_document("author_intent", max_chars=4000)),
            ("当前聚焦", planning.read_story_document("current_focus", max_chars=4000)),
            ("故事背景", planning.read_story_document("background", max_chars=4000)),
            ("基础设定", planning.read_story_document("foundation", max_chars=5000)),
            ("已确认大纲", planning.read_outline_source(max_chars=14000)),
            ("近期章节摘要", "\n".join(summaries)),
            ("人物当前状态", "\n".join(character_state)),
            ("关系当前状态", "\n".join(relationship_state)),
            ("未决伏笔", "\n".join(unresolved[:30])),
        ]
        rendered = [
            f"# 正典推演上下文（锚点：{anchor_chapter_id} {anchor.get('title', '')}）"
        ]
        sections.insert(2, ("分歧锚点章节", anchor_detail))
        sections.insert(3, ("锚点前置章纲", "\n".join(preceding_outline)))
        sections.insert(4, ("锚点及后续推演窗口", "\n".join(forecast_outline)))
        for heading, content in sections:
            clean = str(content or "").strip()
            if clean:
                rendered.extend(["", f"## {heading}", "", clean])
        return {
            "base_chapter": base_chapter,
            "anchor_chapter_id": anchor_chapter_id,
            "anchor_chapter_title": str(anchor.get("title") or anchor_chapter_id),
            "anchor_chapter_status": str(anchor.get("status") or "planned"),
            "anchor_chapter_number": anchor_number,
            "anchor_chapter_path": anchor_path,
            "outline_revision": str(outline.get("revision") or ""),
            "facts_revision": str(runtime_state.revision),
            "context_fingerprint": self.context_fingerprint(),
            "context_brief": "\n".join(rendered),
        }

    def chapter_options(self) -> dict[str, Any]:
        from tools.outline_tree import build_outline_structure

        outline = build_outline_structure(self.novel_root)
        chapters = self._chapters(outline.get("roots", []))
        return {
            "outline_revision": str(outline.get("revision") or ""),
            "recommended_chapter_id": str(
                (outline.get("recommendation") or {}).get("chapter_id") or ""
            ),
            "chapter_options": [
                {
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or item.get("id") or ""),
                    "status": str(item.get("status") or "planned"),
                    "path": [str(part) for part in (item.get("path") or []) if part],
                    "number": self._chapter_number(str(item.get("id") or "")) or index,
                }
                for index, item in enumerate(chapters, start=1)
            ],
        }

    def _canonical_input_paths(self) -> list[Path]:
        patterns = (
            "src/outline.md",
            "src/story/**/*.md",
            "src/characters/**/*.md",
            "src/world/**/*.md",
            "data/world/*.md",
            "data/world/*.json",
            "data/foreshadowing/dag.yaml",
            "data/memory/chapters/*.yaml",
            "data/manuscript/**/*.md",
        )
        paths: set[Path] = set()
        for pattern in patterns:
            paths.update(path for path in self.novel_root.glob(pattern) if path.is_file())
        return sorted(paths, key=lambda item: item.relative_to(self.novel_root).as_posix())

    def _require(self, forecast_id: str) -> NarrativeForecastV1:
        forecast = self.load(forecast_id)
        if forecast is None:
            raise NarrativeForecastError("剧情推演不存在", code="FORECAST_NOT_FOUND")
        return forecast

    def _clean_forecast_id(self, forecast_id: str) -> str:
        clean = str(forecast_id or "")
        if not re.fullmatch(r"forecast_[A-Za-z0-9_-]+", clean):
            raise NarrativeForecastError("无效剧情推演 ID", code="INVALID_FORECAST_ID")
        return clean

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.project_root).as_posix()
        except ValueError:
            return str(path)

    @staticmethod
    def _chapters(roots: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def visit(nodes: Any) -> None:
            if not isinstance(nodes, list):
                return
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                if node.get("kind") == "chapter":
                    result.append(node)
                visit(node.get("children"))

        visit(roots)
        return result

    @staticmethod
    def _chapter_number(chapter_id: str) -> int:
        match = re.search(r"(\d+)", chapter_id)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _render_outline_chapter(item: dict[str, Any], *, marker: str = "") -> str:
        chapter_id = str(item.get("id") or "")
        title = str(item.get("title") or chapter_id)
        status = "已有正文" if item.get("status") == "drafted" else "待写"
        path = " / ".join(str(part) for part in (item.get("path") or []) if part)
        heading = f"- {chapter_id} {title} [{status}]"
        if marker:
            heading += f" [{marker}]"
        if path:
            heading += f"\n  所属：{path}"
        summary = str(item.get("summary") or "").strip()
        if summary:
            heading += "\n  " + summary.replace("\n", "\n  ")
        return heading

    @staticmethod
    def _forecast_anchor_label(forecast: NarrativeForecastV1) -> str:
        if forecast.anchor_chapter_id:
            return f"{forecast.anchor_chapter_id} {forecast.anchor_chapter_title}".strip()
        return f"第 {forecast.base_chapter} 章之后（旧推演未记录锚点）"

    @staticmethod
    def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise NarrativeForecastError(
                f"{name} 必须是 {minimum}–{maximum} 的整数",
                code=f"INVALID_{name.upper()}",
            ) from exc
        if parsed < minimum or parsed > maximum:
            raise NarrativeForecastError(
                f"{name} 必须是 {minimum}–{maximum} 的整数",
                code=f"INVALID_{name.upper()}",
            )
        return parsed

    @staticmethod
    def _hash(payload: Any) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content.rstrip("\n") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(path)

    @classmethod
    def _render_branch(
        cls,
        branch: ForecastBranchV1,
        *,
        include_id: bool = True,
    ) -> str:
        title = (
            f"## {branch.branch_id}：{branch.title}"
            if include_id
            else f"## {branch.title}"
        )
        lines = [
            title,
            "",
            "### 前提与假设",
            "",
            branch.premise,
            "",
            "### 未来章节节拍",
            "",
        ]
        lines.extend(
            f"- 第 +{beat.offset} 章"
            f"{f'（{beat.chapter_id}）' if beat.chapter_id else ''}：{beat.summary}"
            for beat in branch.beats
        )
        lines.extend(["", "### 人物决策", ""])
        if branch.character_decisions:
            lines.extend(
                f"- {item.character}：{item.decision}"
                for item in branch.character_decisions
            )
        else:
            lines.append("- 无")
        changes = branch.projected_changes
        lines.extend(
            [
                "",
                "### 预计变化",
                "",
                f"- 人物：{cls._join(changes.characters)}",
                f"- 关系：{cls._join(changes.relationships)}",
                f"- 世界：{cls._join(changes.world)}",
                f"- 伏笔：{cls._join(changes.foreshadowing)}",
                "",
                "### 一致性风险",
                "",
            ]
        )
        if branch.risks:
            lines.extend(f"- [{item.kind}] {item.description}" for item in branch.risks)
        else:
            lines.append("- 无")
        lines.extend(["", "### 不确定性", ""])
        if branch.uncertainties:
            lines.extend(f"- {item}" for item in branch.uncertainties)
        else:
            lines.append("- 无")
        lines.extend(
            [
                "",
                "### 作者意图匹配度",
                "",
                f"{branch.intent_alignment.score}/100：{branch.intent_alignment.rationale}",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _join(items: tuple[str, ...]) -> str:
        return "；".join(items) if items else "无"

    @staticmethod
    def _table_cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")


def narrative_forecast_action(
    project_root: Path,
    novel_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    service = NarrativeForecastService(project_root, novel_id)
    action = str(payload.get("action") or "list")
    if action == "list":
        current_fingerprint = service.context_fingerprint()
        forecasts = service.list(limit=int(payload.get("limit") or 20))
        return {
            "forecasts": [
                service.payload(
                    forecast,
                    include_context=False,
                    current_fingerprint=current_fingerprint,
                )
                for forecast in forecasts
            ],
            **service.chapter_options(),
        }
    if action == "create":
        forecast = service.create(
            divergence=str(payload.get("divergence") or ""),
            anchor_chapter_id=str(payload.get("anchor_chapter_id") or ""),
            branch_count=payload.get("branch_count", 3),
            horizon=payload.get("horizon", 5),
        )
        return service.payload(forecast)

    forecast_id = str(payload.get("forecast_id") or "")
    if action == "get":
        return service.payload(service.get(forecast_id))
    if action == "stage":
        return service.payload(
            service.stage(
                forecast_id,
                payload.get("branches"),
                forecast_revision=str(payload.get("revision") or ""),
            )
        )
    if action == "select":
        return service.payload(
            service.select(
                forecast_id,
                str(payload.get("branch_id") or ""),
                forecast_revision=str(payload.get("revision") or ""),
            )
        )
    raise NarrativeForecastError("未知剧情推演操作", code="INVALID_FORECAST_ACTION")
