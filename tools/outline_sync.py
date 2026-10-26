from pathlib import Path

import yaml

from .outline_cache import serialize_outline_hierarchy
from .outline_parser import OutlineMdParser


def sync_outline_to_hierarchy(src_dir: Path, data_dir: Path) -> None:
    outline_path = src_dir / "outline.md"
    hierarchy_path = data_dir / "hierarchy.yaml"

    with open(outline_path, "r", encoding="utf-8") as f:
        content = f.read()

    hierarchy = OutlineMdParser.for_path(src_dir).parse(
        content, data_dir.parent.name if data_dir.parent.name else ""
    )
    data = serialize_outline_hierarchy(hierarchy)

    with open(hierarchy_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
