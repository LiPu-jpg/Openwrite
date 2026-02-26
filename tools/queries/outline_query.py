"""Outline query helpers."""

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from tools.parsers.markdown_parser import parse_markdown_file
except ImportError:  # pragma: no cover - supports legacy path injection
    from parsers.markdown_parser import parse_markdown_file


class OutlineQuery:
    """Read-only queries on outline files."""

    def __init__(self, project_dir: Optional[Path] = None, novel_id: str = "my_novel"):
        self.project_dir = project_dir or self._find_project_dir()
        self.novel_id = novel_id
        self.base_dir = self.project_dir / "data" / "novels" / novel_id / "outline"

    def _find_project_dir(self) -> Path:
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / "tools").exists():
                return parent
        return cwd

    def get_archetype(self) -> Optional[str]:
        archetype_file = self.base_dir / "archetype.md"
        if not archetype_file.exists():
            return None
        return parse_markdown_file(str(archetype_file)).get("raw_content")

    def get_volume(self, volume_id: str) -> Optional[Dict[str, Any]]:
        volume_file = self.base_dir / "volumes" / f"{volume_id}.md"
        if not volume_file.exists():
            return None
        return parse_markdown_file(str(volume_file))

    def get_chapter(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        chapter_file = self.base_dir / "chapters" / f"{chapter_id}.md"
        if not chapter_file.exists():
            return None
        return parse_markdown_file(str(chapter_file))

    def get_all_volumes(self) -> List[str]:
        volumes_dir = self.base_dir / "volumes"
        if not volumes_dir.exists():
            return []
        return sorted(file.stem for file in volumes_dir.glob("vol_*.md"))

    def get_all_chapters(self) -> List[str]:
        chapters_dir = self.base_dir / "chapters"
        if not chapters_dir.exists():
            return []
        return sorted(file.stem for file in chapters_dir.glob("ch_*.md"))

    def search_foreshadowings(
        self,
        keywords: List[str],
        min_weight: Optional[int] = None,
        layer: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search foreshadowing tags in chapter markdown files."""
        results: List[Dict[str, Any]] = []

        for chapter_id in self.get_all_chapters():
            chapter_data = self.get_chapter(chapter_id) or {}
            annotations = chapter_data.get("annotations", {})
            foreshadowings = annotations.get("foreshadowings", [])

            for item in foreshadowings:
                attrs = item.get("attributes", {})
                weight = int(attrs.get("weight", 0) or 0)
                item_layer = attrs.get("layer", "")
                content = item.get("content", "")

                if keywords and not any(kw.lower() in content.lower() for kw in keywords):
                    continue
                if min_weight is not None and weight < min_weight:
                    continue
                if layer is not None and item_layer != layer:
                    continue

                results.append({"chapter_id": chapter_id, "foreshadowing": item})

        return results

    def get_pending_foreshadowings(self) -> List[Dict[str, Any]]:
        """Return foreshadowings without a matching recovery ref in scanned chapters."""
        created: Dict[str, Dict[str, Any]] = {}
        recovered_ids: set[str] = set()

        for chapter_id in self.get_all_chapters():
            chapter_data = self.get_chapter(chapter_id) or {}
            annotations = chapter_data.get("annotations", {})
            for item in annotations.get("foreshadowings", []):
                item_id = item.get("attributes", {}).get("id")
                if item_id:
                    created[item_id] = {"chapter_id": chapter_id, "foreshadowing": item}
            for item in annotations.get("recovers", []):
                ref = item.get("attributes", {}).get("ref")
                if ref:
                    recovered_ids.add(ref)

        return [entry for item_id, entry in created.items() if item_id not in recovered_ids]
