"""世界观查询工具

扫描 data/novels/{novel_id}/src/world/entities/*.md，返回结构化摘要。
LLM 通过此工具快速了解全部世界观实体，按需再 Read 具体文件。

用法:
    python3 -m tools.world_query <novel_id>                    # 列出所有实体摘要
    python3 -m tools.world_query <novel_id> <entity_id>        # 查看单个实体详情
    python3 -m tools.world_query <novel_id> --type concept     # 按类型筛选
    python3 -m tools.world_query <novel_id> --relations        # 输出关系图谱
    python3 tools/world_query.py <novel_id>                    # 兼容直跑
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.frontmatter import parse_toml_front_matter


def parse_entity(filepath: Path) -> Dict[str, Any]:
    """解析单个 Markdown 实体文件为结构化数据。

    解析规则:
        - 文件名(不含.md) = id
        - H1 = name
        - 第一个 blockquote = "type | subtype | status"
        - H1 后第一段正文 = description
        - ## 规则 下的列表 = rules
        - ## 特征 下的列表 = features
        - ## 关联 下的列表 = relations (格式: "entity_id — 说明")
        - 其他 ## = extra sections
    """
    text = filepath.read_text(encoding="utf-8")
    meta, body = parse_toml_front_matter(text)
    meta_relations = meta.get("related", []) if isinstance(meta.get("related"), list) else []

    status_from_meta = "status" in meta
    entity: Dict[str, Any] = {
        "id": str(meta.get("id", filepath.stem)).strip() or filepath.stem,
        "name": str(meta.get("name", "")).strip(),
        "type": str(meta.get("type", "")).strip(),
        "subtype": str(meta.get("subtype", "")).strip(),
        "status": str(meta.get("status", "active")).strip() or "active",
        "description": str(meta.get("summary", "")).strip(),
        "rules": [],
        "features": [],
        "relations": _normalize_meta_relations(meta_relations),
        "tags": list(meta.get("tags", [])) if isinstance(meta.get("tags"), list) else [],
        "detail_refs": list(meta.get("detail_refs", []))
        if isinstance(meta.get("detail_refs"), list)
        else [],
        "extra_sections": {},
        "file": str(filepath),
    }

    lines = body.split("\n")
    i = 0

    # Skip leading blank lines / comments
    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("#") is False):
        if lines[i].strip().startswith("# ") and not lines[i].strip().startswith("## "):
            break
        i += 1

    # Find H1 title
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("# ") and not line.startswith("## "):
            entity["name"] = line[2:].strip()
            i += 1
            break
        i += 1

    # Find optional legacy metadata blockquote (> type | subtype | status).
    # Front matter may only partially fill these fields, so we still probe and
    # only backfill missing values instead of skipping the line entirely.
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("> "):
            meta_line = line[2:].strip()
            parts = [p.strip() for p in meta_line.split("|")]
            if len(parts) >= 1 and not entity["type"]:
                entity["type"] = parts[0]
            if len(parts) >= 2 and not entity["subtype"]:
                entity["subtype"] = parts[1]
            if len(parts) >= 3 and not status_from_meta:
                entity["status"] = parts[2] or entity["status"]
            i += 1
            break
        if line.startswith("## ") or line.startswith("# "):
            break
        break

    # Find description (first paragraph after metadata)
    desc_lines: List[str] = []
    # Skip blank lines
    while i < len(lines) and not lines[i].strip():
        i += 1
    if not entity["description"]:
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped or stripped.startswith("## "):
                break
            desc_lines.append(stripped)
            i += 1
        entity["description"] = " ".join(desc_lines)

    # Parse sections
    current_section = ""
    section_items: List[str] = []
    section_text_lines: List[str] = []

    def flush_section():
        nonlocal section_items, section_text_lines
        key = _normalize_section(current_section)
        if key == "rules":
            entity["rules"] = section_items[:]
        elif key == "features":
            entity["features"] = section_items[:]
        elif key == "relations":
            entity["relations"].extend(_parse_relations(section_items))
        elif current_section:
            content = "\n".join(section_text_lines).strip()
            if section_items:
                content = "\n".join(f"- {item}" for item in section_items)
            entity["extra_sections"][current_section] = content
        section_items = []
        section_text_lines = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("## "):
            flush_section()
            current_section = stripped[3:].strip()
            i += 1
            continue

        if stripped.startswith("- "):
            section_items.append(stripped[2:].strip())
        elif stripped:
            section_text_lines.append(stripped)

        i += 1

    flush_section()
    entity["relations"] = _dedupe_relations(entity["relations"])

    return entity


def _normalize_section(name: str) -> str:
    """将段落标题归一化为字段名。"""
    mapping = {
        "规则": "rules",
        "rules": "rules",
        "特征": "features",
        "features": "features",
        "关联": "relations",
        "relations": "relations",
    }
    return mapping.get(name, mapping.get(name.lower(), ""))


def _parse_relations(items: List[str]) -> List[Dict[str, str]]:
    """解析关联列表。格式: 'entity_id — 说明' 或 'entity_id - 说明'"""
    relations = []
    for item in items:
        # Support both — (em dash) and - (hyphen) as separator
        match = re.match(r"^(\S+)\s*[—–-]\s*(.+)$", item)
        if match:
            relations.append(
                {
                    "target": match.group(1).strip(),
                    "description": match.group(2).strip(),
                }
            )
        else:
            relations.append({"target": item.strip(), "description": ""})
    return relations


def _normalize_meta_relations(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Normalize TOML front matter related entries to legacy relation shape."""
    relations: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target", "")).strip()
        if not target:
            continue
        description = (
            str(item.get("description", "")).strip()
            or str(item.get("note", "")).strip()
            or str(item.get("kind", "")).strip()
        )
        relations.append({"target": target, "description": description})
    return relations


def _dedupe_relations(relations: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Preserve order while removing duplicate relation entries."""
    deduped: List[Dict[str, str]] = []
    seen = set()
    for rel in relations:
        target = str(rel.get("target", "")).strip()
        description = str(rel.get("description", "")).strip()
        key = (target, description)
        if not target or key in seen:
            continue
        seen.add(key)
        deduped.append({"target": target, "description": description})
    return deduped


def list_entities(
    novel_id: str,
    entity_type: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> List[Dict[str, str]]:
    """列出所有实体的摘要（id + name + type + status + description 前50字）。

    这是 LLM 应该首先调用的函数 — 快速了解全局，无需读取每个文件。
    """
    root = (project_root or Path(__file__).parent.parent).resolve()
    entities_dir = root / "data" / "novels" / novel_id / "src" / "world" / "entities"

    if not entities_dir.exists():
        return []

    results = []
    for f in sorted(entities_dir.glob("*.md")):
        entity = parse_entity(f)
        if entity_type and entity["type"] != entity_type:
            continue
        desc = entity["description"]
        short_desc = desc[:60] + "..." if len(desc) > 60 else desc
        results.append(
            {
                "id": entity["id"],
                "name": entity["name"],
                "type": entity["type"],
                "subtype": entity["subtype"],
                "status": entity["status"],
                "description": short_desc,
            }
        )

    return results


def get_entity(
    novel_id: str,
    entity_id: str,
    project_root: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """获取单个实体的完整结构化数据。"""
    root = (project_root or Path(__file__).parent.parent).resolve()
    filepath = (
        root / "data" / "novels" / novel_id / "src" / "world" / "entities" / f"{entity_id}.md"
    )

    if not filepath.exists():
        return None

    return parse_entity(filepath)


def get_relations_graph(
    novel_id: str,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """从所有实体的 ## 关联 段落汇总生成关系图谱。

    不再依赖手动维护的 graph.yaml —— 关系数据直接从实体文件中提取。
    """
    root = (project_root or Path(__file__).parent.parent).resolve()
    entities_dir = root / "data" / "novels" / novel_id / "src" / "world" / "entities"

    if not entities_dir.exists():
        return {"entities": [], "relations": []}

    all_entities = []
    all_relations = []
    seen_relations = set()

    for f in sorted(entities_dir.glob("*.md")):
        entity = parse_entity(f)
        all_entities.append(entity["id"])
        for rel in entity["relations"]:
            edge = (
                entity["id"],
                rel["target"],
                rel["description"],
            )
            if edge in seen_relations:
                continue
            seen_relations.add(edge)
            all_relations.append(
                {
                    "source": entity["id"],
                    "target": rel["target"],
                    "description": rel["description"],
                }
            )

    return {"entities": all_entities, "relations": all_relations}


# ─── CLI ────────────────────────────────────────────────────────────


def _print_summary_table(entities: List[Dict[str, str]]):
    """打印实体摘要表。"""
    if not entities:
        print("（无实体）")
        return

    # Header
    print(f"{'ID':<28} {'名称':<16} {'类型':<20} {'状态':<8} 描述")
    print("─" * 100)
    for e in entities:
        type_str = f"{e['type']}/{e['subtype']}" if e["subtype"] else e["type"]
        print(f"{e['id']:<28} {e['name']:<16} {type_str:<20} {e['status']:<8} {e['description']}")


def _print_entity_detail(entity: Dict[str, Any]):
    """打印单个实体详情。"""
    type_str = f"{entity['type']}/{entity['subtype']}" if entity["subtype"] else entity["type"]
    print(f"# {entity['name']}")
    print(f"  ID: {entity['id']}  |  类型: {type_str}  |  状态: {entity['status']}")
    print(f"  文件: {entity['file']}")
    print()
    print(f"  {entity['description']}")

    if entity["rules"]:
        print(f"\n  规则 ({len(entity['rules'])}条):")
        for r in entity["rules"]:
            print(f"    - {r}")

    if entity["features"]:
        print(f"\n  特征 ({len(entity['features'])}条):")
        for f in entity["features"]:
            print(f"    - {f}")

    if entity["relations"]:
        print(f"\n  关联 ({len(entity['relations'])}条):")
        for r in entity["relations"]:
            desc = f" — {r['description']}" if r["description"] else ""
            print(f"    → {r['target']}{desc}")

    for section, content in entity["extra_sections"].items():
        print(f"\n  {section}:")
        for line in content.split("\n"):
            print(f"    {line}")


def _print_relations(graph: Dict[str, Any]):
    """打印关系图谱。"""
    print(f"实体: {', '.join(graph['entities'])}")
    print(f"关系 ({len(graph['relations'])}条):")
    for r in graph["relations"]:
        desc = f" ({r['description']})" if r["description"] else ""
        print(f"  {r['source']} → {r['target']}{desc}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    novel_id = sys.argv[1]
    root = Path(__file__).parent.parent.resolve()
    if "--project-root" in sys.argv:
        idx = sys.argv.index("--project-root")
        if idx + 1 >= len(sys.argv):
            print("--project-root 缺少路径")
            sys.exit(1)
        root = Path(sys.argv[idx + 1]).expanduser().resolve()

    # --relations flag
    if "--relations" in sys.argv:
        graph = get_relations_graph(novel_id, root)
        _print_relations(graph)
        return

    # --type filter
    entity_type = None
    if "--type" in sys.argv:
        idx = sys.argv.index("--type")
        if idx + 1 < len(sys.argv):
            entity_type = sys.argv[idx + 1]

    # Specific entity (skip flag values)
    entity_id = None
    skip_next = False
    for arg in sys.argv[2:]:
        if skip_next:
            skip_next = False
            continue
        if arg in ("--type", "--project-root", "--relations"):
            skip_next = arg in {"--type", "--project-root"}
            continue
        entity_id = arg
        break

    if entity_id:
        entity = get_entity(novel_id, entity_id, root)
        if entity:
            _print_entity_detail(entity)
        else:
            print(f"实体不存在: {entity_id}")
            sys.exit(1)
    else:
        entities = list_entities(novel_id, entity_type, root)
        _print_summary_table(entities)


if __name__ == "__main__":
    main()
