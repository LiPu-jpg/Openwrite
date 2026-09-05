import json
import logging
import os
from http import HTTPStatus
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
import yaml

from tools.agent.book_state import BookStage, BookStateStore
from tools.cli import _save_chapter
from tools.context_builder import ContextBuilder
from tools.init_project import init_project
from tools.llm.response import ProviderResponseError
from tools.manuscript_editing import ManuscriptVersionStore
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.model_profiles import ModelProfileStore
from tools.novel_service import NovelServiceError
from tools.project_registry import ProjectRegistry
from tools.review_store import ReviewStore
from tools.revision_service import RevisionService
from tools.studio import (
    StudioApplication,
    StudioError,
    create_server,
    render_chat_markdown,
)
from tools.studio_contracts import StudioError as ContractStudioError
from tools.studio_contracts import studio_error_payload
from tools.studio_http import POST_ROUTE_PATTERNS, POST_ROUTES, resolve_post_route
from tools.studio_preferences import StudioModelSettingsStore
from tools.workflow_scheduler import WorkflowScheduler


def _studio_javascript(assets: Path) -> str:
    modules = sorted((assets / "js").glob("*.js"))
    return "\n".join(path.read_text(encoding="utf-8") for path in [assets / "app.js", *modules])


def test_studio_assets_load_shared_core_as_an_es_module():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    app = (assets / "app.js").read_text(encoding="utf-8")
    core = (assets / "js" / "core.js").read_text(encoding="utf-8")
    application = (assets / "js" / "application.js").read_text(encoding="utf-8")
    revisions = (assets / "js" / "revisions.js").read_text(encoding="utf-8")
    tasks = (assets / "js" / "tasks.js").read_text(encoding="utf-8")
    structured_assets = (assets / "js" / "assets.js").read_text(encoding="utf-8")

    assert '<script type="module" src="/app.js?v=startup-recovery-1"></script>' in html
    assert 'import "/js/application.js?v=startup-recovery-1"' in app
    assert 'from "/js/core.js"' in application
    assert "export const state" in core
    assert "export async function api" in core
    assert "error.requestId" in core
    assert 'from "/js/revisions.js"' in application
    assert "showRevisionPreview" in revisions
    assert "DOCUMENT_CONFLICT" in revisions
    assert 'from "/js/tasks.js"' in application
    assert "enqueueTask" in tasks
    assert "/api/tasks" in tasks
    assert 'from "/js/assets.js"' in application
    assert "openStructuredAsset" in structured_assets
    assert "/api/assets/package/preview" in structured_assets
    assert "data-package-action" in structured_assets
    assert "\\`" not in application
    assert "innerHTML" not in application
    assert "appendSafeChatMarkup" in application
    assert 'save_origin: silent ? "autosave" : "manual"' in application
    assert "known_source_revision" in application
    assert "dsh 会话预算：不可用" in application
    assert "item.protection_reason" in application


def test_studio_advanced_tools_explain_scope_and_support_accessible_help():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    application = (assets / "js" / "application.js").read_text(encoding="utf-8")
    styles = (assets / "styles.css").read_text(encoding="utf-8")
    tools_view = html.split('<section id="tools-view"', 1)[1].split("</main>", 1)[0]

    help_ids = (
        "tool-sync-help",
        "tool-context-help",
        "tool-asset-help",
        "tool-run-help",
        "tool-plan-help",
        "tool-forecast-help",
    )
    assert tools_view.count('class="tool-help-button"') == len(help_ids)
    assert tools_view.count('data-tool-help aria-expanded="false"') == len(help_ids)
    for help_id in help_ids:
        assert f'aria-controls="{help_id}"' in tools_view
        assert f'id="{help_id}" class="tool-help-panel" hidden' in tools_view
    assert "只读" in tools_view
    assert "会写入" in tools_view
    assert "候选不直接改大纲" in tools_view
    assert "function toggleToolHelp(button)" in application
    assert "closeOpenToolHelp(true)" in application
    assert '.tool-help-button[aria-expanded="true"]' in styles
    assert ".tool-help-panel[hidden]" in styles
    assert ".tool-workflow-heading" in styles


def test_studio_writer_workspace_keeps_primary_navigation_and_contextual_tools():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    application = (assets / "js" / "application.js").read_text(encoding="utf-8")
    styles = (assets / "styles.css").read_text(encoding="utf-8")
    primary_nav = html.split('<div class="nav-group nav-primary">', 1)[1].split("</div>", 1)[0]

    assert primary_nav.count('class="nav-item') == 6
    assert 'data-view="research"' in html
    assert 'id="research-settings-open"' in html
    assert 'id="research-settings-dialog"' in html
    assert 'id="library-tabs"' in html
    assert 'id="editor-find-panel"' in html
    assert 'id="editor-reading-toggle"' in html
    assert 'id="editor-focus-toggle"' in html
    assert 'id="inspector-assistant-form"' in html
    assert 'id="inspector-backdrop"' in html
    assert 'class="mobile-compact-icon"' in html
    assert 'id="revision-hunks-list"' in html
    assert 'id="delete-chapter"' in html
    assert 'id="chapter-delete-dialog"' in html
    assert 'id="writing-targets-open"' in html
    assert 'id="writing-targets-dialog"' in html
    assert 'id="writing-target-chapter"' in html
    assert 'api("/api/project/writing-targets"' in application
    assert 'id="reference-synthesize"' in html
    assert 'id="reference-structure-confirm"' in html
    assert 'id="reference-send-goethe"' in html
    assert 'id="reference-adoption-preview"' in html
    assert 'id="reference-adoption-apply"' in html
    assert '"character", "world", "relationship", "progression", "timeline"' in application
    assert 'role.value = item.category === "risk" ? "avoid" : "auxiliary"' in application
    assert 'world: ["setting_candidates", "craft"]' in application
    assert "标准 SKILL.md" in application
    assert "useRuntimeSkill" in application
    assert "function scheduleAutoSave()" in application
    assert "if (!state.workspace) return;" in application
    assert "toggleMobileNavigation(false, false)" in application
    assert "toggleInspector(false, false)" in application
    assert 'action: "prepare"' in application
    assert "renderReferenceStructure" in application
    assert "enqueueReferenceAnalysis" in application
    assert "synthesizeReferenceProfile" in application
    assert "previewReferenceAdoption" in application
    assert "applyReferenceAdoption" in application
    assert "inspector.contains(document.activeElement)" in application
    assert "sidebar.contains(document.activeElement)" in application
    assert "saveDocument({ silent: true })" in application
    assert "function findNextEditorMatch()" in application
    assert "function openChapterDeleteDialog()" in application
    assert 'api("/api/chapter/delete"' in application
    assert 'api("/api/chat"' in application
    assert "【精确人物状态】" in application
    assert "【语义远距记忆（仅供参考）】" in application
    assert "语义召回" in application
    assert ".app.editor-focus .workspace-shell" in styles
    assert ".editor-view.reading-width .document-editor" in styles
    assert ".inspector-backdrop:not([hidden])" in styles
    assert "@media (max-width: 360px)" in styles
    assert ".source-analysis-toolbar" in styles


def test_studio_structured_asset_ui_keeps_raw_mode_and_explicit_import_decisions():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    javascript = _studio_javascript(assets)
    styles = (assets / "styles.css").read_text(encoding="utf-8")
    styles = (assets / "styles.css").read_text(encoding="utf-8")

    assert 'id="library-navigation"' in html
    assert 'data-library-view="characters"' in html
    assert 'data-library-view="settings"' in html
    assert '<option value="character">角色</option>' in html
    assert '<option value="world">设定</option>' in html
    assert '<option value="progression">成长体系</option>' in html
    assert 'data-asset-mode="raw"' in html
    assert 'role="tablist" aria-label="资料编辑方式"' in html
    assert 'id="asset-package-dialog"' in html
    assert "ASSET_CONFLICT" in javascript
    assert "replace" in javascript and "rename" in javascript and "skip" in javascript
    assert "function addRelationField" in javascript
    assert "function createRelationReferenceRow" in javascript
    assert "draft.relation_view || {}" in javascript
    assert 'option.addEventListener("pointerdown", choose)' in javascript
    assert "保存后生效" in javascript
    assert 'search.placeholder = "搜索名称、ID、类型或标签"' in javascript
    assert 'data.related = $$(".asset-relation-row")' in javascript
    assert "请先保存当前更改，再切换编辑方式" in javascript
    assert ".asset-editor-pane" in styles
    assert ".asset-stage-row" in styles
    assert ".asset-field-section" in styles
    assert ".asset-relation-options[hidden]" in styles
    assert ".asset-relation-reference-row" in styles
    assert "@media (max-width: 900px)" in styles
    assert ".asset-relation-row {\n    position: relative;\n    padding-right: 44px;" in styles
    assert "--asset-label-column: 128px;" in styles
    assert "grid-template-columns: var(--asset-label-column) minmax(0, 1fr);" in styles
    assert ".asset-form-actions .form-status {\n  grid-column: 2;" in styles
    assert ".asset-field {\n  display: grid;\n  align-self: start;" in styles


def test_studio_continuity_distinguishes_field_and_registered_relations():
    root = Path(__file__).parents[1] / "tools" / "studio_assets"
    html = (root / "index.html").read_text(encoding="utf-8")
    javascript = (root / "js" / "application.js").read_text(encoding="utf-8")
    styles = (root / "styles.css").read_text(encoding="utf-8")

    assert 'id="relationship-origin"' in html
    assert '<option value="canonical">资料字段</option>' in html
    assert '<option value="annotation">内联注册</option>' in html
    assert "//**A~&gt;B:具体关系**" in html
    assert "同章以正文事实为准" in html
    assert 'path.classList.toggle("annotation", edge.origin === "annotation")' in javascript
    assert 'refreshContinuity: loadContinuity' in javascript
    assert ".relationship-edge.annotation" in styles
    assert html.index('class="tool-card relationship-card"') < html.index('class="truth-grid"')
    assert ".relationship-card {\n  margin-top: 26px;\n  padding: 0;\n  border: 0;" in styles
    assert "height: clamp(620px, 68vh, 760px);" in styles


def test_studio_post_route_registry_matches_application_surface():
    assert POST_ROUTES
    for route, contract in POST_ROUTES.items():
        assert route.startswith("/api/")
        assert hasattr(StudioApplication, contract.method_name)
    assert POST_ROUTE_PATTERNS
    contract, parameters = resolve_post_route(
        "/api/revisions/rev_20260802120000_abcdef1234/apply"
    )
    assert contract is not None and contract.method_name == "apply_revision"
    assert parameters["proposal_id"].startswith("rev_")


def test_studio_error_contract_preserves_legacy_error_string():
    error = ContractStudioError(
        "原文已变化",
        HTTPStatus.CONFLICT,
        code="DOCUMENT_CONFLICT",
        recoverable=True,
        details={"chapter_id": "ch_001"},
    )
    payload = studio_error_payload(error, "req_test")

    assert payload["error"] == "原文已变化"
    assert payload["code"] == "DOCUMENT_CONFLICT"
    assert payload["recoverable"] is True
    assert payload["details"] == {"chapter_id": "ch_001"}
    assert payload["request_id"] == "req_test"


def test_studio_model_form_uses_valid_output_step_and_interface_presets():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    javascript = _studio_javascript(assets)
    styles = (assets / "styles.css").read_text(encoding="utf-8")

    assert (
        'id="model-max-tokens" type="number" min="256" max="10000000" step="1" value="24000"'
    ) in html
    assert (
        'id="model-context-tokens" type="number" min="12000" max="10000000" '
        'step="1000" value="64000"'
    ) in html
    assert 'value="openai">OpenAI 格式接口<' in html
    assert 'value="anthropic">Anthropic 格式接口<' in html
    assert 'id="model-preset-help"' in html
    assert 'id="model-remember-key" type="checkbox" checked' in html
    assert 'id="model-embedding-provider"' in html
    assert 'value="local">本地 FastEmbed<' in html
    assert 'id="model-embedding-preset"' in html
    assert 'id="model-embedding-preset-help"' in html
    assert 'id="model-embedding-test"' in html
    assert "/api/model/embedding/test" in javascript
    assert 'model: "jinaai/jina-embeddings-v2-base-zh"' in javascript
    assert 'model: "intfloat/multilingual-e5-large"' in javascript
    assert 'model: "text-embedding-v3"' in javascript
    assert 'model: "Qwen/Qwen3-Embedding-0.6B"' in javascript
    assert "function applyEmbeddingPreset()" in javascript
    assert "function syncEmbeddingPreset()" in javascript
    assert "[data-embedding-cloud][hidden]" in styles
    assert "function renderPresetOptions(" in javascript
    assert "function renderPresetHelp(" in javascript
    assert "接口模板；当前容量以下方数值为准" in javascript
    assert "(surface().presets || []).forEach" in javascript
    assert 'interfaces.label = "接口模板"' in javascript
    assert 'model: "gpt-5.6-sol"' in javascript
    assert 'model: "claude-sonnet-5"' in javascript
    assert "remember_api_key" in javascript
    assert "Number(preset.context_tokens) === Number(profile?.context_tokens)" in javascript
    assert "Number(preset.max_tokens) === Number(profile?.max_output_tokens)" in javascript
    assert "if (exact) return exact.id;" in javascript
    assert (
        'return name === "deepseek-v4-flash" ? "deepseek-flash" : "deepseek-pro";'
        not in javascript
    )


def test_studio_local_embedding_probe_does_not_require_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured = {}

    def fake_probe(settings):
        captured["settings"] = settings
        return {
            "ok": True,
            "provider": "local",
            "model": settings.model,
            "dimension": settings.dimension,
            "latency_ms": 1,
        }

    monkeypatch.setattr("tools.embedding_runtime.run_embedding_probe", fake_probe)
    app = StudioApplication(
        tmp_path,
        model_profile_store=ModelProfileStore(tmp_path / "profiles"),
    )
    result = app.test_embedding_connection(
        {
            "id": "local-search",
            "label": "Local Search",
            "provider": "local",
            "base_url": "",
            "model": "BAAI/bge-small-zh-v1.5",
            "dimension": 512,
            "max_tokens": 512,
        }
    )

    assert result["ok"] is True
    assert captured["settings"].provider == "local"
    assert captured["settings"].api_key == ""


def test_studio_onboarding_ui_guides_new_projects_and_next_actions():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    javascript = _studio_javascript(assets)
    styles = (assets / "styles.css").read_text(encoding="utf-8")

    assert "runNextAction" in javascript
    assert "agentEmptyGuidance" in javascript
    assert "next_action_items" in javascript
    assert "open_goethe" in javascript
    assert 'id="product-tour"' in html
    assert 'id="product-tour-spotlight"' in html
    assert 'id="product-tour-back"' in html
    assert "productTourSteps" in javascript
    assert "认识你的写作工作台" in javascript
    assert "左侧是作品的工作地图" in javascript
    assert "故事、人物、世界" in javascript
    assert "goToPreviousProductTourStep" in javascript
    assert "productTourStorageKey" in javascript
    assert "productTourDebugMode" in javascript
    assert 'get("debug") === "onboarding"' in javascript
    assert '"?debug=onboarding"' in javascript
    assert 'writeLocalValue(productTourStorageKey, "seen")' in javascript
    assert "startProductTour" in javascript
    assert "advanceProductTourAfterAction" in javascript
    assert "onProfileSaved" in javascript
    assert 'advanceProductTourAfterAction("model")' in javascript
    assert "const tourAction" in javascript
    assert "告诉 Goethe 你想写什么故事" in javascript
    assert "next-action-button" in styles
    assert ".product-tour-spotlight" in styles
    assert ".product-tour-card" in styles
    assert "project-demo-seed" not in html
    assert "自定义作品目录（可选）" in html
    assert 'id="project-path" required' not in html
    assert "suggestProjectPath" in javascript
    assert "confirmDeleteProject" in javascript
    assert "recent-project-delete" in styles
    assert "delete-project-form" not in html


def test_studio_init_accepts_demo_short_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    app = StudioApplication(
        tmp_path,
        model_settings_store=StudioModelSettingsStore(tmp_path / "prefs"),
    )
    result = app.initialize_project(
        {
            "project_path": str(tmp_path / "demo_book"),
            "novel_id": "demo_novel",
            "title": "雾城来信",
            "template": "demo_short",
        }
    )
    assert result["initialized"] is True
    assert result["snapshot"]["readiness"]["characters"] is True
    assert result["snapshot"]["readiness"]["outline"] is True
    assert result["snapshot"]["readiness"]["author_intent"] is True


def test_studio_delete_project_removes_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    app = StudioApplication(
        tmp_path,
        model_settings_store=StudioModelSettingsStore(tmp_path / "prefs"),
    )
    app.initialize_project(
        {
            "project_path": str(tmp_path / "doomed_novel"),
            "novel_id": "doomed",
            "title": "将删之书",
            "template": "default",
        }
    )
    assert (tmp_path / "doomed_novel" / "novel_config.yaml").exists()

    with pytest.raises(StudioError, match="确认"):
        app.delete_project({"project_path": str(tmp_path / "doomed_novel"), "confirm": "wrong"})

    app.delete_project({"project_path": str(tmp_path / "doomed_novel"), "confirm": "doomed"})
    assert not (tmp_path / "doomed_novel").exists()


def test_relationship_topology_includes_search_and_context_controls():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    javascript = _studio_javascript(assets)
    styles = (assets / "styles.css").read_text(encoding="utf-8")

    assert 'id="relationship-search" type="search"' in html
    assert 'id="relationship-search-status"' in html
    assert "findRelationshipMatches" in javascript
    assert "相邻上下文" in javascript
    assert "search-match" in javascript
    assert ".relationship-node.search-match" in styles


def test_relationship_topology_uses_compact_node_metrics():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    javascript = _studio_javascript(assets)
    styles = (assets / "styles.css").read_text(encoding="utf-8")

    assert "const RELATIONSHIP_NODE_SCALE = 0.76;" in javascript
    assert 'label.setAttribute("y", String(relationshipNodeSize(34)))' in javascript
    assert "const minY = relationshipNodeSize(58);" in javascript
    assert 'relationshipNodeSize(kind === "character" ? 19 : 17)' in javascript
    assert 'createElementNS("http://www.w3.org/2000/svg", "path")' in javascript
    assert "function relationshipEdgePath(" in javascript
    assert "function highlightRelationshipNeighborhood(" in javascript
    assert ".relationship-edge.is-highlighted" in styles
    assert ".relationship-node.label-prominent" in styles
    assert "#relationship-graph { min-height: 430px; height: 430px; }" in styles


def test_outline_tree_ui_supports_direct_text_editing():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    javascript = _studio_javascript(assets)
    styles = (assets / "styles.css").read_text(encoding="utf-8")

    assert 'id="outline-search" type="search"' in html
    assert 'id="outline-expand-all"' in html
    assert 'id="outline-collapse-all"' in html
    assert 'data-outline-status="planned"' in html
    assert 'data-outline-status="drafted"' in html
    assert 'data-outline-pane="tree"' in html
    assert 'data-outline-pane="detail"' in html
    assert "startOutlineInlineRename" in javascript
    assert 'operation: "update_summary"' in javascript
    assert "function renderOutlineTree()" in javascript
    assert "function outlineNodeVisible(node)" in javascript
    assert "function setAllOutlineExpanded(expanded)" in javascript
    assert "function renderOutlineBreadcrumb(node)" in javascript
    assert "function setOutlineMobilePane(pane)" in javascript
    assert "outline-summary-editor" in javascript
    assert ".outline-tree-title-input" in styles
    assert ".outline-summary-editor" in styles
    assert ".outline-summary-editor.markdown-editor-host .vditor-ir .vditor-reset" in styles
    assert "padding: 14px 4px 24px !important" in styles
    assert '.outline-workspace[data-mobile-pane="tree"] .outline-detail' in styles


def test_outline_tree_prioritizes_progressive_disclosure_and_title_width():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    javascript = _studio_javascript(assets)
    styles = (assets / "styles.css").read_text(encoding="utf-8")

    assert '<h1 id="outline-title">大纲</h1>' in html
    assert "outlineExpandedIds: new Set()" in javascript
    assert "initializeOutlineExpansion" in javascript
    assert "revealOutlineNode" in javascript
    assert "state.workspace?.snapshot?.current_chapter" in javascript
    assert 'outlineIcon("icon-chevron-right")' in javascript
    assert "outlineInspectorAutoCollapsed" in javascript
    assert 'toggleInspectorCollapsed(true, { persist: false })' in javascript
    assert "grid-template-columns: minmax(300px, 350px)" in styles
    assert "@media (max-width: 1080px)" in styles
    assert "position: absolute" in styles


def test_studio_uses_local_vditor_for_markdown_editing_surfaces():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    application = (assets / "js" / "application.js").read_text(encoding="utf-8")
    structured_assets = (assets / "js" / "assets.js").read_text(encoding="utf-8")
    editor_adapter = (assets / "js" / "markdown-editor.js").read_text(encoding="utf-8")
    styles = (assets / "styles.css").read_text(encoding="utf-8")

    assert 'href="/vendor/vditor/dist/index.css"' in html
    assert 'src="/vendor/vditor/dist/js/icons/ant.js"' in html
    assert 'src="/vendor/vditor/dist/index.min.js"' in html
    assert '<div id="document-editor" class="document-editor"' in html
    assert '<textarea id="document-editor"' not in html
    assert (assets / "vendor" / "vditor" / "dist" / "index.min.js").is_file()
    assert (assets / "vendor" / "vditor" / "dist" / "js" / "icons" / "ant.js").is_file()
    assert (assets / "vendor" / "vditor" / "dist" / "js" / "lute" / "lute.min.js").is_file()
    assert 'icon: ""' in editor_adapter
    assert 'mode: "ir"' in editor_adapter
    assert 'cdn: VDITOR_CDN' in editor_adapter
    assert 'body > svg[version="1.1"]:not(.icon-sprite)' in styles
    assert "initializePrimaryMarkdownEditor" in application
    assert 'className = "markdown-editor-fallback"' in editor_adapter
    assert 'id="editor-fallback-notice"' in html
    assert 'id="bootstrap-error"' in html
    assert "showBootstrapError" in application
    assert "retryBootstrap" in application
    assert "mountMarkdownEditor(editorHost" in application
    assert 'key === "body_markdown"' in structured_assets
    assert "mountMarkdownEditor(input" in structured_assets
    assert "onInput: markAssetDirty" in structured_assets


def test_agent_chat_ui_supports_sessions_and_collapsible_inspector():
    assets = Path(__file__).parent.parent / "tools" / "studio_assets"
    html = (assets / "index.html").read_text(encoding="utf-8")
    javascript = _studio_javascript(assets)
    styles = (assets / "styles.css").read_text(encoding="utf-8")

    assert 'id="agent-session-new"' in html
    assert 'id="agent-session-delete"' in html
    assert 'id="agent-session-list"' in html
    assert 'id="inspector-collapse"' in html
    assert 'id="inspector-restore"' in html
    assert 'id="agent-activity-template"' in html
    assert 'class="agent-activity-events"' in html
    assert "agentSessionId" in javascript
    assert '"/api/agent/session"' in javascript
    assert '"/api/agent/session/delete"' in javascript
    assert "deleteAgentSession" in javascript
    assert "清空初始会话记录" in javascript
    assert "session_id" in javascript
    assert "startAgentActivity" in javascript
    assert "pollAgentActivity" in javascript
    assert "renderAgentActivityEvents" in javascript
    assert "renderAgentActivityEvent" in javascript
    assert 'appendAgentActivityDetail(content, "查看参数"' in javascript
    assert 'appendAgentActivityDetail(content, "查看结果"' in javascript
    assert "preserveHistory: true" in javascript
    assert "/api/agent/activity" in javascript
    assert "finishAgentActivity" in javascript
    assert 'case "model_retry"' in javascript
    assert "模型输出校验失败，自动修复" in javascript
    assert "耗时较久" in javascript
    assert "可能异常" in javascript
    assert "toggleInspectorCollapsed" in javascript
    assert ".agent-console" in styles
    assert ".agent-session-item" in styles
    assert ".danger-mini-button" in styles
    assert ".agent-activity" in styles
    assert ".agent-activity.long-running" in styles
    assert ".agent-activity.possibly-stuck" in styles
    assert ".agent-activity-event-detail" in styles
    assert ".agent-activity-chevron" in styles
    assert "@keyframes agentPulse" in styles
    assert ".app.inspector-collapsed" in styles


def test_studio_debug_mode_writes_sanitized_backend_log(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path, debug=True)

    app._debug_event(
        "unit_test",
        api_key="secret-value",
        token="token-value",
        message="后台记录" * 200,
        nested={"authorization": "bearer secret"},
    )
    for handler in logging.getLogger("tools.studio").handlers:
        handler.flush()

    log_path = tmp_path / "data" / "novels" / "demo" / "data" / "logs" / "studio-debug.log"
    assert app.debug_log_path == log_path
    text = log_path.read_text(encoding="utf-8")

    assert "studio.project_activated" in text
    assert "studio.unit_test" in text
    assert "secret-value" not in text
    assert "token-value" not in text
    assert "bearer secret" not in text
    assert "<redacted>" in text


def test_studio_chat_markdown_renders_commonmark_without_raw_html():
    rendered = render_chat_markdown(
        "## 计划\n\n- **第一步**\n- `第二步`\n\n<script>alert('xss')</script>\n"
        "\n[危险链接](javascript:alert('xss'))"
    )

    assert "<h2>计划</h2>" in rendered
    assert "<li><strong>第一步</strong></li>" in rendered
    assert "<code>第二步</code>" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert 'href="javascript:' not in rendered


def test_studio_agent_sessions_can_be_created_selected_and_listed(tmp_path: Path):
    from tools.agent.goethe_session_state import GoetheSessionStateStore
    from tools.agent.session_state import SessionStateStore

    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)

    goethe_created = app.create_agent_session({"agent": "goethe"})
    goethe_session_id = goethe_created["active_session_id"]
    assert goethe_session_id.startswith("goethe-")
    assert goethe_created["history"]["session_id"] == goethe_session_id
    assert goethe_created["history"]["path"].startswith("data/workflows/sessions/goethe/")

    goethe_store = GoetheSessionStateStore(
        tmp_path,
        "demo",
        session_id=goethe_session_id,
    )
    goethe_store.append_turn("user", "扩写第一篇的大纲")
    goethe_store.append_turn("assistant", "已经拆成三幕推进。")
    goethe_surface = app.agent_surface("goethe", limit=10, session_id=goethe_session_id)
    assert [message["content"] for message in goethe_surface["history"]["messages"]] == [
        "扩写第一篇的大纲",
        "已经拆成三幕推进。",
    ]
    assert any(
        session["id"] == goethe_session_id
        and session["title"] == "扩写第一篇的大纲"
        and session["messages"] == 2
        for session in goethe_surface["sessions"]
    )

    default_surface = app.agent_surface("goethe", limit=10, session_id="default")
    assert default_surface["history"]["path"] == "data/workflows/goethe_session.jsonl"
    assert default_surface["history"]["messages"] == []

    dante_created = app.create_agent_session({"agent": "dante"})
    dante_session_id = dante_created["active_session_id"]
    assert dante_session_id.startswith("dante-")
    dante_store = SessionStateStore(tmp_path, "demo", session_id=dante_session_id)
    dante_store.append_turn("user", "根据大纲推进第一章")
    dante_surface = app.agent_surface("dante", limit=10, session_id=dante_session_id)
    assert dante_surface["history"]["messages"][0]["content"] == "根据大纲推进第一章"
    assert dante_surface["history"]["path"].startswith("data/workflows/sessions/dante/")

    deleted = app.delete_agent_session({"agent": "goethe", "session_id": goethe_session_id})
    assert deleted["deleted"] is True
    assert deleted["deleted_session_id"] == goethe_session_id
    assert deleted["active_session_id"] == "default"
    assert not goethe_store.path.exists()
    assert not goethe_store.transcript_path.exists()
    assert not any(session["id"] == goethe_session_id for session in deleted["sessions"])


@pytest.mark.parametrize("agent_name", ["goethe", "dante"])
def test_studio_default_agent_session_can_be_cleared(
    tmp_path: Path,
    agent_name: str,
):
    from tools.agent.goethe_session_state import GoetheSessionStateStore
    from tools.agent.session_state import SessionStateStore

    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)
    store = (
        GoetheSessionStateStore(tmp_path, "demo")
        if agent_name == "goethe"
        else SessionStateStore(tmp_path, "demo")
    )
    state = store.load_or_create()
    state.conversation_summary = "不应在清空后继续进入上下文。"
    state.working_memory = {"old_context": "应被清除"}
    store.save(state)
    store.append_turn("user", "这是一条旧问题")
    store.append_turn("assistant", "这是一条旧回答")

    cleared = app.delete_agent_session(
        {"agent": agent_name, "session_id": "default"}
    )

    assert cleared["cleared"] is True
    assert cleared["deleted"] is False
    assert cleared["deleted_session_id"] == "default"
    assert cleared["active_session_id"] == "default"
    assert cleared["history"]["messages"] == []
    assert cleared["sessions"][0]["id"] == "default"
    assert cleared["sessions"][0]["exists"] is False
    assert not store.path.exists()
    assert not store.transcript_path.exists()


def _read_json(url: str) -> dict:
    with build_opener(ProxyHandler({})).open(url) as response:
        return json.loads(response.read())


def test_studio_workspace_exposes_novel_only_documents(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")
    _save_chapter(tmp_path, "demo", "ch_001", "第一章 雨夜", "门外有人。")

    payload = StudioApplication(tmp_path).workspace()

    assert payload["snapshot"]["title"] == "雾城来信"
    assert payload["documents"]["outline"][0]["path"] == "src/outline.md"
    assert payload["documents"]["chapters"][0]["path"].endswith("ch_001.md")
    assert set(payload["documents"]) == {
        "outline",
        "core",
        "characters",
        "settings",
        "chapters",
    }


def test_studio_bootstraps_first_project_without_cli(tmp_path: Path):
    app = StudioApplication(tmp_path)

    before = app.workspace()
    assert before["initialized"] is False
    assert before["snapshot"]["title"] == "新小说"

    after = app.initialize_project({"novel_id": "mist_city", "title": "雾城来信"})

    assert after["initialized"] is True
    assert after["snapshot"]["novel_id"] == "mist_city"
    assert after["snapshot"]["title"] == "雾城来信"
    assert (tmp_path / "novel_config.yaml").exists()
    assert (tmp_path / ".openwrite" / "project.yaml").exists()


def test_studio_uses_a_title_based_default_directory_from_framework_root(
    tmp_path: Path,
):
    framework = tmp_path / "framework"
    (framework / "tools").mkdir(parents=True)
    (framework / "tools" / "studio.py").write_text("", encoding="utf-8")
    (framework / "pyproject.toml").write_text('[project]\nname = "openwrite"\n', encoding="utf-8")
    app = StudioApplication(framework)
    result = app.initialize_project({"novel_id": "mist_city", "title": "雾城来信"})

    target = tmp_path / "OpenWriteNovels" / "雾城来信"
    assert result["project"]["root"] == str(target.resolve())
    assert (target / "novel_config.yaml").is_file()


def test_studio_opens_external_project_and_lists_recent_projects(tmp_path: Path):
    launcher = tmp_path / "framework"
    launcher.mkdir()
    project = tmp_path / "private_novel"
    project.mkdir()
    init_project(project, "demo", "私密作品")
    registry = ProjectRegistry(tmp_path / "recent.yaml", allow_ephemeral=True)
    app = StudioApplication(launcher, project_registry=registry)

    workspace = app.open_project({"project_path": str(project)})

    assert workspace["initialized"] is True
    assert workspace["snapshot"]["title"] == "私密作品"
    assert workspace["project"]["root"] == str(project.resolve())
    assert workspace["project"]["recent"][0]["path"] == str(project.resolve())


def test_studio_never_treats_framework_root_as_a_novel_project(tmp_path: Path):
    framework = tmp_path / "framework"
    (framework / "tools").mkdir(parents=True)
    (framework / "tools" / "studio.py").write_text("", encoding="utf-8")
    (framework / "pyproject.toml").write_text(
        '[project]\nname = "openwrite"\n', encoding="utf-8"
    )
    init_project(framework, "stale_demo", "旧测试小说")

    workspace = StudioApplication(framework).workspace()

    assert workspace["initialized"] is False
    assert workspace["project"]["framework_root"] is True


def test_studio_searches_project_assets(tmp_path: Path):
    init_project(tmp_path, "demo")
    path = tmp_path / "data" / "novels" / "demo" / "src" / "story" / "background.md"
    path.write_text("# 故事背景\n\n钟楼每天少走十三秒。\n", encoding="utf-8")
    app = StudioApplication(tmp_path)

    result = app.search_project("十三秒", "story")

    assert result["results"][0]["path"] == "src/story/background.md"


def test_studio_context_preview_exposes_traceable_manifest(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)

    preview = app.context_preview("ch_001")

    assert preview["manifest"]["strategy"] == "hierarchical-provenance-v1"
    assert preview["manifest"]["revision"]
    refreshed = app.context_preview(
        "ch_001",
        preview["manifest"]["packet_revision"],
        "older-source-revision",
    )
    assert refreshed["manifest"]["previous_freshness"] == {
        "status": "stale",
        "reason": "source_revision_changed",
        "previous_revision": preview["manifest"]["packet_revision"],
        "current_revision": refreshed["manifest"]["packet_revision"],
        "previous_source_revision": "older-source-revision",
        "current_source_revision": refreshed["manifest"]["source_revision"],
    }


def test_protected_context_budget_error_keeps_actionable_details():
    source = NovelServiceError(
        "受保护上下文超过预算",
        code="PROTECTED_CONTEXT_OVER_BUDGET",
        details={"budget_tokens": 1000, "required_tokens": 1400},
    )

    translated = StudioApplication._translate_service_error(source)

    assert translated.status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert translated.code == "PROTECTED_CONTEXT_OVER_BUDGET"
    assert translated.details == {"budget_tokens": 1000, "required_tokens": 1400}


def test_studio_outline_structure_and_smart_chapter_creation(tmp_path: Path, monkeypatch):
    init_project(tmp_path, "demo")
    novel = tmp_path / "data" / "novels" / "demo"
    (novel / "src" / "outline.md").write_text(
        """# 第一卷
## 第一幕
### 第一节
#### 第一章：开门
发现门外的脚印。
#### 第二章：追踪
沿脚印进入雨巷。
""",
        encoding="utf-8",
    )
    manuscript = novel / "data" / "manuscript" / "arc_001"
    manuscript.mkdir(parents=True, exist_ok=True)
    (manuscript / "ch_001.md").write_text("已有正文", encoding="utf-8")
    acceptance = ManuscriptAcceptanceService(tmp_path, "demo")
    baseline = acceptance.establish_baseline(confirm=True)
    acceptance.resume(
        baseline["operation_id"],
        analyzer=lambda *args: {
            "chapter_summary": "已有正文",
            "observations": "",
            "legacy_updates": {},
            "state_delta": {},
        },
    )
    monkeypatch.setenv("LLM_API_KEY", "configured-for-test")
    calls = []

    def fake_writer(root: Path, args: dict) -> dict:
        calls.append(args)
        return {"ok": True, "chapter_id": args["chapter_id"], "word_count": 1200}

    app = StudioApplication(tmp_path, writer_executor=fake_writer)
    outline = app.outline_structure()

    assert outline["counts"]["chapter"] == 2
    assert outline["recommendation"]["chapter_id"] == "ch_002"
    result = app.write_next_chapter(
        {
            "chapter_id": "ch_002",
            "outline_revision": outline["revision"],
            "guidance": outline["recommendation"]["guidance"],
            "target_words": 3200,
        }
    )
    assert result["result"]["chapter_id"] == "ch_002"
    assert calls[0]["chapter_id"] == "ch_002"

    with pytest.raises(StudioError) as drafted:
        app.write_next_chapter({"chapter_id": "ch_001", "target_words": 3000})
    assert drafted.value.status == HTTPStatus.CONFLICT

    (novel / "src" / "outline.md").write_text("# 已变更", encoding="utf-8")
    with pytest.raises(StudioError) as stale:
        app.write_next_chapter(
            {
                "chapter_id": "ch_002",
                "outline_revision": outline["revision"],
                "target_words": 3000,
            }
        )
    assert stale.value.status == HTTPStatus.CONFLICT


def test_studio_persists_unified_writing_targets_and_applies_them_to_outline(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    novel = tmp_path / "data" / "novels" / "demo"
    (novel / "src" / "outline.md").write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n#### 第一章：开门\n脚印。\n",
        encoding="utf-8",
    )
    app = StudioApplication(tmp_path)

    workspace = app.update_writing_targets(
        {
            "book_words": 240000,
            "chapter_words": 3600,
            "outline_volume_words": 900,
            "outline_act_words": 600,
            "outline_section_words": 360,
            "outline_chapter_words": 220,
        }
    )

    assert workspace["project"]["writing_targets"]["chapter_words"] == 3600
    assert workspace["snapshot"]["target_units"] == 240000
    stored = yaml.safe_load((tmp_path / "novel_config.yaml").read_text(encoding="utf-8"))
    assert stored["writing_targets"]["outline_section_words"] == 360

    outline = app.outline_structure()
    chapter = outline["roots"][0]["children"][0]["children"][0]["children"][0]
    assert outline["recommendation"]["target_words"] == 3600
    assert chapter["chapter_target_words"] == 3600
    assert chapter["detail_target_words"] == 220

    with pytest.raises(StudioError, match="每章正文默认必须在"):
        app.update_writing_targets({"chapter_words": 100})


def test_studio_incrementally_edits_outline_tree_with_revision_guard(tmp_path: Path):
    init_project(tmp_path, "demo")
    novel = tmp_path / "data" / "novels" / "demo"
    outline_path = novel / "src" / "outline.md"
    outline_path.write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n#### 第一章：开门\n脚印。\n",
        encoding="utf-8",
    )
    app = StudioApplication(tmp_path)
    before = app.outline_structure()

    result = app.edit_outline_structure(
        {
            "operation": "add_child",
            "node_id": "section_001",
            "kind": "chapter",
            "title": "第二章：追踪",
            "revision": before["revision"],
        }
    )

    assert result["selected_node_id"] == "ch_002"
    assert result["outline"]["counts"]["chapter"] == 2
    assert "#### 第二章：追踪" in outline_path.read_text(encoding="utf-8")
    assert "checkpoint" in result

    refreshed = result["outline"]
    summary = app.edit_outline_structure(
        {
            "operation": "update_summary",
            "node_id": "section_001",
            "summary": "树上直接修改这一节内容。\n继续保留子章。",
            "revision": refreshed["revision"],
        }
    )
    source = outline_path.read_text(encoding="utf-8")
    assert "树上直接修改这一节内容。" in source
    assert "#### 第一章：开门" in source
    assert "#### 第二章：追踪" in source
    assert summary["selected_node_id"] == "section_001"

    with pytest.raises(StudioError) as stale:
        app.edit_outline_structure(
            {
                "operation": "rename",
                "node_id": "section_001",
                "title": "第一节：旧页面覆盖",
                "revision": before["revision"],
            }
        )
    assert stale.value.status == HTTPStatus.CONFLICT


def test_studio_delete_returns_renumbering_impact(tmp_path: Path):
    init_project(tmp_path, "demo")
    novel = tmp_path / "data" / "novels" / "demo"
    outline_path = novel / "src" / "outline.md"
    outline_path.write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n"
        "#### 第14章：删除\n#### 第15章：补位\n#### 第16章：继续\n",
        encoding="utf-8",
    )
    app = StudioApplication(tmp_path)
    before = app.outline_structure()

    result = app.edit_outline_structure(
        {
            "operation": "delete",
            "node_id": "ch_014",
            "revision": before["revision"],
        }
    )

    assert result["outline"]["counts"]["chapter"] == 2
    assert [(item["old_id"], item["new_id"]) for item in result["renumbered"]] == [
        ("ch_015", "ch_014"),
        ("ch_016", "ch_015"),
    ]
    assert result["skipped_renumbering"] == []
    assert "第14章：补位" in outline_path.read_text(encoding="utf-8")
    assert "连续重编号 2 个" in result["message"]


def test_studio_model_configuration_persists_local_settings_and_never_echoes_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings_store = StudioModelSettingsStore(tmp_path / "studio-settings")
    app = StudioApplication(tmp_path, model_settings_store=settings_store)

    payload = app.configure_model(
        {
            "provider": "openai",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-pro",
            "api_key": "session-test-secret",
            "api_format": "chat",
            "context_tokens": 160000,
            "max_tokens": 24000,
        }
    )

    assert payload["model"] == {
        "configured": True,
        "provider": "openai",
        "base_url": "https://api.deepseek.com",
        "name": "deepseek-v4-pro",
        "api_format": "chat",
        "context_tokens": 160000,
        "max_tokens": 24000,
        "persistence": {
            "settings_saved": True,
            "credential_saved": True,
            "remember_api_key": True,
        },
    }
    payload_json = json.dumps(payload)
    assert "session-test-secret" not in payload_json
    assert str(settings_store.directory) not in payload_json
    assert "session-test-secret" not in (tmp_path / "novel_config.yaml").read_text(encoding="utf-8")
    assert settings_store.load_credential() == "session-test-secret"
    builder = ContextBuilder(tmp_path, "demo")
    assert builder.CONTEXT_WINDOW_TOKENS == 160000
    assert builder.MAX_TOKENS == 131200


def test_workspace_model_status_uses_configured_named_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    preferences = StudioModelSettingsStore(tmp_path / "studio-settings")
    app = StudioApplication(
        tmp_path,
        model_settings_store=preferences,
        model_profile_store=ModelProfileStore(preferences.directory),
    )

    result = app.save_model_profile(
        {
            "id": "prose",
            "label": "正文模型",
            "provider": "custom",
            "base_url": "https://models.example/v1",
            "model": "novel-model",
            "api_format": "chat",
            "context_tokens": 128000,
            "max_output_tokens": 16000,
            "temperature": 0.7,
            "timeout_seconds": 120,
        }
        | {"api_key": "named-profile-secret", "remember_api_key": True}
    )

    workspace = result["workspace"]
    assert workspace["model"] == {
        "configured": True,
        "provider": "custom",
        "base_url": "https://models.example/v1",
        "name": "novel-model",
        "api_format": "chat",
        "context_tokens": 128000,
        "max_tokens": 16000,
        "persistence": {
            "settings_saved": False,
            "credential_saved": False,
            "remember_api_key": False,
        },
    }
    assert "named-profile-secret" not in json.dumps(result, ensure_ascii=False)


def test_studio_model_configuration_does_not_persist_inherited_process_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    monkeypatch.setenv("LLM_API_KEY", "process-only-secret")
    settings_store = StudioModelSettingsStore(tmp_path / "studio-settings")
    app = StudioApplication(tmp_path, model_settings_store=settings_store)

    payload = app.configure_model(
        {
            "provider": "openai",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": "",
            "api_format": "chat",
            "context_tokens": 160000,
            "max_tokens": 6000,
            "remember_api_key": True,
        }
    )

    assert payload["model"]["configured"] is True
    assert payload["model"]["persistence"] == {
        "settings_saved": True,
        "credential_saved": False,
        "remember_api_key": True,
    }
    assert os.environ["LLM_API_KEY"] == "process-only-secret"
    assert settings_store.load_credential() == ""


def test_studio_model_connection_test_does_not_replace_active_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    monkeypatch.setenv("LLM_API_KEY", "active-secret")
    monkeypatch.setenv("LLM_MODEL", "active-model")
    captured = {}

    def fake_test(settings):
        captured.update(settings)
        return {"reply": "OK"}

    app = StudioApplication(tmp_path, model_test_executor=fake_test)
    result = app.test_model_connection(
        {
            "provider": "openai",
            "base_url": "https://api.deepseek.com",
            "model": "candidate-model",
            "api_key": "candidate-secret",
            "api_format": "chat",
            "context_tokens": 160000,
            "max_tokens": 24000,
        }
    )

    assert result["ok"] is True
    assert result["model"] == "candidate-model"
    assert result["reply"] == "OK"
    assert captured["api_key"] == "candidate-secret"
    assert os.environ["LLM_MODEL"] == "active-model"
    assert os.environ["LLM_API_KEY"] == "active-secret"
    assert "candidate-secret" not in json.dumps(result)


def test_studio_rejects_invalid_live_model_budgets(tmp_path: Path, monkeypatch):
    init_project(tmp_path, "demo")
    monkeypatch.setenv("LLM_API_KEY", "active-secret")
    app = StudioApplication(tmp_path)

    with pytest.raises(StudioError, match="上下文预算"):
        app.configure_model(
            {
                "model": "deepseek-v4-pro",
                "base_url": "https://api.deepseek.com",
                "context_tokens": 1000,
            }
        )


def test_studio_accepts_output_above_the_legacy_cap(tmp_path: Path, monkeypatch):
    init_project(tmp_path, "demo")
    monkeypatch.setenv("LLM_API_KEY", "active-secret")
    app = StudioApplication(
        tmp_path,
        project_registry=ProjectRegistry(
            tmp_path / "registry" / "recent.yaml", allow_ephemeral=True
        ),
        model_settings_store=StudioModelSettingsStore(tmp_path / "studio-settings"),
    )

    settings = app._validated_model_settings(
        {
            "model": "future-long-output-model",
            "base_url": "https://example.com/v1",
            "context_tokens": 2_000_000,
            "max_tokens": 750_000,
        }
    )

    assert settings["context_tokens"] == 2_000_000
    assert settings["max_tokens"] == 750_000


def test_studio_model_connection_errors_never_echo_provider_key_fragments(tmp_path: Path):
    init_project(tmp_path, "demo")

    def fail_with_provider_body(settings):
        raise RuntimeError("401 authentication failed; Your api key: ****-7f70 is invalid")

    app = StudioApplication(tmp_path, model_test_executor=fail_with_provider_body)
    with pytest.raises(StudioError) as captured:
        app.test_model_connection(
            {
                "provider": "openai",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-pro",
                "api_key": "secret-ending-7f70",
            }
        )

    message = str(captured.value)
    assert message == "连接测试失败：认证失败，请检查 API Key。"
    assert "7f70" not in message


def test_studio_default_model_connection_test_allows_reasoning_budget(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, int] = {}

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def chat(self, messages, temperature, max_tokens, stream):
            captured["max_tokens"] = max_tokens
            return SimpleNamespace(content="OK")

    monkeypatch.setattr("tools.llm.LLMClient", FakeClient)

    result = StudioApplication._default_model_connection_test(
        {
            "provider": "openai",
            "api_key": "secret",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "max_tokens": 24000,
            "api_format": "chat",
        }
    )

    assert result == {"reply": "OK"}
    assert captured["max_tokens"] == 32


def test_studio_empty_model_connection_reply_gets_actionable_error():
    message = StudioApplication._safe_model_connection_error(RuntimeError("empty model reply"))

    assert message == "连接测试失败：模型返回空内容，请调大最大输出后重试。"


def test_studio_document_write_is_atomic_and_version_checked(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)
    document = app.read_document("src/story/background.md")

    saved = app.write_document(
        document["path"],
        "# 故事背景\n\n一座只在雨夜出现的城。\n",
        document["version"],
    )

    assert "雨夜" in saved["content"]
    with pytest.raises(StudioError) as conflict:
        app.write_document(document["path"], "旧内容", document["version"])
    assert conflict.value.status == HTTPStatus.CONFLICT


def test_studio_document_write_respects_the_cross_process_project_lock(tmp_path: Path):
    from tools.project_lock import ProjectWriteLock

    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)
    document = app.read_document("src/story/background.md")

    with ProjectWriteLock(tmp_path, "demo", operation="concurrent-write"):
        with pytest.raises(StudioError) as busy:
            app.write_document(document["path"], "不能越过项目锁", document["version"])

    assert busy.value.status == HTTPStatus.CONFLICT
    assert busy.value.code == "PROJECT_BUSY"
    assert busy.value.recoverable is True
    assert app.read_document(document["path"])["content"] == document["content"]


def test_studio_chapter_saves_create_coalesced_author_history(tmp_path: Path):
    init_project(tmp_path, "demo")
    chapter = _save_chapter(tmp_path, "demo", "ch_001", "第一章", "初稿")
    app = StudioApplication(tmp_path)
    document = app.read_document(app._relative(chapter))
    ReviewStore(tmp_path, "demo").save(
        "ch_001",
        {
            "score": 90,
            "passed": True,
            "issues": 0,
            "issue_details": [],
            "review_v2": {
                "schema_version": "openwrite.review.v2",
                "execution_status": "completed",
                "quality_score": 90,
                "coverage": 1.0,
                "gate_status": "pass",
                "delivery_status": "pass",
                "production_gate_status": "disabled_uncalibrated",
            },
        },
    )

    first = app.write_document(
        document["path"], "自动稿一", document["version"], save_origin="autosave"
    )
    second = app.write_document(
        document["path"], "自动稿二", first["version"], save_origin="autosave"
    )
    manual = app.write_document(
        document["path"], "手动稿", second["version"], save_origin="manual"
    )

    versions = ManuscriptVersionStore(tmp_path, "demo").list("ch_001")
    assert [item.reason for item in versions] == ["manual", "autosave"]
    assert first["author_version"]["created"] is True
    assert second["author_version"]["created"] is False
    assert manual["author_version"]["created"] is True
    assert first["acceptance"]["status"] == "pending"
    assert second["acceptance"]["status"] == "pending"
    assert manual["acceptance"]["status"] == "pending"
    assert manual["acceptance"]["current_revision"] == manual["revision"]
    assert ManuscriptVersionStore(tmp_path, "demo").load(
        "ch_001", versions[1].version_id
    )[1] == document["content"]
    assert ManuscriptVersionStore(tmp_path, "demo").load(
        "ch_001", versions[0].version_id
    )[1] == "自动稿二"
    review = ReviewStore(tmp_path, "demo").load("ch_001")
    assert review is not None
    assert review["stale"] is True
    assert review["review_v2"]["freshness_status"] == "stale"
    chapter_review = app.workspace()["documents"]["chapters"][0]["review"]
    assert chapter_review["stale"] is True
    workspace = app.workspace()
    assert workspace["manuscript_acceptance"]["status"] == "pending"
    assert workspace["documents"]["chapters"][0]["acceptance"]["operation_id"] == manual[
        "acceptance"
    ]["operation_id"]
    assert chapter_review["review_v2"]["delivery_status"] == "stale"


def test_studio_document_write_response_stays_bound_to_its_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """A later writer must not change the content/version acknowledged to the first."""
    init_project(tmp_path, "demo")
    first_app = StudioApplication(tmp_path)
    second_app = StudioApplication(tmp_path)
    initial = first_app.read_document("src/story/background.md")
    first_replaced = Event()
    release_first = Event()

    def staged_refresh(_index):
        if not first_replaced.is_set():
            first_replaced.set()
            assert release_first.wait(timeout=5)
        return {}

    monkeypatch.setattr(
        "tools.studio_application.CharacterStateIndex.refresh",
        staged_refresh,
    )
    outcome: dict[str, object] = {}

    def write_first() -> None:
        try:
            outcome["first"] = first_app.write_document(
                initial["path"],
                "请求 A",
                initial["version"],
            )
        except Exception as exc:  # pragma: no cover - asserted below
            outcome["error"] = exc

    thread = Thread(target=write_first)
    thread.start()
    assert first_replaced.wait(timeout=5)
    after_first_replace = second_app.read_document(initial["path"])
    assert after_first_replace["content"] == "请求 A"
    try:
        second = second_app.write_document(
            initial["path"],
            "请求 B",
            after_first_replace["version"],
        )
    finally:
        release_first.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert "error" not in outcome
    first = outcome["first"]
    assert isinstance(first, dict)
    assert first["content"] == "请求 A"
    assert first["revision"] == RevisionService.fingerprint("请求 A")
    assert first["version"] == after_first_replace["version"]
    assert second["content"] == "请求 B"


def test_studio_manual_chapter_delete_is_latest_only_and_cleans_derived_data(
    tmp_path: Path,
):
    from tools.chapter_memory import ChapterMemoryStore
    from tools.review_store import ReviewStore

    init_project(tmp_path, "demo")
    registry = ProjectRegistry(tmp_path / "registry" / "recent.yaml", allow_ephemeral=True)
    app = StudioApplication(
        tmp_path,
        project_registry=registry,
        model_settings_store=StudioModelSettingsStore(tmp_path / "prefs"),
    )
    first_path = _save_chapter(tmp_path, "demo", "ch_001", "第一章", "旧雨落城。")
    latest_path = _save_chapter(tmp_path, "demo", "ch_002", "第二章", "钟声停了。")
    memory = ChapterMemoryStore(tmp_path, "demo")
    memory.save(
        chapter_id="ch_002",
        title="第二章",
        summary="钟声停了。",
        word_count=5,
    )
    reviews = ReviewStore(tmp_path, "demo")
    reviews.save("ch_002", {"score": 90, "passed": True, "issues": 0})
    novel_root = tmp_path / "data" / "novels" / "demo"
    revision_root = novel_root / "data" / "revisions" / "ch_002"
    annotation_root = novel_root / "data" / "annotations" / "ch_002"
    revision_root.mkdir(parents=True)
    annotation_root.mkdir(parents=True)
    (revision_root / "derived.json").write_text("{}", encoding="utf-8")
    (annotation_root / "derived.json").write_text("{}", encoding="utf-8")

    first = app.read_document(first_path.relative_to(novel_root).as_posix())
    with pytest.raises(StudioError, match="最新章节") as not_latest:
        app.delete_chapter(
            {"path": first["path"], "version": first["version"], "confirm": "ch_001"}
        )
    assert not_latest.value.status == HTTPStatus.CONFLICT

    latest = app.read_document(latest_path.relative_to(novel_root).as_posix())
    with pytest.raises(StudioError, match="请输入 ch_002") as unconfirmed:
        app.delete_chapter(
            {"path": latest["path"], "version": latest["version"], "confirm": "wrong"}
        )
    assert unconfirmed.value.status == HTTPStatus.PRECONDITION_REQUIRED

    result = app.delete_chapter(
        {"path": latest["path"], "version": latest["version"], "confirm": "ch_002"}
    )

    assert result["chapter_id"] == "ch_002"
    assert result["previous_chapter"] == "ch_001"
    assert result["backup"]["label"] == "Studio 删除前自动备份"
    backup = novel_root / result["backup"]["content_file"]
    assert "钟声停了" in backup.read_text(encoding="utf-8")
    assert latest_path.exists() is False
    assert memory.path_for("ch_002").exists() is False
    assert reviews.path_for("ch_002").exists() is False
    assert revision_root.exists() is False
    assert annotation_root.exists() is False
    assert app.workspace()["snapshot"]["current_chapter"] == "ch_001"

    remaining = app.read_document(first_path.relative_to(novel_root).as_posix())
    cleared = app.delete_chapter(
        {"path": remaining["path"], "version": remaining["version"], "confirm": "ch_001"}
    )
    cleared_workspace = cleared["workspace"]
    cleared_state = BookStateStore(tmp_path, "demo").load_or_create()
    assert cleared["previous_chapter"] == ""
    assert cleared["runtime_restored"] is True
    assert cleared_workspace["documents"]["chapters"] == []
    assert cleared_workspace["snapshot"]["current_chapter"] == ""
    assert cleared_state.stage == BookStage.ROLLING_OUTLINE


def test_studio_batch_delete_removes_only_latest_tail(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)
    for number in range(1, 5):
        _save_chapter(tmp_path, "demo", f"ch_{number:03d}", f"第{number}章", f"正文 {number}")

    latest = app.read_document("data/manuscript/arc_001/ch_004.md")
    with pytest.raises(StudioError) as stale:
        app.delete_chapters_batch({
            "keep_through": "ch_002",
            "confirm": "DELETE_AFTER:ch_002",
            "version": "stale",
        })
    assert stale.value.status == HTTPStatus.CONFLICT

    result = app.delete_chapters_batch({
        "keep_through": "ch_002",
        "confirm": "DELETE_AFTER:ch_002",
        "version": latest["version"],
    })
    assert result["deleted_count"] == 2
    assert [item["chapter_id"] for item in result["deleted_chapters"]] == ["ch_004", "ch_003"]
    assert (tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_001.md").exists()
    assert (tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_002.md").exists()
    assert not (tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_003.md").exists()
    assert not (tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_004.md").exists()


def test_studio_rejects_paths_outside_novel_documents(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)

    with pytest.raises(StudioError) as traversal:
        app.read_document("../../README.md")
    assert traversal.value.status == HTTPStatus.FORBIDDEN

    with pytest.raises(StudioError):
        app.write_document("data/workflows/book_state.yaml", "x", None)


def test_studio_focus_and_writer_reuse_openwrite_pipeline(tmp_path: Path, monkeypatch):
    init_project(tmp_path, "demo")
    monkeypatch.setenv("LLM_API_KEY", "configured-for-test")
    calls: list[dict] = []

    def fake_writer(root: Path, args: dict) -> dict:
        calls.append(args)
        path = _save_chapter(root, "demo", args["chapter_id"], "第一章", "测试正文")
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": "第一章",
            "word_count": 4,
            "draft_path": str(path),
            "truth_updates": {},
        }

    def fake_reviewer(root: Path, args: dict) -> dict:
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": False,
            "score": 90,
            "issues": 1,
            "summary": "警告 1 项",
            "issue_details": [
                {
                    "severity": "warning",
                    "category": "节奏检查",
                    "description": "开场略慢",
                    "suggestion": "提前冲突",
                    "dimension": 7,
                }
            ],
        }

    app = StudioApplication(
        tmp_path,
        writer_executor=fake_writer,
        review_executor=fake_reviewer,
    )
    updated = app.update_focus(
        {
            "goal": "完成开篇承诺",
            "must_keep": ["雨夜意象"],
            "must_avoid": ["解释真相"],
        }
    )
    assert updated["snapshot"]["creative_focus"]["goal"] == "完成开篇承诺"

    result = app.write_next_chapter({"target_words": 800, "guidance": "从敲门声开始"})
    assert calls[0]["target_words"] == 800
    assert result["result"]["chapter_id"] == "ch_001"
    chapter_change = result["mutation_summary"]
    assert chapter_change["items"][0]["entity_kind"] == "manuscript"
    assert chapter_change["items"][0]["before"]["kind"] == "missing"
    assert chapter_change["items"][0]["after"]["value"] == "# 第一章\n\n测试正文"
    assert len(result["workspace"]["documents"]["chapters"]) == 1
    written_state = BookStateStore(tmp_path, "demo").load_or_create()
    assert written_state.stage == BookStage.REVIEW_AND_REVISE
    workflow = WorkflowScheduler(tmp_path, "demo").load_workflow("ch_001")
    assert workflow is not None
    assert next(stage for stage in workflow.stages if stage.name == "writing").status == "completed"

    chapter_path = result["workspace"]["documents"]["chapters"][0]["path"]
    review = app.review_chapter({"path": chapter_path})
    assert review["result"]["score"] == 90
    assert review["review_framework"]["id"] == "openwrite.standard-chapter-review"
    assert review["review_framework"]["invariants"]["node_count"] == 47
    review_path = tmp_path / "data" / "novels" / "demo" / "data" / "reviews" / "ch_001.json"
    assert review_path.exists()
    refreshed = app.workspace()
    assert refreshed["documents"]["chapters"][0]["review"]["score"] == 90
    assert "90 分" in refreshed["documents"]["chapters"][0]["subtitle"]
    reviewed_state = BookStateStore(tmp_path, "demo").load_or_create()
    assert reviewed_state.stage == BookStage.REVIEW_AND_REVISE
    assert reviewed_state.blocking_reason == "review_revision_requested"


@pytest.mark.parametrize("bad_v2", [None, [], "invalid", 42, True, {}])
def test_review_v2_boundary_rejects_malformed_before_persistence(
    tmp_path: Path, bad_v2: object
):
    init_project(tmp_path, "demo")
    chapter = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "manuscript"
        / "arc_001"
        / "ch_001.md"
    )
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("# Chapter\n\n正文\n", encoding="utf-8")

    def reviewer(root: Path, args: dict) -> dict:
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "score": 95,
            "passed": True,
            "issue_details": [],
            "review_v2": bad_v2,
        }

    app = StudioApplication(tmp_path, review_executor=reviewer)
    with pytest.raises(StudioError) as error:
        app.review_chapter({"path": "data/manuscript/arc_001/ch_001.md"})
    assert error.value.code == "CONTRACT_INVALID"
    review_path = tmp_path / "data" / "novels" / "demo" / "data" / "reviews" / "ch_001.json"
    assert not review_path.exists()


def test_studio_http_serves_ui_api_and_blocks_unsigned_writes(tmp_path: Path):
    init_project(tmp_path, "demo")
    chapter = _save_chapter(tmp_path, "demo", "ch_001", "第一章", "旧正文")
    history = ManuscriptVersionStore(tmp_path, "demo")
    historical = history.checkpoint("ch_001", label="HTTP 历史")
    chapter.write_text("# 第一章\n\n当前正文", encoding="utf-8")
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(ProxyHandler({}))
    try:
        health = _read_json(f"{base}/api/health")
        assert health == {"ok": True}

        versions = _read_json(f"{base}/api/manuscript/versions?chapter=ch_001")
        assert versions["data"]["versions"][0]["label"] == "HTTP 历史"
        preview = _read_json(
            f"{base}/api/manuscript/versions/{historical.version_id}/compare"
            "?chapter=ch_001"
        )
        assert preview["data"]["current"]["revision"] == history.fingerprint(
            chapter.read_text(encoding="utf-8")
        )
        assert preview["data"]["diff"]["hunks"]

        with opener.open(f"{base}/") as response:
            html = response.read().decode("utf-8")
            assert "OpenWrite Studio" in html
            assert 'id="outline-add-volume"' in html
            assert 'id="outline-node-add-child"' in html
            assert 'id="outline-edit-dialog"' in html
            assert 'id="outline-edit-impact"' in html
            assert 'id="agent-session-new"' in html
            assert 'id="agent-session-delete"' in html
            assert 'id="inspector-collapse"' in html
            assert "default-src 'self'" in response.headers["Content-Security-Policy"]

        with opener.open(f"{base}/js/core.js") as response:
            core_module = response.read().decode("utf-8")
            assert "javascript" in response.headers["Content-Type"]
            assert "export async function api" in core_module

        with pytest.raises(HTTPError) as missing_asset:
            opener.open(f"{base}/js/missing-startup-module.js")
        assert missing_asset.value.code == HTTPStatus.NOT_FOUND
        missing_payload = json.loads(missing_asset.value.read())
        assert missing_payload["code"] == "STATIC_ASSET_NOT_FOUND"
        assert missing_payload["details"]["path"] == "js/missing-startup-module.js"

        agent_surface = _read_json(f"{base}/api/agents?agent=goethe&session_id=default&limit=5")
        assert agent_surface["active_session_id"] == "default"
        assert agent_surface["sessions"][0]["id"] == "default"

        new_session_request = Request(
            f"{base}/api/agent/session",
            method="POST",
            data=json.dumps({"agent": "goethe"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(new_session_request) as response:
            new_session = json.loads(response.read())
        assert new_session["created"] is True
        assert new_session["active_session_id"].startswith("goethe-")
        assert any(
            session["id"] == new_session["active_session_id"] for session in new_session["sessions"]
        )
        delete_session_request = Request(
            f"{base}/api/agent/session/delete",
            method="POST",
            data=json.dumps(
                {
                    "agent": "goethe",
                    "session_id": new_session["active_session_id"],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(delete_session_request) as response:
            deleted_session = json.loads(response.read())
        assert deleted_session["deleted"] is True
        assert deleted_session["active_session_id"] == "default"
        assert not any(
            session["id"] == new_session["active_session_id"]
            for session in deleted_session["sessions"]
        )

        request = Request(
            f"{base}/api/focus",
            method="POST",
            data=json.dumps({"goal": "测试"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as denied:
            opener.open(request)
        assert denied.value.code == HTTPStatus.FORBIDDEN
        denied_payload = json.loads(denied.value.read())
        assert denied_payload["error"] == "缺少 Studio 写入凭证"
        assert denied_payload["code"] == "WRITE_CREDENTIAL_REQUIRED"
        assert denied_payload["request_id"].startswith("req_")
        assert denied.value.headers["X-Request-ID"] == denied_payload["request_id"]

        outline = _read_json(f"{base}/api/outline")
        outline_edit = Request(
            f"{base}/api/outline/edit",
            method="POST",
            data=json.dumps(
                {
                    "operation": "rename",
                    "node_id": "volume_001",
                    "title": "第一卷：网页增量编辑",
                    "revision": outline["revision"],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(outline_edit) as response:
            edited_outline = json.loads(response.read())
        assert edited_outline["outline"]["roots"][0]["title"] == "第一卷：网页增量编辑"

        document = _read_json(f"{base}/api/document?path=src%2Fstory%2Fbackground.md")
        assert isinstance(document["version"], str)
        save_request = Request(
            f"{base}/api/document",
            method="PUT",
            data=json.dumps(
                {
                    "path": document["path"],
                    "content": "# 故事背景\n\nHTTP 保存测试。\n",
                    "version": document["version"],
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-OpenWrite-Studio": "1",
            },
        )
        with opener.open(save_request) as response:
            saved = json.loads(response.read())
        assert "HTTP 保存测试" in saved["content"]

        preview_request = Request(
            f"{base}/api/document/change-plan",
            method="POST",
            data=json.dumps(
                {
                    "action": "preview",
                    "path": document["path"],
                    "edits": [
                        {"old_text": "HTTP 保存测试", "new_text": "确认后的 HTTP 修改"}
                    ],
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-OpenWrite-Studio": "1",
                "X-OpenWrite-Workspace-Root": str(tmp_path),
                "X-OpenWrite-Session-Id": "ses_trace",
                "X-OpenWrite-Tool-Call-Id": "call_preview",
                "X-OpenWrite-Root-Call-Id": "call_root",
                "X-OpenWrite-Tool-Name": "novel_document_change_plan",
            },
        )
        with opener.open(preview_request) as response:
            planned = json.loads(response.read())["data"]
        assert planned["applied"] is False
        assert planned["mutation_summary"]["execution_status"] == "proposed"
        assert planned["operation_trace"]["schema_version"] == "openwrite.operation-trace.v1"

        apply_request = Request(
            f"{base}/api/document/change-plan",
            method="POST",
            data=json.dumps(
                {"action": "apply", "preview_token": planned["preview_token"]}
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-OpenWrite-Studio": "1",
                "X-OpenWrite-Workspace-Root": str(tmp_path),
                "X-OpenWrite-Session-Id": "ses_trace",
                "X-OpenWrite-Tool-Call-Id": "call_apply",
                "X-OpenWrite-Root-Call-Id": "call_root",
                "X-OpenWrite-Tool-Name": "novel_document_change_plan",
            },
        )
        with opener.open(apply_request) as response:
            applied_plan = json.loads(response.read())["data"]
        assert applied_plan["applied"] is True
        assert applied_plan["undo_preview_token"]
        assert applied_plan["mutation_summary"]["execution_status"] == "committed"
        trace_request = Request(
            f"{base}/api/traces?limit=5",
            headers={"X-OpenWrite-Workspace-Root": str(tmp_path)},
        )
        with opener.open(trace_request) as response:
            traces = json.loads(response.read())["data"]["records"]
        applied_trace = next(
            item for item in traces if item["trace_id"] == applied_plan["operation_trace"]["trace_id"]
        )
        assert applied_trace["request"]["tool_call_id"] == "call_apply"
        assert applied_trace["request"]["root_call_id"] == "call_root"
        assert applied_trace["request"]["tool_name"] == "novel_document_change_plan"
        assert applied_trace["domain_change"]["execution_status"] == "committed"
        assert applied_trace["privacy"]["raw_mutation_values_stored"] is False
        changed_document = _read_json(
            f"{base}/api/document?path=src%2Fstory%2Fbackground.md"
        )
        assert "确认后的 HTTP 修改" in changed_document["content"]

        focus_path = (
            tmp_path
            / "data"
            / "novels"
            / "demo"
            / "src"
            / "story"
            / "current_focus.md"
        )
        focus_before = focus_path.read_text(encoding="utf-8")
        structured_preview_request = Request(
            f"{base}/api/structured/change-plan",
            method="POST",
            data=json.dumps(
                {
                    "action": "preview",
                    "change_kind": "focus",
                    "change": {"goal": "HTTP 结构化确认", "must_keep": ["雨夜"]},
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-OpenWrite-Studio": "1",
                "X-OpenWrite-Workspace-Root": str(tmp_path),
                "X-OpenWrite-Session-Id": "ses_trace",
                "X-OpenWrite-Tool-Call-Id": "call_structured_preview",
                "X-OpenWrite-Root-Call-Id": "call_root",
                "X-OpenWrite-Tool-Name": "novel_structured_change_plan",
            },
        )
        with opener.open(structured_preview_request) as response:
            structured_plan = json.loads(response.read())["data"]
        assert focus_path.read_text(encoding="utf-8") == focus_before
        assert structured_plan["status"] == "proposed"

        structured_apply_request = Request(
            f"{base}/api/structured/change-plan",
            method="POST",
            data=json.dumps(
                {
                    "action": "apply",
                    "preview_token": structured_plan["preview_token"],
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-OpenWrite-Studio": "1",
                "X-OpenWrite-Workspace-Root": str(tmp_path),
                "X-OpenWrite-Session-Id": "ses_trace",
                "X-OpenWrite-Tool-Call-Id": "call_structured_apply",
                "X-OpenWrite-Root-Call-Id": "call_root",
                "X-OpenWrite-Tool-Name": "novel_structured_change_plan",
            },
        )
        with opener.open(structured_apply_request) as response:
            structured_applied = json.loads(response.read())["data"]
        assert structured_applied["status"] == "applied"
        assert structured_applied["mutation_summary"]["execution_status"] == "committed"
        assert "HTTP 结构化确认" in focus_path.read_text(encoding="utf-8")
        with opener.open(trace_request) as response:
            structured_traces = json.loads(response.read())["data"]["records"]
        structured_trace = next(
            item
            for item in structured_traces
            if item["trace_id"] == structured_applied["operation_trace"]["trace_id"]
        )
        assert structured_trace["request"]["tool_name"] == "novel_structured_change_plan"
        assert structured_trace["domain_change"]["execution_status"] == "committed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_sync_create_import_and_context_preview(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")
    app = StudioApplication(tmp_path)
    assert app.workspace()["version"] == "5.8.0"

    character = app.create_document(
        {"kind": "character", "name": "林岑", "description": "在雨夜追查旧信的记者。"}
    )
    assert character["document"]["path"].startswith("src/characters/")
    world = app.create_document(
        {"kind": "world", "name": "雾城钟楼", "description": "每天少走十三秒。"}
    )
    assert world["document"]["path"].startswith("src/world/entities/")

    synced = app.sync_project()
    assert synced["after"]["needs_sync"] is False
    assert synced["after"]["cards"] == 1

    import_payload = {
        "filename": "旧稿.txt",
        "content": "第一章 雨夜\n门外有人。\n\n第二章 回声\n门后没有人。",
        "arc_id": "arc_001",
    }
    import_preview = app.preview_import(import_payload)
    assert import_preview["chapter_count"] == 2
    assert import_preview["can_import"] is True
    assert [item["chapter_id"] for item in import_preview["chapters"]] == [
        "ch_001",
        "ch_002",
    ]
    manuscript = tmp_path / "data" / "novels" / "demo" / "data" / "manuscript"
    assert not list(manuscript.rglob("*.md"))

    imported = app.import_text(
        import_payload
    )
    assert [item["chapter_id"] for item in imported["imported"]] == ["ch_001", "ch_002"]

    conflict_preview = app.preview_import({**import_payload, "start_number": 1})
    assert conflict_preview["can_import"] is False
    assert conflict_preview["conflicts"] == ["ch_001", "ch_002"]

    preview = app.context_preview("ch_001")
    assert preview["chapter_id"] == "ch_001"
    assert "作者意图" in preview["markdown"]

    with pytest.raises(StudioError) as conflict:
        app.create_document({"kind": "character", "name": "林岑"})
    assert conflict.value.status == HTTPStatus.CONFLICT
    operations = app.workspace()["operations"]
    assert operations["sync"]["needs_sync"] is False
    assert any(item["name"] == "项目配置" and item["ok"] for item in operations["diagnostics"])


def test_studio_continuity_and_foreshadowing_management(tmp_path: Path):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)

    created = app.manage_foreshadowing(
        {
            "action": "create",
            "node_id": "hook_clock_001",
            "content": "钟楼每天少走十三秒",
            "weight": 8,
            "created_at": "ch_001",
            "target_chapter": "ch_010",
        }
    )

    nodes = created["continuity"]["foreshadowing"]["nodes"]
    assert nodes[0]["id"] == "hook_clock_001"
    assert created["workspace"]["snapshot"]["pending_foreshadowing"] == 1
    assert created["continuity"]["foreshadowing_validation"]["valid"] is True


def test_studio_mutations_report_entity_level_before_after_and_revisions(
    tmp_path: Path,
):
    init_project(tmp_path, "demo", "变更摘要")
    app = StudioApplication(tmp_path)

    document = app.read_document("src/story/background.md")
    saved = app.write_document(
        "src/story/background.md",
        "# 主题\n\n新的主题约束。\n",
        document["version"],
        save_origin="manual",
    )
    document_change = saved["mutation_summary"]
    assert document_change["schema_version"] == "openwrite.mutation-summary.v1"
    assert document_change["execution_status"] == "committed"
    assert document_change["source_revision"] == document["revision"]
    assert document_change["result_revision"] == saved["revision"]
    assert document_change["items"][0]["entity_kind"] == "canon"
    assert document_change["items"][0]["field"] == "content"
    assert document_change["items"][0]["before"]["value"] == document["content"]
    assert document_change["items"][0]["after"]["value"] == "# 主题\n\n新的主题约束。\n"

    character = app.create_asset(
        {"kind": "character", "id": "lin_cen", "data": {"name": "林岑", "goal": "逃离"}}
    )["asset"]
    changed_character = app.update_asset(
        {
            "kind": "character",
            "id": "lin_cen",
            "revision": character["revision"],
            "data": {"goal": "保护旧城"},
        }
    )
    character_items = changed_character["mutation_summary"]["items"]
    goal_change = next(item for item in character_items if item["field"] == "data.goal")
    assert goal_change["entity_kind"] == "character"
    assert goal_change["before"]["value"] == "逃离"
    assert goal_change["after"]["value"] == "保护旧城"
    assert goal_change["source_revision"] == character["revision"]
    assert goal_change["result_revision"] == changed_character["asset"]["revision"]

    world = app.create_asset(
        {"kind": "world", "id": "old_city", "data": {"name": "旧城", "status": "封闭"}}
    )["asset"]
    changed_world = app.update_asset(
        {
            "kind": "world",
            "id": "old_city",
            "revision": world["revision"],
            "data": {"status": "戒严"},
        }
    )
    status_change = next(
        item for item in changed_world["mutation_summary"]["items"]
        if item["field"] == "data.status"
    )
    assert status_change["entity_kind"] == "world"
    assert status_change["before"]["value"] == "封闭"
    assert status_change["after"]["value"] == "戒严"

    outline_before = app.outline_structure()
    outline_edit = app.edit_outline_structure(
        {
            "operation": "rename",
            "node_id": outline_before["roots"][0]["id"],
            "title": "改名后的第一卷",
            "revision": outline_before["revision"],
        }
    )
    outline_change = outline_edit["mutation_summary"]
    assert outline_change["items"][0]["entity_kind"] == "outline"
    assert outline_change["source_revision"] == outline_before["revision"]
    assert outline_change["result_revision"] == outline_edit["outline"]["revision"]

    hook = app.manage_foreshadowing(
        {
            "action": "create",
            "node_id": "hook_mutation_001",
            "content": "钟楼停摆",
            "weight": 8,
            "target_chapter": "ch_010",
        }
    )
    hook_item = hook["mutation_summary"]["items"][0]
    assert hook_item["entity_kind"] == "foreshadowing"
    assert hook_item["field"] == "node"
    assert hook_item["before"]["kind"] == "missing"
    assert hook_item["after"]["value"]["content"] == "钟楼停摆"

    focus_before = app._service().focus_snapshot()
    focus = app.update_focus(
        {"goal": "守住旧城", "must_keep": ["雨夜"], "must_avoid": ["旁白解释"]}
    )
    focus_items = focus["mutation_summary"]["items"]
    assert any(
        item["field"] == "goal"
        and item["before"]["value"] == focus_before["goal"]
        and item["after"]["value"] == "守住旧城"
        for item in focus_items
    )

    targets = app.update_writing_targets({"chapter_words": 3600})
    target_item = next(
        item for item in targets["mutation_summary"]["items"]
        if item["field"] == "chapter_words"
    )
    assert target_item["entity_kind"] == "project"
    assert target_item["before"]["value"] != target_item["after"]["value"]


def test_structured_change_plans_preview_and_apply_all_direct_domain_writes(
    tmp_path: Path,
):
    init_project(tmp_path, "demo", "结构化变更计划")
    app = StudioApplication(tmp_path)
    novel = tmp_path / "data" / "novels" / "demo"

    character = app.create_asset(
        {"kind": "character", "id": "lin_cen", "data": {"name": "林岑", "goal": "逃离"}}
    )["asset"]
    outline = app.outline_structure()
    cases = [
        (
            "outline",
            {
                "operation": "rename",
                "node_id": outline["roots"][0]["id"],
                "title": "雨夜卷",
                "revision": outline["revision"],
            },
            novel / "src" / "outline.md",
            "outline",
        ),
        (
            "asset",
            {
                "kind": "character",
                "id": "lin_cen",
                "revision": character["revision"],
                "data": {"goal": "守住旧城"},
            },
            novel / character["path"],
            "character",
        ),
        (
            "focus",
            {"goal": "守住旧城", "must_keep": ["雨夜"], "must_avoid": ["旁白解释"]},
            novel / "src" / "story" / "current_focus.md",
            "canon",
        ),
        (
            "foreshadowing",
            {
                "action": "create",
                "node_id": "hook_plan_001",
                "content": "钟楼少走十三秒",
                "weight": 8,
                "target_chapter": "ch_010",
            },
            novel / "data" / "foreshadowing" / "dag.yaml",
            "foreshadowing",
        ),
        (
            "writing_targets",
            {"chapter_words": 3600, "outline_chapter_words": 240},
            tmp_path / "novel_config.yaml",
            "project",
        ),
    ]

    for change_kind, change, target, entity_kind in cases:
        before = target.read_text(encoding="utf-8")
        preview = app.structured_change_plan(
            {"action": "preview", "change_kind": change_kind, "change": change}
        )
        assert target.read_text(encoding="utf-8") == before
        assert preview["status"] == "proposed"
        assert preview["applied"] is False
        assert preview["changed"] is True
        assert len(preview["preview_token"]) == 24
        assert preview["mutation_summary"]["execution_status"] == "proposed"
        assert preview["mutation_summary"]["items"][0]["entity_kind"] == entity_kind

        applied = app.structured_change_plan(
            {"action": "apply", "preview_token": preview["preview_token"]}
        )
        after = target.read_text(encoding="utf-8")
        assert after != before
        assert applied["status"] == "applied"
        assert applied["applied"] is True
        assert applied["source_revision"] == preview["source_revision"]
        assert applied["result_revision"] == preview["result_revision"]
        assert applied["mutation_summary"]["execution_status"] == "committed"
        assert len(applied["undo_preview_token"]) == 24

        undone = app.structured_change_plan(
            {"action": "undo", "preview_token": applied["undo_preview_token"]}
        )
        assert undone["status"] == "undone"
        assert target.read_text(encoding="utf-8") == before


def test_structured_change_plan_reject_retry_conflict_and_token_integrity(
    tmp_path: Path,
):
    init_project(tmp_path, "demo", "结构化变更计划")
    app = StudioApplication(tmp_path)
    focus_path = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "src"
        / "story"
        / "current_focus.md"
    )

    rejected = app.structured_change_plan(
        {"action": "preview", "change_kind": "focus", "change": {"goal": "先守桥"}}
    )
    app.structured_change_plan(
        {"action": "reject", "preview_token": rejected["preview_token"]}
    )
    with pytest.raises(StudioError) as consumed:
        app.structured_change_plan(
            {"action": "apply", "preview_token": rejected["preview_token"]}
        )
    assert consumed.value.code == "STRUCTURED_PREVIEW_INVALID"

    preview = app.structured_change_plan(
        {"action": "preview", "change_kind": "focus", "change": {"goal": "守住旧城"}}
    )
    focus_path.write_text(focus_path.read_text(encoding="utf-8") + "\n外部修改\n", encoding="utf-8")
    with pytest.raises(StudioError) as conflict:
        app.structured_change_plan(
            {"action": "apply", "preview_token": preview["preview_token"]}
        )
    assert conflict.value.status == HTTPStatus.CONFLICT
    assert conflict.value.code == "STRUCTURED_REVISION_CONFLICT"

    retried = app.structured_change_plan(
        {"action": "retry", "preview_token": preview["preview_token"]}
    )
    assert retried["retried_from"] == preview["preview_token"]
    assert retried["source_revision"] != preview["source_revision"]
    applied = app.structured_change_plan(
        {"action": "apply", "preview_token": retried["preview_token"]}
    )
    committed = focus_path.read_text(encoding="utf-8")
    focus_path.write_text(committed + "\n并发追加\n", encoding="utf-8")
    with pytest.raises(StudioError) as unsafe_undo:
        app.structured_change_plan(
            {"action": "undo", "preview_token": applied["undo_preview_token"]}
        )
    assert unsafe_undo.value.code == "STRUCTURED_REVISION_CONFLICT"
    assert focus_path.read_text(encoding="utf-8").endswith("并发追加\n")

    integrity = app.structured_change_plan(
        {"action": "preview", "change_kind": "focus", "change": {"goal": "篡改测试"}}
    )
    record_path = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "workflows"
        / "structured_change_plans"
        / f"{integrity['preview_token']}.json"
    )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["result_content"] = "伪造内容"
    record_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(StudioError) as invalid_record:
        app.structured_change_plan(
            {"action": "apply", "preview_token": integrity["preview_token"]}
        )
    assert invalid_record.value.code == "STRUCTURED_PREVIEW_INVALID"

    with pytest.raises(StudioError) as tampered:
        app.structured_change_plan(
            {"action": "apply", "preview_token": "0" * 24}
        )
    assert tampered.value.code == "STRUCTURED_PREVIEW_INVALID"


def test_studio_chat_and_source_extraction_use_injected_real_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    monkeypatch.setenv("LLM_API_KEY", "configured-for-test")
    chat_calls: list[tuple[str, str]] = []
    source_calls: list[dict] = []

    def fake_chat(root: Path, novel_id: str, agent: str, message: str) -> dict:
        chat_calls.append((agent, message))
        return {"content": f"{agent} 已收到：{message}"}

    def fake_source(root: Path, payload: dict) -> dict:
        source_calls.append(payload)
        source_root = root / "data" / "novels" / "demo" / "data" / "sources" / payload["source_id"]
        (source_root / "style").mkdir(parents=True)
        (source_root / "source.md").write_text("# 来源", encoding="utf-8")
        return {"ok": True, "source_id": payload["source_id"]}

    app = StudioApplication(
        tmp_path,
        chat_executor=fake_chat,
        source_executor=fake_source,
    )
    chat = app.chat_turn(
        {
            "agent": "goethe",
            "session_id": "goethe-20260729-120000-test01",
            "run_id": "run-studio-activity-01",
            "message": "整理第一篇",
        }
    )
    assert chat["content"] == "goethe 已收到：整理第一篇"
    assert chat["content_html"] == "<p>goethe 已收到：整理第一篇</p>\n"
    assert chat["session_id"] == "goethe-20260729-120000-test01"
    assert chat["run_id"] == "run-studio-activity-01"
    assert chat_calls == [("goethe", "整理第一篇")]
    activity = app.agent_activity("run-studio-activity-01")
    assert activity["status"] == "complete"
    assert activity["step_index"] == 4
    assert activity["elapsed_seconds"] >= 0

    extracted = app.source_action(
        {
            "action": "extract",
            "source_id": "reference_01",
            "focus": "style",
            "content": "雨落在旧钟楼上。",
        }
    )
    assert extracted["result"]["ok"] is True
    assert source_calls[0]["focus"] == "style"
    packs = extracted["workspace"]["operations"]["source_packs"]
    assert packs[0]["source_id"] == "reference_01"


def test_studio_chat_exposes_recoverable_model_output_errors(tmp_path: Path):
    init_project(tmp_path, "demo")

    def malformed_chat(root: Path, novel_id: str, agent: str, message: str) -> dict:
        raise ProviderResponseError(
            "MALFORMED_TOOL_ARGUMENTS",
            "工具 stage_outline_edits 的参数不是有效 JSON：第 1 行第 42 列，字符串没有闭合",
            details={
                "tool_name": "stage_outline_edits",
                "line": 1,
                "column": 42,
                "likely_truncated": True,
            },
        )

    preferences = StudioModelSettingsStore(tmp_path / "preferences")
    app = StudioApplication(
        tmp_path,
        chat_executor=malformed_chat,
        project_registry=ProjectRegistry(
            tmp_path / "registry.yaml",
            allow_ephemeral=True,
        ),
        model_settings_store=preferences,
        model_profile_store=ModelProfileStore(preferences.directory),
    )

    with pytest.raises(StudioError) as raised:
        app.chat_turn(
            {
                "agent": "goethe",
                "run_id": "run-malformed-tool-arguments",
                "message": "重排整卷大纲",
            }
        )

    assert raised.value.status == HTTPStatus.BAD_GATEWAY
    assert raised.value.code == "MALFORMED_TOOL_ARGUMENTS"
    assert raised.value.recoverable is True
    assert raised.value.details["failed_tool_executed"] is False
    activity = app.agent_activity("run-malformed-tool-arguments")
    assert activity["status"] == "error"
    assert "stage_outline_edits" in activity["note"]
    assert "第 1 行第 42 列" in activity["note"]


def test_studio_source_analysis_v2_exposes_evidence_profile_and_confirmed_promotion(
    tmp_path: Path,
):
    from tools.source_analysis import SourceAnalysisService

    init_project(tmp_path, "demo")
    analysis = SourceAnalysisService(tmp_path, "demo")

    def analyzer(text: str, context: dict) -> dict:
        quote = text[:4]
        return {
            "summary": "钟声作为递进信号。",
            "findings": [
                {
                    "category": "method",
                    "claim": "用重复物象建立递进节奏",
                    "confidence": 0.9,
                    "reusable": True,
                    "source_bound": False,
                    "evidence": [
                        {"start": 0, "end": len(quote), "quote": quote}
                    ],
                }
            ],
        }

    for source_id in ("reference_a", "reference_b"):
        content = f"第一章\n\n{source_id} 的钟声逐次加快。"
        analysis.prepare(
            source_id,
            content,
            relative_name=f"{source_id}.txt",
            input_budget_tokens=500,
        )
        analysis.analyze(source_id, analyzer=analyzer)

    app = StudioApplication(tmp_path)
    try:
        status = app.source_action(
            {"action": "status_v2", "source_id": "reference_a"}
        )
        assert status["result"]["complete"] is True
        assert status["result"]["report"]["findings"][0]["evidence"]
        packs = status["workspace"]["operations"]["source_packs"]
        assert packs[0]["analysis_v2"]["status"] == "completed"
        assert packs[0]["analysis_v2"]["source_sha256"]
        assert packs[0]["analysis_v2"]["relative_name"] == "reference_a.txt"
        assert packs[0]["analysis_v2"]["total_chars"] > 0

        profile = app.source_action(
            {
                "action": "synthesize_v2",
                "source_ids": ["reference_a", "reference_b"],
            }
        )["result"]
        preview = app.source_action(
            {
                "action": "promotion_preview_v2",
                "profile_id": profile["profile_id"],
                "target": "style",
            }
        )["result"]
        applied = app.source_action(
            {
                "action": "promote_v2",
                "preview_id": preview["preview_id"],
                "confirm": True,
            }
        )["result"]
        assert applied["ok"] is True
        assert (
            tmp_path
            / "data"
            / "novels"
            / "demo"
            / "data"
            / "style"
            / "reference_profile.md"
        ).is_file()
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_studio_source_task_fails_when_chunk_analysis_fails(tmp_path: Path, monkeypatch):
    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)
    monkeypatch.setattr(
        app,
        "source_action",
        lambda payload: {
            "result": {
                "analysis": {
                    "ok": False,
                    "failures": [
                        {
                            "chunk_id": "chk_0000_test",
                            "code": "MODEL_REASONING_ONLY",
                            "message": "模型只返回了推理内容，没有最终答案",
                        }
                    ],
                }
            }
        },
    )
    context = SimpleNamespace(phase=lambda *args: None, checkpoint=lambda: None)

    with pytest.raises(StudioError) as raised:
        app._task_source_operation(
            {"action": "analyze_v2", "source_id": "reference_failed"},
            context,
        )

    assert raised.value.code == "MODEL_REASONING_ONLY"
    assert raised.value.recoverable is True
    assert raised.value.details["source_id"] == "reference_failed"


def test_studio_http_exposes_context_and_import_routes(tmp_path: Path):
    init_project(tmp_path, "demo")
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(ProxyHandler({}))
    try:
        context = _read_json(f"{base}/api/context?chapter=ch_001")
        assert context["chapter_id"] == "ch_001"

        request = Request(
            f"{base}/api/import",
            method="POST",
            data=json.dumps(
                {
                    "filename": "draft.md",
                    "content": "# 第一章 雨夜\n\n门外有人。",
                    "arc_id": "arc_001",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(request) as response:
            payload = json.loads(response.read())
        assert payload["imported"][0]["chapter_id"] == "ch_001"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_http_exposes_real_agent_activity(tmp_path: Path):
    init_project(tmp_path, "demo")
    server = create_server(tmp_path, port=0)
    server.app._start_agent_activity(
        "run-http-activity-01",
        agent="dante",
        session_id="default",
    )
    server.app._record_agent_activity(
        "run-http-activity-01",
        {
            "event": "tool_started",
            "turn": 2,
            "tool": "get_context",
            "tool_call_id": "call_context_01",
            "arguments": {
                "chapter_id": "ch_007",
                "api_key": "sk-abcdefghijklmnop",
                "note": "Authorization: Bearer private-value",
            },
        },
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        activity = _read_json(f"{base}/api/agent/activity?run_id=run-http-activity-01")
        assert activity["status"] == "running"
        assert activity["phase"] == "tool_running"
        assert activity["step_index"] == 2
        assert activity["title"] == "Dante 正在调用工具"
        assert activity["note"] == "第 2 轮：组装章节上下文"
        assert activity["tool"] == "get_context"
        event = activity["events"][0]
        assert event["sequence"] == 1
        assert event["tool_label"] == "组装章节上下文"
        assert event["tool_call_id"] == "call_context_01"
        assert event["arguments"]
        assert "chapter_id" in event["arguments"]
        assert "sk-abcdefghijklmnop" not in event["arguments"]
        assert "private-value" not in event["arguments"]
        assert "redacted" in event["arguments"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_http_can_initialize_an_empty_workspace(tmp_path: Path):
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(ProxyHandler({}))
    try:
        assert _read_json(f"{base}/api/workspace")["initialized"] is False
        request = Request(
            f"{base}/api/project/init",
            method="POST",
            data=json.dumps({"novel_id": "web_novel", "title": "前端新书"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(request) as response:
            payload = json.loads(response.read())
        assert payload["initialized"] is True
        assert payload["snapshot"]["title"] == "前端新书"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_revision_api_uses_envelope_and_dynamic_apply_route(tmp_path: Path):
    init_project(tmp_path, "demo")
    chapter = _save_chapter(
        tmp_path,
        "demo",
        "ch_001",
        "第一章",
        "林舟推开门。门外没有人。",
    )

    def revise(root: Path, payload: dict) -> dict:
        assert root == tmp_path
        assert payload["selection"] == "门外没有人"
        return {
            "replacement_text": "门外看起来没有人",
            "rationale": "保留观察的不确定性。",
            "risk_flags": [],
        }

    server = create_server(tmp_path, port=0, revision_executor=revise)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(ProxyHandler({}))
    content = chapter.read_text(encoding="utf-8")
    selected = "门外没有人"
    start = content.index(selected)

    def post(path: str, payload: dict) -> tuple[dict, str]:
        request = Request(
            f"{base}{path}",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(request) as response:
            return json.loads(response.read()), response.headers["X-Request-ID"]

    try:
        created, request_id = post(
            "/api/revisions/selection",
            {
                "chapter_id": "ch_001",
                "start": start,
                "end": start + len(selected),
                "original_text": selected,
                "action": "rewrite",
            },
        )
        assert created["ok"] is True
        assert created["error"] is None
        assert created["request_id"] == request_id
        proposal_id = created["data"]["proposal_id"]

        listed = _read_json(f"{base}/api/revisions?chapter=ch_001")
        assert listed["data"]["proposals"][0]["proposal_id"] == proposal_id

        applied, apply_request_id = post(f"/api/revisions/{proposal_id}/apply", {})
        assert applied["request_id"] == apply_request_id
        assert applied["data"]["proposal"]["status"] == "applied"
        assert "门外看起来没有人" in chapter.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_revision_api_returns_document_conflict_details(tmp_path: Path):
    init_project(tmp_path, "demo")
    chapter = _save_chapter(tmp_path, "demo", "ch_001", "第一章", "门外没有人。")
    server = create_server(
        tmp_path,
        port=0,
        revision_executor=lambda root, payload: "门外似乎没有人",
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(ProxyHandler({}))
    content = chapter.read_text(encoding="utf-8")
    selected = "门外没有人"
    start = content.index(selected)

    def request(path: str, payload: dict) -> dict:
        return json.loads(
            opener.open(
                Request(
                    f"{base}{path}",
                    method="POST",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-OpenWrite-Studio": "1",
                    },
                )
            ).read()
        )

    try:
        created = request(
            "/api/revisions/selection",
            {
                "chapter_id": "ch_001",
                "start": start,
                "end": start + len(selected),
                "original_text": selected,
            },
        )
        proposal_id = created["data"]["proposal_id"]
        chapter.write_text(content + "\n新增一段。", encoding="utf-8")
        with pytest.raises(HTTPError) as response:
            request(f"/api/revisions/{proposal_id}/apply", {})
        payload = json.loads(response.value.read())
        assert response.value.code == HTTPStatus.CONFLICT
        assert payload["code"] == "DOCUMENT_CONFLICT"
        assert payload["recoverable"] is True
        assert payload["details"]["proposal_id"] == proposal_id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
