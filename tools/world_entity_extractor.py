"""世界观实体/关系 LLM 自动抽取器 — 从章节文本中提取实体和关系。

Strangler Fig 模式：
- 有 llm_client 时使用 LLM 抽取（高质量）
- 无 llm_client 时使用规则引擎（正则 + 关键词匹配）
- LLM 失败时自动 fallback 到规则引擎
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass
class ExtractedEntity:
    """抽取到的实体。"""

    id: str
    name: str
    entity_type: str = "concept"
    description: str = ""
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class ExtractedRelation:
    """抽取到的关系。"""

    source_id: str
    target_id: str
    relation: str
    note: str = ""
    weight: int = 3


@dataclass
class ExtractionResult:
    """抽取结果。"""

    entities: List[ExtractedEntity] = field(default_factory=list)
    relations: List[ExtractedRelation] = field(default_factory=list)
    method: str = "rule"  # "llm" or "rule"
    raw_response: str = ""


# 规则引擎用的模式
_LOCATION_PATTERNS = [
    re.compile(r"(?:来到|到达|抵达|前往|位于|在)(?:了)?「?([^」，。\s]{2,8})」?"),
    re.compile(r"「([^」]{2,8})」(?:城|镇|村|山|谷|洞|殿|阁|塔|岛|湖|河)"),
]
_CHAR_PATTERNS = [
    re.compile(r"「([^」]{2,6})」(?:说|道|笑|怒|叹|喊|问|答|想)"),
    re.compile(r"([^\s，。]{2,4})(?:师父|师兄|师姐|师弟|师妹|前辈|晚辈|道友)"),
]
_ITEM_PATTERNS = [
    re.compile(r"(?:取出|拿出|祭出|掏出|使用)(?:了)?「?([^」，。\s]{2,8})」?"),
    re.compile(r"「([^」]{2,8})」(?:剑|刀|枪|法宝|丹药|灵石|功法|秘籍)"),
]
_RELATION_KEYWORDS = {
    "belongs_to": ["属于", "隶属", "门下", "弟子", "成员"],
    "located_at": ["位于", "在", "来到", "到达", "抵达"],
    "ally": ["盟友", "结盟", "联手", "合作"],
    "enemy": ["敌对", "对抗", "交战", "仇敌"],
    "master_of": ["师父", "师尊", "传授"],
    "owns": ["持有", "拥有", "取出", "祭出"],
}


class WorldEntityExtractor:
    """世界观实体/关系抽取器。"""

    def __init__(
        self,
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
    ):
        self._llm_client = llm_client
        self._router = router

    def extract(
        self,
        text: str,
        chapter_id: str = "",
        existing_entities: Optional[List[str]] = None,
    ) -> ExtractionResult:
        """从文本中抽取实体和关系。

        Args:
            text: 章节文本。
            chapter_id: 章节 ID（用于标注）。
            existing_entities: 已知实体名列表（帮助消歧）。

        Returns:
            ExtractionResult。
        """
        existing = existing_entities or []

        # LLM 分支
        if self._llm_client and self._router:
            try:
                return self._extract_with_llm(text, chapter_id, existing)
            except Exception as e:
                logger.warning("LLM 抽取失败，fallback 到规则引擎: %s", e)

        # 规则引擎 fallback
        return self._extract_with_rules(text, chapter_id, existing)

    def _extract_with_llm(
        self,
        text: str,
        chapter_id: str,
        existing: List[str],
    ) -> ExtractionResult:
        """使用 LLM 抽取。"""
        messages = self._build_prompt(text, chapter_id, existing)
        model = self._router.get_model("review") if self._router else None
        if not model:
            raise RuntimeError("无可用模型")

        response = self._llm_client.complete(messages=messages, model=model)
        content = response.content.strip()

        # 解析 JSON
        parsed = self._parse_llm_response(content)
        result = ExtractionResult(method="llm", raw_response=content)

        for e in parsed.get("entities", []):
            eid = self._to_id(e.get("name", ""))
            if not eid:
                continue
            result.entities.append(
                ExtractedEntity(
                    id=eid,
                    name=e.get("name", eid),
                    entity_type=e.get("type", "concept"),
                    description=e.get("description", ""),
                    attributes=e.get("attributes", {}),
                )
            )

        for r in parsed.get("relations", []):
            src = self._to_id(r.get("source", ""))
            tgt = self._to_id(r.get("target", ""))
            if not src or not tgt:
                continue
            result.relations.append(
                ExtractedRelation(
                    source_id=src,
                    target_id=tgt,
                    relation=r.get("relation", "related_to"),
                    note=r.get("note", ""),
                    weight=int(r.get("weight", 3)),
                )
            )

        return result

    def _extract_with_rules(
        self,
        text: str,
        chapter_id: str,
        existing: List[str],
    ) -> ExtractionResult:
        """使用规则引擎抽取。"""
        result = ExtractionResult(method="rule")
        seen_entities: Dict[str, ExtractedEntity] = {}

        # 抽取地点
        for pattern in _LOCATION_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1).strip()
                eid = self._to_id(name)
                if eid and eid not in seen_entities:
                    seen_entities[eid] = ExtractedEntity(
                        id=eid,
                        name=name,
                        entity_type="location",
                    )

        # 抽取人物（仅新发现的，不在 existing 中的也记录）
        for pattern in _CHAR_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1).strip()
                eid = self._to_id(name)
                if eid and eid not in seen_entities:
                    seen_entities[eid] = ExtractedEntity(
                        id=eid,
                        name=name,
                        entity_type="character",
                    )

        # 抽取物品
        for pattern in _ITEM_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1).strip()
                eid = self._to_id(name)
                if eid and eid not in seen_entities:
                    seen_entities[eid] = ExtractedEntity(
                        id=eid,
                        name=name,
                        entity_type="item",
                    )

        result.entities = list(seen_entities.values())

        # 抽取关系（基于关键词共现）
        entity_names = {e.name: e.id for e in result.entities}
        # 加入已知实体
        for name in existing:
            eid = self._to_id(name)
            if eid:
                entity_names[name] = eid

        seen_rels: set = set()
        for rel_type, keywords in _RELATION_KEYWORDS.items():
            for kw in keywords:
                for match in re.finditer(re.escape(kw), text):
                    # 在关键词前后 30 字符内查找实体名
                    start = max(0, match.start() - 30)
                    end = min(len(text), match.end() + 30)
                    window = text[start:end]
                    found_in_window = [
                        (name, eid)
                        for name, eid in entity_names.items()
                        if name in window
                    ]
                    if len(found_in_window) >= 2:
                        src = found_in_window[0]
                        tgt = found_in_window[1]
                        key = (src[1], tgt[1], rel_type)
                        if key not in seen_rels:
                            seen_rels.add(key)
                            result.relations.append(
                                ExtractedRelation(
                                    source_id=src[1],
                                    target_id=tgt[1],
                                    relation=rel_type,
                                )
                            )

        return result

    @staticmethod
    def _build_prompt(
        text: str,
        chapter_id: str,
        existing: List[str],
    ) -> List[Dict[str, str]]:
        """构建 LLM 抽取 prompt。"""
        system = (
            "你是一位世界观知识图谱构建专家，负责从小说文本中抽取实体和关系。\n\n"
            "## 实体类型\n"
            "- character: 人物角色\n"
            "- location: 地点场所\n"
            "- organization: 组织门派\n"
            "- item: 物品法宝\n"
            "- concept: 概念术语（境界、功法等）\n"
            "- event: 重要事件\n\n"
            "## 关系类型\n"
            "- belongs_to: 从属（弟子→门派）\n"
            "- located_at: 位于（角色→地点）\n"
            "- ally: 盟友\n"
            "- enemy: 敌对\n"
            "- master_of: 师徒\n"
            "- owns: 持有\n"
            "- above: 层级高于（境界）\n"
            "- related_to: 其他关联\n\n"
            "## 输出格式（严格 JSON）\n"
            "```json\n"
            "{\n"
            '  "entities": [\n'
            '    {"name": "实体名", "type": "类型", "description": "简述", '
            '"attributes": {"key": "value"}}\n'
            "  ],\n"
            '  "relations": [\n'
            '    {"source": "源实体名", "target": "目标实体名", '
            '"relation": "关系类型", "note": "说明", "weight": 3}\n'
            "  ]\n"
            "}\n"
            "```\n\n"
            "注意：\n"
            "- 只抽取文本中明确提到的实体和关系\n"
            "- 不要推测或虚构\n"
            "- weight 1-10，越重要越高\n"
            "- 优先识别已知实体列表中的实体"
        )

        existing_str = ""
        if existing:
            existing_str = f"\n## 已知实体\n{', '.join(existing[:50])}\n"

        # 截断文本避免超长
        truncated = text[:6000] if len(text) > 6000 else text
        user = (
            f"## 章节\n{chapter_id or '未知'}\n"
            f"{existing_str}"
            f"\n## 文本\n{truncated}\n\n"
            "请抽取实体和关系，输出 JSON。"
        )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _parse_llm_response(content: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON。"""
        # 尝试提取 ```json ... ``` 块
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("LLM 返回非法 JSON: %s", content[:200])
            return {"entities": [], "relations": []}

    @staticmethod
    def _to_id(name: str) -> str:
        """将名称转为合法 ID。"""
        name = name.strip()
        if not name or len(name) < 2:
            return ""
        # 中文直接用拼音风格 ID
        return re.sub(r"[^\w\u4e00-\u9fff]", "_", name).lower()
