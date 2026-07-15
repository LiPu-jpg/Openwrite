"""真相文件管理器

管理 3 个运行时状态文件：
1. world/current_state.md - 世界当前状态
2. world/ledger.md - 资源账本
3. world/relationships.md - 角色关系矩阵

注意：
- 章节摘要 → outline/hierarchy.yaml + compressed/
- 伏笔列表 → foreshadowing/dag.yaml
- 情感弧线 → outline hierarchy 的 arc/section_emotional_arc
- 支线进度 → outline hierarchy

支持状态快照和回滚。

这里维护的是“运行态真相文件”，不是故事设定真源：
- `src/` 里的背景、角色、世界文档偏长期资产
- `data/world/*.md` 里的 truth files 偏当前章节推进后的状态投影
写作、审查、workflow 读取的都是这一层运行态。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
import tempfile
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

from .frontmatter import compose_toml_document, parse_toml_front_matter, strip_front_matter_padding

logger = logging.getLogger(__name__)


@dataclass
class TruthFiles:
    """真相文件集合（精简版）。

    同时兼容当前 canonical 名称和历史别名，避免旧调用点在迁移期间全部失效。
    """

    current_state: str = ""
    ledger: str = ""
    relationships: str = ""
    metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    _ALIASES = {
        "particle_ledger": "ledger",
        "character_matrix": "relationships",
    }

    def __getattr__(self, name: str) -> str:
        alias = self._ALIASES.get(name)
        if alias:
            return getattr(self, alias)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: str) -> None:
        alias = self._ALIASES.get(name)
        if alias:
            super().__setattr__(alias, value)
            return
        super().__setattr__(name, value)

    def __dir__(self) -> List[str]:
        return [item for item in super().__dir__() if item != "metadata"]


@dataclass
class StateSnapshot:
    """状态快照"""

    id: str
    chapter_number: int
    created_at: str
    files: TruthFiles


class TruthFilesManager:
    """真相文件管理器

    文件分布：
    - world/current_state.md - 世界当前状态
    - world/ledger.md - 资源账本
    - world/relationships.md - 角色关系矩阵

    用法:
        manager = TruthFilesManager(project_root, novel_id)

        # 加载当前真相文件
        truth = manager.load_truth_files()

        # 更新真相文件
        manager.update_truth_files(truth, {
            "current_state": "新状态...",
        })

        # 创建快照
        manager.create_snapshot(chapter_number=5)

        # 回滚到快照
        manager.restore_snapshot("snapshot_5")
    """

    TRUTH_FILES = {
        "current_state": "current_state.md",
        "ledger": "ledger.md",
        "relationships": "relationships.md",
    }

    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = project_root.resolve()
        self.novel_id = novel_id
        self.novel_root = project_root / "data" / "novels" / novel_id
        self.runtime_root = self.novel_root / "data"
        self.world_dir = self.runtime_root / "world"
        self.snapshots_dir = self.runtime_root / "snapshots"

    def _get_file_path(self, attr_name: str) -> Path:
        """获取文件路径"""
        if attr_name == "current_state":
            return self.world_dir / "current_state.md"
        elif attr_name in ("ledger", "particle_ledger"):
            return self.world_dir / "ledger.md"
        elif attr_name in ("relationships", "character_matrix"):
            return self.world_dir / "relationships.md"
        raise ValueError(f"Unknown truth file: {attr_name}")

    def ensure_dirs(self):
        """确保目录存在"""
        self.world_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def load_truth_files(self) -> TruthFiles:
        """加载所有真相文件。

        读取时会优先解析 front matter，把“索引字段 + 正文说明”拆回运行态对象。
        """
        truth = TruthFiles()

        # 三个 truth file 是固定集合；缺失时补默认 metadata，而不是直接报错中断写作链。
        for attr_name in ["current_state", "ledger", "relationships"]:
            file_path = self._get_file_path(attr_name)
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    meta, body = parse_toml_front_matter(content)
                    clean_body = strip_front_matter_padding(body if meta else content)
                    truth.metadata[attr_name] = meta or self._default_metadata(attr_name, clean_body)
                    setattr(truth, attr_name, clean_body)
                except Exception as e:
                    logger.warning(f"Failed to load {attr_name}: {e}")
            else:
                truth.metadata[attr_name] = self._default_metadata(attr_name, "")

        return truth

    def save_truth_files(self, truth: TruthFiles):
        """保存所有真相文件。

        保存时统一写成 `TOML front matter + Markdown body`，保证人和 agent 读的是同一份文档。
        """
        self.ensure_dirs()

        rendered: Dict[str, str] = {}
        for attr_name in ["current_state", "ledger", "relationships"]:
            content = getattr(truth, attr_name, "")
            meta = truth.metadata.get(attr_name) or self._default_metadata(attr_name, content)
            truth.metadata[attr_name] = meta
            rendered[attr_name] = compose_toml_document(meta, content)

        temporary: Dict[str, Path] = {}
        try:
            for attr_name, document in rendered.items():
                file_path = self._get_file_path(attr_name)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=file_path.parent,
                    prefix=f".{file_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(document)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary[attr_name] = Path(handle.name)
            for attr_name in ["current_state", "ledger", "relationships"]:
                temporary[attr_name].replace(self._get_file_path(attr_name))
        except Exception:
            for path in temporary.values():
                path.unlink(missing_ok=True)
            raise

    def update_truth_files(self, truth: TruthFiles, updates: Dict[str, str]):
        """更新指定的真相文件。

        这里只做字段替换和统一保存，不负责推导状态差异。
        """
        for key, value in updates.items():
            if hasattr(truth, key):
                setattr(truth, key, value)

        self.save_truth_files(truth)

    def create_snapshot(self, chapter_number: int) -> str:
        """创建状态快照

        Returns:
            快照 ID
        """
        import json

        self.ensure_dirs()

        # snapshot 记录的是一个时刻的完整运行态，用于 rewrite/rollback，而不是长期审阅文档。
        truth = self.load_truth_files()
        snapshot_id = f"snapshot_{chapter_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        snapshot: Dict[str, Any] = {
            "id": snapshot_id,
            "chapter_number": chapter_number,
            "created_at": datetime.now().isoformat(),
            "files": {
                "current_state": truth.current_state,
                "ledger": truth.ledger,
                "relationships": truth.relationships,
            },
        }

        # 快照故意落成 JSON，避免再引入一套 front matter/Markdown 解析成本。
        snapshot_path = self.snapshots_dir / f"{snapshot_id}.json"
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(f"Created snapshot: {snapshot_id}")
        return snapshot_id

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """恢复到指定快照"""
        import json

        snapshot_path = self.snapshots_dir / f"{snapshot_id}.json"
        if not snapshot_path.exists():
            logger.error(f"Snapshot not found: {snapshot_id}")
            return False

        try:
            with snapshot_path.open("r", encoding="utf-8") as f:
                snapshot = json.load(f)

            # 回滚时同时兼容旧快照里的历史字段名，避免已存在的 snapshot 因命名迁移失效。
            truth = TruthFiles(
                current_state=snapshot["files"].get("current_state", ""),
                ledger=snapshot["files"].get("ledger", snapshot["files"].get("particle_ledger", "")),
                relationships=snapshot["files"].get(
                    "relationships", snapshot["files"].get("character_matrix", "")
                ),
            )

            self.save_truth_files(truth)
            logger.info(f"Restored snapshot: {snapshot_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to restore snapshot: {e}")
            return False

    def load_snapshot_before(self, chapter_number: int) -> TruthFiles | None:
        """Load the latest pre-write truth snapshot for a chapter without restoring it."""
        import json

        target = max(int(chapter_number) - 1, 0)
        candidates = sorted(self.snapshots_dir.glob(f"snapshot_{target}_*.json"))
        if not candidates:
            return None
        try:
            snapshot = json.loads(candidates[-1].read_text(encoding="utf-8"))
            files = snapshot.get("files", {})
            if not isinstance(files, dict):
                return None
            return TruthFiles(
                current_state=str(files.get("current_state") or ""),
                ledger=str(files.get("ledger") or files.get("particle_ledger") or ""),
                relationships=str(
                    files.get("relationships")
                    or files.get("character_matrix")
                    or ""
                ),
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """列出所有快照。

        这里只返回用于选择和展示的轻量元信息，不把整份 snapshot 内容全部读回内存。
        """
        import json

        snapshots = []
        if not self.snapshots_dir.exists():
            return snapshots

        for path in sorted(self.snapshots_dir.glob("snapshot_*.json")):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    snapshots.append(
                        {
                            "id": data.get("id", ""),
                            "chapter_number": data.get("chapter_number", 0),
                            "created_at": data.get("created_at", ""),
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to load snapshot {path}: {e}")

        return snapshots

    def filter_hooks_by_pov(
        self,
        hooks: str,
        pov_character: str,
        chapter_summaries: str,
    ) -> str:
        """POV 感知过滤伏笔

        只返回 POV 角色应该知道的伏笔。
        """
        if not hooks or not pov_character:
            return hooks

        lines = hooks.strip().split("\n")
        filtered = []

        for line in lines:
            # 这里还是启发式过滤：宁可少裁剪，也不要把 POV 明显知道的伏笔误删掉。
            if pov_character in line:
                filtered.append(line)
                continue

            # 检查章节摘要中 POV 角色是否在场
            if self._character_mentioned_in_summaries(pov_character, chapter_summaries):
                filtered.append(line)

        return "\n".join(filtered) if filtered else hooks

    def _default_metadata(self, attr_name: str, content: str) -> Dict[str, Any]:
        """为 truth file 补齐最小 front matter 索引。"""
        detail_map = {
            "current_state": ["scene", "actors", "open_threads"],
            "ledger": ["resources", "constraints", "balances"],
            "relationships": ["bonds", "status", "goals"],
        }
        return {
            "id": attr_name,
            "type": "runtime_truth",
            "summary": self._summarize_truth_content(content),
            "detail_refs": detail_map.get(attr_name, ["details"]),
        }

    def _summarize_truth_content(self, content: str) -> str:
        """从正文里抽一条可读摘要，给 agent 和 CLI 做轻量索引。"""
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith("|"):
                continue
            stripped = re.sub(r"^[-*]\s*", "", stripped)
            stripped = re.sub(r"^[^：:]+[：:]\s*", "", stripped)
            if stripped:
                return stripped[:160]
        return content.strip()[:160]

    def _character_mentioned_in_summaries(self, character: str, summaries: str) -> bool:
        """检查角色是否在章节摘要中提及"""
        if not summaries:
            return False

        # 简单匹配
        pattern = rf"{re.escape(character)}"
        return bool(re.search(pattern, summaries))

    def extract_facts_from_chapter(
        self,
        content: str,
        chapter_number: int,
        pov_character: Optional[str] = None,
    ) -> Dict[str, str]:
        """从章节内容中提取事实（用于更新真相文件）"""
        facts: Dict[str, str] = {}

        # 这是一个低保真 fallback：没有结构化 extractor 时，先靠正则抓最明显的事实。
        # 它更适合兜底和测试，不是最终的事实抽取策略。

        # 提取物品获得/失去
        items_gained = re.findall(r"获得了?(.+?)[。，！]", content)
        items_lost = re.findall(r"失去了?(.+?)[。，！]", content)

        if items_gained:
            facts["items_gained"] = items_gained
        if items_lost:
            facts["items_lost"] = items_lost

        # 提取数值变化
        money_changes = re.findall(r"(\d+)\s*(?:金币|元|银两|晶石)", content)
        if money_changes:
            facts["money_changes"] = [int(m) for m in money_changes]

        # 提取新角色
        new_characters = re.findall(r"(?:新角色|登场)：(.+?)[。，]", content)
        if new_characters:
            facts["new_characters"] = new_characters

        # 提取关系变化
        relationship_changes = re.findall(
            r"(?:关系|情感|感觉).*?(?:对|给|与).*?[是变成成为了](.+?)[。，]", content
        )
        if relationship_changes:
            facts["relationship_changes"] = relationship_changes

        return facts
