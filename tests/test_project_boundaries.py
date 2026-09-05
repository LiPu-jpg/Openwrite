import subprocess
from pathlib import Path

import pytest
import yaml

from tools.context_manifest import build_context_manifest, check_context_manifest_freshness
from tools.git_checkpoint import GitCheckpointManager
from tools.init_project import init_project
from tools.project_registry import ProjectRegistry, is_framework_root
from tools.project_search import ProjectSearchIndex
from tools.resources import resolve_craft_dir


def test_distribution_excludes_deepresearch_runtime_artifacts() -> None:
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")

    assert '"deepresearch/**/artifacts/**"' in pyproject
    assert "prune integrations/deepresearch/packages/*/artifacts" in manifest


def test_distribution_includes_local_studio_editor_assets() -> None:
    root = Path(__file__).parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    required = [
        "index.css",
        "index.min.js",
        "js/icons/ant.js",
        "js/lute/lute.min.js",
    ]

    assert "recursive-include tools/studio_assets *" in manifest
    assert "!/tools/studio_assets/vendor/vditor/dist/**" in ignore
    for relative in required:
        asset = root / "tools" / "studio_assets" / "vendor" / "vditor" / "dist" / relative
        assert asset.is_file()


@pytest.mark.parametrize(
    "novel_id",
    ["", "a", "../escape", "/tmp/book", "book/part", "含空格", "two words"],
)
def test_project_initialization_rejects_unsafe_novel_ids(
    tmp_path: Path, novel_id: str
):
    project = tmp_path / "novel"

    with pytest.raises(ValueError, match="小说 ID"):
        init_project(project, novel_id)

    assert not project.exists()


def test_project_initialization_rejects_existing_id_conflict(tmp_path: Path):
    init_project(tmp_path, "first_book")

    with pytest.raises(ValueError, match="已经绑定"):
        init_project(tmp_path, "second_book")

    config = yaml.safe_load((tmp_path / "novel_config.yaml").read_text(encoding="utf-8"))
    assert config["novel_id"] == "first_book"
    assert not (tmp_path / "data" / "novels" / "second_book").exists()


def test_project_initialization_rolls_back_new_files_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import tools.outline_sync as outline_sync

    project = tmp_path / "failed-project"

    def fail_sync(*args, **kwargs):
        raise RuntimeError("forced sync failure")

    monkeypatch.setattr(outline_sync, "sync_outline_to_hierarchy", fail_sync)

    with pytest.raises(RuntimeError, match="forced sync failure"):
        init_project(project, "failed_book")

    assert not project.exists()


def test_project_initialization_creates_standalone_git_repository(tmp_path: Path):
    project = tmp_path / "novel"
    init_project(project, "demo")

    git_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=project,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert Path(git_root).resolve() == project.resolve()
    assert (project / ".git").exists()


def test_project_registry_keeps_only_existing_projects(tmp_path: Path):
    project = tmp_path / "novel"
    project.mkdir()
    init_project(project, "demo", "雾城来信")
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)

    registry.remember(project)

    assert registry.list()[0]["path"] == str(project.resolve())
    assert registry.list()[0]["title"] == "雾城来信"
    project.rename(tmp_path / "moved")
    assert registry.list() == []


def test_project_registry_does_not_remember_ephemeral_projects(tmp_path: Path):
    project = tmp_path / "novel"
    init_project(project, "demo", "临时验收小说")
    registry = ProjectRegistry(tmp_path / "registry.yaml")

    registry.remember(project)

    assert registry.list() == []
    assert not registry.path.exists()


def test_project_registry_prunes_framework_and_ephemeral_history(tmp_path: Path):
    framework = tmp_path / "framework"
    (framework / "tools").mkdir(parents=True)
    (framework / "tools" / "studio.py").write_text("", encoding="utf-8")
    (framework / "pyproject.toml").write_text(
        '[project]\nname = "openwrite"\n', encoding="utf-8"
    )
    init_project(framework, "framework_demo", "框架误记录")
    temporary = tmp_path / "temporary"
    init_project(temporary, "temporary_demo", "临时验收小说")
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "projects": [
                    {"path": str(framework), "title": "框架误记录"},
                    {"path": str(temporary), "title": "临时验收小说"},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    registry = ProjectRegistry(registry_path)

    assert registry.list() == []
    assert yaml.safe_load(registry_path.read_text(encoding="utf-8"))["projects"] == []


def test_framework_detection_requires_package_and_studio(tmp_path: Path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "studio.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "openwrite"\n', encoding="utf-8"
    )
    assert is_framework_root(tmp_path) is True


def test_craft_resources_fall_back_to_installed_framework(tmp_path: Path):
    bundled = resolve_craft_dir(tmp_path)
    assert (bundled / "scene_craft.md").is_file()
    custom = tmp_path / "craft"
    custom.mkdir()
    (custom / "scene_craft.md").write_text("custom", encoding="utf-8")
    assert resolve_craft_dir(tmp_path) == custom


def test_project_search_returns_line_provenance_and_refreshes(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")
    novel_root = tmp_path / "data" / "novels" / "demo"
    character = novel_root / "src" / "characters" / "lin_cen.md"
    character.write_text(
        "# 林岑\n\n## 未解目标\n\n她在雨夜寻找失踪的旧信。\n", encoding="utf-8"
    )
    index = ProjectSearchIndex(novel_root)

    payload = index.search("雨夜 旧信", scope="characters")

    assert payload["indexed"] >= 1
    result = payload["results"][0]
    assert result["path"] == "src/characters/lin_cen.md"
    assert result["line"] == 5
    assert result["heading"] == "未解目标"

    character.write_text("# 林岑\n\n她改为寻找钟楼。\n", encoding="utf-8")
    refreshed = index.search("旧信", scope="characters")["results"]
    assert all("旧信" not in item["snippet"] for item in refreshed)
    assert index.search("钟楼", scope="characters")["results"][0]["line"] == 3


def test_project_search_exposes_outline_as_its_own_scope(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")
    novel_root = tmp_path / "data" / "novels" / "demo"
    outline = novel_root / "src" / "outline.md"
    outline.write_text("# 大纲\n\n## 第一章\n\n雨夜收到旧信。\n", encoding="utf-8")

    payload = ProjectSearchIndex(novel_root).search("旧信", scope="outline")

    assert payload["results"][0]["path"] == "src/outline.md"
    assert payload["results"][0]["scope"] == "outline"
    story_results = ProjectSearchIndex(novel_root).search("旧信", scope="story")["results"]
    assert all(item["path"] != "src/outline.md" for item in story_results)


def test_context_manifest_records_layers_sources_and_revision(tmp_path: Path):
    init_project(tmp_path, "demo")
    novel_root = tmp_path / "data" / "novels" / "demo"
    packet = {
        "creative_focus": "本章必须保留雨夜意象",
        "story_background": "一座只在雨夜出现的城。",
        "current_arc_sections": [{"summary": "记者收到旧信"}],
    }

    manifest = build_context_manifest(novel_root, packet)

    assert manifest["strategy"] == "hierarchical-provenance-v1"
    assert manifest["revision"]
    levels = {item["section"]: item["level"] for item in manifest["items"]}
    assert levels["creative_focus"] == 1
    assert levels["current_arc_sections"] == 2
    focus = next(item for item in manifest["items"] if item["section"] == "creative_focus")
    assert focus["sources"][0]["path"] == "src/story/current_focus.md"
    assert focus["protected"] is True
    assert focus["selection_reason"]
    assert focus["snippet"] == "本章必须保留雨夜意象"
    assert manifest["request_budget"]["scope"] == "openwrite_writing_request"
    assert manifest["session_budget"] == {
        "scope": "dsh_session",
        "available": False,
        "reason": "not_reported_by_session_runtime",
    }


def test_context_manifest_marks_old_source_snapshot_stale(tmp_path: Path):
    init_project(tmp_path, "demo")
    novel_root = tmp_path / "data" / "novels" / "demo"
    focus_path = novel_root / "src" / "story" / "current_focus.md"
    focus_path.write_text("雨夜必须出现钟声。", encoding="utf-8")
    manifest = build_context_manifest(
        novel_root,
        {"creative_focus": "雨夜必须出现钟声。"},
    )

    assert check_context_manifest_freshness(novel_root, manifest)["status"] == "current"
    focus_path.write_text("雨夜必须出现钟声，并让旧信被烧毁。", encoding="utf-8")

    freshness = check_context_manifest_freshness(novel_root, manifest)
    assert freshness["status"] == "stale"
    assert freshness["reason"] == "source_revision_changed"
    assert freshness["changed_sources"] == ["src/story/current_focus.md"]


def test_context_manifest_prefers_canonical_library_groups_without_double_counting(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    novel_root = tmp_path / "data" / "novels" / "demo"
    packet = {
        "core_documents": {"background": "核心背景"},
        "story_background": "核心背景",
        "setting_documents": {"world.rules": "设定规则"},
        "concept_documents": {"world.rules": "设定规则"},
        "continuity_documents": {"current_state": "当前状态"},
        "current_state": "当前状态",
    }

    manifest = build_context_manifest(novel_root, packet)
    sections = {item["section"] for item in manifest["items"]}

    assert manifest["schema_version"] == 2
    assert {"core_documents", "setting_documents", "continuity_documents"} <= sections
    assert {"story_background", "concept_documents", "current_state"}.isdisjoint(
        sections
    )

    empty_manifest = build_context_manifest(
        novel_root,
        {"setting_documents": {"world.rules": ""}},
    )
    assert empty_manifest["items"] == []


def test_git_checkpoint_requires_private_standalone_content_repository(tmp_path: Path):
    project = tmp_path / "novel"
    project.mkdir()
    init_project(project, "demo")
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
    metadata_path = project / ".openwrite" / "project.yaml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    metadata["git"]["auto_checkpoint"] = True
    metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    outline = project / "data" / "novels" / "demo" / "src" / "outline.md"
    outline.write_text(outline.read_text(encoding="utf-8") + "\n新增一幕。\n", encoding="utf-8")

    result = GitCheckpointManager(project).checkpoint(
        ["data/novels/demo/src/outline.md"], "outline: add a new act"
    )

    assert result.ok is True
    assert result.committed is True
    subject = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=project,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert subject == "outline: add a new act"


def test_git_checkpoint_uses_nested_standalone_content_repository(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    project = tmp_path / "novel"
    project.mkdir()
    init_project(project, "demo")

    status = GitCheckpointManager(project).status()

    assert status["eligible"] is True
    assert status["project_type"] == "novel-content"
    git_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=project,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert Path(git_root).resolve() == project.resolve()
