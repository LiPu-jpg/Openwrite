from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from tools.asset_package import AssetPackageError, AssetPackageService
from tools.init_project import init_project
from tools.structured_assets import StructuredAssetError, StructuredAssetService


def test_structured_character_update_preserves_unknown_fields_and_markdown(tmp_path: Path):
    init_project(tmp_path, "demo")
    service = StructuredAssetService(tmp_path, "demo")
    created = service.create(
        "character",
        {
            "id": "char_linzhou",
            "data": {
                "name": "林舟",
                "summary": "钟楼修复师",
                "aliases": ["小林"],
                "custom_field": "不会进入允许字段",
            },
            "body_markdown": "# 林舟\n\n## 背景\n\n他负责修复旧钟。\n",
        },
    )
    path = tmp_path / "data" / "novels" / "demo" / created["path"]
    content = path.read_text(encoding="utf-8").replace(
        'summary = "钟楼修复师"',
        'summary = "钟楼修复师"\nlegacy_note = "保留我"',
    )
    path.write_text(content, encoding="utf-8")
    loaded = service.read("character", "char_linzhou")

    updated = service.update(
        "character",
        "char_linzhou",
        {"data": {"goal": "找回缺失的一分钟"}},
        expected_revision=loaded["revision"],
    )

    assert updated["data"]["goal"] == "找回缺失的一分钟"
    assert updated["data"]["legacy_note"] == "保留我"
    assert "他负责修复旧钟" in updated["body_markdown"]
    with pytest.raises(StructuredAssetError) as conflict:
        service.update(
            "character",
            "char_linzhou",
            {"data": {"goal": "旧版本覆盖"}},
            expected_revision=loaded["revision"],
        )
    assert conflict.value.code == "ASSET_CONFLICT"


def test_progression_system_requires_unique_readable_stages(tmp_path: Path):
    init_project(tmp_path, "demo")
    service = StructuredAssetService(tmp_path, "demo")

    created = service.create(
        "progression",
        {
            "id": "clock_sense",
            "data": {
                "name": "听钟能力",
                "kind": "ability",
                "summary": "通过代价逐步听见时间缺口",
                "stages": [
                    {"id": "latent", "name": "潜伏", "requirements": []},
                    {
                        "id": "echo",
                        "name": "回响",
                        "requirements": ["第一次主动承担代价"],
                    },
                ],
            },
        },
    )

    assert created["data"]["stages"][1]["requirements"] == ["第一次主动承担代价"]
    with pytest.raises(StructuredAssetError, match="不能重复"):
        service.create(
            "progression",
            {
                "id": "broken_system",
                "name": "错误体系",
                "kind": "rank",
                "stages": [
                    {"id": "same", "name": "一"},
                    {"id": "same", "name": "二"},
                ],
            },
        )


def test_nested_assets_require_unique_ids_within_the_same_kind(tmp_path: Path):
    init_project(tmp_path, "demo")
    root = tmp_path / "data" / "novels" / "demo" / "src" / "world" / "entities"
    first = root / "domains" / "shared.md"
    second = root / "threats" / "other_name.md"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    content = '+++\nid = "shared"\nname = "重复设定"\nkind = "concept"\n+++\n'
    first.write_text(content, encoding="utf-8")
    second.write_text(content, encoding="utf-8")
    service = StructuredAssetService(tmp_path, "demo")

    with pytest.raises(StructuredAssetError) as read_error:
        service.read("world", "shared")
    with pytest.raises(StructuredAssetError) as list_error:
        service.list("world")

    assert read_error.value.code == "ASSET_CONFLICT"
    assert "domains/shared.md" in str(read_error.value)
    assert "threats/other_name.md" in str(read_error.value)
    assert list_error.value.code == "ASSET_CONFLICT"


def _source_assets(root: Path) -> StructuredAssetService:
    init_project(root, "source")
    service = StructuredAssetService(root, "source")
    service.create(
        "progression",
        {
            "id": "clock_sense",
            "name": "听钟能力",
            "kind": "ability",
            "stages": [{"id": "latent", "name": "潜伏"}],
        },
    )
    service.create(
        "world",
        {
            "id": "org_clockkeepers",
            "data": {
                "name": "守钟人",
                "kind": "organization",
                "summary": "维护钟塔秩序",
                "related": [{"target": "char_linzhou", "kind": "member"}],
            },
        },
    )
    service.create(
        "character",
        {
            "id": "char_linzhou",
            "data": {
                "name": "林舟",
                "summary": "钟楼修复师",
                "organization": "org_clockkeepers",
                "progression_system": "clock_sense",
                "progression_stage": "latent",
                "related": [{"target": "org_clockkeepers", "kind": "member_of"}],
            },
        },
    )
    return service


def test_asset_package_previews_conflicts_and_atomically_imports_with_remap(
    tmp_path: Path,
):
    source_root = tmp_path / "source_project"
    target_root = tmp_path / "target_project"
    _source_assets(source_root)
    package_path = tmp_path / "clock_assets.owasset.zip"
    exported = AssetPackageService(source_root, "source").export(package_path)

    init_project(target_root, "target")
    target_assets = StructuredAssetService(target_root, "target")
    target_assets.create(
        "character",
        {"id": "char_linzhou", "name": "另一个林舟", "summary": "目标项目已有角色"},
    )
    package = AssetPackageService(target_root, "target")
    preview = package.preview_import(package_path)

    assert exported["asset_count"] == 3
    assert preview["counts"] == {"new": 2, "conflict": 1}
    assert preview["missing_dependencies"] == []
    assert next(item for item in preview["assets"] if item["id"] == "char_linzhou")["diff"]

    result = package.import_package(
        package_path,
        expected_sha256=preview["package_sha256"],
        resolutions={
            "char_linzhou": {"action": "rename", "new_id": "char_linzhou_imported"}
        },
    )

    assert len(result["imported"]) == 3
    assert target_assets.read("character", "char_linzhou")["name"] == "另一个林舟"
    imported = target_assets.read("character", "char_linzhou_imported")
    assert imported["data"]["organization"] == "org_clockkeepers"
    organization = target_assets.read("world", "org_clockkeepers")
    assert organization["data"]["related"][0]["target"] == "char_linzhou_imported"
    assert (target_root / "data" / "novels" / "target" / result["receipt_path"]).is_file()


def test_asset_package_replace_preserves_an_existing_nested_location(tmp_path: Path):
    source_root = tmp_path / "source_project"
    target_root = tmp_path / "target_project"
    init_project(source_root, "source")
    source_assets = StructuredAssetService(source_root, "source")
    source_assets.create(
        "world",
        {
            "id": "chaos_beast",
            "data": {
                "name": "新乱律者",
                "kind": "concept",
                "summary": "新版本",
            },
        },
    )
    package_path = tmp_path / "nested_replace.owasset.zip"
    AssetPackageService(source_root, "source").export(package_path)

    init_project(target_root, "target")
    nested = (
        target_root
        / "data"
        / "novels"
        / "target"
        / "src"
        / "world"
        / "entities"
        / "antagonists"
        / "chaos_beast.md"
    )
    nested.parent.mkdir(parents=True)
    nested.write_text(
        '+++\nid = "chaos_beast"\nname = "旧乱律者"\nkind = "concept"\n'
        'summary = "旧版本"\n+++\n',
        encoding="utf-8",
    )
    package = AssetPackageService(target_root, "target")
    preview = package.preview_import(package_path)

    result = package.import_package(
        package_path,
        expected_sha256=preview["package_sha256"],
        resolutions={"chaos_beast": {"action": "replace"}},
    )

    assert result["imported"][0]["path"].endswith(
        "world/entities/antagonists/chaos_beast.md"
    )
    assert "新乱律者" in nested.read_text(encoding="utf-8")
    assert not (nested.parent.parent / "chaos_beast.md").exists()


def test_asset_package_blocks_missing_dependencies_and_changed_source(tmp_path: Path):
    source_root = tmp_path / "source_project"
    target_root = tmp_path / "target_project"
    _source_assets(source_root)
    package_path = tmp_path / "character_only.owasset.zip"
    AssetPackageService(source_root, "source").export(
        package_path,
        selections=[{"kind": "character", "id": "char_linzhou"}],
    )
    init_project(target_root, "target")
    package = AssetPackageService(target_root, "target")
    preview = package.preview_import(package_path)

    assert preview["missing_dependencies"] == ["clock_sense", "org_clockkeepers"]
    with pytest.raises(AssetPackageError) as missing:
        package.import_package(
            package_path,
            expected_sha256=preview["package_sha256"],
        )
    assert missing.value.code == "ASSET_DEPENDENCY_MISSING"

    with package_path.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(AssetPackageError) as changed:
        package.import_package(
            package_path,
            expected_sha256=preview["package_sha256"],
            allow_missing_dependencies=True,
        )
    assert changed.value.code == "ASSET_PACKAGE_CONFLICT"


def test_asset_package_rejects_archive_path_traversal(tmp_path: Path):
    init_project(tmp_path, "demo")
    package_path = tmp_path / "unsafe.owasset.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.writestr("../outside.md", "bad")
        archive.writestr("manifest.yaml", "format: openwrite-asset-package\nversion: 1\n")

    with pytest.raises(AssetPackageError, match="不安全路径"):
        AssetPackageService(tmp_path, "demo").preview_import(package_path)


def test_importing_a_skipped_dependency_is_reported_as_dangling(tmp_path: Path):
    """Skipping a packaged dependency must fail the import, not leave a dangle.

    `missing_dependencies` only looked at what the package does not contain, so
    skipping `char_linzhou` while importing `org_clockkeepers` passed the gate
    and left the imported organization pointing at an asset that does not exist.
    """
    source_root = tmp_path / "source_project"
    target_root = tmp_path / "target_project"
    _source_assets(source_root)
    package_path = tmp_path / "clock_assets.owasset.zip"
    AssetPackageService(source_root, "source").export(package_path)

    init_project(target_root, "target")
    package = AssetPackageService(target_root, "target")
    preview = package.preview_import(package_path)

    with pytest.raises(AssetPackageError) as excinfo:
        package.import_package(
            package_path,
            expected_sha256=preview["package_sha256"],
            resolutions={"char_linzhou": {"action": "skip"}},
        )

    assert excinfo.value.code == "ASSET_DEPENDENCY_MISSING"
    assert "char_linzhou" in (excinfo.value.details or {}).get("missing_dependencies", [])
