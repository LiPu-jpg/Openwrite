from __future__ import annotations

from pathlib import Path

from tools.resource_resolver import ResourceResolver


def test_resolver_prefers_workspace_craft_override(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    default_root = tmp_path / "defaults"
    (workspace / "craft").mkdir(parents=True)
    (default_root / "craft").mkdir(parents=True)
    (workspace / "craft" / "dialogue_craft.md").write_text("workspace craft", encoding="utf-8")
    (default_root / "craft" / "dialogue_craft.md").write_text("default craft", encoding="utf-8")

    resolver = ResourceResolver(workspace=workspace, default_root=default_root)

    assert resolver.read_text("craft", "dialogue_craft.md") == "workspace craft"


def test_resolver_falls_back_to_default_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    default_root = tmp_path / "defaults"
    (default_root / "craft").mkdir(parents=True)
    (default_root / "craft" / "dialogue_craft.md").write_text("default craft", encoding="utf-8")

    resolver = ResourceResolver(workspace=workspace, default_root=default_root)

    assert resolver.read_text("craft", "dialogue_craft.md") == "default craft"


def test_resolver_falls_back_to_package_resources(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    default_root = tmp_path / "defaults"
    
    # Intentionally do not create the files in workspace or default_root
    resolver = ResourceResolver(workspace=workspace, default_root=default_root)
    
    # This should fall back to the package resources (e.g. language_packs/vi/writer.md)
    text = resolver.read_text("language_packs/vi", "writer.md")
    assert text.strip() != ""
    assert "Bạn là tác giả tiểu thuyết tiếng Việt chuyên nghiệp" in text
