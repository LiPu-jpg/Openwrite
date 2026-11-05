import os
import tempfile
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

    # Atomic write: a bare open(...,"w") truncates in place, so a crash mid-write
    # leaves a half-written hierarchy.yaml. The freshness check only compares
    # mtimes, so that truncated file then reads as current and every consumer
    # (workspace snapshot, context build, reading order) works from a partial
    # outline. Write to a sibling temp file and rename over the target.
    hierarchy_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".hierarchy.", suffix=".tmp", dir=str(hierarchy_path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.dump(data, handle, allow_unicode=True, default_flow_style=False, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, hierarchy_path)
    finally:
        temporary.unlink(missing_ok=True)
