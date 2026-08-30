from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.chapter_assembler import ChapterAssemblerV2
from tools.chapter_pipeline import _style_profile
from tools.init_project import init_project
from tools.project_registry import ProjectRegistry
from tools.reference_library import ReferenceLibraryService
from tools.source_analysis import SourceAnalysisError
from tools.studio import StudioApplication
from tools.style_synthesizer import build_style_manifest


def _analyzer(text: str, context: dict) -> dict:
    quote = text[: min(10, len(text))]
    return {
        "summary": f"第 {context['chunk_index'] + 1} 块摘要",
        "model": "fixture-model",
        "findings": [
            {
                "category": "voice",
                "claim": "动作先于解释，使用短段落推进冲突",
                "confidence": 0.9,
                "reusable": True,
                "source_bound": False,
                "evidence": [{"start": 0, "end": len(quote), "quote": quote}],
            }
        ],
    }


def _text(label: str) -> str:
    return (
        f"序言\n{label}的测试原文。\n"
        f"第一章 雨夜\n\n{label}推开门。\n“谁在那里？”\n"
        f"第二章 钟声\n\n钟声连续响了三次。\n{label}没有回头。\n"
    )


def _asset_analyzer(text: str, context: dict) -> dict:
    categories = [
        "world",
        "relationship",
        "progression",
        "timeline",
        "thread",
        "arc_summary",
        "chapter_summary",
        "hook",
    ]
    findings = []
    for index, category in enumerate(categories):
        start = min(index, len(text) - 1)
        findings.append(
            {
                "category": category,
                "claim": f"{category} 的证据化结论",
                "confidence": 0.85,
                "reusable": category in {"hook", "thread"},
                "source_bound": category not in {"hook", "thread"},
                "evidence": [
                    {"start": start, "end": start + 1, "quote": text[start : start + 1]}
                ],
            }
        )
    return {
        "summary": f"第 {context['chunk_index'] + 1} 块资产摘要",
        "model": "fixture-model",
        "findings": findings,
    }


def test_reference_library_keeps_raw_source_outside_project_and_gates_analysis(
    tmp_path: Path,
):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "参考库测试")
    service = ReferenceLibraryService(
        library,
        project_root=project,
        novel_id="demo",
    )

    prepared = service.prepare(
        "reference_a",
        _text("甲"),
        title="甲参考",
        relative_name="alpha.txt",
        input_budget_tokens=500,
    )

    assert prepared["structure"]["status"] == "awaiting_confirmation"
    assert len(prepared["structure"]["units"]) == 3
    assert (library / "sources" / "reference_a" / "library.json").is_file()
    assert not (
        project / "data" / "novels" / "demo" / "data" / "sources" / "reference_a"
    ).exists()
    with pytest.raises(SourceAnalysisError) as error:
        service.analyze("reference_a", analyzer=_analyzer)
    assert error.value.code == "CONFIRMATION_REQUIRED"

    service.confirm_structure("reference_a")
    analyzed = service.analyze("reference_a", analyzer=_analyzer)

    assert analyzed["ok"] is True
    assert set(analyzed["assets"]) == {
        "style",
        "structure",
        "characters",
        "world",
        "relationships",
        "progression",
        "timeline",
        "threads",
        "summaries",
        "risks",
        "fingerprint",
    }
    status = service.status("reference_a")
    assert status["analysis"]["complete"] is True
    assert any(asset["kind"] == "fingerprint" for asset in status["assets"])


def test_single_chapter_heading_keeps_front_matter_and_chapter_boundaries(tmp_path: Path):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "单章结构测试")
    service = ReferenceLibraryService(library, project_root=project, novel_id="demo")

    prepared = service.prepare(
        "single_chapter",
        "作品信息\n作者信息\n\n# 第1章 起点\n正文从这里开始。\n",
        title="单章参考",
        relative_name="single.txt",
        input_budget_tokens=500,
    )

    units = prepared["structure"]["units"]
    assert [item["kind"] for item in units] == ["front_matter", "chapter"]
    assert units[0]["end"] == units[1]["start"]
    assert units[-1]["end"] == prepared["record"]["total_chars"]


def test_read_content_returns_snapshot_and_confirmed_units(tmp_path: Path):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "参考原文读取测试")
    service = ReferenceLibraryService(library, project_root=project, novel_id="demo")
    source = _text("读取")

    prepared = service.prepare(
        "reference_read",
        source,
        title="可读参考",
        relative_name="read.txt",
        input_budget_tokens=500,
    )
    service.confirm_structure("reference_read")

    result = service.read_content("reference_read")

    assert result["content"] == source
    assert result["record"]["source_id"] == "reference_read"
    assert result["structure"]["status"] == "confirmed"
    assert len(result["units"]) == len(prepared["structure"]["units"])
    assert result["units"][0]["title"] == prepared["structure"]["units"][0]["title"]
    for unit, expected in zip(result["units"], prepared["structure"]["units"]):
        assert unit["unit_id"] == expected["unit_id"]
        assert unit["content"] == source[expected["start"] : expected["end"]]


def test_studio_application_reads_reference_content(tmp_path: Path):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "Studio 参考原文入口测试")
    service = ReferenceLibraryService(library, project_root=project, novel_id="demo")
    source = _text("应用入口")
    service.prepare(
        "reference_studio",
        source,
        title="Studio 参考",
        relative_name="studio.txt",
        input_budget_tokens=500,
    )
    service.confirm_structure("reference_studio")

    app = StudioApplication(project, reference_library_root=library)
    result = app.read_reference_library_content("reference_studio")

    assert result["content"] == source
    assert result["units"][-1]["content"]


def test_reference_analysis_materializes_story_assets_in_private_library(tmp_path: Path):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "故事资产测试")
    service = ReferenceLibraryService(library, project_root=project, novel_id="demo")
    service.prepare(
        "reference_assets",
        _text("资产"),
        title="资产参考",
        relative_name="assets.txt",
        input_budget_tokens=500,
    )
    service.confirm_structure("reference_assets")

    analyzed = service.analyze("reference_assets", analyzer=_asset_analyzer)

    asset_root = library / "sources" / "reference_assets" / "assets"
    assert analyzed["assets"]["world"]["items"] == 1
    assert analyzed["assets"]["relationships"]["items"] == 1
    assert analyzed["assets"]["progression"]["items"] == 1
    assert analyzed["assets"]["timeline"]["items"] == 1
    assert analyzed["assets"]["threads"]["items"] == 2
    assert analyzed["assets"]["summaries"]["items"] == 2
    assert json.loads((asset_root / "world.json").read_text(encoding="utf-8"))[
        "findings"
    ][0]["category"] == "world"
    assert not (
        project / "data" / "novels" / "demo" / "data" / "sources" / "reference_assets"
    ).exists()


def test_confirmed_adoption_writes_snapshot_recipe_and_review_fingerprint(tmp_path: Path):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "采纳测试")
    service = ReferenceLibraryService(
        library,
        project_root=project,
        novel_id="demo",
    )
    for source_id, label in (("reference_a", "甲"), ("reference_b", "乙")):
        service.prepare(
            source_id,
            _text(label),
            title=f"{label}参考",
            relative_name=f"{source_id}.txt",
            input_budget_tokens=500,
        )
        service.confirm_structure(source_id)
        service.analyze(source_id, analyzer=_analyzer)

    profile = service.synthesize(["reference_a", "reference_b"])
    item = profile.common_methods[0]
    preview = service.preview_adoption(
        profile.profile_id,
        [
            {
                "item_id": item.item_id,
                "target": "style",
                "dimension": "rhythm",
                "role": "primary",
                "scope": "project",
            }
        ],
    )

    assert "data/style/recipe.yaml" in preview.proposed_files
    assert "data/style/fingerprint.yaml" in preview.proposed_files
    with pytest.raises(SourceAnalysisError) as confirmation:
        service.apply_adoption(preview.preview_id, confirm=False)
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    applied = service.apply_adoption(preview.preview_id, confirm=True)
    novel_root = project / "data" / "novels" / "demo"
    recipe = yaml.safe_load(
        (novel_root / "data" / "style" / "recipe.yaml").read_text(encoding="utf-8")
    )
    fingerprint = yaml.safe_load(
        (novel_root / "data" / "style" / "fingerprint.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert applied["ok"] is True
    assert recipe["selections"][0]["claim"] == item.claim
    assert recipe["selections"][0]["role"] == "primary"
    assert fingerprint["mode"] == "review_validation"
    assert fingerprint["writer_injection"] is False
    assert (novel_root / "data" / "style" / "composed.md").is_file()
    assert (
        novel_root
        / "data"
        / "reference_adoptions"
        / f"{applied['adoption_id']}.yaml"
    ).is_file()


def test_adoption_rejects_two_primary_styles_for_same_dimension(tmp_path: Path):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "冲突测试")
    service = ReferenceLibraryService(
        library,
        project_root=project,
        novel_id="demo",
    )
    for source_id, label, claim in (
        ("reference_a", "甲", "使用短句推进"),
        ("reference_b", "乙", "使用长句延宕"),
    ):
        service.prepare(
            source_id,
            _text(label),
            title=f"{label}参考",
            relative_name=f"{source_id}.txt",
            input_budget_tokens=500,
        )
        service.confirm_structure(source_id)

        def analyzer(text: str, context: dict, *, current_claim=claim) -> dict:
            payload = _analyzer(text, context)
            payload["findings"][0]["claim"] = current_claim
            return payload

        service.analyze(source_id, analyzer=analyzer)

    profile = service.synthesize(["reference_a", "reference_b"])
    items = [*profile.differences, *profile.optional_variants]
    assert len(items) == 2
    with pytest.raises(SourceAnalysisError) as conflict:
        service.preview_adoption(
            profile.profile_id,
            [
                {
                    "item_id": item.item_id,
                    "target": "style",
                    "dimension": "rhythm",
                    "role": "primary",
                    "scope": "project",
                }
                for item in items
            ],
        )
    assert conflict.value.code == "INVALID_INPUT"


def test_multi_source_profile_clusters_semantic_claims_and_keeps_evidence(tmp_path: Path):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "语义对照测试")
    service = ReferenceLibraryService(library, project_root=project, novel_id="demo")
    claims = {
        "reference_a": "动作先于解释，使用短段落推进冲突",
        "reference_b": "动作先于解释，用短段落推动冲突",
    }
    for source_id, label in (("reference_a", "甲"), ("reference_b", "乙")):
        service.prepare(
            source_id,
            _text(label),
            title=f"{label}参考",
            relative_name=f"{source_id}.txt",
            input_budget_tokens=500,
        )
        service.confirm_structure(source_id)

        def analyzer(text: str, context: dict, *, claim=claims[source_id]) -> dict:
            payload = _analyzer(text, context)
            payload["findings"][0]["claim"] = claim
            return payload

        service.analyze(source_id, analyzer=analyzer)

    profile = service.synthesize(["reference_a", "reference_b"])

    assert len(profile.common_methods) == 1
    assert profile.common_methods[0].source_ids == ["reference_a", "reference_b"]
    assert {item.source_id for item in profile.common_methods[0].evidence} == {
        "reference_a",
        "reference_b",
    }


def test_reference_intent_excludes_bound_facts_but_continuation_can_adopt_them(
    tmp_path: Path,
):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "意图策略测试")
    service = ReferenceLibraryService(library, project_root=project, novel_id="demo")

    def bound_analyzer(text: str, context: dict) -> dict:
        payload = _analyzer(text, context)
        payload["findings"][0].update(
            {
                "category": "world",
                "claim": "旧稿中的雾钟每天少走十三秒",
                "reusable": False,
                "source_bound": True,
            }
        )
        return payload

    for source_id, intent in (("external", "reference"), ("own_draft", "continuation")):
        service.prepare(
            source_id,
            _text(source_id),
            title=source_id,
            relative_name=f"{source_id}.txt",
            intent=intent,
            input_budget_tokens=500,
        )
        service.confirm_structure(source_id)
        service.analyze(source_id, analyzer=bound_analyzer)

    external = service.synthesize(["external"])
    own_draft = service.synthesize(["own_draft"])

    assert not external.optional_variants
    assert any("旧稿中的雾钟" in item for item in external.excluded_items)
    item = own_draft.optional_variants[0]
    assert item.source_bound is True
    preview = service.preview_adoption(
        own_draft.profile_id,
        [
            {
                "item_id": item.item_id,
                "target": "setting_candidates",
                "dimension": "craft",
                "role": "auxiliary",
                "scope": "project",
            }
        ],
    )
    assert "旧稿中的雾钟" in preview.proposed_files[
        "data/planning/reference_setting_candidates.md"
    ]
    with pytest.raises(SourceAnalysisError, match="不能作为风格配方"):
        service.preview_adoption(
            own_draft.profile_id,
            [
                {
                    "item_id": item.item_id,
                    "target": "style",
                    "dimension": "craft",
                    "role": "auxiliary",
                    "scope": "project",
                }
            ],
        )


def test_writer_excludes_fingerprint_while_reviewer_keeps_it():
    documents = {
        "work.composed": "动作先于解释。",
        "work.fingerprint": "targets:\n  dialogue_ratio: 0.4",
    }

    writer = _style_profile(documents, 2000, include_fingerprint=False)
    reviewer = _style_profile(documents, 2000, include_fingerprint=True)

    assert "动作先于解释" in writer
    assert "dialogue_ratio" not in writer
    assert "dialogue_ratio" in reviewer


def test_reference_library_lists_profile_ids_and_adoption_status(tmp_path: Path):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "画像导航测试")
    service = ReferenceLibraryService(library, project_root=project, novel_id="demo")

    for source_id in ("reference_a", "reference_b"):
        service.prepare(
            source_id,
            _text(source_id),
            title=source_id,
            relative_name=f"{source_id}.txt",
            input_budget_tokens=500,
        )
        service.confirm_structure(source_id)
        service.analyze(source_id, analyzer=_analyzer)

    profile = service.synthesize(["reference_a", "reference_b"])
    preview = service.preview_adoption(
        profile.profile_id,
        [
            {
                "item_id": profile.common_methods[0].item_id,
                "target": "style",
                "dimension": "narration",
                "role": "primary",
                "scope": "project",
            }
        ],
    )
    service.apply_adoption(preview.preview_id, confirm=True)

    profiles = service.list_profiles()

    assert profiles == [
        {
            "profile_id": profile.profile_id,
            "source_ids": ["reference_a", "reference_b"],
            "source_intents": {
                "reference_a": "reference",
                "reference_b": "reference",
            },
            "generated_at": profile.generated_at,
            "status": "current",
            "stale_source_ids": [],
            "item_counts": {
                "common_methods": 1,
                "differences": 0,
                "optional_variants": 0,
                "conflicts": 0,
                "excluded": 0,
            },
            "adoption_ids": [preview.adoption.adoption_id],
        }
    ]


def test_style_recipe_compiles_project_rules_and_resolves_scoped_overrides(
    tmp_path: Path,
):
    project = tmp_path / "project"
    init_project(project, "demo", "范围风格测试")
    style_root = project / "data" / "novels" / "demo" / "data" / "style"
    recipe = {
        "schema_version": 1,
        "novel_id": "demo",
        "selections": [
            {
                "claim": "全书使用近距离第三人称",
                "target": "style",
                "dimension": "narration",
                "role": "primary",
                "scope": "project",
                "scope_id": "",
            },
            {
                "claim": "本篇冲突段改用短段落",
                "target": "style",
                "dimension": "rhythm",
                "role": "auxiliary",
                "scope": "arc",
                "scope_id": "arc_002",
            },
            {
                "claim": "本章不要解释人物动机",
                "target": "style",
                "dimension": "avoid",
                "role": "avoid",
                "scope": "chapter",
                "scope_id": "ch_007",
            },
        ],
    }
    style_root.mkdir(parents=True, exist_ok=True)
    (style_root / "recipe.yaml").write_text(
        yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    manifest = build_style_manifest(project, "demo", "reference-recipe")
    assembler = ChapterAssemblerV2(project, "demo")
    scoped = assembler._load_scoped_style_rules(
        chapter_id="ch_007", arc_id="arc_002"
    )

    assert "全书使用近距离第三人称" in manifest["narration_rules"]
    assert manifest["primary_signals"] == ["全书使用近距离第三人称"]
    assert "本篇冲突段改用短段落" not in manifest["rhythm_rules"]
    assert "本篇冲突段改用短段落" in scoped
    assert "本章不要解释人物动机" in scoped


def test_studio_reference_surface_uses_injected_private_library(tmp_path: Path):
    project = tmp_path / "project"
    library = tmp_path / "private-library"
    init_project(project, "demo", "Studio 参考库测试")
    app = StudioApplication(
        project,
        project_registry=ProjectRegistry(
            tmp_path / "recent.yaml", allow_ephemeral=True
        ),
        reference_library_root=library,
    )
    try:
        prepared = app.reference_library_action(
            {
                "action": "prepare",
                "source_id": "reference_studio",
                "title": "Studio 参考",
                "relative_name": "studio.txt",
                "intent": "reference",
                "content": _text("丙"),
                "input_budget_tokens": 500,
            }
        )
        confirmed = app.reference_library_action(
            {"action": "confirm_structure", "source_id": "reference_studio"}
        )

        records = confirmed["workspace"]["operations"]["reference_library"]
        assert prepared["result"]["structure"]["status"] == "awaiting_confirmation"
        assert records[0]["record"]["title"] == "Studio 参考"
        assert records[0]["structure"]["status"] == "confirmed"
        assert (library / "sources" / "reference_studio" / "library.json").is_file()
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)
