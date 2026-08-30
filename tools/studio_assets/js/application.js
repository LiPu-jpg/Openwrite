import {
  $, $$, api, countWritingUnits, formatNumber, labels,
  readinessLabels, setSaveState, showToast, state,
} from "/js/core.js";
import {
  appendReviewIssueActions, bindRevisionUI, showRevisionPreview, syncRevisionControls,
} from "/js/revisions.js";
import { bindTaskCenter, enqueueTask, refreshTasks } from "/js/tasks.js";
import { bindAssetUI, openStructuredAsset } from "/js/assets.js";
import {
  bindModelProfilesUI, openModelProfilesDialog, renderModelProfilesUI,
  updateRoutedModelIndicator,
} from "/js/models.js";

import {
  destroyMarkdownEditorsWithin, getPrimaryMarkdownEditor,
  initializePrimaryMarkdownEditor, mountMarkdownEditor, setMarkdownEditorTheme,
} from "/js/markdown-editor.js";

const libraryViews = ["core", "characters", "settings"];
const legacyLibraryViews = { story: "core", world: "settings", assets: "characters" };

function readLocalValue(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function writeLocalValue(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    // The current session remains usable when browser storage is unavailable.
  }
}

async function loadWorkspace() {
  state.workspace = await api("/api/workspace");
  renderWorkspace();
  renderRecentProjects();
  document.querySelector("#app").setAttribute("aria-busy", "false");
  if (!state.workspace.initialized) suggestProjectPath();
  if (state.workspace.initialized) refreshTasks();
}

function showBootstrapError(error) {
  const status = Number(error?.status || 0);
  const hint = status >= 500
    ? "当前作品可能包含旧版或损坏的数据；可先重试，或打开其他作品继续排查。"
    : (status === 0
      ? "无法连接本地 Studio 服务，请确认启动窗口仍在运行。"
      : "可重试载入，或打开其他作品检查是否仅当前项目受影响。");
  const detail = $("#bootstrap-error-detail");
  if (detail) detail.textContent = `${error?.message || "未知启动错误"} ${hint}`;
  const reference = [error?.code, error?.requestId].filter(Boolean).join(" · ");
  const request = $("#bootstrap-error-request");
  if (request) {
    request.textContent = reference;
    request.hidden = !reference;
  }
  const alert = $("#bootstrap-error");
  if (alert) alert.hidden = false;
  const title = $("#book-title");
  if (title) title.textContent = "作品载入失败";
  const location = $("#book-location");
  if (location) location.textContent = "OpenWrite Studio 仍可切换作品";
  $("#app")?.setAttribute("aria-busy", "false");
  showToast(error?.message || "作品载入失败", true);
}

function hideBootstrapError() {
  const alert = $("#bootstrap-error");
  if (alert) alert.hidden = true;
}

async function retryBootstrap() {
  const button = $("#bootstrap-retry");
  button.disabled = true;
  $("#app").setAttribute("aria-busy", "true");
  try {
    await loadWorkspace();
    await routeFromLocation();
  } catch (error) {
    showBootstrapError(error);
  } finally {
    button.disabled = false;
  }
}

async function loadResearch() {
  try {
    const payload = await api("/api/research");
    state.research.status = payload.data;
    renderResearch();
  } catch (error) {
    $("#research-runtime-status").textContent = error.message;
  }
}

function researchSearchProvider(providerId) {
  return (state.research.status?.settings?.search_providers || [])
    .find((provider) => provider.id === providerId) || null;
}

function renderResearchSearchKeyState() {
  const providerId = $("#research-settings-search").value || "bocha";
  const provider = researchSearchProvider(providerId);
  const requiresKey = Boolean(provider?.requires_api_key);
  $("#research-search-key-field").hidden = !requiresKey;
  $("#research-search-key-state").textContent = provider?.credential_configured
    ? "本机已有凭据；留空即可沿用"
    : "尚未保存 Key";
  $("#research-search-key-clear").disabled = !provider?.credential_configured;
}

function renderResearchConfiguration() {
  const surface = state.research.status || {};
  const settings = surface.settings || {};
  const model = surface.model_route || {};
  if (!state.research.searchProviderInitialized) {
    $("#research-search").value = settings.search_provider || "bocha";
    state.research.searchProviderInitialized = true;
  }
  const search = researchSearchProvider($("#research-search").value);
  const modelReady = Boolean(model.configured && model.compatible);
  const searchReady = Boolean(search?.configured);
  $("#research-llm").value = model.model
    ? `${model.label} · ${model.model}`
    : "尚未配置深度研究模型路由";
  $("#research-settings-model").textContent = model.model
    ? `${model.label} · ${model.model}`
    : "尚未配置";
  const notes = [];
  if (!model.configured) notes.push("模型档案缺少 API Key");
  else if (!model.compatible) notes.push("当前模型不是 OpenAI-compatible 接口");
  if (!searchReady) notes.push(`${search?.label || "搜索服务"}缺少 API Key`);
  $("#research-api-state").textContent = notes.length
    ? notes.join(" · ")
    : `${model.label || "研究模型"} · ${search?.label || "不联网"}已就绪`;
  $("#research-submit").disabled = !surface.available || !modelReady || !searchReady;
  renderResearchSearchKeyState();
}

function renderResearch() {
  const surface = state.research.status || {};
  const status = $("#research-runtime-status");
  if (surface.available) {
    status.textContent = `运行环境已就绪 · ${surface.reports?.length || 0} 份报告`;
    status.classList.add("ready");
  } else {
    status.textContent = surface.setup_hint || "运行环境未就绪，请先安装 integrations/deepresearch 的依赖";
    status.classList.remove("ready");
  }
  renderResearchConfiguration();
  const reports = surface.reports || [];
  $("#research-report-count").textContent = String(reports.length);
  const root = $("#research-report-list");
  root.replaceChildren();
  if (!reports.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "完成一次研究后，报告会出现在这里。";
    root.append(empty);
    return;
  }
  reports.forEach((report) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `research-report-item${state.research.selectedReportId === report.id ? " active" : ""}`;
    const title = document.createElement("strong");
    title.textContent = report.title;
    const meta = document.createElement("span");
    meta.textContent = `${report.status} · ${report.created_at || "时间未知"}`;
    button.append(title, meta);
    button.addEventListener("click", () => openResearchReport(report.id));
    root.append(button);
  });
}

function openResearchSettings() {
  const settings = state.research.status?.settings || {};
  $("#research-settings-search").value = settings.search_provider || "bocha";
  $("#research-search-api-key").value = "";
  $("#research-search-api-key").type = "password";
  $("#research-search-key-toggle").textContent = "显示";
  $("#research-search-key-toggle").setAttribute("aria-pressed", "false");
  $("#research-search-remember-key").checked = true;
  $("#research-settings-status").textContent = "";
  renderResearchConfiguration();
  $("#research-settings-dialog").showModal();
}

async function saveResearchSettings(event) {
  event.preventDefault();
  const button = $("#research-settings-save");
  button.disabled = true;
  $("#research-settings-status").textContent = "正在保存…";
  try {
    state.research.status = await api("/api/research/settings", {
      method: "POST",
      body: JSON.stringify({
        search_provider: $("#research-settings-search").value,
        search_api_key: $("#research-search-api-key").value.trim(),
        remember_api_key: $("#research-search-remember-key").checked,
      }),
    });
    state.research.searchProviderInitialized = false;
    renderResearch();
    $("#research-settings-status").textContent = "API 设置已保存。";
    $("#research-search-api-key").value = "";
    showToast("深度研究 API 设置已保存");
  } catch (error) {
    $("#research-settings-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function clearResearchSearchKey() {
  const providerId = $("#research-settings-search").value;
  const provider = researchSearchProvider(providerId);
  if (!provider?.credential_configured) return;
  if (!window.confirm(`清除本机保存的 ${provider.label} API Key？`)) return;
  try {
    state.research.status = await api("/api/research/settings", {
      method: "POST",
      body: JSON.stringify({
        search_provider: providerId,
        clear_api_key: true,
      }),
    });
    renderResearch();
    $("#research-settings-status").textContent = `${provider.label} API Key 已清除。`;
  } catch (error) {
    $("#research-settings-status").textContent = error.message;
  }
}

function toggleResearchSearchKey() {
  const input = $("#research-search-api-key");
  const visible = input.type === "text";
  input.type = visible ? "password" : "text";
  $("#research-search-key-toggle").textContent = visible ? "显示" : "隐藏";
  $("#research-search-key-toggle").setAttribute("aria-pressed", String(!visible));
}

async function openResearchReport(reportId) {
  try {
    const payload = await api(`/api/research/reports/${encodeURIComponent(reportId)}`);
    const report = payload.data;
    state.research.selectedReportId = reportId;
    $("#research-report-panel").hidden = false;
    $("#research-report-title").textContent = report.metadata?.title || reportId;
    $("#research-report-meta").textContent = `${report.metadata?.status || ""} · ${report.metadata?.episode_id || ""}`;
    $("#research-report-content").textContent = report.content || "";
    renderResearch();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function submitResearch(event) {
  event.preventDefault();
  const button = $("#research-submit");
  const formStatus = $("#research-form-status");
  button.disabled = true;
  formStatus.textContent = "正在加入后台任务…";
  try {
    await enqueueTask(
      "research",
      {
        prompt: $("#research-prompt").value.trim(),
        search: $("#research-search").value,
        quality: $("#research-quality").value,
        cycles: Number($("#research-cycles").value || 2),
        language: "zh-CN",
      },
      {
        label: "研究任务已加入队列",
        onComplete: async (task) => {
          await loadResearch();
          if (task.result?.report_id) await openResearchReport(task.result.report_id);
        },
      },
    );
    formStatus.textContent = "任务已加入队列，可在任务中心查看进度。";
  } catch (error) {
    formStatus.textContent = error.message;
  } finally {
    renderResearchConfiguration();
  }
}

function suggestProjectPath() {
  const project = state.workspace?.project || {};
  const input = $("#project-path");
  const hint = $("#project-path-hint");
  if (!input) return;
  const titleInput = $("#project-title");
  const update = () => {
    const title = (titleInput?.value || "").trim();
    const slug = title
      .toLowerCase()
      .replace(/[^\w\u4e00-\u9fff]+/g, "_")
      .replace(/^_|_$/g, "")
      .slice(0, 40) || "my_novel";
    const defaultPath = `../OpenWriteNovels/${slug}`;
    input.placeholder = defaultPath;
    if (hint) {
      hint.textContent = project.requires_external_location
        ? `留空时自动保存到 ${defaultPath}（框架目录同级）`
        : "留空时在当前启动目录创建作品；也可在这里指定其他目录。";
    }
  };
  if (titleInput && !titleInput.dataset.projectPathHintBound) {
    titleInput.addEventListener("input", update);
    titleInput.dataset.projectPathHintBound = "true";
  }
  update();
}

function renderWorkspace() {
  const { snapshot, model } = state.workspace;
  $("#writing-targets-open").disabled = !state.workspace.initialized;
  $("#book-title").textContent = snapshot.title;
  $("#book-location").textContent = `${snapshot.current_arc} / ${snapshot.current_chapter}`;
  $("#metric-words").textContent = formatNumber(snapshot.writing_units);
  $("#metric-chapters").textContent = formatNumber(snapshot.chapters);
  $("#metric-characters").textContent = formatNumber(snapshot.characters);
  $("#metric-hooks").textContent = formatNumber(snapshot.pending_foreshadowing);

  const percent = snapshot.target_units
    ? Math.min(100, Math.round((snapshot.writing_units / snapshot.target_units) * 100))
    : 0;
  $("#progress-percent").textContent = `${percent}%`;
  $("#progress-current").textContent = `${formatNumber(snapshot.writing_units)} 字`;
  $("#progress-target").textContent = snapshot.target_units
    ? `目标 ${formatNumber(snapshot.target_units)} 字`
    : "目标未设置";
  $("#progress-fill").style.width = `${percent}%`;
  const progress = $(".progress-track");
  progress.setAttribute("aria-valuenow", String(percent));

  const profileCount = state.workspace.model_profiles?.profiles?.length || 0;
  const modelState = $("#model-state");
  modelState.textContent = profileCount ? `模型档案 · ${profileCount}` : "模型档案 · 未配置";
  modelState.classList.toggle("ready", profileCount > 0);
  renderModelProfilesUI();

  renderReadiness(snapshot.readiness);
  $("#onboarding-open").hidden = false;
  $("#onboarding-open").textContent = "新手引导";
  renderRecentChapters();
  renderNextActions(snapshot.next_action_items || snapshot.next_actions || []);
  renderTransferSummary();
  fillFocus(snapshot.creative_focus);
  $("#fact-arc").textContent = snapshot.current_arc;
  $("#fact-chapter").textContent = snapshot.current_chapter;
  $("#fact-stage").textContent = snapshot.stage;
  $("#fact-world").textContent = String(snapshot.world_documents);
  $("#fact-tokens").textContent = formatNumber(snapshot.total_tokens);
  $("#fact-review-score").textContent = snapshot.reviewed_chapters
    ? `${snapshot.average_review_score} / 100`
    : "-";
  renderDocumentList(documentListGroupForView(state.view));
  syncChapterDeleteControl();
  renderOperations();
  renderInspectorContext();
  hideBootstrapError();
}

function renderReadiness(readiness) {
  const root = $("#readiness-list");
  root.replaceChildren();
  let readyCount = 0;
  Object.entries(readinessLabels).forEach(([key, label]) => {
    const ready = Boolean(readiness[key]);
    if (ready) readyCount += 1;
    const row = document.createElement("div");
    row.className = `readiness-row${ready ? " ready" : ""}`;
    const name = document.createElement("span");
    name.textContent = label;
    const status = document.createElement("span");
    status.className = "readiness-state";
    status.textContent = ready ? "就绪" : "待完善";
    row.append(name, status);
    root.append(row);
  });
  $("#readiness-score").textContent = `${readyCount} / ${Object.keys(readinessLabels).length}`;
}

function renderRecentChapters() {
  const root = $("#recent-chapters");
  root.replaceChildren();
  const chapters = state.workspace.documents.chapters.slice(-5).reverse();
  if (!chapters.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "尚无正文";
    root.append(empty);
    return;
  }
  chapters.forEach((doc) => {
    const button = document.createElement("button");
    button.className = "recent-row";
    button.type = "button";
    const title = document.createElement("span");
    title.textContent = doc.title;
    const meta = document.createElement("span");
    meta.textContent = doc.subtitle;
    button.append(title, meta);
    button.addEventListener("click", () => openDocument(doc.path, true));
    root.append(button);
  });
}

function renderNextActions(actions) {
  const root = $("#next-actions");
  root.replaceChildren();
  const items = normalizeNextActions(actions);
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "next-action next-action-button";
    button.textContent = item.label;
    button.title = item.cli || item.label;
    button.addEventListener("click", () => runNextAction(item));
    root.append(button);
  });
}

function normalizeNextActions(actions) {
  if (!Array.isArray(actions) || !actions.length) return [];
  return actions.map((action) => {
    if (action && typeof action === "object") {
      return {
        id: action.id || "",
        label: action.label || action.cli || "下一步",
        cli: action.cli || "",
        studio_action: action.studio_action || "",
        seed: action.seed || "",
      };
    }
    const text = String(action || "");
    const lower = text.toLowerCase();
    let studioAction = "";
    if (lower.includes("goethe")) studioAction = "open_goethe";
    else if (lower.includes("dante")) studioAction = "open_dante";
    else if (lower.includes("focus") || text.includes("罗盘")) studioAction = "open_focus";
    else if (text.includes("创建")) studioAction = "open_project_dialog";
    return { id: "", label: text, cli: text, studio_action: studioAction, seed: "" };
  });
}

function runNextAction(item) {
  const action = item.studio_action || "";
  if (action === "open_project_dialog") {
    openProjectDialog();
    return;
  }
  if (action === "open_focus") {
    setView("dashboard");
    const goal = $("#focus-goal");
    if (goal) {
      goal.focus();
      goal.scrollIntoView({ block: "center", behavior: "smooth" });
    }
    showToast("请在创作罗盘中填写本阶段目标");
    return;
  }
  if (action === "open_goethe" || action === "open_dante") {
    const agent = action === "open_dante" ? "dante" : "goethe";
    setView("agents");
    chooseAgent(agent);
    if (item.seed) {
      $("#chat-input").value = item.seed;
      $("#chat-input").focus();
    }
    return;
  }
  showToast(item.label);
}

function fillFocus(focus) {
  $("#focus-goal").value = focus.goal || "";
  $("#focus-keep").value = (focus.must_keep || []).join("\n");
  $("#focus-avoid").value = (focus.must_avoid || []).join("\n");
  $("#focus-notes").value = (focus.notes || []).join("\n");
}

function renderDocumentList(group) {
  const root = $("#document-list");
  root.replaceChildren();
  const allDocuments = state.workspace?.documents[group] || [];
  const isLibrary = libraryViews.includes(group);
  syncLibraryBrowser(group, allDocuments);
  const query = isLibrary ? state.library.query.trim().toLocaleLowerCase() : "";
  const category = isLibrary ? state.library.category : "all";
  const documents = allDocuments.filter((doc) => {
    if (category !== "all" && doc.category !== category) return false;
    if (!query) return true;
    return [doc.title, doc.subtitle, doc.category_label, doc.path]
      .some((value) => String(value || "").toLocaleLowerCase().includes(query));
  });
  $("#document-group-title").textContent = labels[group] || "最近章节";
  $("#document-count").textContent = isLibrary && documents.length !== allDocuments.length
    ? `${documents.length}/${allDocuments.length}`
    : String(documents.length);
  if (!documents.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = allDocuments.length ? "没有符合当前筛选的资料。" : emptyDocumentTip(group);
    root.append(empty);
    return;
  }
  let currentCategory = "";
  documents.forEach((doc) => {
    if (isLibrary && doc.category !== currentCategory) {
      currentCategory = doc.category;
      const heading = document.createElement("div");
      heading.className = "document-category-heading";
      heading.textContent = doc.category_label || doc.subtitle || "未分类";
      heading.setAttribute("role", "heading");
      heading.setAttribute("aria-level", "2");
      root.append(heading);
    }
    const button = document.createElement("button");
    button.className = "document-item";
    const activePath = state.library.editorMode === "asset"
      ? state.assets.draft?.path
      : state.document?.path;
    button.classList.toggle("active", activePath === doc.path);
    button.type = "button";
    button.setAttribute("role", "listitem");
    const title = document.createElement("strong");
    title.textContent = doc.title;
    const subtitle = document.createElement("span");
    subtitle.textContent = doc.structured ? "字段 + 原文" : (doc.subtitle || doc.path);
    button.append(title, subtitle);
    button.addEventListener("click", () => {
      if (doc.structured && doc.asset_kind && doc.asset_id) {
        openStructuredAsset(doc, true);
      } else {
        openDocument(doc.path, true);
      }
    });
    root.append(button);
  });
}

function syncLibraryBrowser(group, documents) {
  const isLibrary = libraryViews.includes(group);
  $("#library-browser-tools").hidden = !isLibrary;
  if (!isLibrary) return;
  $("#library-filter").value = state.library.query;
  const categories = [];
  const seen = new Set();
  documents.forEach((doc) => {
    if (!doc.category || seen.has(doc.category)) return;
    seen.add(doc.category);
    categories.push([doc.category, doc.category_label || doc.subtitle || doc.category]);
  });
  if (state.library.category !== "all" && !seen.has(state.library.category)) {
    state.library.category = "all";
  }
  const select = $("#library-category-filter");
  select.replaceChildren(new Option("全部子分类", "all"));
  categories.forEach(([value, label]) => select.append(new Option(label, value)));
  select.value = state.library.category;
}

function syncLibraryActions(view) {
  const create = $("#asset-create");
  const kind = $("#library-create-kind");
  const options = view === "characters"
    ? [["character", "角色"]]
    : view === "settings"
      ? [["world", "设定条目"], ["progression", "成长体系"]]
      : [];
  kind.replaceChildren(...options.map(([value, label]) => new Option(label, value)));
  kind.hidden = !options.length;
  create.hidden = !options.length;
  $("#asset-package-export").disabled = state.library.editorMode !== "asset" || !state.assets.selected?.id;
}

function openProjectPath(path, pushHistory = true) {
  for (const scope of libraryViews) {
    const summary = (state.workspace?.documents?.[scope] || []).find((item) => item.path === path);
    if (!summary) continue;
    if (summary.structured && summary.asset_kind && summary.asset_id) {
      return openStructuredAsset(summary, pushHistory);
    }
    break;
  }
  return openDocument(path, pushHistory);
}

function navSection(view) {
  if (libraryViews.includes(normalizeView(view))) return "library";
  if (view === "agents") return "agents";
  return view;
}

function normalizeView(view) {
  return legacyLibraryViews[view] || view;
}

function documentListGroupForView(view) {
  const normalized = normalizeView(view);
  if (normalized === "outline") return "outline";
  return ["chapters", ...libraryViews].includes(normalized) ? normalized : "chapters";
}

function syncNavigationState(view = state.view) {
  view = normalizeView(view);
  const section = navSection(view);
  $$(".nav-item").forEach((item) => {
    const itemSection = item.dataset.navSection || item.dataset.view || "";
    item.classList.toggle("active", itemSection === section);
  });
  $$('[data-library-view]').forEach((button) => {
    const active = button.dataset.libraryView === view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#library-navigation").hidden = !libraryViews.includes(view);
  syncLibraryActions(view);
}

function setView(view, pushHistory = true) {
  view = normalizeView(view);
  if (!state.workspace) return;
  const previousView = state.view;
  if (view !== state.view && state.dirty && !window.confirm("当前文档尚未保存，仍要离开吗？")) return;
  if (view !== state.view && state.assets.dirty && !window.confirm("当前资料尚未保存，仍要离开吗？")) return;
  if (view !== state.view) {
    state.dirty = false;
    state.assets.dirty = false;
    state.library.category = "all";
  }
  state.view = view;
  if (view === "outline" && previousView !== "outline" && !state.inspectorCollapsed) {
    state.outlineInspectorAutoCollapsed = true;
    toggleInspectorCollapsed(true, { persist: false });
  } else if (view !== "outline" && previousView === "outline" && state.outlineInspectorAutoCollapsed) {
    state.outlineInspectorAutoCollapsed = false;
    toggleInspectorCollapsed(false, { persist: false });
  }
  syncNavigationState(view);
  const toolsNav = $(".nav-tools");
  if (toolsNav && ["continuity", "research", "search", "transfer", "deconstruct", "skills", "tools"].includes(view)) toolsNav.open = true;
  const dashboard = view === "dashboard";
  const outlineView = view === "outline";
  const reviewView = view === "review";
  const researchView = view === "research";
  const documentView = ["chapters", ...libraryViews].includes(view);
  $("#dashboard-view").hidden = !dashboard;
  $("#editor-view").hidden = !documentView;
  $("#outline-view").hidden = !outlineView;
  $("#review-workspace-view").hidden = !reviewView;
  $("#research-view").hidden = !researchView;
  $("#search-view").hidden = view !== "search";
  $("#agents-view").hidden = view !== "agents";
  $("#continuity-view").hidden = view !== "continuity";
  $("#transfer-view").hidden = view !== "transfer";
  $("#deconstruct-view").hidden = view !== "deconstruct";
  $("#skills-view").hidden = view !== "skills";
  $("#tools-view").hidden = view !== "tools";
  renderDocumentList(documentListGroupForView(view));
  const activePath = state.library.editorMode === "asset"
    ? state.assets.draft?.path
    : state.document?.path;
  const activeGroup = activePath
    ? documentGroup(activePath)
    : (state.library.editorMode === "asset" ? kindLibraryView(state.assets.kind) : "");
  if (documentView && activeGroup !== view) {
    const first = state.workspace.documents[view]?.[0];
    if (first?.structured && first.asset_kind && first.asset_id) {
      openStructuredAsset(first, false);
    } else if (first) {
      openDocument(first.path, false);
    } else {
      showEmptyEditor(view);
    }
  }
  if (outlineView) loadOutline();
  if (view === "agents") loadAgentSurface(state.agent);
  if (view === "continuity") loadContinuity();
  if (researchView) loadResearch();
  if (reviewView) renderReviewWorkspace();
  updateRoutedModelIndicator();
  toggleMobileNavigation(false);
  if (pushHistory) {
    const debugQuery = productTourDebugMode() ? "?debug=onboarding" : "";
    history.pushState(
      { view },
      "",
      dashboard ? `/${debugQuery}` : `/${debugQuery}#${encodeURIComponent(view)}`,
    );
  }
}

async function openDocument(path, pushHistory) {
  if (state.dirty && !window.confirm("当前文档尚未保存，仍要离开吗？")) return;
  if (state.assets.dirty && !window.confirm("当前资料尚未保存，仍要离开吗？")) return;
  clearTimeout(state.autoSaveTimer);
  state.autoSaveTimer = null;
  try {
    const doc = await api(`/api/document?path=${encodeURIComponent(path)}`);
    state.document = doc;
    state.dirty = false;
    state.assets.selected = null;
    state.assets.draft = null;
    state.assets.dirty = false;
    state.library.editorMode = "document";
    const group = libraryViews.includes(doc.scope) ? doc.scope : documentGroup(path);
    state.view = group;
    syncNavigationState(group);
    $("#dashboard-view").hidden = true;
    $("#editor-view").hidden = false;
    $("#outline-view").hidden = true;
    $("#review-workspace-view").hidden = true;
    $("#research-view").hidden = true;
    $("#search-view").hidden = true;
    $("#agents-view").hidden = true;
    $("#continuity-view").hidden = true;
    $("#transfer-view").hidden = true;
    $("#deconstruct-view").hidden = true;
    $("#skills-view").hidden = true;
    $("#tools-view").hidden = true;
    showDocumentEditor();
    $("#editor-path").textContent = doc.path;
    $("#editor-title").value = doc.title;
    const editor = getPrimaryMarkdownEditor();
    await editor.setDisabled(false);
    await editor.setValue(doc.content);
    const reviewProfileId = state.workspace.model_profiles?.routes?.review
      || state.workspace.model_profiles?.default_profile_id;
    const reviewProfile = state.workspace.model_profiles?.profiles?.find((profile) =>
      profile.id === reviewProfileId
    );
    $("#review-document").hidden = group !== "chapters" || !reviewProfile?.configured;
    syncRevisionControls();
    syncChapterDeleteControl();
    $("#outline-tree-back").hidden = group !== "outline";
    updateEditorCount();
    await loadEditorTarget(path);
    setSaveState("已保存", false);
    $("#editor-autosave-state").textContent = "即时渲染 · 自动保存已开启";
    renderDocumentList(group);
    if (pushHistory) {
      const debugQuery = productTourDebugMode() ? "?debug=onboarding" : "";
      history.pushState({ path }, "", `/${debugQuery}#doc=${encodeURIComponent(path)}`);
    }
    await editor.focus();
    updateRoutedModelIndicator();
    renderInspectorContext();
  } catch (error) {
    showToast(error.message, true);
  }
}

function activateStructuredAssetEditor(asset, options = {}) {
  const group = normalizeView(options.scope || kindLibraryView(asset.kind));
  state.view = group;
  state.document = null;
  state.dirty = false;
  state.library.editorMode = "asset";
  syncNavigationState(group);
  $("#dashboard-view").hidden = true;
  $("#editor-view").hidden = false;
  $("#outline-view").hidden = true;
  $("#review-workspace-view").hidden = true;
  $("#research-view").hidden = true;
  $("#search-view").hidden = true;
  $("#agents-view").hidden = true;
  $("#continuity-view").hidden = true;
  $("#transfer-view").hidden = true;
  $("#deconstruct-view").hidden = true;
  $("#skills-view").hidden = true;
  $("#tools-view").hidden = true;
  $("#document-editor-pane").hidden = true;
  $("#asset-editor-pane").hidden = false;
  $("#document-editor-actions").hidden = true;
  $("#editor-commandbar").hidden = true;
  $("#editor-find-panel").hidden = true;
  $("#editor-path").textContent = asset.path || "尚未保存";
  $("#editor-title").value = asset.isNew
    ? `新建${asset.kind === "character" ? "角色" : "设定"}`
    : (asset.name || asset.id);
  renderDocumentList(group);
  syncLibraryActions(group);
  if (options.pushHistory) {
    const debugQuery = productTourDebugMode() ? "?debug=onboarding" : "";
    const hash = asset.id
      ? `asset=${encodeURIComponent(asset.kind)}:${encodeURIComponent(asset.id)}`
      : group;
    history.pushState(
      { assetKind: asset.kind, assetId: asset.id || "" },
      "",
      `/${debugQuery}#${hash}`,
    );
  }
  $("#asset-form").querySelector("input, textarea, select")?.focus();
  updateRoutedModelIndicator();
  renderInspectorContext();
}

function showDocumentEditor() {
  $("#document-editor-pane").hidden = false;
  $("#asset-editor-pane").hidden = true;
  $("#document-editor-actions").hidden = false;
  $("#editor-commandbar").hidden = false;
}

function showEmptyEditor(group) {
  state.library.editorMode = "document";
  state.document = null;
  showDocumentEditor();
  $("#editor-path").textContent = "";
  $("#editor-title").value = labels[group] || "资料库";
  const editor = getPrimaryMarkdownEditor();
  editor.setValue(emptyDocumentTip(group));
  editor.setDisabled(true);
  $("#save-document").disabled = true;
  $("#review-document").hidden = true;
  syncChapterDeleteControl();
}

function kindLibraryView(kind) {
  return kind === "character" ? "characters" : "settings";
}

async function loadOutline(chapterId = "") {
  try {
    const suffix = chapterId ? `?chapter=${encodeURIComponent(chapterId)}` : "";
    state.outline = await api(`/api/outline${suffix}`);
    const expansionKey = [
      state.workspace?.project?.root || "",
      state.workspace?.snapshot?.novel_id || "",
    ].join(":");
    if (state.outlineExpansionKey !== expansionKey) {
      state.outlineExpansionKey = expansionKey;
      state.outlineExpandedIds = new Set();
      state.outlineExpansionInitialized = false;
      state.outlineSelectedId = null;
      state.outlineQuery = "";
      state.outlineStatusFilter = "all";
      state.outlineMobilePane = "tree";
    }
    if (chapterId) state.outlineSelectedId = chapterId;
    const nodeIds = new Set(flattenOutline(state.outline.roots || []).map((node) => node.id));
    if (state.outlineSelectedId && !nodeIds.has(state.outlineSelectedId)) state.outlineSelectedId = null;
    const currentChapterId = state.workspace?.snapshot?.current_chapter || "";
    if (!state.outlineSelectedId) {
      state.outlineSelectedId = state.outline.recommendation?.chapter_id
        || (nodeIds.has(currentChapterId) ? currentChapterId : "")
        || state.outline.roots[0]?.id
        || null;
    }
    initializeOutlineExpansion();
    revealOutlineNode(state.outlineSelectedId);
    renderOutline();
  } catch (error) {
    showToast(error.message, true);
  }
}

function flattenOutline(nodes, result = []) {
  nodes.forEach((node) => {
    result.push(node);
    flattenOutline(node.children || [], result);
  });
  return result;
}

function outlineNodePathIds(nodes, targetId, ancestors = []) {
  for (const node of nodes) {
    if (node.id === targetId) return ancestors;
    const path = outlineNodePathIds(node.children || [], targetId, [...ancestors, node.id]);
    if (path) return path;
  }
  return null;
}

function revealOutlineNode(nodeId, includeNode = false) {
  if (!nodeId || !state.outline) return;
  const path = outlineNodePathIds(state.outline.roots || [], nodeId);
  (path || []).forEach((id) => state.outlineExpandedIds.add(id));
  const node = outlineNodeById(nodeId);
  if (includeNode && node?.children?.length) state.outlineExpandedIds.add(node.id);
}

function initializeOutlineExpansion() {
  if (state.outlineExpansionInitialized || !state.outline) return;
  state.outlineExpansionInitialized = true;
  const targetId = state.outline.recommendation?.chapter_id
    || state.workspace?.snapshot?.current_chapter
    || state.outlineSelectedId;
  revealOutlineNode(targetId, true);
}

function outlineIcon(symbolId) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${symbolId}`);
  svg.append(use);
  return svg;
}

function renderOutline() {
  const outline = state.outline;
  if (!outline) return;
  const counts = outline.counts || {};
  const stats = $("#outline-stats");
  stats.replaceChildren();
  [
    [counts.volume || 0, "卷"],
    [counts.act || 0, "幕"],
    [counts.section || 0, "节"],
    [counts.chapter || 0, "章"],
    [outline.drafted_chapters || 0, "已写"],
  ].forEach(([value, label]) => {
    const item = document.createElement("span");
    const number = document.createElement("strong");
    number.textContent = String(value);
    item.append(number, document.createTextNode(label));
    stats.append(item);
  });
  if (state.outlineRenamingId && !outlineNodeById(state.outlineRenamingId)) {
    state.outlineRenamingId = null;
  }
  renderOutlineTree();
  renderOutlineDetail();
  syncOutlineMobilePane();
  const smart = $("#outline-smart-create");
  smart.disabled = !outline.recommendation || !state.workspace.model.configured;
  smart.title = state.workspace.model.configured ? "" : "请先配置模型";
}

function outlineNodeDirectMatch(node) {
  const query = state.outlineQuery.trim().toLocaleLowerCase();
  const status = state.outlineStatusFilter;
  const queryMatch = !query || [node.title, node.id, node.label, ...(node.path || [])]
    .join(" ")
    .toLocaleLowerCase()
    .includes(query);
  const statusMatch = status === "all" || (node.kind === "chapter" && node.status === status);
  return queryMatch && statusMatch;
}

function outlineNodeVisible(node) {
  return outlineNodeDirectMatch(node)
    || (node.children || []).some((child) => outlineNodeVisible(child));
}

function renderOutlineTree() {
  const outline = state.outline;
  if (!outline) return;
  const roots = (outline.roots || []).filter((node) => outlineNodeVisible(node));
  const filtered = Boolean(state.outlineQuery.trim()) || state.outlineStatusFilter !== "all";
  const visibleCount = flattenOutline(roots).filter((node) => outlineNodeVisible(node)).length;
  const totalCount = flattenOutline(outline.roots || []).length;
  $("#outline-tree-count").textContent = filtered ? `${visibleCount}/${totalCount}` : String(totalCount);
  $("#outline-filter-status").textContent = filtered
    ? (visibleCount ? `显示 ${visibleCount} 个节点` : "没有匹配节点")
    : "";
  $("#outline-search").value = state.outlineQuery;
  $$("[data-outline-status]").forEach((button) => {
    const active = button.dataset.outlineStatus === state.outlineStatusFilter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const root = $("#outline-tree");
  root.replaceChildren();
  roots.forEach((node) => root.append(buildOutlineTreeItem(node, filtered)));
  if (!roots.length) {
    const empty = document.createElement("li");
    empty.className = "outline-tree-empty";
    empty.textContent = "没有匹配节点";
    root.append(empty);
  }
}

function buildOutlineTreeItem(node, filtered = false) {
  const item = document.createElement("li");
  item.className = `outline-tree-item kind-${node.kind}`;
  item.setAttribute("role", "treeitem");
  item.dataset.nodeId = node.id;
  const row = document.createElement("div");
  row.className = "outline-tree-row";
  const children = (node.children || []).filter((child) => outlineNodeVisible(child));
  const group = document.createElement("ul");
  group.setAttribute("role", "group");
  const expanded = filtered || state.outlineExpandedIds.has(node.id);
  if (children.length) {
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "outline-tree-toggle";
    toggle.setAttribute("aria-label", `${expanded ? "收起" : "展开"}${node.title}`);
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.append(outlineIcon("icon-chevron-right"));
    group.hidden = !expanded;
    toggle.addEventListener("click", () => {
      const next = toggle.getAttribute("aria-expanded") !== "true";
      if (next) state.outlineExpandedIds.add(node.id);
      else state.outlineExpandedIds.delete(node.id);
      toggle.setAttribute("aria-expanded", String(next));
      toggle.setAttribute("aria-label", `${next ? "收起" : "展开"}${node.title}`);
      group.hidden = !next;
    });
    row.append(toggle);
  } else {
    const spacer = document.createElement("span"); spacer.className = "outline-tree-spacer"; row.append(spacer);
  }
  const inlineEditing = state.outlineRenamingId === node.id;
  const nodeControl = inlineEditing ? document.createElement("div") : document.createElement("button");
  if (!inlineEditing) nodeControl.type = "button";
  nodeControl.className = `outline-tree-node${inlineEditing ? " editing" : ""}`;
  nodeControl.setAttribute("aria-current", String(node.id === state.outlineSelectedId));
  const badge = document.createElement("span"); badge.className = "outline-kind-badge"; badge.textContent = node.label;
  if (inlineEditing) {
    const input = document.createElement("input");
    input.className = "outline-tree-title-input";
    input.value = node.title;
    input.setAttribute("aria-label", `修改${node.title}`);
    nodeControl.append(badge, input);
    let handled = false;
    const finish = (commit) => {
      if (handled) return;
      handled = true;
      finishOutlineInlineRename(node.id, input.value, commit);
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        finish(true);
      } else if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      }
    });
    input.addEventListener("blur", () => finish(true));
    window.requestAnimationFrame(() => {
      input.focus();
      input.select();
    });
  } else {
    const title = document.createElement("span"); title.className = "outline-tree-title"; title.textContent = node.title;
    nodeControl.append(badge, title);
    if (node.kind === "chapter") {
      const drafted = node.status === "drafted";
      const status = document.createElement("span");
      status.className = `outline-chapter-status ${node.status}`;
      status.setAttribute("aria-label", drafted ? "已有正文" : "尚未写作");
      status.title = drafted ? "已有正文" : "尚未写作";
      if (drafted) status.append(outlineIcon("icon-check"));
      nodeControl.append(status);
    }
    nodeControl.title = node.editable ? `${node.title} · 双击修改标题` : node.title;
    nodeControl.addEventListener("mousedown", (event) => {
      if (event.detail >= 2) {
        event.preventDefault();
        startOutlineInlineRename(node);
      }
    });
    nodeControl.addEventListener("click", async () => {
      state.outlineSelectedId = node.id;
      revealOutlineNode(node.id, true);
      if (window.matchMedia("(max-width: 820px)").matches) state.outlineMobilePane = "detail";
      if (node.kind === "chapter") await loadOutline(node.id); else renderOutline();
    });
    nodeControl.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      startOutlineInlineRename(node);
    });
    nodeControl.addEventListener("keydown", (event) => {
      if (event.key === "F2") {
        event.preventDefault();
        startOutlineInlineRename(node);
      }
    });
  }
  row.append(nodeControl);
  if (node.editable) {
    const actions = document.createElement("span");
    actions.className = "outline-row-actions";
    if (node.child_kind) {
      const add = document.createElement("button");
      add.type = "button";
      add.className = "outline-row-action";
      const addMark = document.createElement("span");
      addMark.setAttribute("aria-hidden", "true");
      addMark.textContent = "+";
      add.append(addMark);
      add.setAttribute("aria-label", `在${node.title}下新增${outlineKindLabel(node.child_kind)}`);
      add.title = `新增${outlineKindLabel(node.child_kind)}`;
      add.addEventListener("click", () => openOutlineEditDialog("add_child", node));
      actions.append(add);
    }
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "outline-row-action";
    rename.append(outlineIcon("icon-pen"));
    rename.setAttribute("aria-label", `修改${node.title}`);
    rename.title = "改名";
    rename.addEventListener("click", () => startOutlineInlineRename(node));
    actions.append(rename);
    row.append(actions);
  }
  item.append(row);
  children.forEach((child) => group.append(buildOutlineTreeItem(child, filtered)));
  if (children.length) item.append(group);
  return item;
}

function setAllOutlineExpanded(expanded) {
  if (!state.outline) return;
  state.outlineExpandedIds = expanded
    ? new Set(flattenOutline(state.outline.roots || [])
      .filter((node) => (node.children || []).length)
      .map((node) => node.id))
    : new Set();
  renderOutlineTree();
}

function setOutlineMobilePane(pane) {
  state.outlineMobilePane = pane === "detail" ? "detail" : "tree";
  syncOutlineMobilePane();
}

function syncOutlineMobilePane() {
  const pane = state.outlineMobilePane === "detail" ? "detail" : "tree";
  $(".outline-workspace").dataset.mobilePane = pane;
  $$("[data-outline-pane]").forEach((button) => {
    const active = button.dataset.outlinePane === pane;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

function renderOutlineDetail() {
  const nodes = flattenOutline(state.outline?.roots || []);
  const node = nodes.find((item) => item.id === state.outlineSelectedId);
  const title = $("#outline-detail-title");
  title.textContent = node?.title || "选择一个节点";
  title.contentEditable = String(Boolean(node?.editable));
  title.classList.toggle("editable", Boolean(node?.editable));
  title.dataset.nodeId = node?.id || "";
  title.dataset.originalTitle = node?.title || "";
  renderOutlineBreadcrumb(node);
  const meta = $("#outline-node-meta");
  meta.replaceChildren();
  if (node) {
    const kind = document.createElement("span");
    kind.className = `outline-meta-kind kind-${node.kind}`;
    kind.textContent = node.label;
    const id = document.createElement("code");
    id.textContent = node.id;
    const line = document.createElement("span");
    line.textContent = `第 ${node.line} 行`;
    meta.append(kind, id, line);
    if (node.kind === "chapter") {
      const status = document.createElement("span");
      status.className = `outline-meta-status ${node.status}`;
      status.textContent = node.status === "drafted" ? "已有正文" : "待写";
      meta.append(status);
    }
    if (node.detail_target_words) {
      const detailTarget = document.createElement("span");
      detailTarget.textContent = `大纲 ${formatNumber(node.content_units || 0)} / ${formatNumber(node.detail_target_words)} 字`;
      meta.append(detailTarget);
    }
    if (node.kind === "chapter" && node.chapter_target_words) {
      const bodyTarget = document.createElement("span");
      bodyTarget.textContent = `正文目标 ${formatNumber(node.chapter_target_words)} 字`;
      meta.append(bodyTarget);
    }
  }
  renderOutlineSummaryEditor(node);
  $("#outline-node-source").disabled = !node;
  $("#outline-node-rename").disabled = !node?.editable;
  $("#outline-node-add-child").disabled = !node?.child_kind;
  $("#outline-node-add-child").textContent = node?.child_kind ? `新增${outlineKindLabel(node.child_kind)}` : "新增下级";
  $("#outline-node-add-after").disabled = !node?.editable;
  $("#outline-node-add-after").textContent = node?.editable ? `新增同级${node.label}` : "新增同级";
  $("#outline-node-delete").disabled = !node?.can_delete;
  $("#outline-node-delete").title = node?.editable && !node?.can_delete ? (node.delete_blocked_reason || "该节点不能安全删除") : "";
  const create = $("#outline-node-create");
  create.disabled = !node || node.kind !== "chapter" || (node.status !== "drafted" && !state.workspace.model.configured);
  create.textContent = node?.status === "drafted" ? "打开已写正文" : "用此章创建正文";
}

function renderOutlineBreadcrumb(node) {
  const root = $("#outline-breadcrumb");
  root.replaceChildren();
  if (!node) {
    root.textContent = "选择一个节点";
    return;
  }
  const pathIds = [...(outlineNodePathIds(state.outline?.roots || [], node.id) || []), node.id];
  pathIds.forEach((nodeId, index) => {
    const pathNode = outlineNodeById(nodeId);
    if (!pathNode) return;
    if (index) {
      const separator = document.createElement("span");
      separator.setAttribute("aria-hidden", "true");
      separator.textContent = "/";
      root.append(separator);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = pathNode.title;
    button.setAttribute("aria-current", pathNode.id === node.id ? "page" : "false");
    button.addEventListener("click", async () => {
      state.outlineSelectedId = pathNode.id;
      revealOutlineNode(pathNode.id, true);
      if (pathNode.kind === "chapter") await loadOutline(pathNode.id); else renderOutline();
    });
    root.append(button);
  });
}

function renderOutlineSummaryEditor(node) {
  const root = $("#outline-node-summary");
  destroyMarkdownEditorsWithin(root);
  root.replaceChildren();
  if (!node) {
    root.textContent = "选择一个节点后查看或修改内容。";
    return;
  }
  if (!node.editable) {
    root.textContent = node.summary || "这个节点尚未填写摘要。";
    return;
  }
  const editorHost = document.createElement("div");
  editorHost.className = "outline-summary-editor";
  editorHost.setAttribute("aria-label", `修改${node.title}的内容`);
  const originalValue = node.content || "";
  const actions = document.createElement("div");
  actions.className = "outline-summary-actions";
  const status = document.createElement("span");
  status.textContent = "已保存";
  status.setAttribute("role", "status");
  const save = document.createElement("button");
  save.type = "button";
  save.className = "quiet-button";
  save.textContent = "保存内容";
  save.disabled = true;
  let editor;
  const syncState = (value = editor?.getValue() || originalValue) => {
    const changed = value !== originalValue;
    save.disabled = !changed;
    status.textContent = changed ? "未保存" : "已保存";
  };
  editor = mountMarkdownEditor(editorHost, {
    value: originalValue,
    compact: true,
    minHeight: 210,
    placeholder: "这个节点尚未填写内容。",
    onInput: (value) => syncState(value),
    onKeydown: (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        event.stopPropagation();
        submitOutlineSummary(node.id, editor, originalValue, status, save);
      } else if (event.key === "Escape") {
        event.preventDefault();
        editor.setValue(originalValue).then(() => syncState(originalValue));
      }
    },
  });
  save.addEventListener("click", () => submitOutlineSummary(node.id, editor, originalValue, status, save));
  actions.append(status, save);
  root.append(editorHost, actions);
}

async function submitOutlineSummary(nodeId, editor, originalValue, status, save) {
  const value = editor.getValue();
  if (!outlineNodeById(nodeId) || value === originalValue) return;
  await editor.setDisabled(true);
  save.disabled = true;
  status.textContent = "正在保存…";
  try {
    await commitOutlineEdit({
      operation: "update_summary",
      node_id: nodeId,
      summary: value,
    }, { selectNodeId: nodeId });
  } catch (error) {
    status.textContent = error.message;
    showToast(error.message, true);
    if (error.status === 409) {
      await loadOutline();
    } else {
      await editor.setDisabled(false);
      save.disabled = false;
    }
  }
}

function handleOutlineDetailTitleKeydown(event) {
  if (event.key === "Enter") {
    event.preventDefault();
    event.currentTarget.blur();
  } else if (event.key === "Escape") {
    event.preventDefault();
    event.currentTarget.textContent = event.currentTarget.dataset.originalTitle || "";
    event.currentTarget.blur();
  }
}

function handleOutlineDetailTitlePaste(event) {
  if (!event.currentTarget.isContentEditable) return;
  event.preventDefault();
  const text = event.clipboardData?.getData("text/plain") || "";
  document.execCommand("insertText", false, text.replace(/\s*\n\s*/g, " "));
}

async function submitOutlineDetailTitle(event) {
  const target = event.currentTarget;
  const nodeId = target.dataset.nodeId || "";
  const node = outlineNodeById(nodeId);
  const title = target.textContent.trim();
  if (!node?.editable || !title || title === target.dataset.originalTitle) {
    target.textContent = target.dataset.originalTitle || target.textContent;
    return;
  }
  target.contentEditable = "false";
  try {
    await commitOutlineEdit({
      operation: "rename",
      node_id: nodeId,
      kind: node.kind,
      title,
    }, { selectNodeId: nodeId });
  } catch (error) {
    showToast(error.message, true);
    target.textContent = target.dataset.originalTitle || node.title;
    if (error.status === 409) await loadOutline(); else renderOutlineDetail();
  }
}

function selectedOutlineNode() {
  return flattenOutline(state.outline?.roots || []).find((node) => node.id === state.outlineSelectedId);
}

function outlineNodeById(nodeId) {
  return flattenOutline(state.outline?.roots || []).find((node) => node.id === nodeId);
}

function startOutlineInlineRename(node) {
  if (!node?.editable) return;
  state.outlineRenamingId = node.id;
  state.outlineSelectedId = node.id;
  renderOutline();
}

async function finishOutlineInlineRename(nodeId, value, commit) {
  const node = outlineNodeById(nodeId);
  state.outlineRenamingId = null;
  const title = String(value || "").trim();
  if (!commit || !node || title === node.title) {
    renderOutline();
    return;
  }
  try {
    await commitOutlineEdit({
      operation: "rename",
      node_id: nodeId,
      kind: node.kind,
      title,
    }, { selectNodeId: nodeId });
  } catch (error) {
    showToast(error.message, true);
    if (error.status === 409) await loadOutline(); else renderOutline();
  }
}

function outlineKindLabel(kind) {
  return { volume: "卷", act: "幕", section: "节", chapter: "章" }[kind] || "节点";
}

function suggestedOutlineTitle(kind) {
  const nodes = flattenOutline(state.outline?.roots || []);
  if (kind === "chapter") {
    const numbers = nodes
      .filter((node) => node.kind === "chapter")
      .map((node) => Number(String(node.id).match(/\d+/)?.[0] || 0));
    return `第${Math.max(0, ...numbers) + 1}章：新章节`;
  }
  const count = nodes.filter((node) => node.kind === kind).length + 1;
  return `第${count}${outlineKindLabel(kind)}：新${outlineKindLabel(kind)}`;
}

function openOutlineEditDialog(operation, node = null) {
  const dialog = $("#outline-edit-dialog");
  const titleField = $("#outline-edit-title-field");
  const submit = $("#outline-edit-submit");
  let kind = node?.kind || "volume";
  let heading = "编辑大纲节点";
  let context = "";
  let value = node?.title || "";
  let help = "修改会增量写回 src/outline.md，并自动建立 Git 存档。";
  const impact = $("#outline-edit-impact");
  impact.replaceChildren();
  impact.hidden = true;
  if (operation === "add_child") {
    kind = node?.child_kind || "volume";
    heading = `新增${outlineKindLabel(kind)}`;
    context = node ? `添加到“${node.title}”下面。` : "添加到大纲根节点。";
    value = suggestedOutlineTitle(kind);
  } else if (operation === "add_after") {
    heading = `新增同级${outlineKindLabel(kind)}`;
    context = `添加在“${node?.title || "当前节点"}”之后。`;
    value = suggestedOutlineTitle(kind);
  } else if (operation === "rename") {
    heading = `修改${node?.label || "节点"}标题`;
    context = `只修改“${node?.title || ""}”这一行，不重写其他大纲内容。`;
    if (node?.kind === "chapter" && node?.status === "drafted") {
      help = "该章已有正文：可以修改标题文字，但不能更换章节编号。";
    }
  } else if (operation === "delete") {
    heading = `删除${node?.label || "节点"}`;
    const count = node?.delete_renumber_count || 0;
    context = `将删除“${node?.title || ""}”及其 ${node?.descendant_count || 0} 个下级节点，并让 ${count} 个后续节点连续补位。`;
    const impactTitle = document.createElement("strong");
    impactTitle.textContent = count ? `编号影响 · ${count} 项` : "编号影响 · 无后续补位";
    impact.append(impactTitle);
    const preview = node?.delete_renumber_preview || [];
    if (preview.length) {
      const list = document.createElement("ul");
      preview.forEach((change) => {
        const item = document.createElement("li");
        item.textContent = `${change.old_title} → ${change.new_title}`;
        list.append(item);
      });
      impact.append(list);
      if (count > preview.length) {
        const rest = document.createElement("span");
        rest.textContent = `另有 ${count - preview.length} 项将在同一次保存中补位。`;
        impact.append(rest);
      }
    }
    if (node?.delete_renumber_skipped) {
      const skipped = document.createElement("span");
      skipped.textContent = `${node.delete_renumber_skipped} 个无编号标题将保持不变。`;
      impact.append(skipped);
    }
    impact.hidden = false;
    help = "删除、连续重编号与 Git 存档会原子完成；若影响已有正文的章节号，系统会阻止操作。";
  }
  $("#outline-edit-operation").value = operation;
  $("#outline-edit-node-id").value = node?.id || "";
  $("#outline-edit-kind").value = kind;
  $("#outline-edit-title").textContent = heading;
  $("#outline-edit-context").textContent = context;
  $("#outline-edit-name").value = value;
  $("#outline-edit-help").textContent = help;
  $("#outline-edit-progress").textContent = "";
  titleField.hidden = operation === "delete";
  $("#outline-edit-help").hidden = false;
  $("#outline-edit-name").required = operation !== "delete";
  submit.textContent = operation === "delete" ? "确认删除" : "保存修改";
  submit.className = operation === "delete" ? "danger-button" : "primary-button";
  submit.disabled = false;
  dialog.showModal();
  if (operation !== "delete") $("#outline-edit-name").select();
}

async function commitOutlineEdit(edit, options = {}) {
  const payload = await api("/api/outline/edit", {
    method: "POST",
    body: JSON.stringify({
      ...edit,
      revision: state.outline?.revision || "",
    }),
  });
  state.outline = payload.outline;
  state.outlineSelectedId = payload.selected_node_id || options.selectNodeId || state.outline.recommendation?.chapter_id || null;
  revealOutlineNode(state.outlineSelectedId, true);
  renderOutline();
  showToast(payload.message || "大纲已更新");
  await loadWorkspace();
  return payload;
}

async function submitOutlineEdit(event) {
  event.preventDefault();
  const submit = $("#outline-edit-submit");
  const progress = $("#outline-edit-progress");
  submit.disabled = true;
  let blockedByConflict = false;
  progress.textContent = "正在安全写入大纲…";
  try {
    await commitOutlineEdit({
      operation: $("#outline-edit-operation").value,
      node_id: $("#outline-edit-node-id").value,
      kind: $("#outline-edit-kind").value,
      title: $("#outline-edit-name").value,
    });
    $("#outline-edit-dialog").close();
  } catch (error) {
    progress.textContent = error.message;
    if (error.status === 409) {
      await loadOutline();
      progress.textContent = "大纲已刷新。请关闭窗口并重新选择节点，避免把旧操作应用到新结构。";
      blockedByConflict = true;
    }
  } finally {
    submit.disabled = blockedByConflict;
  }
}

function openOutlineSource(line = 1) {
  openDocument("src/outline.md", true).then(async () => {
    const editor = getPrimaryMarkdownEditor();
    const lines = editor.getValue().split("\n");
    const cursor = lines.slice(0, Math.max(0, line - 1)).join("\n").length;
    await editor.selectRange(cursor, cursor);
  });
}

async function openSmartWriteDialog(chapterId = "") {
  if (!state.outline || chapterId) await loadOutline(chapterId);
  const recommendation = state.outline?.recommendation;
  if (!recommendation) { showToast("大纲里没有可创建的章纲", true); return; }
  if (recommendation.status === "drafted") {
    const doc = state.workspace.documents.chapters.find((item) => item.path.endsWith(`/${recommendation.chapter_id}.md`));
    if (doc) await openDocument(doc.path, true); else showToast("章节正文记录不存在", true);
    return;
  }
  if (!state.workspace.model.configured) { showToast("请先配置模型", true); return; }
  $("#write-chapter-id").textContent = recommendation.chapter_id;
  $("#write-chapter-title").textContent = recommendation.title;
  $("#write-breadcrumb").textContent = recommendation.breadcrumb.join(" / ");
  $("#write-outline-revision").value = state.outline.revision;
  $("#write-guidance").value = recommendation.guidance;
  $("#write-words").value = String(recommendation.target_words);
  $("#write-dialog").showModal();
}

function documentGroup(path) {
  if (path === "src/outline.md") return "outline";
  if (path.startsWith("data/manuscript/")) return "chapters";
  if (path.startsWith("data/world/") || path.startsWith("data/foreshadowing/")) return "continuity";
  if (path.startsWith("src/characters/")) return "characters";
  if (path.startsWith("src/world/") || path.startsWith("src/progression/")) return "settings";
  return "core";
}

function updateEditorCount() {
  const value = getPrimaryMarkdownEditor().getValue();
  const count = countWritingUnits(value);
  $("#editor-word-count").textContent = `${formatNumber(count)} 字`;
  const target = Number(state.editorTargetWords || 0);
  const targetLabel = $("#editor-target-count");
  const progress = $("#editor-chapter-progress");
  const isChapter = documentGroup(state.document?.path || "") === "chapters";
  targetLabel.hidden = !isChapter || !target;
  progress.hidden = !isChapter || !target;
  if (isChapter && target) {
    const percent = Math.min(999, Math.round((count / target) * 100));
    targetLabel.textContent = `目标 ${formatNumber(target)}`;
    progress.textContent = `${formatNumber(count)} / ${formatNumber(target)} 字 · ${percent}%`;
  }
  if (state.document) state.document.content = value;
  renderInspectorContext();
}

async function loadEditorTarget(path) {
  state.editorTargetWords = 0;
  updateEditorCount();
  if (documentGroup(path) !== "chapters") return;
  const chapterId = path.split("/").pop()?.replace(/\.md$/i, "") || "";
  if (!chapterId) return;
  try {
    const outline = await api(`/api/outline?chapter=${encodeURIComponent(chapterId)}`);
    if (state.document?.path !== path) return;
    state.editorTargetWords = Number(outline.recommendation?.target_words || 0);
    updateEditorCount();
  } catch (error) {
    if (state.document?.path === path) {
      $("#editor-chapter-progress").hidden = true;
    }
  }
}

function scheduleAutoSave() {
  clearTimeout(state.autoSaveTimer);
  $("#editor-autosave-state").textContent = "等待自动保存";
  state.autoSaveTimer = setTimeout(() => {
    state.autoSaveTimer = null;
    saveDocument({ silent: true });
  }, 1400);
}

async function saveDocument(options = {}) {
  const silent = Boolean(options.silent);
  if (!state.document || !state.dirty || state.saving) return;
  clearTimeout(state.autoSaveTimer);
  state.autoSaveTimer = null;
  state.saving = true;
  const editor = getPrimaryMarkdownEditor();
  const contentAtStart = editor.getValue();
  setSaveState("保存中", true);
  $("#editor-autosave-state").textContent = "正在保存";
  try {
    const saved = await api("/api/document", {
      method: "PUT",
      body: JSON.stringify({
        path: state.document.path,
        content: contentAtStart,
        version: state.document.version,
      }),
    });
    state.document = saved;
    const changedDuringSave = editor.getValue() !== contentAtStart;
    state.dirty = changedDuringSave;
    if (changedDuringSave) {
      state.document.content = editor.getValue();
      setSaveState("还有新内容", true);
      $("#editor-autosave-state").textContent = "新内容等待自动保存";
      scheduleAutoSave();
    } else {
      setSaveState("已保存", false);
      $("#editor-autosave-state").textContent = silent ? "已自动保存" : "已保存";
    }
    if (!silent) showToast("文档已保存");
    await loadWorkspace();
  } catch (error) {
    const conflict = error.status === 409;
    setSaveState(conflict ? "版本冲突" : "保存失败", true);
    $("#editor-autosave-state").textContent = conflict ? "版本冲突，请重新载入" : "自动保存失败";
    if (!silent || conflict) showToast(error.message, true);
  } finally {
    state.saving = false;
    $("#save-document").disabled = !state.dirty;
    syncChapterDeleteControl();
  }
}

function markEditorDirty() {
  state.dirty = true;
  setSaveState("未保存", true);
  updateEditorCount();
  syncRevisionControls();
  syncChapterDeleteControl();
  scheduleAutoSave();
}

function syncChapterDeleteControl() {
  const button = $("#delete-chapter");
  if (!button) return;
  const isChapter = documentGroup(state.document?.path || "") === "chapters";
  button.hidden = !isChapter;
  button.disabled = !isChapter || state.dirty || state.saving;
  if (!isChapter) return;
  const latest = state.workspace?.documents?.chapters?.at(-1);
  button.title = latest?.path === state.document?.path
    ? "手动删除当前最新章节"
    : `为保护连续性，请先删除最新章节 ${latest?.path?.match(/ch_\d+/)?.[0] || ""}`;
}

function openChapterDeleteDialog() {
  if (!state.document || documentGroup(state.document.path) !== "chapters") return;
  if (state.dirty || state.saving) {
    showToast("请先保存正文再删除", true);
    return;
  }
  const latest = state.workspace?.documents?.chapters?.at(-1);
  if (!latest || latest.path !== state.document.path) {
    const latestId = latest?.path?.match(/ch_\d+/)?.[0] || "最新章节";
    showToast(`为保护连续性，请先打开并删除 ${latestId}`, true);
    return;
  }
  const chapterId = state.document.path.match(/(ch_\d+)\.md$/)?.[1] || "";
  if (!chapterId) return;
  $("#chapter-delete-context").textContent = `即将删除《${state.document.title}》（${chapterId}）。如需清空全部正文，请从最新章开始依次删除。`;
  $("#chapter-delete-confirm").value = "";
  $("#chapter-delete-confirm").placeholder = chapterId;
  $("#chapter-delete-status").textContent = `请输入 ${chapterId}`;
  $("#chapter-delete-submit").disabled = true;
  $("#chapter-delete-dialog").showModal();
  $("#chapter-delete-confirm").focus();
}

function syncChapterDeleteConfirmation() {
  const chapterId = state.document?.path?.match(/(ch_\d+)\.md$/)?.[1] || "";
  const matches = $("#chapter-delete-confirm").value.trim() === chapterId;
  $("#chapter-delete-submit").disabled = !matches;
  $("#chapter-delete-status").textContent = matches
    ? "确认信息匹配，可以删除"
    : `请输入 ${chapterId}`;
}

async function deleteCurrentChapter(event) {
  event.preventDefault();
  if (!state.document) return;
  const deletedPath = state.document.path;
  const chapterId = deletedPath.match(/(ch_\d+)\.md$/)?.[1] || "";
  const submit = $("#chapter-delete-submit");
  submit.disabled = true;
  $("#chapter-delete-cancel").disabled = true;
  $("#chapter-delete-status").textContent = "正在保存删除前版本并清理正文…";
  try {
    const payload = await api("/api/chapter/delete", {
      method: "POST",
      body: JSON.stringify({
        path: deletedPath,
        version: state.document.version,
        confirm: $("#chapter-delete-confirm").value.trim(),
      }),
    });
    state.document = null;
    state.dirty = false;
    clearTimeout(state.autoSaveTimer);
    state.autoSaveTimer = null;
    $("#chapter-delete-dialog").close();
    await loadWorkspace();
    const previous = payload.previous_chapter
      ? state.workspace.documents.chapters.find((item) =>
          item.path.endsWith(`/${payload.previous_chapter}.md`)
        )
      : null;
    if (previous) {
      await openDocument(previous.path, false);
    } else {
      showEmptyEditor("chapters");
      history.replaceState({ view: "chapters" }, "", "/#chapters");
    }
    showToast(`${chapterId} 正文已删除；大纲保持不变`);
  } catch (error) {
    $("#chapter-delete-status").textContent = error.message;
    showToast(error.message, true);
    submit.disabled = false;
  } finally {
    $("#chapter-delete-cancel").disabled = false;
  }
}

function toggleEditorFind(open = $("#editor-find-panel").hidden) {
  const panel = $("#editor-find-panel");
  panel.hidden = !open;
  if (open) {
    $("#editor-find-query").focus();
    $("#editor-find-query").select();
  } else {
    $("#editor-find-status").textContent = "输入文字开始查找";
    getPrimaryMarkdownEditor().focus();
  }
}

async function findNextEditorMatch() {
  const editor = getPrimaryMarkdownEditor();
  const value = editor.getValue();
  const query = $("#editor-find-query").value;
  const status = $("#editor-find-status");
  if (!query) {
    status.textContent = "输入文字开始查找";
    return false;
  }
  let index = value.indexOf(query, editor.selection().end);
  let wrapped = false;
  if (index < 0) {
    index = value.indexOf(query);
    wrapped = index >= 0;
  }
  if (index < 0) {
    status.textContent = "没有匹配内容";
    return false;
  }
  await editor.selectRange(index, index + query.length);
  const count = value.split(query).length - 1;
  const current = value.slice(0, index).split(query).length;
  status.textContent = `${current} / ${count}${wrapped ? " · 已回到开头" : ""}`;
  return true;
}

async function replaceEditorMatch() {
  const editor = getPrimaryMarkdownEditor();
  const query = $("#editor-find-query").value;
  if (!query) return;
  let selection = editor.selection();
  const value = editor.getValue();
  const selected = value.slice(selection.start, selection.end);
  if (selected !== query) {
    if (!await findNextEditorMatch()) return;
    selection = editor.selection();
  }
  const start = selection.start;
  const replacement = $("#editor-replace-value").value;
  await editor.setValue(
    editor.getValue().slice(0, start) + replacement + editor.getValue().slice(selection.end),
    false,
  );
  await editor.selectRange(start + replacement.length, start + replacement.length);
  markEditorDirty();
  $("#editor-find-status").textContent = "已替换当前匹配";
  await findNextEditorMatch();
}

async function replaceAllEditorMatches() {
  const editor = getPrimaryMarkdownEditor();
  const value = editor.getValue();
  const query = $("#editor-find-query").value;
  if (!query) return;
  const count = value.split(query).length - 1;
  if (!count) {
    $("#editor-find-status").textContent = "没有匹配内容";
    return;
  }
  await editor.setValue(value.split(query).join($("#editor-replace-value").value), false);
  markEditorDirty();
  $("#editor-find-status").textContent = `已替换 ${count} 处`;
}

function toggleEditorReadingMode() {
  state.editorReadingMode = !state.editorReadingMode;
  $("#editor-view").classList.toggle("reading-width", state.editorReadingMode);
  $("#editor-reading-toggle").setAttribute("aria-pressed", String(state.editorReadingMode));
}

function toggleEditorFocusMode(force) {
  state.editorFocusMode = typeof force === "boolean" ? force : !state.editorFocusMode;
  $("#app").classList.toggle("editor-focus", state.editorFocusMode);
  $("#editor-focus-toggle").setAttribute("aria-pressed", String(state.editorFocusMode));
  if (state.editorFocusMode) toggleInspector(false);
  getPrimaryMarkdownEditor().focus();
}

const safeChatTags = new Set([
  "a", "blockquote", "br", "code", "em", "h1", "h2", "h3", "h4", "hr",
  "li", "ol", "p", "pre", "strong", "ul",
]);

function appendSafeChatMarkup(root, renderedHtml, fallbackText) {
  if (!renderedHtml) {
    root.textContent = fallbackText;
    return;
  }
  const parsed = new DOMParser().parseFromString(renderedHtml, "text/html");
  const appendNode = (source, target) => {
    if (source.nodeType === 3) {
      target.append(document.createTextNode(source.textContent || ""));
      return;
    }
    if (source.nodeType !== 1) return;
    const tag = source.tagName.toLowerCase();
    let destination = safeChatTags.has(tag)
      ? document.createElement(tag)
      : document.createDocumentFragment();
    if (tag === "a") {
      const href = source.getAttribute("href") || "";
      try {
        const url = new URL(href, location.href);
        if (!["http:", "https:"].includes(url.protocol)) {
          destination = document.createElement("span");
        } else {
          destination.href = url.href;
          destination.target = "_blank";
          destination.rel = "noopener noreferrer";
        }
      } catch (error) {
        destination = document.createElement("span");
      }
    }
    source.childNodes.forEach((child) => appendNode(child, destination));
    target.append(destination);
  };
  parsed.body.childNodes.forEach((child) => appendNode(child, root));
  if (!root.hasChildNodes()) root.textContent = fallbackText;
}

function appendInspectorAssistantMessage(author, content, renderedHtml = "", error = false) {
  const item = document.createElement("article");
  if (error) item.classList.add("error");
  const name = document.createElement("strong");
  name.textContent = author;
  const body = document.createElement(renderedHtml ? "div" : "p");
  if (renderedHtml) {
    body.className = "chat-markdown";
    appendSafeChatMarkup(body, renderedHtml, content);
  } else {
    body.textContent = content;
  }
  item.append(name, body);
  $("#inspector-assistant-log").append(item);
  item.scrollIntoView({ block: "end", behavior: "smooth" });
}

function buildInspectorAssistantMessage(prompt) {
  const editor = getPrimaryMarkdownEditor();
  const value = editor.getValue();
  const range = editor.selection();
  const selection = value.slice(range.start, range.end).trim().slice(0, 5000);
  const cursor = range.end;
  const excerpt = value.slice(Math.max(0, cursor - 1800), cursor + 1800).trim();
  const context = [
    `当前文档：${state.document?.title || "未命名"}`,
    selection ? `当前选区：\n${selection}` : `光标附近文本：\n${excerpt || "（空）"}`,
  ].join("\n\n");
  return `${prompt}\n\n【Studio 当前上下文】\n${context}\n\n请只提供分析或建议；如需改写，先给出可审阅提案，不要直接写入正典文件。`;
}

async function submitInspectorAssistant(event) {
  event?.preventDefault();
  if (state.assistantSubmitting) return;
  const input = $("#inspector-assistant-input");
  const prompt = input.value.trim();
  if (!prompt) return;
  state.assistantSubmitting = true;
  state.agent = "dante";
  syncNavigationState(state.view);
  appendInspectorAssistantMessage("你", prompt);
  input.value = "";
  $("#inspector-assistant-submit").disabled = true;
  $("#inspector-assistant-status").textContent = "Dante 正在读取当前写作上下文…";
  toggleInspector(true);
  const sessionId = activeAgentSessionId("dante");
  const message = buildInspectorAssistantMessage(prompt);
  const runId = startAgentActivity("dante", prompt);
  try {
    const payload = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ agent: "dante", session_id: sessionId, run_id: runId, message }),
    });
    state.agentSessionId.dante = payload.session_id || sessionId;
    appendInspectorAssistantMessage("Dante", payload.content || "本轮已完成。", payload.content_html || "");
    state.workspace = payload.workspace;
    renderWorkspace();
    finishAgentActivity("complete");
  } catch (error) {
    appendInspectorAssistantMessage("系统", error.message, "", true);
    finishAgentActivity("error", error.message);
  } finally {
    state.assistantSubmitting = false;
    $("#inspector-assistant-submit").disabled = false;
    $("#inspector-assistant-status").textContent = "";
    input.focus();
  }
}

async function saveFocus(event) {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    state.workspace = await api("/api/focus", {
      method: "POST",
      body: JSON.stringify({
        goal: $("#focus-goal").value,
        must_keep: $("#focus-keep").value.split("\n"),
        must_avoid: $("#focus-avoid").value.split("\n"),
        notes: $("#focus-notes").value.split("\n"),
      }),
    });
    renderWorkspace();
    showToast("创作罗盘已更新");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function initializeProject(event) {
  event.preventDefault();
  const submit = $("#project-submit");
  submit.disabled = true;
  $("#project-progress").textContent = "正在创建小说目录、真源和运行态…";
  try {
    state.workspace = await api("/api/project/init", {
      method: "POST",
      body: JSON.stringify({
        project_path: $("#project-path").value.trim(),
        novel_id: $("#project-id").value.trim(),
        title: $("#project-title").value.trim(),
        template: "default",
      }),
    });
    renderWorkspace();
    $("#project-dialog").close();
    showToast("小说工作区已创建，从你的创作资料开始");
    advanceProductTourAfterAction("project");
  } catch (error) {
    $("#project-progress").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

const productTourSteps = {
  workspace: {
    target: "#dashboard-title",
    title: "先认识你的写作工作台",
    copy: "这里不是只和 AI 聊天的页面。OpenWrite 把策划、资料、正文、校验和写作都放进同一个作品工作区；先花半分钟看一圈，再开始创建你的故事。",
    next: "浏览工作区",
    nextStep: "navigation",
  },
  navigation: {
    target: ".view-nav",
    title: "左侧是作品的工作地图",
    copy: "总览看进度和下一步；大纲规划章节；正文管理已写内容。故事、人物、世界保存创作资料；AI 协作和 Goethe、Dante 对话；搜索、连续性、工具箱用来查找、校验和处理项目。",
    next: "看看规划区",
    nextStep: "planning",
  },
  planning: {
    target: '[data-view="outline"]',
    title: "先把故事变成可写的结构",
    copy: "大纲负责卷、幕、节、章的推进。故事、人物、世界三个区域负责保存设定和关系，它们会成为 AI 规划与写作时读取的依据。",
    next: "看看正文区",
    nextStep: "writing",
  },
  writing: {
    target: '[data-view="chapters"]',
    title: "正文区只处理已经落笔的内容",
    copy: "在这里打开、编辑和审阅章节。等大纲确认后，右上角“写下一章”会让 Dante 先读取上下文，再帮你起草正文。",
    next: "看看 AI 协作",
    nextStep: "agents",
  },
  agents: {
    target: '[data-view="agents"]',
    title: "AI 协作分成策划和写作两位助手",
    copy: "Goethe 用来聊灵感、人物、设定和大纲；Dante 接手已经确认的素材，推进章节创作。你始终可以修改结果，AI 不会替你悄悄定稿。",
    next: "看看检查工具",
    nextStep: "safeguards",
  },
  safeguards: {
    target: '[data-view="continuity"]',
    title: "搜索、连续性和工具箱负责查漏补缺",
    copy: "搜索跨文档查资料；连续性检查人物、时间线和设定是否冲突；工具箱处理导入、导出和项目操作。它们不打断写作，但在需要时随时可用。",
    next: "认识顶栏控制",
    nextStep: "controls",
  },
  controls: {
    target: "#project-settings-open",
    title: "顶栏控制作品、模型和写作入口",
    copy: "“作品”用于新建或切换书；“模型设置”连接你的 AI；“写下一章”在大纲准备好后启动正文流程。现在从连接模型开始。",
    next: "开始设置",
    nextStep: "model",
  },
  model: {
    target: "#model-settings-open",
    title: "先连接你的 AI",
    copy: "点击这里，选择服务商并填入 API Key。配置成功后，引导会自动继续。",
    next: "已配置，继续",
    nextStep: "project",
    nextWhen: () => Boolean(state.workspace?.model?.configured),
  },
  project: {
    target: "#project-settings-open",
    title: "创建一个空白作品",
    copy: "点击“作品”后填写书名和小说 ID。目录可留空，创建完成会自动进入故事规划。",
    next: "已创建，继续",
    nextStep: "idea",
    nextWhen: () => Boolean(state.workspace?.initialized),
  },
  idea: {
    target: "#chat-input",
    view: "agents",
    agent: "goethe",
    title: "告诉 Goethe 你想写什么故事",
    copy: "像和编辑聊天一样描述题材、主角、冲突或一个画面。不用套模板；发送后引导会教你让它生成大纲。",
  },
  outline: {
    target: "#chat-input",
    view: "agents",
    agent: "goethe",
    title: "让 Goethe 整理成可写大纲",
    copy: "等 Goethe 回复完刚才的构想后，再发送：“基于刚才的想法，先生成前五章可写大纲，给我确认”。发送后，去大纲页检查和编辑结果。",
  },
  review: {
    target: '[data-view="outline"]',
    view: "outline",
    title: "检查并确认大纲",
    copy: "在这里查看卷、幕、节、章；需要调整时直接编辑 Markdown 原文。确认有可写章节后，再开始写作。",
    next: "准备写第一章",
    nextStep: "write",
  },
  write: {
    target: "#write-open",
    title: "开始第一章",
    copy: "点击“写下一章”，Dante 会先读取已确认的大纲和设定，再生成正文。",
    next: "完成引导",
    nextStep: "done",
  },
};

const productTourStorageKey = "openwrite-product-tour-v2";
const productTourStepLabels = {
  workspace: "认识工作台",
  navigation: "工作区导航",
  planning: "故事规划",
  writing: "正文写作",
  agents: "AI 协作",
  safeguards: "检查工具",
  controls: "顶栏控制",
  model: "模型配置",
  project: "创建作品",
  idea: "故事构想",
  outline: "生成大纲",
  review: "确认大纲",
  write: "开始写作",
};

function productTourDebugMode() {
  return new URLSearchParams(window.location.search).get("debug") === "onboarding";
}

function preferredTourStep() {
  if (!state.workspace?.model?.configured) return "model";
  if (!state.workspace?.initialized) return "project";
  if (!state.workspace?.snapshot?.readiness?.outline) return "idea";
  return "write";
}

function startProductTour(forcedStep = "") {
  const isAutomatic = !forcedStep;
  const debugMode = productTourDebugMode();
  // Embed mode (dsh shell): never auto-start the tour inside the iframe.
  if (isAutomatic && document.documentElement.dataset.embed === "dsh") return;
  if (isAutomatic && !debugMode && readLocalValue(productTourStorageKey)) return;
  const step = forcedStep || "workspace";
  const guide = productTourSteps[step];
  if (!guide) return;
  if (isAutomatic && !debugMode) writeLocalValue(productTourStorageKey, "seen");
  state.productTour.active = true;
  state.productTour.step = step;
  if (guide.view && state.view !== guide.view) setView(guide.view);
  if (guide.agent && state.agent !== guide.agent) chooseAgent(guide.agent);
  requestAnimationFrame(renderProductTour);
}

function renderProductTour() {
  if (!state.productTour.active) return;
  const guide = productTourSteps[state.productTour.step];
  const target = $(guide.target);
  if (!target) return;
  const rect = target.getBoundingClientRect();
  const padding = 7;
  const spotlight = $("#product-tour-spotlight");
  const card = $("#product-tour-card");
  const root = $("#product-tour");
  root.hidden = false;
  spotlight.style.top = `${Math.max(4, rect.top - padding)}px`;
  spotlight.style.left = `${Math.max(4, rect.left - padding)}px`;
  spotlight.style.width = `${rect.width + padding * 2}px`;
  spotlight.style.height = `${rect.height + padding * 2}px`;
  const cardWidth = Math.min(360, window.innerWidth - 28);
  const fitsBelow = rect.bottom + 220 < window.innerHeight;
  const top = fitsBelow ? rect.bottom + 18 : Math.max(12, rect.top - 210);
  const left = Math.min(Math.max(14, rect.left), window.innerWidth - cardWidth - 14);
  card.style.top = `${top}px`;
  card.style.left = `${left}px`;
  card.dataset.placement = fitsBelow ? "bottom" : "top";
  const stepKeys = Object.keys(productTourSteps);
  const stepIndex = stepKeys.indexOf(state.productTour.step);
  const completedLabels = stepKeys
    .slice(0, stepIndex)
    .map((key) => productTourStepLabels[key]);
  $("#product-tour-progress").textContent = `${stepIndex + 1} / ${stepKeys.length}${completedLabels.length ? ` · 已完成：${completedLabels.join("、")}` : ""}`;
  $("#product-tour-title").textContent = guide.title;
  $("#product-tour-copy").textContent = guide.copy;
  const next = $("#product-tour-next");
  next.hidden = !guide.next || (guide.nextWhen && !guide.nextWhen());
  next.textContent = guide.next || "下一步";
  $("#product-tour-back").hidden = stepIndex <= 0;
}

function advanceProductTourAfterAction(action) {
  if (!state.productTour.active || state.productTour.step !== action) return;
  const following = { model: "project", project: "idea", idea: "outline", outline: "review" }[action];
  if (following) startProductTour(following);
}

function advanceProductTourManually() {
  const guide = productTourSteps[state.productTour.step];
  if (guide?.nextStep === "done") {
    finishProductTour();
    return;
  }
  if (guide?.nextStep) startProductTour(guide.nextStep);
}

function goToPreviousProductTourStep() {
  const stepKeys = Object.keys(productTourSteps);
  const stepIndex = stepKeys.indexOf(state.productTour.step);
  if (stepIndex > 0) startProductTour(stepKeys[stepIndex - 1]);
}

function finishProductTour() {
  state.productTour.active = false;
  state.productTour.step = "";
  $("#product-tour").hidden = true;
  if (!productTourDebugMode()) writeLocalValue(productTourStorageKey, "done");
  showToast("引导已完成。随时可从总览重新打开。");
}

function openProjectDialog() {
  $("#project-progress").textContent = "";
  $("#open-project-progress").textContent = "";
  renderRecentProjects();
  $("#project-dialog").showModal();
  $("#open-project-path").focus();
}

function openWritingTargetsDialog() {
  if (!state.workspace?.initialized) {
    showToast("请先打开作品", true);
    return;
  }
  const targets = state.workspace.project?.writing_targets || {};
  $("#writing-target-book").value = String(targets.book_words || 100000);
  $("#writing-target-chapter").value = String(targets.chapter_words || 3000);
  $("#writing-target-volume").value = String(targets.outline_volume_words || 800);
  $("#writing-target-act").value = String(targets.outline_act_words || 500);
  $("#writing-target-section").value = String(targets.outline_section_words || 300);
  $("#writing-target-outline-chapter").value = String(targets.outline_chapter_words || 180);
  $("#writing-targets-status").textContent = "";
  $("#writing-targets-dialog").showModal();
  $("#writing-target-chapter").focus();
  $("#writing-target-chapter").select();
}

async function saveWritingTargets(event) {
  event.preventDefault();
  const submit = $("#writing-targets-submit");
  const status = $("#writing-targets-status");
  submit.disabled = true;
  status.textContent = "正在保存字数规划…";
  try {
    state.workspace = await api("/api/project/writing-targets", {
      method: "POST",
      body: JSON.stringify({
        book_words: Number($("#writing-target-book").value),
        chapter_words: Number($("#writing-target-chapter").value),
        outline_volume_words: Number($("#writing-target-volume").value),
        outline_act_words: Number($("#writing-target-act").value),
        outline_section_words: Number($("#writing-target-section").value),
        outline_chapter_words: Number($("#writing-target-outline-chapter").value),
      }),
    });
    renderWorkspace();
    if (state.view === "outline") {
      const selected = selectedOutlineNode();
      await loadOutline(selected?.kind === "chapter" ? selected.id : "");
    }
    $("#writing-targets-dialog").close();
    showToast("字数规划已保存");
  } catch (error) {
    status.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

async function openProject(event) {
  event.preventDefault();
  const submit = $("#open-project-submit");
  submit.disabled = true;
  $("#open-project-progress").textContent = "正在校验并打开作品…";
  try {
    state.workspace = await api("/api/project/open", {
      method: "POST",
      body: JSON.stringify({ project_path: $("#open-project-path").value.trim() }),
    });
    state.document = null;
    state.dirty = false;
    renderWorkspace();
    renderRecentProjects();
    $("#project-dialog").close();
    setView("dashboard");
    showToast(`已打开 ${state.workspace.snapshot.title}`);
  } catch (error) {
    $("#open-project-progress").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

async function openRecentProject(projectPath) {
  $("#open-project-path").value = projectPath;
  await openProject(new Event("submit", { cancelable: true }));
}

function renderRecentProjects() {
  const root = $("#recent-projects");
  root.replaceChildren();
  const projects = state.workspace?.project?.recent || [];
  projects.forEach((project) => {
    const row = document.createElement("div");
    row.className = "recent-project-row";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-project";
    const title = document.createElement("strong");
    title.textContent = project.title;
    const path = document.createElement("span");
    path.textContent = project.path;
    button.append(title, path);
    button.addEventListener("click", () => {
      openRecentProject(project.path);
    });
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "recent-project-delete";
    delBtn.textContent = "删除";
    delBtn.title = `删除 ${project.title}`;
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      confirmDeleteProject(project);
    });
    row.append(button, delBtn);
    root.append(row);
  });
}

async function confirmDeleteProject(project) {
  const confirmed = window.confirm(
    `确定要永久删除作品「${project.title}」吗？\n\n此操作不可撤销。`,
  );
  if (!confirmed) return;
  try {
    state.workspace = await api("/api/project/delete", {
      method: "POST",
      body: JSON.stringify({
        project_path: project.path,
        confirm: project.novel_id,
      }),
    });
    renderWorkspace();
    renderRecentProjects();
    showToast(`已删除「${project.title}」`);
    if (!state.workspace.initialized) {
      setView("dashboard");
    }
  } catch (error) {
    showToast(error.message, true);
  }
}

async function searchProject(event) {
  event.preventDefault();
  const query = $("#search-query").value.trim();
  const scope = $("#search-scope").value;
  if (!query) return;
  $("#search-status").textContent = "正在更新 LightRAG 索引并搜索…";
  const root = $("#search-results");
  root.replaceChildren();
  try {
    const payload = await api(`/api/search?q=${encodeURIComponent(query)}&scope=${encodeURIComponent(scope)}`);
    const engine = payload.engine === "lightrag" ? "LightRAG" : "精确文本降级";
    const embedding = payload.embedding?.model
      ? ` · ${payload.embedding.provider_label || payload.embedding.provider} / ${payload.embedding.model}`
      : "";
    const warning = payload.warning ? ` · ${payload.warning}` : "";
    $("#search-status").textContent = `${engine}${embedding} 已索引 ${payload.indexed} 份文档，找到 ${payload.results.length} 条结果${warning}`;
    payload.results.forEach((result) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-result";
      const heading = document.createElement("strong");
      heading.textContent = result.heading || result.title;
      const location = document.createElement("span");
      location.textContent = [
        result.scope_label,
        result.category_label,
        result.retrieval?.includes("semantic") ? "语义召回" : "精确命中",
        `${result.path}:${result.line}`,
      ].filter(Boolean).join(" · ");
      const snippet = document.createElement("p");
      snippet.textContent = result.snippet;
      button.append(heading, location, snippet);
      button.addEventListener("click", () => openProjectPath(result.path, true));
      root.append(button);
    });
    if (!payload.results.length) root.textContent = "没有命中。可以缩短关键词或切换到“全部资产”。";
  } catch (error) {
    $("#search-status").textContent = error.message;
    showToast(error.message, true);
  }
}

function renderOperations() {
  const operations = state.workspace?.operations || {};
  const diagnostics = operations.diagnostics || [];
  const runtimeFindings = operations.runtime_diagnostics?.findings || [];
  const diagnosticRoot = $("#diagnostic-list");
  diagnosticRoot.replaceChildren();
  diagnostics.forEach((item) => {
    const row = document.createElement("div");
    row.className = `operation-row${item.ok ? " ok" : ""}`;
    const name = document.createElement("strong");
    name.textContent = item.name;
    const detail = document.createElement("span");
    detail.textContent = item.detail;
    row.append(name, detail);
    diagnosticRoot.append(row);
  });
  runtimeFindings.forEach((finding) => {
    const row = document.createElement("div");
    row.className = `operation-row diagnostic-${finding.severity}`;
    const name = document.createElement("strong");
    name.textContent = finding.summary;
    const detail = document.createElement("span");
    detail.textContent = finding.explanation;
    row.append(name, detail);
    diagnosticRoot.append(row);
  });
  const sync = operations.sync || {};
  $("#sync-status").textContent = sync.needs_sync
    ? `待同步：大纲 ${sync.outline_pending ? "有变更" : "已同步"}，角色卡 ${sync.cards || 0}/${sync.profiles || 0}`
    : "src 与 data 已同步";
  renderReferenceLibrary(
    operations.reference_library || [],
    operations.reference_style || {},
  );
  renderRuntimeSkillStatus(operations);
  renderChapterRuns(operations.chapter_runs_v2 || {});
  renderRollingPlans(operations.rolling_plans || {});
  renderNarrativeForecasts(operations.narrative_forecasts || {});
}

let rollingPlanItems = [];
let selectedRollingPlan = null;

function renderRollingPlans(payload) {
  rollingPlanItems = payload.candidates || [];
  const select = $("#rolling-plan-select");
  const previous = selectedRollingPlan?.candidate_id || select.value;
  select.replaceChildren();
  rollingPlanItems.forEach((candidate) => {
    const option = document.createElement("option");
    option.value = candidate.candidate_id;
    option.textContent = `${candidate.current_arc} · ${candidate.state} · ${candidate.next_window.length} 章`;
    select.append(option);
  });
  selectedRollingPlan = rollingPlanItems.find((item) => item.candidate_id === previous) || rollingPlanItems[0] || null;
  if (selectedRollingPlan) select.value = selectedRollingPlan.candidate_id;
  $("#rolling-plan-count").textContent = String(rollingPlanItems.length);
  renderSelectedRollingPlan();
}

function renderSelectedRollingPlan() {
  $("#rolling-plan-report").textContent = selectedRollingPlan?.goethe_brief || "生成候选后可交给 Goethe 形成待确认大纲草案";
  $("#rolling-plan-goethe").disabled = !selectedRollingPlan;
}

async function createRollingPlan() {
  try {
    const candidate = await api("/api/rolling-plans", {method: "POST", body: JSON.stringify({action: "create", window_size: Number($("#rolling-plan-window").value || 5)})});
    selectedRollingPlan = candidate;
    rollingPlanItems.unshift(candidate);
    renderRollingPlans({candidates: rollingPlanItems});
    $("#rolling-plan-status").textContent = "候选已生成，canonical 大纲未修改";
  } catch (error) { $("#rolling-plan-status").textContent = error.message; }
}

function sendRollingPlanToGoethe() {
  if (!selectedRollingPlan) return;
  chooseAgent("goethe");
  setView("agents");
  $("#chat-input").value = `请根据滚动规划候选 ${selectedRollingPlan.candidate_id} 形成完整 Markdown 大纲提案。先调用 manage_rolling_plan get 读取候选，完成后调用 manage_rolling_plan stage 暂存提案，不要直接确认覆盖大纲。`;
  $("#chat-input").focus();
}

let narrativeForecastItems = [];
let selectedNarrativeForecast = null;
let activeNarrativeBranchId = "";
let narrativeForecastChapterOptions = [];
let narrativeForecastRecommendedChapterId = "";

function renderNarrativeForecastChapterOptions(payload) {
  if (Array.isArray(payload.chapter_options)) {
    narrativeForecastChapterOptions = payload.chapter_options;
    narrativeForecastRecommendedChapterId = payload.recommended_chapter_id || "";
  }
  const select = $("#narrative-forecast-anchor");
  const previous = select.value;
  select.replaceChildren();
  narrativeForecastChapterOptions.forEach((chapter) => {
    const option = document.createElement("option");
    const status = chapter.status === "drafted" ? "已有正文" : "待写";
    option.value = chapter.id;
    option.textContent = `${chapter.id} · ${chapter.title} · ${status}`;
    option.title = [...(chapter.path || []), chapter.title].join(" / ");
    select.append(option);
  });
  if (!narrativeForecastChapterOptions.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "大纲中暂无章节";
    select.append(option);
  }
  const preferred = narrativeForecastChapterOptions.find((chapter) => chapter.id === previous)
    || narrativeForecastChapterOptions.find(
      (chapter) => chapter.id === narrativeForecastRecommendedChapterId,
    )
    || narrativeForecastChapterOptions[0];
  select.value = preferred?.id || "";
  $("#narrative-forecast-create").disabled = !preferred;
}

function renderNarrativeForecasts(payload) {
  renderNarrativeForecastChapterOptions(payload);
  narrativeForecastItems = payload.forecasts || [];
  const select = $("#narrative-forecast-select");
  const previous = selectedNarrativeForecast?.forecast_id || select.value;
  select.replaceChildren();
  narrativeForecastItems.forEach((forecast) => {
    const option = document.createElement("option");
    option.value = forecast.forecast_id;
    const stateLabel = forecast.effective_state === "stale"
      ? "已过期"
      : (forecast.state === "active" ? "已完成" : "生成中");
    const selectedLabel = forecast.selected_branch_id ? ` · 已选 ${forecast.selected_branch_id}` : "";
    const anchorLabel = forecast.anchor_chapter_id ? ` · ${forecast.anchor_chapter_id}` : "";
    option.textContent = `${forecast.divergence.slice(0, 42)}${anchorLabel} · ${stateLabel}${selectedLabel}`;
    select.append(option);
  });
  if (!narrativeForecastItems.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无推演";
    select.append(option);
  }
  selectedNarrativeForecast = narrativeForecastItems.find((item) => item.forecast_id === previous)
    || narrativeForecastItems[0]
    || null;
  if (selectedNarrativeForecast) select.value = selectedNarrativeForecast.forecast_id;
  $("#narrative-forecast-count").textContent = String(narrativeForecastItems.length);
  renderSelectedNarrativeForecast();
}

function renderSelectedNarrativeForecast() {
  const forecast = selectedNarrativeForecast;
  const result = $("#narrative-forecast-result");
  result.hidden = !forecast;
  if (!forecast) {
    activeNarrativeBranchId = "";
    return;
  }
  const stale = forecast.effective_state === "stale" || forecast.stale;
  const stateLabel = stale ? "上下文已变" : (forecast.state === "active" ? "推演完成" : "等待 Goethe");
  $("#narrative-forecast-state").textContent = stateLabel;
  $("#narrative-forecast-state").classList.toggle("stale", stale);
  $("#narrative-forecast-question").textContent = forecast.divergence;
  const anchorLabel = forecast.anchor_chapter_id
    ? `${forecast.anchor_chapter_id} · ${forecast.anchor_chapter_title}`
    : `第 ${forecast.base_chapter} 章之后 · 旧推演未记录锚点`;
  $("#narrative-forecast-meta").textContent = `锚点 ${anchorLabel} · ${forecast.branch_count} 条分支 · 覆盖 ${forecast.horizon} 章`;
  renderNarrativeForecastComparison(forecast);

  const branches = forecast.branches || [];
  if (!branches.some((branch) => branch.branch_id === activeNarrativeBranchId)) {
    activeNarrativeBranchId = forecast.selected_branch_id || branches[0]?.branch_id || "";
  }
  renderNarrativeForecastTabs(forecast);
  renderNarrativeForecastBranch(forecast);
}

function renderNarrativeForecastComparison(forecast) {
  const root = $("#narrative-forecast-comparison");
  root.replaceChildren();
  const branches = forecast.branches || [];
  if (!branches.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "上下文已建立，等待 Goethe 返回结构化分支。";
    root.append(empty);
    return;
  }
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  const corner = document.createElement("th");
  corner.scope = "col";
  corner.textContent = "比较项";
  headRow.append(corner);
  branches.forEach((branch) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = branch.title;
    headRow.append(cell);
  });
  head.append(headRow);
  table.append(head);

  const body = document.createElement("tbody");
  const rows = [
    ["意图匹配", (branch) => `${branch.intent_alignment?.score ?? 0}/100`],
    ["分支前提", (branch) => branch.premise || "未填写"],
    ["未来节拍", (branch) => `${(branch.beats || []).length} 个`],
    ["一致性风险", (branch) => `${(branch.risks || []).length} 项`],
  ];
  rows.forEach(([label, valueFor]) => {
    const row = document.createElement("tr");
    const heading = document.createElement("th");
    heading.scope = "row";
    heading.textContent = label;
    row.append(heading);
    branches.forEach((branch) => {
      const cell = document.createElement("td");
      cell.textContent = valueFor(branch);
      row.append(cell);
    });
    body.append(row);
  });
  table.append(body);
  root.append(table);
}

function renderNarrativeForecastTabs(forecast) {
  const root = $("#narrative-forecast-tabs");
  root.replaceChildren();
  (forecast.branches || []).forEach((branch) => {
    const button = document.createElement("button");
    const active = branch.branch_id === activeNarrativeBranchId;
    button.type = "button";
    button.className = `segment${active ? " active" : ""}`;
    button.role = "tab";
    button.setAttribute("aria-selected", String(active));
    button.textContent = `${branch.branch_id.replace("branch-", "路线 ")} · ${branch.title}`;
    button.addEventListener("click", () => {
      activeNarrativeBranchId = branch.branch_id;
      renderNarrativeForecastTabs(forecast);
      renderNarrativeForecastBranch(forecast);
    });
    root.append(button);
  });
  root.hidden = !(forecast.branches || []).length;
}

function appendForecastListSection(root, title, items, formatter = (item) => item) {
  const section = document.createElement("section");
  const heading = document.createElement("h4");
  heading.textContent = title;
  section.append(heading);
  if (items.length) {
    const list = document.createElement("ul");
    items.forEach((item) => {
      const row = document.createElement("li");
      row.textContent = formatter(item);
      list.append(row);
    });
    section.append(list);
  } else {
    const empty = document.createElement("p");
    empty.textContent = "无";
    section.append(empty);
  }
  root.append(section);
}

function renderNarrativeForecastBranch(forecast) {
  const root = $("#narrative-forecast-detail");
  root.replaceChildren();
  const branch = (forecast.branches || []).find((item) => item.branch_id === activeNarrativeBranchId);
  const selectButton = $("#narrative-forecast-select-branch");
  const continueButton = $("#narrative-forecast-continue");
  if (!branch) {
    selectButton.disabled = true;
    continueButton.disabled = true;
    return;
  }

  const header = document.createElement("div");
  header.className = "narrative-forecast-detail-heading";
  const heading = document.createElement("h3");
  heading.textContent = branch.title;
  const score = document.createElement("strong");
  score.textContent = `${branch.intent_alignment?.score ?? 0}/100`;
  header.append(heading, score);
  const premise = document.createElement("p");
  premise.className = "narrative-forecast-premise";
  premise.textContent = branch.premise;
  root.append(header, premise);

  appendForecastListSection(
    root,
    "未来章节节拍",
    branch.beats || [],
    (beat) => `第 +${beat.offset} 章${beat.chapter_id ? `（${beat.chapter_id}）` : ""}：${beat.summary}`,
  );
  appendForecastListSection(
    root,
    "人物决策",
    branch.character_decisions || [],
    (item) => `${item.character}：${item.decision}`,
  );
  const changes = branch.projected_changes || {};
  appendForecastListSection(root, "人物与关系变化", [
    ...(changes.characters || []).map((item) => `人物：${item}`),
    ...(changes.relationships || []).map((item) => `关系：${item}`),
    ...(changes.world || []).map((item) => `世界：${item}`),
    ...(changes.foreshadowing || []).map((item) => `伏笔：${item}`),
  ]);
  appendForecastListSection(
    root,
    "一致性风险",
    branch.risks || [],
    (risk) => `[${forecastRiskLabel(risk.kind)}] ${risk.description}`,
  );
  appendForecastListSection(root, "不确定性", branch.uncertainties || []);

  const rationale = document.createElement("p");
  rationale.className = "narrative-forecast-rationale";
  rationale.textContent = branch.intent_alignment?.rationale || "";
  root.append(rationale);
  const selected = forecast.selected_branch_id === branch.branch_id;
  selectButton.disabled = selected;
  selectButton.textContent = selected ? "当前规划分支" : "选为规划分支";
  continueButton.disabled = !forecast.selected_branch_id;
}

function forecastRiskLabel(kind) {
  return {continuity: "连续性", causality: "因果", character: "人物"}[kind] || kind;
}

async function createNarrativeForecast() {
  const divergence = $("#narrative-forecast-divergence").value.trim();
  const anchorChapterId = $("#narrative-forecast-anchor").value;
  if (!divergence) {
    $("#narrative-forecast-status").textContent = "请先填写分歧点";
    $("#narrative-forecast-divergence").focus();
    return;
  }
  if (!anchorChapterId) {
    $("#narrative-forecast-status").textContent = "请先选择分歧点所在的大纲章节";
    $("#narrative-forecast-anchor").focus();
    return;
  }
  const button = $("#narrative-forecast-create");
  button.disabled = true;
  $("#narrative-forecast-status").textContent = "正在固化当前正典上下文…";
  try {
    const forecast = await api("/api/narrative-forecasts", {
      method: "POST",
      body: JSON.stringify({
        action: "create",
        divergence,
        anchor_chapter_id: anchorChapterId,
        branch_count: Number($("#narrative-forecast-branch-count").value || 3),
        horizon: Number($("#narrative-forecast-horizon").value || 5),
      }),
    });
    narrativeForecastItems.unshift(forecast);
    selectedNarrativeForecast = forecast;
    activeNarrativeBranchId = "";
    renderNarrativeForecasts({forecasts: narrativeForecastItems});
    $("#narrative-forecast-status").textContent = `已绑定 ${forecast.anchor_chapter_id}，等待发送给 Goethe`;
    chooseAgent("goethe");
    setView("agents");
    $("#chat-input").value = `请执行剧情多线推演 ${forecast.forecast_id}，分歧锚点是 ${forecast.anchor_chapter_id}「${forecast.anchor_chapter_title}」。先调用 manage_narrative_forecast get 读取固化上下文，再严格按 goethe_brief 生成 ${forecast.branch_count} 条相互隔离的路线，并调用 manage_narrative_forecast stage 保存结果。不要替我选择分支，也不要修改大纲或正文。`;
    $("#chat-input").focus();
    showToast("推演上下文已建立，请发送给 Goethe");
  } catch (error) {
    $("#narrative-forecast-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = !narrativeForecastChapterOptions.length;
  }
}

async function refreshNarrativeForecasts() {
  const button = $("#narrative-forecast-refresh");
  button.disabled = true;
  $("#narrative-forecast-status").textContent = "正在刷新推演结果…";
  try {
    const payload = await api("/api/narrative-forecasts", {
      method: "POST",
      body: JSON.stringify({action: "list", limit: 20}),
    });
    renderNarrativeForecasts(payload);
    $("#narrative-forecast-status").textContent = payload.forecasts?.length ? "推演结果已刷新" : "暂无推演";
  } catch (error) {
    $("#narrative-forecast-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function selectNarrativeForecastBranch() {
  if (!selectedNarrativeForecast || !activeNarrativeBranchId) return;
  const button = $("#narrative-forecast-select-branch");
  button.disabled = true;
  $("#narrative-forecast-status").textContent = "正在记录分支选择…";
  try {
    const updated = await api("/api/narrative-forecasts", {
      method: "POST",
      body: JSON.stringify({
        action: "select",
        forecast_id: selectedNarrativeForecast.forecast_id,
        branch_id: activeNarrativeBranchId,
        revision: selectedNarrativeForecast.revision,
      }),
    });
    narrativeForecastItems = narrativeForecastItems.map((item) => (
      item.forecast_id === updated.forecast_id ? updated : item
    ));
    selectedNarrativeForecast = updated;
    renderNarrativeForecasts({forecasts: narrativeForecastItems});
    $("#narrative-forecast-status").textContent = "分支已记录，canonical 大纲与正文未修改";
  } catch (error) {
    $("#narrative-forecast-status").textContent = error.message;
  } finally {
    renderNarrativeForecastBranch(selectedNarrativeForecast || {});
  }
}

function continueSelectedNarrativeForecast() {
  if (!selectedNarrativeForecast?.selected_branch_id) return;
  const forecast = selectedNarrativeForecast;
  chooseAgent("goethe");
  setView("agents");
  $("#chat-input").value = `请调用 manage_narrative_forecast get 读取 ${forecast.forecast_id}，围绕锚点 ${forecast.anchor_chapter_id || "（旧推演）"} 和已选的 ${forecast.selected_branch_id} 分析如何映射到现有大纲，并给出最小修改建议。这一轮先讨论，不要修改或确认 canonical 大纲。`;
  $("#chat-input").focus();
}

let selectedChapterRun = null;
let chapterRunItems = [];

function renderChapterRuns(payload) {
  const runs = payload.runs || [];
  chapterRunItems = runs;
  const select = $("#chapter-run-select");
  const previous = selectedChapterRun?.run_id || select.value;
  select.replaceChildren();
  runs.forEach((run) => {
    const option = document.createElement("option");
    option.value = run.run_id;
    option.textContent = `${run.chapter_id} · ${run.status} · ${run.next_stage || "完成"}`;
    select.append(option);
  });
  $("#chapter-run-count").textContent = String(runs.length);
  selectedChapterRun = runs.find((run) => run.run_id === previous) || runs[0] || null;
  if (selectedChapterRun) select.value = selectedChapterRun.run_id;
  renderSelectedChapterRun();
}

function renderSelectedChapterRun() {
  const run = selectedChapterRun;
  const report = $("#chapter-run-report");
  const interventionSelect = $("#chapter-intervention-select");
  interventionSelect.replaceChildren();
  if (!run) {
    report.textContent = "写作或审稿后可在这里查看八阶段状态";
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无干预";
    interventionSelect.append(option);
    return;
  }
  const stages = Object.entries(run.stages || {}).map(([name, stage]) => {
    const detail = stage.error_code ? ` · ${stage.error_code}` : "";
    return `${name.padEnd(12)} ${stage.status}${detail}`;
  });
  report.textContent = `${run.chapter_id} · ${run.status}\n下一阶段: ${run.next_stage || "已完成"}\n\n${stages.join("\n")}`;
  (run.interventions || []).forEach((item) => {
    const option = document.createElement("option");
    option.value = item.intervention_id;
    option.textContent = `${item.state} · ${item.request.slice(0, 36)}`;
    interventionSelect.append(option);
  });
  if (!(run.interventions || []).length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无干预";
    interventionSelect.append(option);
  }
}

async function refreshChapterRuns() {
  try {
    const payload = await api("/api/chapter-runs-v2", {method: "POST", body: JSON.stringify({action: "list", limit: 10})});
    renderChapterRuns(payload);
    $("#chapter-run-status").textContent = "运行状态已刷新";
  } catch (error) { $("#chapter-run-status").textContent = error.message; }
}

async function recordChapterIntervention(event) {
  event.preventDefault();
  if (!selectedChapterRun) return;
  const request = $("#chapter-intervention-request").value.trim();
  if (!request) return;
  try {
    const payload = await api("/api/chapter-runs-v2", {method: "POST", body: JSON.stringify({
      action: "record_intervention", run_id: selectedChapterRun.run_id,
      revision: selectedChapterRun.revision, request,
      scope: $("#chapter-intervention-scope").value,
      risk: $("#chapter-run-risk").value,
      rewrite_required: $("#chapter-intervention-rewrite").checked,
    })});
    selectedChapterRun = payload.run;
    $("#chapter-intervention-request").value = "";
    renderSelectedChapterRun();
    $("#chapter-run-status").textContent = "干预已记录，尚未应用";
  } catch (error) { $("#chapter-run-status").textContent = error.message; }
}

async function advanceChapterIntervention() {
  if (!selectedChapterRun) return;
  const interventionId = $("#chapter-intervention-select").value;
  if (!interventionId) return;
  const stateName = $("#chapter-intervention-state").value;
  const proposal = $("#chapter-intervention-proposal").value.trim();
  try {
    const payload = await api("/api/chapter-runs-v2", {method: "POST", body: JSON.stringify({
      action: "update_intervention", run_id: selectedChapterRun.run_id,
      revision: selectedChapterRun.revision, intervention_id: interventionId,
      state: stateName, proposal, confirm: ["confirmed", "applied"].includes(stateName),
    })});
    selectedChapterRun = payload.run;
    renderSelectedChapterRun();
    $("#chapter-run-status").textContent = `干预已推进到 ${payload.intervention.state}`;
  } catch (error) { $("#chapter-run-status").textContent = error.message; }
}

function renderRuntimeSkillStatus(operations) {
  const runtime = operations.runtime_skills || {};
  const ruleStatus = operations.runtime_rules || {};
  const skills = runtime.skills || [];
  const diagnostics = runtime.diagnostics || [];
  state.runtimeSkill.skills = skills;
  state.runtimeSkill.diagnostics = diagnostics;
  const active = ruleStatus.active === false ? "未启用" : (ruleStatus.revision ? `已启用 · ${ruleStatus.revision}` : "未启用");
  $("#runtime-skill-status").textContent = `可用 Skill ${skills.length} · 规则 ${active}`;
  $("#skill-available-count").textContent = String(skills.length);
  $("#skill-active-count").textContent = String(state.runtimeSkill.resolution?.skills?.length || 0);
  $("#skill-diagnostic-count").textContent = String(diagnostics.length);
  renderRuntimeSkillCatalog();
}

function runtimeSkillLayerLabel(layer) {
  return { builtin: "内置", global: "全局", project: "本作品" }[layer] || layer;
}

function useRuntimeSkill(skillId, agent) {
  setView("agents");
  chooseAgent(agent);
  const input = $("#chat-input");
  const mention = `@${skillId}`;
  const current = input.value.trim();
  input.value = current.includes(mention) ? current : `${mention}${current ? ` ${current}` : " "}`;
  input.focus();
  showToast(`${mention} 将只在下一轮 ${agent === "goethe" ? "Goethe" : "Dante"} 对话中启用`);
}

function renderRuntimeSkillCatalog() {
  const root = $("#runtime-skill-list");
  root.replaceChildren();
  const activeIds = new Set((state.runtimeSkill.resolution?.skills || []).map((skill) => skill.id));
  if (!state.runtimeSkill.skills.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "没有发现可用 Skill";
    root.append(empty);
    return;
  }
  state.runtimeSkill.skills.forEach((skill) => {
    const row = document.createElement("article");
    row.className = `runtime-skill-row${activeIds.has(skill.id) ? " active" : ""}`;
    const header = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = skill.name || skill.id;
    const version = document.createElement("code");
    version.textContent = `${skill.id}@${skill.version}`;
    header.append(name, version);
    const description = document.createElement("p");
    description.textContent = skill.description || "未提供说明";
    const meta = document.createElement("div");
    meta.className = "skill-meta";
    [
      runtimeSkillLayerLabel(skill.layer),
      skill.source_format === "standard-skill-md" ? "标准 SKILL.md" : "OpenWrite manifest",
      skill.activation === "explicit" ? "显式调用" : "自动匹配",
      `${skill.budget?.max_tool_calls || 0} 次工具上限`,
      skill.output_contract || "text",
    ].forEach((value) => {
      const badge = document.createElement("span");
      badge.textContent = value;
      meta.append(badge);
    });
    if ((skill.requires || []).length) {
      const dependency = document.createElement("small");
      dependency.textContent = `依赖：${skill.requires.join("、")}`;
      meta.append(dependency);
    }
    const actions = document.createElement("div");
    actions.className = "row-actions skill-use-actions";
    [["Goethe", "goethe"], ["Dante", "dante"]].forEach(([label, agent]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "quiet-button";
      button.textContent = `交给 ${label}`;
      button.title = `在下一轮 ${label} 对话中启用 @${skill.id}`;
      button.addEventListener("click", () => useRuntimeSkill(skill.id, agent));
      actions.append(button);
    });
    row.append(header, description, meta, actions);
    root.append(row);
  });
}

function appendSkillDiagnostics(root, diagnostics) {
  if (!diagnostics?.length) return;
  const section = document.createElement("section");
  section.className = "skill-resolution-section diagnostics";
  const heading = document.createElement("h3");
  heading.textContent = "诊断";
  section.append(heading);
  diagnostics.forEach((diagnostic) => {
    const row = document.createElement("p");
    row.className = `skill-diagnostic ${diagnostic.severity || "error"}`;
    row.textContent = `${diagnostic.skill_id ? `${diagnostic.skill_id} · ` : ""}${diagnostic.message}`;
    section.append(row);
  });
  root.append(section);
}

function renderRuntimeSkillResolution(payload) {
  const root = $("#runtime-skill-report");
  root.replaceChildren();
  const summary = document.createElement("div");
  summary.className = "skill-resolution-summary";
  [
    [payload.skills?.length || 0, "启用 Skills"],
    [payload.allowed_tools?.length || 0, "允许工具"],
    [payload.budget?.max_tool_calls || 0, "工具调用上限"],
  ].forEach(([value, label]) => {
    const metric = document.createElement("span");
    const number = document.createElement("strong");
    number.textContent = String(value);
    metric.append(number, document.createTextNode(label));
    summary.append(metric);
  });
  root.append(summary);

  const selected = document.createElement("section");
  selected.className = "skill-resolution-section";
  const selectedTitle = document.createElement("h3");
  selectedTitle.textContent = "本次启用";
  selected.append(selectedTitle);
  const selectedList = document.createElement("div");
  selectedList.className = "skill-token-list";
  (payload.skills || []).forEach((skill) => {
    const token = document.createElement("span");
    token.textContent = skill.name || skill.id;
    selectedList.append(token);
  });
  if (!(payload.skills || []).length) selectedList.textContent = "没有匹配当前运行的 Skill";
  selected.append(selectedList);
  root.append(selected);

  if ((payload.reasons || []).length) {
    const reasons = document.createElement("section");
    reasons.className = "skill-resolution-section";
    const heading = document.createElement("h3");
    heading.textContent = "启用依据";
    const list = document.createElement("ul");
    payload.reasons.forEach((reason) => {
      const item = document.createElement("li");
      item.textContent = reason;
      list.append(item);
    });
    reasons.append(heading, list);
    root.append(reasons);
  }

  const tools = document.createElement("details");
  tools.className = "skill-tool-boundary";
  const toolsSummary = document.createElement("summary");
  toolsSummary.textContent = `工具边界 · ${payload.allowed_tools?.length || 0}`;
  const toolList = document.createElement("div");
  toolList.className = "skill-token-list tools";
  (payload.allowed_tools || []).forEach((tool) => {
    const token = document.createElement("code");
    token.textContent = tool;
    toolList.append(token);
  });
  tools.append(toolsSummary, toolList);
  root.append(tools);
  appendSkillDiagnostics(root, payload.diagnostics || []);
}

async function resolveRuntimeSkills() {
  $("#runtime-skill-status").textContent = "正在解析 Runtime Skill…";
  try {
    const payload = await api("/api/runtime-skills", {method: "POST", body: JSON.stringify({action: "resolve", agent: $("#runtime-skill-agent").value, task: $("#runtime-skill-task").value})});
    state.runtimeSkill.resolution = payload;
    renderRuntimeSkillResolution(payload);
    renderRuntimeSkillCatalog();
    $("#skill-active-count").textContent = String(payload.skills?.length || 0);
    $("#runtime-skill-status").textContent = `解析完成 · ${payload.skills?.length || 0} 个 Skill 生效`;
  } catch (error) { $("#runtime-skill-status").textContent = error.message; }
}

async function diagnoseRuntimeSkills() {
  $("#runtime-skill-status").textContent = "正在检查 Runtime Skill…";
  try {
    const payload = await api("/api/runtime-skills", {method: "POST", body: JSON.stringify({action: "diagnose"})});
    const root = $("#runtime-skill-report");
    root.replaceChildren();
    if (payload.diagnostics?.length) appendSkillDiagnostics(root, payload.diagnostics);
    else {
      const clean = document.createElement("p");
      clean.className = "skill-diagnostic clean";
      clean.textContent = `${payload.skills || 0} 个 Skill 均通过依赖、冲突与资源路径检查`;
      root.append(clean);
    }
    $("#skill-diagnostic-count").textContent = String(payload.diagnostics?.length || 0);
    $("#runtime-skill-status").textContent = payload.diagnostics?.length ? "发现需要处理的诊断" : "Skill 检查通过";
  } catch (error) { $("#runtime-skill-status").textContent = error.message; }
}

async function previewRuntimeRules() {
  $("#runtime-skill-status").textContent = "正在生成规则预览…";
  try {
    const payload = await api("/api/rules", {method: "POST", body: JSON.stringify({action: "preview"})});
    state.runtimeSkill.rulePreview = payload;
    $("#runtime-rules-apply").disabled = false;
    $("#runtime-rules-diff").textContent = payload.unified_diff || "规则没有变化";
    $("#runtime-skill-status").textContent = `规则预览已生成 · ${payload.preview_id}`;
  } catch (error) { $("#runtime-skill-status").textContent = error.message; }
}

async function applyRuntimeRules() {
  const preview = state.runtimeSkill.rulePreview;
  if (!preview) return;
  $("#runtime-rules-apply").disabled = true;
  try {
    const payload = await api("/api/rules", {method: "POST", body: JSON.stringify({action: "apply", preview_id: preview.preview_id, confirm: true})});
    state.runtimeSkill.rulePreview = null;
    $("#runtime-rules-diff").textContent = `已启用规则 revision: ${payload.revision}`;
    $("#runtime-skill-status").textContent = "规则已确认应用";
    await loadWorkspace();
  } catch (error) { $("#runtime-rules-apply").disabled = false; $("#runtime-skill-status").textContent = error.message; }
}

function renderSourcePacks(packs) {
  const root = $("#source-list");
  root.replaceChildren();
  $("#source-count").textContent = String(packs.length);
  $("#source-complete-count").textContent = String(
    packs.filter((pack) => pack.analysis_v2?.status === "completed").length,
  );
  const currentSources = new Map(packs.map((pack) => [pack.source_id, pack]));
  Array.from(state.sourceAnalysis.selectedSourceIds).forEach((sourceId) => {
    if (!currentSources.has(sourceId)) state.sourceAnalysis.selectedSourceIds.delete(sourceId);
  });
  if (state.sourceAnalysis.profile) {
    const stale = state.sourceAnalysis.profile.source_ids.some((sourceId) => {
      const current = currentSources.get(sourceId)?.analysis_v2;
      return current?.status !== "completed"
        || current?.source_sha256 !== state.sourceAnalysis.profile.source_revisions[sourceId];
    });
    if (stale) {
      state.sourceAnalysis.profile = null;
      state.sourceAnalysis.promotionPreview = null;
    }
  }
  if (!packs.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "尚无来源包";
    root.append(empty);
    return;
  }
  packs.forEach((pack) => {
    const row = document.createElement("article");
    row.className = `source-row${state.sourceAnalysis.activeSourceId === pack.source_id ? " active" : ""}`;
    const copy = document.createElement("div");
    copy.className = "source-row-select";
    const selection = document.createElement("input");
    selection.type = "checkbox";
    selection.setAttribute("aria-label", `选择来源 ${pack.source_id}`);
    selection.checked = state.sourceAnalysis.selectedSourceIds.has(pack.source_id);
    selection.disabled = pack.analysis_v2?.status !== "completed";
    selection.addEventListener("change", () => {
      if (selection.checked) state.sourceAnalysis.selectedSourceIds.add(pack.source_id);
      else state.sourceAnalysis.selectedSourceIds.delete(pack.source_id);
      syncSourceAnalysisControls();
    });
    const sourceCopy = document.createElement("div");
    const analysis = pack.analysis_v2 || {};
    const title = document.createElement("strong");
    title.textContent = analysis.relative_name || pack.source_id;
    const sourceId = document.createElement("code");
    sourceId.textContent = pack.source_id;
    const meta = document.createElement("span");
    const statusLabel = {
      pending: "等待分析", running: "分析中", completed: "已完成",
      failed: "部分失败", stale: "需要更新", invalid: "数据异常",
    }[analysis.status] || analysis.status;
    meta.textContent = analysis.status
      ? `${statusLabel} · ${analysis.completed_chunks || 0}/${analysis.total_chunks || 0} 块 · ${formatNumber(analysis.total_chars || 0)} 字符${analysis.failed_chunks ? ` · ${analysis.failed_chunks} 失败` : ""}`
      : [pack.style_ready ? "V1 风格" : "", pack.setting_ready ? "V1 设定" : ""]
        .filter(Boolean).join(" + ") || "待分析";
    const progress = document.createElement("span");
    progress.className = "source-progress";
    const progressFill = document.createElement("i");
    const percent = analysis.total_chunks
      ? Math.round(((analysis.completed_chunks || 0) / analysis.total_chunks) * 100)
      : 0;
    progressFill.style.width = `${percent}%`;
    progress.append(progressFill);
    sourceCopy.append(title, sourceId, meta, progress);
    copy.append(selection, sourceCopy);
    const actions = document.createElement("div");
    actions.className = "row-actions";
    const actionSpecs = analysis.status
      ? [["查看证据", "status_v2"]]
      : [["V1 审阅", "review"]];
    actionSpecs.forEach(([label, action]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "text-button";
      button.textContent = label;
      button.addEventListener("click", () => {
        state.sourceAnalysis.activeSourceId = pack.source_id;
        runSourceAction(action, pack.source_id);
      });
      actions.append(button);
    });
    row.append(copy, actions);
    root.append(row);
  });
  syncSourceAnalysisControls();
}

function syncSourceAnalysisControls() {
  $("#source-synthesize").disabled = state.sourceAnalysis.selectedSourceIds.size < 1;
  $("#source-promotion-preview").disabled = !state.sourceAnalysis.profile;
  $("#source-promotion-apply").disabled = !state.sourceAnalysis.promotionPreview;
}

function sourceFocusValues(mode) {
  if (mode === "narrative") return ["structure", "hook", "thread", "arc_summary", "chapter_summary", "pacing", "voice", "reader_drive", "method"];
  if (mode === "setting") return ["promise", "character", "world", "relationship", "progression", "timeline", "conflict", "risk", "method"];
  return ["promise", "structure", "character", "world", "relationship", "progression", "timeline", "conflict", "hook", "thread", "arc_summary", "chapter_summary", "pacing", "voice", "reader_drive", "method", "risk"];
}

function renderSourceAnalysis(result) {
  const report = result?.report || result?.analysis?.report || null;
  const manifest = result?.manifest || result?.analysis?.manifest || null;
  const root = $("#source-report-actions");
  root.replaceChildren();
  const reportRoot = $("#source-report");
  reportRoot.replaceChildren();
  if (!report) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "当前来源还没有可用报告";
    reportRoot.append(empty);
    return;
  }
  const summary = document.createElement("div");
  summary.className = "source-report-summary";
  const summaryHeader = document.createElement("div");
  const summaryTitle = document.createElement("strong");
  summaryTitle.textContent = manifest?.relative_name || report.source_id;
  const summaryStatus = document.createElement("span");
  summaryStatus.className = `status-badge${report.status === "completed" ? " ready" : ""}`;
  summaryStatus.textContent = report.status === "completed" ? "证据完整" : "报告不完整";
  summaryHeader.append(summaryTitle, summaryStatus);
  const summaryText = document.createElement("p");
  summaryText.textContent = report.summary || "暂无摘要";
  const summaryMeta = document.createElement("span");
  const reportModels = (report.models || []).filter(Boolean);
  summaryMeta.textContent = [
    `${report.findings?.length || 0} 条结论`,
    `${manifest?.chunks?.length || 0} 个分块`,
    reportModels.length ? `模型 ${reportModels.join("、")}` : "",
  ].filter(Boolean).join(" · ");
  summary.append(summaryHeader, summaryText, summaryMeta);
  reportRoot.append(summary);

  const categories = {
    promise: "作品承诺", structure: "结构", character: "人物", conflict: "冲突",
    world: "世界设定", relationship: "人物关系", progression: "成长体系", timeline: "时间线",
    hook: "钩子", thread: "叙事线索", arc_summary: "故事弧摘要", chapter_summary: "章节摘要",
    pacing: "节奏", voice: "声音", reader_drive: "阅读驱动",
    method: "可复用方法", risk: "风险",
  };
  const findings = document.createElement("div");
  findings.className = "source-findings";
  (report.findings || []).forEach((finding) => {
    const item = document.createElement("article");
    item.className = "source-finding";
    const findingHeader = document.createElement("div");
    const category = document.createElement("span");
    category.className = "finding-category";
    category.textContent = categories[finding.category] || finding.category;
    const confidence = document.createElement("span");
    confidence.textContent = `${Math.round(Number(finding.confidence || 0) * 100)}% 置信度`;
    findingHeader.append(category, confidence);
    const claim = document.createElement("strong");
    claim.textContent = finding.claim;
    item.append(findingHeader, claim);
    (finding.evidence || []).forEach((evidence) => {
      const quote = document.createElement("blockquote");
      const quoteText = document.createElement("p");
      quoteText.textContent = evidence.quote;
      const location = document.createElement("cite");
      location.textContent = `L${evidence.line_start}-${evidence.line_end}`;
      quote.append(quoteText, location);
      item.append(quote);
    });
    findings.append(item);
  });
  if (!(report.findings || []).length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "没有生成证据化结论";
    findings.append(empty);
  }
  reportRoot.append(findings);
  (manifest?.chunks || []).filter((chunk) => chunk.status === "failed").forEach((chunk) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quiet-button";
    button.textContent = `重试 ${chunk.index + 1}`;
    button.addEventListener("click", () => retrySourceChunk(manifest.source_id, chunk.chunk_id));
    root.append(button);
  });
}

function referenceAnalysisCounts(analysis) {
  const counts = analysis?.chunks || {};
  const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
  return {
    total,
    completed: Number(counts.completed || 0),
    failed: Number(counts.failed || 0),
  };
}

function renderReferenceLibrary(records, styleSurface) {
  const root = $("#reference-list");
  root.replaceChildren();
  $("#reference-count").textContent = String(records.length);
  $("#reference-complete-count").textContent = String(
    records.filter((item) => item.analysis?.complete).length,
  );
  const currentIds = new Set(records.map((item) => item.record?.source_id));
  Array.from(state.referenceLibrary.selectedSourceIds).forEach((sourceId) => {
    if (!currentIds.has(sourceId)) state.referenceLibrary.selectedSourceIds.delete(sourceId);
  });
  if (!records.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "尚未导入参考作品";
    root.append(empty);
  }
  records.forEach((item) => {
    const record = item.record || {};
    const analysis = item.analysis || {};
    const structure = item.structure || {};
    const counts = referenceAnalysisCounts(analysis);
    const row = document.createElement("article");
    row.className = `source-row${state.referenceLibrary.activeSourceId === record.source_id ? " active" : ""}`;
    const selectWrap = document.createElement("div");
    selectWrap.className = "source-row-select";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.referenceLibrary.selectedSourceIds.has(record.source_id);
    checkbox.disabled = !analysis.complete;
    checkbox.setAttribute("aria-label", `选择参考作品 ${record.title}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.referenceLibrary.selectedSourceIds.add(record.source_id);
      else state.referenceLibrary.selectedSourceIds.delete(record.source_id);
      syncReferenceControls();
    });
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = record.title || record.source_id;
    const id = document.createElement("code");
    id.textContent = record.source_id;
    const meta = document.createElement("span");
    const intent = {
      reference: "参考拆解", continuation: "旧稿续写", canon: "同人 Canon", migration: "项目重建",
    }[record.intent] || record.intent;
    const status = analysis.complete
      ? `已拆解 · ${counts.completed}/${counts.total} 块`
      : structure.status === "confirmed"
        ? `${analysis.status === "failed" ? "拆解失败" : "等待拆解"} · ${counts.completed}/${counts.total} 块`
        : `等待确认结构 · ${structure.units?.length || 0} 个单元`;
    meta.textContent = `${intent} · ${status}`;
    const progress = document.createElement("span");
    progress.className = "source-progress";
    const fill = document.createElement("i");
    fill.style.width = `${counts.total ? Math.round((counts.completed / counts.total) * 100) : 0}%`;
    progress.append(fill);
    copy.append(title, id, meta, progress);
    selectWrap.append(checkbox, copy);
    const actions = document.createElement("div");
    actions.className = "row-actions";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-button";
    button.textContent = analysis.complete
      ? "查看证据"
      : structure.status === "confirmed"
        ? "继续拆解"
        : "确认结构";
    button.addEventListener("click", async () => {
      state.referenceLibrary.activeSourceId = record.source_id;
      if (analysis.complete) await loadReferenceStatus(record.source_id);
      else if (structure.status === "confirmed") await enqueueReferenceAnalysis(record.source_id);
      else await loadReferenceStatus(record.source_id, { showStructure: true });
    });
    actions.append(button);
    row.append(selectWrap, actions);
    root.append(row);
  });
  renderReferenceStyle(styleSurface);
  syncReferenceControls();
}

function syncReferenceControls() {
  $("#reference-synthesize").disabled = state.referenceLibrary.selectedSourceIds.size < 1;
  $("#reference-send-goethe").disabled = !state.referenceLibrary.profile;
  $("#reference-adoption-preview").disabled = !state.referenceLibrary.profile;
  $("#reference-adoption-apply").disabled = !state.referenceLibrary.adoptionPreview;
}

function renderReferenceStructure(payload) {
  const structure = payload?.structure || payload?.result?.structure || null;
  if (!structure) return;
  state.referenceLibrary.pendingStructure = {
    sourceId: structure.source_id,
    structure,
  };
  const panel = $("#reference-structure");
  const root = $("#reference-structure-list");
  root.replaceChildren();
  $("#reference-structure-count").textContent = `${structure.units?.length || 0} 个单元`;
  (structure.units || []).forEach((unit, index) => {
    const row = document.createElement("div");
    row.className = "reference-structure-row";
    const order = document.createElement("span");
    order.textContent = String(index + 1).padStart(2, "0");
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = unit.title;
    const meta = document.createElement("small");
    meta.textContent = `${unit.kind} · ${formatNumber(unit.end - unit.start)} 字符 · ${unit.start}-${unit.end}`;
    copy.append(title, meta);
    row.append(order, copy);
    root.append(row);
  });
  panel.hidden = false;
  $("#reference-status").textContent = "卷章结构已解析，请确认所有原文都被覆盖";
  panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function prepareReference(event) {
  event.preventDefault();
  const file = $("#reference-file").files[0];
  const content = file ? await file.text() : $("#reference-content").value;
  const button = $("#reference-prepare");
  button.disabled = true;
  $("#reference-status").textContent = "正在保存私有快照并解析卷章结构…";
  try {
    const payload = await api("/api/reference-library", {
      method: "POST",
      body: JSON.stringify({
        action: "prepare",
        source_id: $("#reference-id").value.trim(),
        title: $("#reference-title").value.trim(),
        relative_name: file?.name || "pasted-reference.txt",
        intent: $("#reference-intent").value,
        focus: sourceFocusValues($("#reference-focus").value),
        input_budget_tokens: Number($("#reference-input-budget").value || 12000),
        content,
      }),
    });
    state.workspace = payload.workspace;
    renderWorkspace();
    renderReferenceStructure(payload.result);
  } catch (error) {
    $("#reference-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function confirmReferenceStructure() {
  const pending = state.referenceLibrary.pendingStructure;
  if (!pending) return;
  $("#reference-structure-confirm").disabled = true;
  try {
    await api("/api/reference-library", {
      method: "POST",
      body: JSON.stringify({ action: "confirm_structure", source_id: pending.sourceId }),
    });
    $("#reference-structure").hidden = true;
    state.referenceLibrary.pendingStructure = null;
    await enqueueReferenceAnalysis(pending.sourceId);
  } catch (error) {
    $("#reference-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    $("#reference-structure-confirm").disabled = false;
  }
}

async function enqueueReferenceAnalysis(sourceId) {
  $("#reference-status").textContent = "正在加入全文拆解任务…";
  try {
    await enqueueTask(
      "reference_operation",
      { action: "analyze", source_id: sourceId },
      {
        label: "参考作品拆解已加入队列",
        onComplete: async () => {
          await loadWorkspace();
          await loadReferenceStatus(sourceId);
          $("#reference-status").textContent = "参考作品拆解完成";
        },
      },
    );
    $("#reference-status").textContent = "全文拆解正在后台执行";
  } catch (error) {
    $("#reference-status").textContent = error.message;
    showToast(error.message, true);
  }
}

async function loadReferenceStatus(sourceId, options = {}) {
  $("#reference-status").textContent = "正在读取参考作品…";
  try {
    const payload = await api("/api/reference-library", {
      method: "POST",
      body: JSON.stringify({ action: "status", source_id: sourceId }),
    });
    state.workspace = payload.workspace;
    state.referenceLibrary.activeSourceId = sourceId;
    renderWorkspace();
    if (options.showStructure || payload.result.structure?.status !== "confirmed") {
      renderReferenceStructure(payload.result);
    } else {
      renderReferenceEvidence(payload.result);
    }
    $("#reference-status").textContent = "参考作品已加载";
  } catch (error) {
    $("#reference-status").textContent = error.message;
    showToast(error.message, true);
  }
}

function renderReferenceEvidence(status) {
  const root = $("#reference-report");
  root.replaceChildren();
  const record = status.record || {};
  const report = status.analysis?.report || null;
  if (!report) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "当前参考作品还没有完整证据报告";
    root.append(empty);
    return;
  }
  const summary = document.createElement("div");
  summary.className = "source-report-summary";
  const heading = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = record.title || report.source_id;
  const badge = document.createElement("span");
  badge.className = "status-badge ready";
  badge.textContent = "全文证据完整";
  heading.append(title, badge);
  const copy = document.createElement("p");
  copy.textContent = report.summary || "暂无摘要";
  const meta = document.createElement("span");
  meta.textContent = `${report.findings?.length || 0} 条结论 · ${(report.models || []).join("、") || "模型未记录"}`;
  summary.append(heading, copy, meta);
  root.append(summary);
  const findings = document.createElement("div");
  findings.className = "source-findings";
  (report.findings || []).forEach((finding) => {
    const item = document.createElement("article");
    item.className = "source-finding";
    const header = document.createElement("div");
    const category = document.createElement("span");
    category.className = "finding-category";
    category.textContent = finding.category;
    const confidence = document.createElement("span");
    confidence.textContent = `${Math.round(Number(finding.confidence || 0) * 100)}%`;
    header.append(category, confidence);
    const claim = document.createElement("strong");
    claim.textContent = finding.claim;
    item.append(header, claim);
    (finding.evidence || []).forEach((evidence) => {
      const quote = document.createElement("blockquote");
      const text = document.createElement("p");
      text.textContent = evidence.quote;
      const location = document.createElement("cite");
      location.textContent = `L${evidence.line_start}-${evidence.line_end}`;
      quote.append(text, location);
      item.append(quote);
    });
    findings.append(item);
  });
  root.append(findings);
}

async function synthesizeReferenceProfile() {
  const sourceIds = Array.from(state.referenceLibrary.selectedSourceIds);
  if (!sourceIds.length) return;
  $("#reference-status").textContent = "正在生成多作品对照画像…";
  try {
    const payload = await api("/api/reference-library", {
      method: "POST",
      body: JSON.stringify({ action: "synthesize", source_ids: sourceIds }),
    });
    state.referenceLibrary.profile = payload.result;
    state.referenceLibrary.adoptionPreview = null;
    renderReferenceAdoptionEditor(payload.result);
    $("#reference-status").textContent = "对照画像已生成，请逐条决定采用方式";
    syncReferenceControls();
  } catch (error) {
    $("#reference-status").textContent = error.message;
    showToast(error.message, true);
  }
}

function referenceCandidateRow(item, group) {
  const row = document.createElement("article");
  row.className = "reference-candidate-row";
  row.dataset.itemId = item.item_id;
  const selection = document.createElement("input");
  selection.type = "checkbox";
  selection.className = "reference-candidate-check";
  selection.setAttribute("aria-label", `采纳 ${item.claim}`);
  const copy = document.createElement("div");
  copy.className = "reference-candidate-copy";
  const claim = document.createElement("strong");
  claim.textContent = item.claim;
  const meta = document.createElement("span");
  meta.textContent = `${group} · ${item.category || "method"} · ${item.source_bound ? "来源事实" : "可复用"} · ${(item.source_ids || []).join("、")}`;
  copy.append(claim, meta);
  const controls = document.createElement("div");
  controls.className = "reference-candidate-controls";
  const specs = [
    ["target", [["style", "风格配方"], ["rules", "项目规则"], ["inspiration", "灵感候选"], ["setting_candidates", "设定候选"]]],
    ["dimension", [["narration", "叙述"], ["language", "语言"], ["dialogue", "对话"], ["rhythm", "节奏"], ["emotion", "情绪"], ["structure", "结构"], ["craft", "技法"], ["avoid", "避让"]]],
    ["role", [["primary", "主风格"], ["auxiliary", "辅助"], ["validation_only", "仅校验"], ["avoid", "禁用"]]],
    ["scope", [["project", "全书"], ["arc", "故事弧"], ["chapter", "章节"]]],
  ];
  specs.forEach(([name, options]) => {
    const select = document.createElement("select");
    select.className = `reference-candidate-${name}`;
    select.setAttribute("aria-label", name);
    options.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.append(option);
    });
    controls.append(select);
  });
  const scopeId = document.createElement("input");
  scopeId.className = "reference-candidate-scope-id";
  scopeId.placeholder = "arc_001 / ch_007";
  scopeId.setAttribute("aria-label", "适用范围 ID");
  scopeId.hidden = true;
  controls.append(scopeId);
  const target = controls.querySelector(".reference-candidate-target");
  const dimension = controls.querySelector(".reference-candidate-dimension");
  const role = controls.querySelector(".reference-candidate-role");
  const scope = controls.querySelector(".reference-candidate-scope");
  const categoryDefaults = {
    voice: ["style", "narration"],
    pacing: ["style", "rhythm"],
    reader_drive: ["style", "craft"],
    method: ["style", "craft"],
    promise: ["rules", "craft"],
    structure: ["inspiration", "structure"],
    conflict: ["inspiration", "structure"],
    hook: ["inspiration", "structure"],
    thread: ["inspiration", "structure"],
    arc_summary: ["inspiration", "structure"],
    chapter_summary: ["inspiration", "structure"],
    character: ["setting_candidates", "craft"],
    world: ["setting_candidates", "craft"],
    relationship: ["setting_candidates", "craft"],
    progression: ["setting_candidates", "craft"],
    timeline: ["setting_candidates", "structure"],
    risk: ["rules", "avoid"],
  };
  const [defaultTarget, defaultDimension] = categoryDefaults[item.category] || ["inspiration", "craft"];
  target.value = item.source_bound && defaultTarget === "style" ? "inspiration" : defaultTarget;
  dimension.value = defaultDimension;
  role.value = item.category === "risk" ? "avoid" : "auxiliary";
  const syncTargetControls = () => {
    const style = target.value === "style";
    dimension.disabled = !style;
    role.disabled = !style;
  };
  target.addEventListener("change", () => {
    syncTargetControls();
  });
  scope.addEventListener("change", () => {
    scopeId.hidden = scope.value === "project";
    if (scopeId.hidden) scopeId.value = "";
  });
  syncTargetControls();
  row.append(selection, copy, controls);
  return row;
}

function renderReferenceAdoptionEditor(profile) {
  const root = $("#reference-report");
  root.replaceChildren();
  const summary = document.createElement("div");
  summary.className = "source-report-summary profile";
  const header = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = "多作品对照与采纳清单";
  const badge = document.createElement("span");
  badge.className = "status-badge ready";
  badge.textContent = `${profile.source_ids?.length || 0} 部作品`;
  header.append(title, badge);
  const meta = document.createElement("p");
  meta.textContent = `profile ${profile.profile_id}`;
  summary.append(header, meta);
  root.append(summary);
  [
    ["共通方法", profile.common_methods || []],
    ["差异特征", profile.differences || []],
    ["可选变体", profile.optional_variants || []],
  ].forEach(([label, items]) => {
    if (!items.length) return;
    const section = document.createElement("section");
    section.className = "reference-candidate-section";
    const heading = document.createElement("h3");
    heading.textContent = `${label} · ${items.length}`;
    section.append(heading);
    items.forEach((item) => section.append(referenceCandidateRow(item, label)));
    root.append(section);
  });
  if ((profile.conflicts || []).length || (profile.excluded_items || []).length) {
    const details = document.createElement("details");
    details.className = "reference-exclusions";
    const summaryLine = document.createElement("summary");
    summaryLine.textContent = `冲突与自动排除 · ${(profile.conflicts || []).length + (profile.excluded_items || []).length}`;
    const list = document.createElement("ul");
    [...(profile.conflicts || []), ...(profile.excluded_items || [])].forEach((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      list.append(item);
    });
    details.append(summaryLine, list);
    root.append(details);
  }
}

function collectReferenceAdoptionSelections() {
  return Array.from($$(".reference-candidate-row"))
    .filter((row) => row.querySelector(".reference-candidate-check").checked)
    .map((row) => ({
      item_id: row.dataset.itemId,
      target: row.querySelector(".reference-candidate-target").value,
      dimension: row.querySelector(".reference-candidate-dimension").value,
      role: row.querySelector(".reference-candidate-role").value,
      scope: row.querySelector(".reference-candidate-scope").value,
      scope_id: row.querySelector(".reference-candidate-scope-id").value.trim(),
    }));
}

async function previewReferenceAdoption() {
  const profile = state.referenceLibrary.profile;
  if (!profile) return;
  const selections = collectReferenceAdoptionSelections();
  if (!selections.length) {
    showToast("请至少勾选一条候选", true);
    return;
  }
  try {
    const payload = await api("/api/reference-library", {
      method: "POST",
      body: JSON.stringify({
        action: "adoption_preview",
        profile_id: profile.profile_id,
        selections,
      }),
    });
    state.referenceLibrary.adoptionPreview = payload.result;
    const root = $("#reference-report");
    root.replaceChildren();
    const summary = document.createElement("div");
    summary.className = "source-report-summary";
    const title = document.createElement("strong");
    title.textContent = "项目采纳预览";
    const meta = document.createElement("span");
    meta.textContent = `${payload.result.adoption?.selections?.length || 0} 条采用 · ${payload.result.adoption?.rejected_item_ids?.length || 0} 条不采用`;
    summary.append(title, meta);
    const diff = document.createElement("pre");
    diff.className = "context-preview promotion-diff";
    diff.textContent = payload.result.unified_diff || "目标文件无变化";
    root.append(summary, diff);
    $("#reference-status").textContent = "采纳差异已生成，尚未写入项目";
    syncReferenceControls();
  } catch (error) {
    $("#reference-status").textContent = error.message;
    showToast(error.message, true);
  }
}

async function applyReferenceAdoption() {
  const preview = state.referenceLibrary.adoptionPreview;
  if (!preview) return;
  $("#reference-adoption-apply").disabled = true;
  try {
    const payload = await api("/api/reference-library", {
      method: "POST",
      body: JSON.stringify({
        action: "adopt",
        preview_id: preview.preview_id,
        confirm: true,
      }),
    });
    state.referenceLibrary.adoptionPreview = null;
    state.workspace = payload.workspace;
    renderWorkspace();
    $("#reference-status").textContent = "采纳快照和风格运行文件已更新";
    showToast("风格配方已确认");
  } catch (error) {
    $("#reference-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    syncReferenceControls();
  }
}

function sendReferenceProfileToGoethe() {
  const profile = state.referenceLibrary.profile;
  if (!profile) return;
  chooseAgent("goethe");
  setView("agents");
  const input = $("#chat-input");
  input.value = `请审议参考画像 ${profile.profile_id}。结合当前作者意图和创作罗盘，逐条说明建议采用、改写或拒绝哪些方法，并给出风格维度、主辅角色和适用范围。不要读取或复述整本原文，只引用证据化结论。`;
  input.focus();
}

function renderReferenceStyle(surface) {
  const root = $("#reference-style-recipe");
  root.replaceChildren();
  const selections = surface?.selections || [];
  const status = $("#reference-style-status");
  status.textContent = selections.length ? `${selections.length} 条已采用` : "尚未配置";
  status.classList.toggle("ready", selections.length > 0);
  if (!selections.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "确认采纳后，Writer 使用的风格说明和 Reviewer 使用的指纹目标会显示在这里。";
    root.append(empty);
    return;
  }
  const groups = new Map();
  selections.forEach((item) => {
    const key = item.dimension || "craft";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  groups.forEach((items, dimension) => {
    const section = document.createElement("section");
    const heading = document.createElement("h3");
    heading.textContent = dimension;
    section.append(heading);
    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "reference-style-row";
      const claim = document.createElement("strong");
      claim.textContent = item.claim;
      const meta = document.createElement("span");
      meta.textContent = `${item.role} · ${item.scope}${item.scope_id ? ` ${item.scope_id}` : ""}`;
      row.append(claim, meta);
      section.append(row);
    });
    root.append(section);
  });
  const targets = surface.fingerprint?.targets || {};
  if (Object.keys(targets).length) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Reviewer 指纹目标";
    const metrics = document.createElement("div");
    metrics.className = "reference-fingerprint-targets";
    Object.entries(targets).forEach(([name, range]) => {
      const metric = document.createElement("span");
      metric.textContent = `${name} ${range.min}-${range.max}`;
      metrics.append(metric);
    });
    details.append(summary, metrics);
    root.append(details);
  }
}

async function runSync() {
  const button = $("#sync-project");
  button.disabled = true;
  $("#sync-status").textContent = "正在同步大纲与角色卡…";
  try {
    const payload = await api("/api/sync", { method: "POST", body: "{}" });
    state.workspace = payload.workspace;
    renderWorkspace();
    showToast("src 与 data 已同步");
  } catch (error) {
    $("#sync-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function inspectContext(event) {
  event.preventDefault();
  const chapter = $("#context-chapter").value.trim() || "next";
  $("#context-meta").textContent = "正在组装上下文…";
  try {
    const payload = await api(`/api/context?chapter=${encodeURIComponent(chapter)}`);
    const manifest = payload.manifest || {};
    const semanticRetrieval = payload.semantic_retrieval || {};
    const semanticResultCount = Number(semanticRetrieval.results || 0);
    const semanticMeta = semanticRetrieval.status === "ready"
      ? ` · 语义召回 ${formatNumber(semanticResultCount)} 条`
      : "";
    $("#context-meta").textContent = `${payload.chapter_id} · 目标 ${formatNumber(payload.target_words)} 字 · ${payload.characters.length} 位相关人物 · 上下文 ${formatNumber(manifest.estimated_tokens)} tokens${semanticMeta} · revision ${manifest.revision || "-"}`;
    const provenance = (manifest.items || []).map((item) => {
      const sources = (item.sources || []).map((source) => source.path).join(", ");
      return `L${item.level} ${item.section} · ${item.estimated_tokens} tokens · ${sources}`;
    }).join("\n");
    const sections = [];
    if (provenance) sections.push(`【上下文来源】\n${provenance}`);
    if (String(payload.character_states || "").trim()) {
      sections.push(`【精确人物状态】\n${payload.character_states.trim()}`);
    }
    if (String(payload.semantic_references || "").trim()) {
      sections.push(`【语义远距记忆（仅供参考）】\n${payload.semantic_references.trim()}`);
    }
    sections.push(`【Canonical Packet】\n${payload.markdown || "上下文为空"}`);
    $("#context-preview").textContent = sections.join("\n\n");
  } catch (error) {
    $("#context-meta").textContent = error.message;
    showToast(error.message, true);
  }
}

function renderTransferSummary() {
  const snapshot = state.workspace?.snapshot || {};
  const chapterCount = Number(snapshot.chapters || 0);
  const writingUnits = Number(snapshot.writing_units || 0);
  $("#transfer-chapter-count").textContent = formatNumber(chapterCount);
  $("#transfer-writing-units").textContent = formatNumber(writingUnits);
  $("#export-book-title").textContent = snapshot.title || "当前作品";
  $("#export-book-range").textContent = `${formatNumber(chapterCount)} 章 · ${formatNumber(writingUnits)} 字`;
  $("#export-readiness").textContent = chapterCount ? "可导出" : "等待正文";
  $("#export-readiness").classList.toggle("ready", chapterCount > 0);
  syncExportFormat();
}

function syncExportFormat() {
  const selected = $('input[name="export-format"]:checked')?.value || "md";
  const chapters = Number(state.workspace?.snapshot?.chapters || 0);
  const labels = { md: "下载 Markdown", txt: "下载纯文本", epub: "下载 EPUB" };
  $$(".export-format").forEach((item) => {
    item.classList.toggle("active", item.querySelector("input")?.checked);
  });
  const download = $("#export-download");
  download.textContent = labels[selected];
  download.classList.toggle("disabled", !chapters);
  download.setAttribute("aria-disabled", String(!chapters));
  if (chapters) download.href = `/api/export?format=${encodeURIComponent(selected)}`;
  else download.removeAttribute("href");
}

function invalidateImportPreview() {
  state.transfer.importPreview = null;
  state.transfer.importContent = "";
  $("#import-submit").disabled = true;
  $("#import-preview").replaceChildren();
  const empty = document.createElement("p");
  empty.className = "empty-state";
  empty.textContent = "重新解析后可确认导入。";
  $("#import-preview").append(empty);
}

async function importPayload() {
  const file = $("#import-file").files[0];
  if (!file) throw new Error("请选择 TXT 或 Markdown 正文文件");
  const content = await file.text();
  return {
    filename: file.name,
    content,
    arc_id: $("#import-arc").value.trim(),
    start_number: $("#import-start").value,
    force: $("#import-force").checked,
  };
}

function renderImportPreview(preview) {
  const root = $("#import-preview");
  root.replaceChildren();
  const summary = document.createElement("div");
  summary.className = `import-preview-summary${preview.can_import ? " ready" : " conflict"}`;
  const copy = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = `${preview.chapter_count} 章 · ${formatNumber(preview.writing_units)} 字`;
  const detail = document.createElement("span");
  detail.textContent = `${preview.arc_id} · 从 ch_${String(preview.start_number).padStart(3, "0")} 开始`;
  copy.append(title, detail);
  const status = document.createElement("span");
  status.className = "status-badge";
  status.textContent = preview.can_import ? "可以导入" : `${preview.conflicts.length} 个冲突`;
  summary.append(copy, status);
  root.append(summary);

  const list = document.createElement("ol");
  list.className = "import-chapter-list";
  preview.chapters.forEach((chapter) => {
    const item = document.createElement("li");
    item.classList.toggle("conflict", chapter.exists);
    const id = document.createElement("code");
    id.textContent = chapter.chapter_id;
    const chapterCopy = document.createElement("div");
    const chapterTitle = document.createElement("strong");
    chapterTitle.textContent = chapter.title;
    const chapterMeta = document.createElement("span");
    chapterMeta.textContent = `${formatNumber(chapter.writing_units)} 字${chapter.exists ? " · 已存在" : ""}`;
    chapterCopy.append(chapterTitle, chapterMeta);
    item.append(id, chapterCopy);
    list.append(item);
  });
  root.append(list);
  $("#import-submit").disabled = !preview.can_import;
}

async function previewImport() {
  const button = $("#import-preview-button");
  button.disabled = true;
  $("#import-status").textContent = "正在解析章节边界…";
  try {
    const payload = await importPayload();
    const preview = await api("/api/import/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.transfer.importPreview = preview;
    state.transfer.importContent = payload.content;
    renderImportPreview(preview);
    $("#import-status").textContent = preview.can_import
      ? "解析完成，请核对章节后确认导入"
      : "发现已存在章节；调整起始章节，或启用覆盖后重新解析";
  } catch (error) {
    invalidateImportPreview();
    $("#import-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function importText(event) {
  event.preventDefault();
  const preview = state.transfer.importPreview;
  if (!preview?.can_import || !state.transfer.importContent) {
    $("#import-status").textContent = "请先解析并核对导入预览";
    return;
  }
  const file = $("#import-file").files[0];
  if (!file) return;
  const button = $("#import-submit");
  button.disabled = true;
  $("#import-status").textContent = "正在导入已确认的章节…";
  try {
    await enqueueTask(
      "manuscript_import",
      {
        filename: file.name,
        content: state.transfer.importContent,
        arc_id: preview.arc_id,
        start_number: preview.start_number,
        force: preview.force,
      },
      {
        label: "旧稿导入任务已加入队列",
        onComplete: async (task) => {
          await loadWorkspace();
          const count = task.result?.imported?.length || 0;
          $("#import-status").textContent = `已导入 ${count} 章`;
          $("#import-file").value = "";
          invalidateImportPreview();
          showToast(`已导入 ${count} 章正文`);
        },
      },
    );
    $("#import-status").textContent = "导入任务正在后台执行";
  } catch (error) {
    $("#import-status").textContent = error.message;
    showToast(error.message, true);
    button.disabled = false;
  }
}

async function createDocument(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const payload = await api("/api/document/create", {
      method: "POST",
      body: JSON.stringify({
        kind: $("#create-kind").value,
        name: $("#create-name").value,
        description: $("#create-description").value,
      }),
    });
    state.workspace = payload.workspace;
    renderWorkspace();
    $("#create-status").textContent = "文档已创建";
    form.reset();
    await openProjectPath(payload.document.path, true);
  } catch (error) {
    $("#create-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function submitChat(event) {
  event.preventDefault();
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) return;
  const requestAgent = state.agent;
  const tourAction = requestAgent === "goethe" ? state.productTour.step : "";
  const sessionId = activeAgentSessionId(requestAgent);
  appendChatMessage("user", "你", message);
  input.value = "";
  $("#chat-submit").disabled = true;
  $$('[data-agent]').forEach((button) => { button.disabled = true; });
  $$(".agent-session-item").forEach((button) => { button.disabled = true; });
  $("#chat-status").textContent = `${requestAgent === "goethe" ? "Goethe" : "Dante"} 正在处理…`;
  const runId = startAgentActivity(requestAgent, message);
  advanceProductTourAfterAction(tourAction);
  try {
    const payload = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        agent: requestAgent,
        session_id: sessionId,
        run_id: runId,
        message,
      }),
    });
    state.agentSessionId[requestAgent] = payload.session_id || sessionId;
    await finishAgentActivity("complete");
    appendChatMessage(
      "assistant",
      requestAgent === "goethe" ? "Goethe" : "Dante",
      payload.content || "本轮已执行完成。",
      payload.content_html || "",
    );
    state.workspace = payload.workspace;
    renderWorkspace();
    await loadAgentSurface(requestAgent, activeAgentSessionId(requestAgent), { preserveHistory: true });
  } catch (error) {
    await finishAgentActivity("error", error.message);
    appendChatMessage("assistant error", "系统", error.message);
  } finally {
    $("#chat-submit").disabled = false;
    $$('[data-agent]').forEach((button) => { button.disabled = false; });
    $("#chat-status").textContent = "";
    input.focus();
  }
}

function appendChatMessage(role, author, content, renderedHtml = "") {
  const log = $("#chat-log");
  const follow = chatLogNearBottom(log);
  const item = document.createElement("article");
  item.className = `chat-message ${role}`;
  const name = document.createElement("strong");
  name.textContent = author;
  const body = document.createElement(renderedHtml ? "div" : "p");
  if (renderedHtml) {
    body.className = "chat-markdown";
    appendSafeChatMarkup(body, renderedHtml, content);
  } else {
    body.textContent = content;
  }
  item.append(name, body);
  log.append(item);
  if (follow) item.scrollIntoView({ block: "end", behavior: "smooth" });
  return item;
}

function startAgentActivity(agent, message) {
  const template = $("#agent-activity-template");
  if (!template) return "";
  if (state.agentActivity.timer) clearInterval(state.agentActivity.timer);
  const log = $("#chat-log");
  const follow = chatLogNearBottom(log);
  const root = template.content.firstElementChild.cloneNode(true);
  state.agentActivity.startedAt = Date.now();
  state.agentActivity.agentLabel = agent === "goethe" ? "Goethe" : "Dante";
  state.agentActivity.baseNote = summarizeAgentActivityMessage(message);
  state.agentActivity.runId = createAgentRunId();
  state.agentActivity.pollPromise = null;
  state.agentActivity.serverTitle = `${state.agentActivity.agentLabel} 正在读取项目`;
  state.agentActivity.serverNote = "正在恢复会话、作品状态和本轮上下文。";
  state.agentActivity.root = root;
  state.agentActivity.eventList = root.querySelector(".agent-activity-events");
  state.agentActivity.lastSequence = 0;
  state.agentActivity.eventCount = 0;
  state.agentActivity.lastEventName = "";
  root.dataset.runId = state.agentActivity.runId;
  root.querySelector(".agent-activity-title").textContent = `${state.agentActivity.agentLabel} 正在工作`;
  root.querySelector(".agent-activity-note").textContent = state.agentActivity.baseNote;
  renderAgentActivityEvent({ event: "connecting", timestamp: Date.now() / 1000 }, { synthetic: true });
  log.append(root);
  if (follow) root.scrollIntoView({ block: "end", behavior: "smooth" });
  updateAgentActivity();
  state.agentActivity.timer = setInterval(() => {
    updateAgentActivity();
    pollAgentActivity();
  }, 700);
  setTimeout(() => {
    if (state.agentActivity.runId === root.dataset.runId) pollAgentActivity();
  }, 120);
  return state.agentActivity.runId;
}

function updateAgentActivity() {
  const root = state.agentActivity.root;
  if (!root) return;
  const elapsed = Math.max(0, Math.floor((Date.now() - state.agentActivity.startedAt) / 1000));
  const longRunning = elapsed >= 5 * 60;
  const possiblyStuck = elapsed >= 15 * 60;
  root.classList.toggle("long-running", longRunning && !possiblyStuck);
  root.classList.toggle("possibly-stuck", possiblyStuck);
  if (possiblyStuck) {
    root.querySelector(".agent-activity-title").textContent = `${state.agentActivity.agentLabel} 可能异常`;
    root.querySelector(".agent-activity-note").textContent = `${state.agentActivity.serverNote || "后台没有返回新状态。"} 已运行超过 15 分钟，请查看 debug 日志。`;
  } else if (longRunning) {
    root.querySelector(".agent-activity-title").textContent = `${state.agentActivity.agentLabel} 耗时较久`;
    root.querySelector(".agent-activity-note").textContent = `${state.agentActivity.serverNote || "正在等待后台返回。"} 已运行超过 5 分钟。`;
  } else {
    root.querySelector(".agent-activity-title").textContent = state.agentActivity.serverTitle
      || `${state.agentActivity.agentLabel} 正在工作`;
    root.querySelector(".agent-activity-note").textContent = state.agentActivity.serverNote
      || state.agentActivity.baseNote;
  }
  root.querySelector(".agent-activity-elapsed").textContent = formatDuration(elapsed);
  root.querySelector(".agent-activity-count").textContent = state.agentActivity.eventCount
    ? `${state.agentActivity.eventCount} 条动态`
    : "正在连接";
}

function pollAgentActivity() {
  const runId = state.agentActivity.runId;
  if (!runId) return Promise.resolve(null);
  if (state.agentActivity.pollPromise) return state.agentActivity.pollPromise;
  const request = (async () => {
    try {
      const payload = await api(`/api/agent/activity?run_id=${encodeURIComponent(runId)}`);
      if (payload.run_id !== state.agentActivity.runId) return null;
      state.agentActivity.serverTitle = payload.title || "";
      state.agentActivity.serverNote = payload.note || "";
      renderAgentActivityEvents(payload.events || []);
      updateAgentActivity();
      return payload;
    } catch (error) {
      if (error.status !== 404) {
        state.agentActivity.serverNote = `活动状态读取失败：${error.message}`;
        updateAgentActivity();
      }
      return null;
    } finally {
      if (state.agentActivity.pollPromise === request) {
        state.agentActivity.pollPromise = null;
      }
    }
  })();
  state.agentActivity.pollPromise = request;
  return request;
}

function createAgentRunId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `run-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function finishAgentActivity(status, message = "") {
  const root = state.agentActivity.root;
  if (!root) return;
  if (state.agentActivity.timer) {
    clearInterval(state.agentActivity.timer);
    state.agentActivity.timer = null;
  }
  await pollAgentActivity();
  const complete = status === "complete";
  root.classList.toggle("complete", complete);
  root.classList.toggle("error", !complete);
  root.classList.remove("long-running", "possibly-stuck");
  if (!["run_completed", "run_failed"].includes(state.agentActivity.lastEventName)) {
    renderAgentActivityEvent({
      event: complete ? "run_completed" : "run_failed",
      reason: complete ? "" : message,
      timestamp: Date.now() / 1000,
    });
  }
  root.querySelector(".agent-activity-events .active")?.classList.remove("active");
  state.agentActivity.serverTitle = complete ? "AI 本轮已完成" : "AI 本轮中断";
  state.agentActivity.serverNote = complete
    ? "回复已写入当前会话历史。"
    : (message || "请求未完成，请检查模型连接或稍后重试。");
  updateAgentActivity();
}

function renderAgentActivityEvents(events) {
  const incoming = [...events].sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0));
  incoming.forEach((activityEvent) => {
    const sequence = Number(activityEvent.sequence || 0);
    if (sequence <= state.agentActivity.lastSequence) return;
    state.agentActivity.eventList?.querySelector(".event-connecting")?.remove();
    renderAgentActivityEvent(activityEvent);
    state.agentActivity.lastSequence = sequence;
  });
}

function renderAgentActivityEvent(activityEvent, options = {}) {
  const list = state.agentActivity.eventList;
  if (!list) return;
  const follow = chatLogNearBottom($("#chat-log"));
  list.querySelector(".active")?.classList.remove("active");
  const item = document.createElement("li");
  const eventName = String(activityEvent.event || "").replace(/[^a-z_]/g, "") || "unknown";
  const failed = activityEvent.ok === false || eventName === "run_failed";
  const terminal = ["run_completed", "run_failed"].includes(eventName);
  item.className = `agent-activity-event event-${eventName}${failed ? " failed" : ""}${terminal ? " terminal" : " active"}`;
  const marker = document.createElement("span");
  marker.className = "agent-activity-event-marker";
  marker.setAttribute("aria-hidden", "true");
  const content = document.createElement("div");
  content.className = "agent-activity-event-content";
  const heading = document.createElement("div");
  heading.className = "agent-activity-event-heading";
  const title = document.createElement("strong");
  title.textContent = describeAgentActivityEvent(activityEvent);
  const meta = document.createElement("span");
  meta.textContent = formatAgentActivityOffset(activityEvent.timestamp);
  heading.append(title, meta);
  content.append(heading);
  if (activityEvent.message) {
    const modelMessage = document.createElement("p");
    modelMessage.className = "agent-activity-message";
    modelMessage.textContent = activityEvent.message;
    content.append(modelMessage);
  }
  if (activityEvent.reason) {
    const reason = document.createElement("p");
    reason.className = "agent-activity-reason";
    reason.textContent = activityEvent.reason;
    content.append(reason);
  }
  appendAgentActivityDetail(content, "查看参数", activityEvent.arguments);
  appendAgentActivityDetail(content, "查看结果", activityEvent.result);
  item.append(marker, content);
  list.append(item);
  state.agentActivity.lastEventName = eventName;
  if (!options.synthetic) state.agentActivity.eventCount += 1;
  if (follow) item.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function describeAgentActivityEvent(activityEvent) {
  const turn = Number(activityEvent.turn || 0);
  const toolLabel = activityEvent.tool_label || activityEvent.tool || "项目工具";
  switch (activityEvent.event) {
    case "connecting": return "连接 Agent 运行时";
    case "run_started": return "已载入作品与会话";
    case "model_started": return turn ? `分析第 ${turn} 轮` : "分析本轮目标";
    case "model_completed": return Number(activityEvent.tool_count || 0)
      ? `决定调用 ${Number(activityEvent.tool_count)} 个工具`
      : "本轮分析完成";
    case "model_retry": return `模型输出校验失败，自动修复第 ${Number(activityEvent.repair_attempt || 1)} 次`;
    case "tool_started": return `调用 ${toolLabel}`;
    case "tool_completed": return `${toolLabel}${activityEvent.ok === false ? "失败" : "返回结果"}`;
    case "response_ready": return "整理最终回复";
    case "run_completed": return "本轮执行完成";
    case "run_failed": return "本轮执行停止";
    default: return "Agent 状态已更新";
  }
}

function appendAgentActivityDetail(container, label, value) {
  if (!value) return;
  const details = document.createElement("details");
  details.className = "agent-activity-event-detail";
  const summary = document.createElement("summary");
  summary.textContent = label;
  const body = document.createElement("pre");
  body.textContent = value;
  details.append(summary, body);
  container.append(details);
}

function formatAgentActivityOffset(timestamp) {
  const eventTime = Number(timestamp || 0) * 1000;
  if (!eventTime) return "";
  return `+${formatDuration(Math.max(0, Math.floor((eventTime - state.agentActivity.startedAt) / 1000)))}`;
}

function chatLogNearBottom(log) {
  if (!log) return false;
  return log.scrollHeight - log.scrollTop - log.clientHeight < 96;
}

function summarizeAgentActivityMessage(message) {
  const compact = String(message || "").replace(/\s+/g, " ").trim();
  if (!compact) return "保持此页打开，完成后会自动写入当前会话。";
  return compact.length > 58
    ? `本轮目标：${compact.slice(0, 58)}...`
    : `本轮目标：${compact}`;
}

function formatDuration(seconds) {
  const safe = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function chooseAgent(agent) {
  state.agent = agent;
  $$('[data-agent]').forEach((button) => button.classList.toggle("active", button.dataset.agent === agent));
  syncNavigationState(state.view);
  $("#chat-submit").textContent = `发送给 ${agent === "goethe" ? "Goethe" : "Dante"}`;
  $("#chat-input").placeholder = agent === "goethe"
    ? "例如：我想写一本……先帮我收敛题材、冲突和主角。"
    : "例如：写下一章，控制在 3000 字，保持当前创作罗盘。";
  loadAgentSurface(agent, activeAgentSessionId(agent));
  updateRoutedModelIndicator();
}

function emptyDocumentTip(group) {
  if (group === "chapters") {
    return "尚无正文。资产就绪后打开 Dante，从第一章开始写。";
  }
  if (group === "characters") {
    return "尚无角色。在 Goethe 说「创建主角…」，或在这里新建角色。";
  }
  if (group === "core") {
    return "作品核心仍是模板。打开 Goethe 先聊创作承诺与故事基础。";
  }
  if (group === "outline") {
    return "大纲仍是模板。找 Goethe 生成首版可写范围大纲。";
  }
  if (group === "settings") {
    return "暂无设定。可先写角色与大纲，再补地点、组织或规则体系。";
  }
  return "暂无文档";
}

function agentEmptyGuidance(agent) {
  const readiness = state.workspace?.snapshot?.readiness || {};
  const missing = Object.entries(readinessLabels)
    .filter(([key]) => !readiness[key])
    .map(([, label]) => label);
  const items = normalizeNextActions(
    state.workspace?.snapshot?.next_action_items || state.workspace?.snapshot?.next_actions || [],
  );
  const seed = items[0]?.seed || "";
  if (agent === "goethe") {
    const gap = missing.length ? `当前缺口：${missing.join("、")}。` : "主要资产已就绪，可检查后交接 Dante。";
    return [
      "Goethe 负责把脑洞收敛成可写资产。",
      gap,
      "建议顺序：书名题材 → 一句话冲突 → 风格禁忌 → 背景人物大纲 → 交接 Dante。",
      seed ? `可以直接发送：${seed}` : "直接描述你的想法即可开始。",
    ].join("\n");
  }
  const writingReady = ["author_intent", "background", "characters", "outline"]
    .every((key) => readiness[key]);
  if (!writingReady) {
    return [
      "Dante 负责持续写正文，但当前写作资产尚未就绪。",
      missing.length ? `缺口：${missing.join("、")}。` : "",
      "请先切换到 Goethe 补齐，再回来预检并写章。",
    ].filter(Boolean).join("\n");
  }
  return [
    "Dante 可以基于已确认大纲推进正文。",
    "建议：先定位章纲，再预检、写作、审查与状态结算。",
    seed || "例如：按当前大纲写下一章。",
  ].join("\n");
}

function activeAgentSessionId(agent = state.agent) {
  return state.agentSessionId[agent] || "default";
}

async function loadAgentSurface(agent, sessionId = activeAgentSessionId(agent), options = {}) {
  $("#agent-history-title").textContent = `${agent === "goethe" ? "Goethe" : "Dante"} 历史对话`;
  $("#agent-history-status").textContent = "正在恢复…";
  $("#agent-tools-summary").textContent = `${agent === "goethe" ? "Goethe" : "Dante"} Tools · 载入中`;
  $("#agent-tools-list").textContent = "";
  try {
    const payload = await api(`/api/agents?agent=${encodeURIComponent(agent)}&session_id=${encodeURIComponent(sessionId)}&limit=80`);
    state.agentSessionId[payload.agent] = payload.active_session_id || sessionId || "default";
    state.agentSessions[payload.agent] = payload.sessions || [];
    renderAgentSessions(payload.agent, state.agentSessions[payload.agent], state.agentSessionId[payload.agent]);
    renderAgentTools(payload.agent, payload.tools || []);
    if (options.preserveHistory) {
      renderAgentHistoryStatus(payload.agent, payload.history || {}, state.agentSessionId[payload.agent]);
    } else {
      renderAgentHistory(payload.agent, payload.history || {}, state.agentSessionId[payload.agent]);
    }
  } catch (error) {
    $("#agent-history-status").textContent = error.message;
    $("#agent-tools-summary").textContent = `${agent === "goethe" ? "Goethe" : "Dante"} Tools · 载入失败`;
  }
}

async function createAgentSession() {
  const button = $("#agent-session-new");
  button.disabled = true;
  $("#agent-history-status").textContent = "正在创建新会话…";
  try {
    const payload = await api("/api/agent/session", {
      method: "POST",
      body: JSON.stringify({ agent: state.agent }),
    });
    state.agentSessionId[payload.agent] = payload.active_session_id || "default";
    state.agentSessions[payload.agent] = payload.sessions || [];
    renderAgentSessions(payload.agent, state.agentSessions[payload.agent], state.agentSessionId[payload.agent]);
    renderAgentTools(payload.agent, payload.tools || []);
    renderAgentHistory(payload.agent, payload.history || {}, state.agentSessionId[payload.agent]);
    $("#chat-input").focus();
  } catch (error) {
    $("#agent-history-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function deleteAgentSession() {
  const sessionId = activeAgentSessionId();
  if (!sessionId) return;
  const session = (state.agentSessions[state.agent] || []).find((item) => item.id === sessionId);
  const title = session?.title || sessionId;
  const agentLabel = state.agent === "goethe" ? "Goethe" : "Dante";
  const clearingDefault = sessionId === "default";
  const prompt = clearingDefault
    ? `清空 ${agentLabel} 初始会话的全部记录？\n\n聊天、上下文摘要和工作记忆都会清除，小说资产不受影响。此操作不可撤销。`
    : `删除 ${agentLabel} 会话「${title}」？这只会删除聊天记录，不会删除小说资产。`;
  const confirmed = window.confirm(prompt);
  if (!confirmed) return;
  const button = $("#agent-session-delete");
  button.disabled = true;
  $("#agent-history-status").textContent = "正在删除会话…";
  try {
    const payload = await api("/api/agent/session/delete", {
      method: "POST",
      body: JSON.stringify({ agent: state.agent, session_id: sessionId }),
    });
    state.agentSessionId[payload.agent] = payload.active_session_id || "default";
    state.agentSessions[payload.agent] = payload.sessions || [];
    renderAgentSessions(payload.agent, state.agentSessions[payload.agent], state.agentSessionId[payload.agent]);
    renderAgentTools(payload.agent, payload.tools || []);
    renderAgentHistory(payload.agent, payload.history || {}, state.agentSessionId[payload.agent]);
    showToast(clearingDefault ? "初始会话已清空" : "会话记录已删除");
    $("#chat-input").focus();
  } catch (error) {
    $("#agent-history-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    updateAgentSessionDeleteButton();
  }
}

function switchAgentSession(agent, sessionId) {
  if (!sessionId || sessionId === activeAgentSessionId(agent)) return;
  state.agentSessionId[agent] = sessionId;
  loadAgentSurface(agent, sessionId);
}

function updateAgentSessionDeleteButton() {
  const button = $("#agent-session-delete");
  if (!button) return;
  const sessionId = activeAgentSessionId();
  const session = (state.agentSessions[state.agent] || []).find((item) => item.id === sessionId);
  const clearingDefault = sessionId === "default";
  const canDelete = Boolean(sessionId && (!clearingDefault || session?.exists));
  button.disabled = !canDelete;
  button.textContent = clearingDefault ? "清空" : "删除";
  button.title = canDelete
    ? (clearingDefault ? "清空初始会话记录" : "删除当前会话记录")
    : "初始会话暂无记录";
}

function renderAgentSessions(agent, sessions, activeSessionId) {
  const root = $("#agent-session-list");
  root.replaceChildren();
  (sessions || []).forEach((session) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "agent-session-item";
    item.dataset.sessionId = session.id;
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", String(session.id === activeSessionId));
    item.classList.toggle("active", session.id === activeSessionId);
    const title = document.createElement("strong");
    title.textContent = session.title || (session.is_default ? "初始会话" : "新会话");
    const meta = document.createElement("span");
    meta.textContent = `${Number(session.messages || 0)} 条 · ${formatAgentSessionTime(session.updated_at)}`;
    const preview = document.createElement("small");
    preview.textContent = session.preview || session.transcript_path || "";
    item.append(title, meta, preview);
    item.addEventListener("click", () => switchAgentSession(agent, session.id));
    root.append(item);
  });
  updateAgentSessionDeleteButton();
  if (!root.children.length) {
    const empty = document.createElement("p");
    empty.className = "form-status";
    empty.textContent = "暂无会话";
    root.append(empty);
  }
}

function formatAgentSessionTime(value) {
  if (!value) return "未开始";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function renderAgentTools(agent, tools) {
  const label = agent === "goethe" ? "Goethe" : "Dante";
  $("#agent-tools-summary").textContent = `${label} Tools · ${tools.length}`;
  const root = $("#agent-tools-list");
  root.replaceChildren();
  tools.forEach((tool) => {
    const item = document.createElement("article");
    item.className = "agent-tool";
    const name = document.createElement("strong");
    name.textContent = tool.name;
    const kind = document.createElement("span");
    kind.textContent = tool.kind;
    const description = document.createElement("p");
    description.textContent = tool.description || "";
    item.append(name, kind, description);
    root.append(item);
  });
  if (!tools.length) root.textContent = "暂无工具";
}

function renderAgentHistory(agent, history, sessionId = "default") {
  const messages = history.messages || [];
  renderAgentHistoryStatus(agent, history, sessionId);
  $("#chat-log").replaceChildren();
  if (!messages.length) {
    appendChatMessage("assistant", "OpenWrite", agentEmptyGuidance(agent));
    return;
  }
  messages.forEach((message) => {
    appendChatMessage(
      message.role,
      message.role === "user" ? "你" : (agent === "goethe" ? "Goethe" : "Dante"),
      message.content,
      message.content_html || "",
    );
  });
}

function renderAgentHistoryStatus(agent, history, sessionId = "default") {
  const messages = history.messages || [];
  const label = agent === "goethe" ? "Goethe" : "Dante";
  const sessionName = sessionId === "default" ? "初始会话" : "当前会话";
  $("#agent-history-title").textContent = `${label} 历史对话`;
  $("#agent-history-status").textContent = messages.length
    ? `${sessionName} · 显示 ${history.shown || messages.length} / ${history.total || messages.length}`
    : `${sessionName} · 暂无历史`;
}

async function loadContinuity() {
  $("#truth-current").textContent = "载入中…";
  try {
    state.continuity = await api("/api/continuity");
    renderContinuity();
  } catch (error) {
    $("#truth-current").textContent = error.message;
    showToast(error.message, true);
  }
}

function renderContinuity() {
  const data = state.continuity || {};
  const truth = data.truth || {};
  $("#truth-current").textContent = truth.current_state || "尚无状态";
  $("#truth-ledger").textContent = truth.ledger || "尚无账本";
  $("#truth-relationships").textContent = truth.relationships || "尚无关系记录";
  renderRelationshipGraph(data.relationship_graph || {});
  const nodes = data.foreshadowing?.nodes || [];
  $("#foreshadow-count").textContent = String(nodes.length);
  const hookRoot = $("#foreshadow-list");
  hookRoot.replaceChildren();
  nodes.forEach((node) => {
    const row = document.createElement("div");
    row.className = "operation-row stacked";
    const heading = document.createElement("strong");
    heading.textContent = `${node.id} · 权重 ${node.weight}`;
    const content = document.createElement("span");
    content.textContent = node.content;
    row.append(heading, content);
    hookRoot.append(row);
  });
  if (!nodes.length) hookRoot.textContent = "暂无待处理伏笔";
  const workflows = data.workflows || [];
  $("#workflow-count").textContent = String(workflows.length);
  const workflowRoot = $("#workflow-list");
  workflowRoot.replaceChildren();
  workflows.forEach((workflow) => {
    const row = document.createElement("div");
    row.className = `operation-row stacked${workflow.error ? " error" : ""}`;
    const heading = document.createElement("strong");
    heading.textContent = `${workflow.chapter_id} · ${workflow.current_stage}`;
    const stages = document.createElement("span");
    stages.textContent = workflow.stages.map((stage) => `${stage.name}:${stage.status}`).join(" · ");
    row.append(heading, stages);
    workflowRoot.append(row);
  });
  if (!workflows.length) workflowRoot.textContent = "暂无活动 workflow";
}

const relationshipKinds = {
  character: "人物", faction: "势力", place: "地点", concept: "概念", unknown: "其他",
};
const RELATIONSHIP_NODE_SCALE = 0.76;

function relationshipNodeSize(value) {
  return Math.round(value * RELATIONSHIP_NODE_SCALE);
}

function renderRelationshipGraph(graph) {
  stopRelationshipSimulation();
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph.edges) ? graph.edges : [];
  const filter = $("#relationship-filter").value;
  const origin = $("#relationship-origin").value;
  const query = normalizeRelationshipSearch($("#relationship-search").value);
  const typedNodes = filter === "all" ? nodes : nodes.filter((node) => node.kind === filter);
  const typedIds = new Set(typedNodes.map((node) => node.id));
  const typedEdges = edges.filter((edge) => (
    typedIds.has(edge.source)
    && typedIds.has(edge.target)
    && (origin === "all" || edge.origin === origin)
  ));
  const matchIds = query ? findRelationshipMatches(typedNodes, typedEdges, query) : new Set();
  const contextIds = new Set(matchIds);
  if (query) {
    typedEdges.forEach((edge) => {
      if (matchIds.has(edge.source) || matchIds.has(edge.target)) {
        contextIds.add(edge.source);
        contextIds.add(edge.target);
      }
    });
  }
  const visibleNodes = query ? typedNodes.filter((node) => contextIds.has(node.id)) : typedNodes;
  const ids = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = typedEdges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  state.relationship.nodes = visibleNodes;
  state.relationship.edges = visibleEdges;
  state.relationship.matchIds = matchIds;
  state.relationship.query = query;
  if (!ids.has(state.relationship.selectedId)) state.relationship.selectedId = null;

  const totalNodes = Number(graph.totals?.nodes ?? nodes.length);
  const totalEdges = Number(graph.totals?.edges ?? edges.length);
  const canonicalEdges = Number(graph.relation_totals?.canonical ?? edges.filter((edge) => edge.origin === "canonical").length);
  const annotationEdges = Number(graph.relation_totals?.annotation ?? edges.filter((edge) => edge.origin === "annotation").length);
  const relationDiagnostics = Array.isArray(graph.diagnostics) ? graph.diagnostics : [];
  const relationHint = totalNodes && !totalEdges
    ? " · 暂无已注册连线，请添加 related 或关系批注"
    : "";
  $("#relationship-summary").textContent = `${totalNodes} 个节点 · ${totalEdges} 条关系（资料字段 ${canonicalEdges} · 内联注册 ${annotationEdges}）${relationDiagnostics.length ? ` · 注册错误 ${relationDiagnostics.length}` : ""}${graph.truncated ? " · 已按性能上限截取" : ""}${relationHint}`;
  $("#relationship-visible-count").textContent = String(visibleNodes.length);
  $("#relationship-search-status").textContent = query
    ? (matchIds.size
      ? `搜索“${$("#relationship-search").value.trim()}”：匹配 ${matchIds.size} 个节点，已保留相邻上下文。按 Enter 定位第一个匹配。`
      : `搜索“${$("#relationship-search").value.trim()}”：没有匹配节点。`)
    : (relationDiagnostics.length
      ? `${relationDiagnostics[0].message}（${relationDiagnostics[0].path}:${relationDiagnostics[0].line}）`
      : "输入名称、ID、摘要或关系文字开始搜索。");
  $("#relationship-empty").textContent = query
    ? "没有匹配节点。可以缩短关键词或切换节点类型。"
    : (filter === "all"
      ? "暂无实体节点。请先在人物或世界实体目录中建立 Markdown 真源。"
      : "当前类型筛选下没有节点。");
  $("#relationship-empty").hidden = visibleNodes.length > 0;

  initializeRelationshipPositions(visibleNodes);
  buildRelationshipSvg(visibleNodes, visibleEdges);
  renderRelationshipNodeList();
  renderRelationshipDetail();
  applyRelationshipTransform();
  updateRelationshipPositions();
  highlightRelationshipNeighborhood(state.relationship.selectedId);

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  state.relationship.paused = reduceMotion;
  updateRelationshipPauseButton();
  if (!reduceMotion && visibleNodes.length > 1) startRelationshipSimulation();
  if (query && matchIds.size) fitRelationshipGraph();
}

function normalizeRelationshipSearch(value) {
  return String(value || "").trim().toLocaleLowerCase("zh-CN");
}

function findRelationshipMatches(nodes, edges, query) {
  const matchIds = new Set();
  const corpusById = new Map(nodes.map((node) => [node.id, [
    node.id, node.label, node.type, node.status, node.description, node.source_path,
  ].filter(Boolean).join(" ").toLocaleLowerCase("zh-CN")]));
  nodes.forEach((node) => {
    if (corpusById.get(node.id)?.includes(query)) matchIds.add(node.id);
  });
  edges.forEach((edge) => {
    if ([edge.label, edge.kind, edge.source_label, edge.origin].filter(Boolean)
      .join(" ").toLocaleLowerCase("zh-CN").includes(query)) {
      matchIds.add(edge.source);
      matchIds.add(edge.target);
    }
  });
  return matchIds;
}

function handleRelationshipSearchKeydown(event) {
  if (event.key === "Escape" && event.currentTarget.value) {
    event.preventDefault();
    event.currentTarget.value = "";
    renderRelationshipGraph(state.continuity?.relationship_graph || {});
    return;
  }
  if (event.key !== "Enter") return;
  event.preventDefault();
  const firstMatch = state.relationship.matchIds.values().next().value;
  if (firstMatch) focusRelationshipNode(firstMatch);
}

function initializeRelationshipPositions(nodes, reset = false) {
  const count = Math.max(nodes.length, 1);
  nodes.forEach((node, index) => {
    if (!reset && state.relationship.positions.has(node.id)) return;
    const hash = Array.from(node.id).reduce((value, char) => ((value * 31) + char.charCodeAt(0)) >>> 0, 7);
    const angle = index * Math.PI * (3 - Math.sqrt(5)) + (hash % 23) / 50;
    const radius = Math.sqrt((index + 0.6) / count);
    state.relationship.positions.set(node.id, {
      x: 480 + Math.cos(angle) * 390 * radius,
      y: 265 + Math.sin(angle) * 215 * radius,
      vx: 0, vy: 0, fixed: false,
    });
  });
}

function relationshipNodeCollisionWidth(node) {
  const labelLength = Array.from(String(node.label || "")).length;
  const displayedLength = Math.min(labelLength, 8);
  return Math.max(
    relationshipNodeSize(54),
    Math.min(relationshipNodeSize(104), relationshipNodeSize(displayedLength * 11 + 16)),
  );
}

function buildRelationshipSvg(nodes, edges) {
  const edgeRoot = $("#relationship-edges");
  const nodeRoot = $("#relationship-nodes");
  edgeRoot.replaceChildren();
  nodeRoot.replaceChildren();
  const degreeById = new Map(nodes.map((node) => [node.id, 0]));
  edges.forEach((edge) => {
    degreeById.set(edge.source, (degreeById.get(edge.source) || 0) + 1);
    degreeById.set(edge.target, (degreeById.get(edge.target) || 0) + 1);
  });
  const maxDegree = Math.max(0, ...degreeById.values());
  const labelThreshold = nodes.length > 32 ? Math.max(2, Math.ceil(maxDegree * 0.45)) : 0;
  edges.forEach((edge) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.classList.add("relationship-edge");
    path.classList.toggle("annotation", edge.origin === "annotation");
    path.classList.toggle("canonical", edge.origin === "canonical");
    path.dataset.edgeId = edge.id;
    path.dataset.sourceId = edge.source;
    path.dataset.targetId = edge.target;
    const searchRelated = Boolean(state.relationship.query) && (
      state.relationship.matchIds.has(edge.source) || state.relationship.matchIds.has(edge.target)
    );
    path.classList.toggle("search-related", searchRelated);
    path.classList.toggle("search-context", Boolean(state.relationship.query) && !searchRelated);
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${edge.label} · ${edge.origin === "canonical" ? "资料字段" : (edge.source_label || "内联注册")}`;
    path.append(title);
    edgeRoot.append(path);
  });
  nodes.forEach((node) => {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.classList.add("relationship-node");
    group.classList.toggle("label-prominent", (degreeById.get(node.id) || 0) >= labelThreshold);
    group.classList.toggle("selected", node.id === state.relationship.selectedId);
    group.classList.toggle("search-match", state.relationship.matchIds.has(node.id));
    group.classList.toggle(
      "search-context",
      Boolean(state.relationship.query) && !state.relationship.matchIds.has(node.id),
    );
    group.dataset.nodeId = node.id;
    group.dataset.kind = node.kind;
    group.setAttribute("tabindex", "0");
    group.setAttribute("role", "button");
    group.setAttribute("aria-label", `${node.label}，${relationshipKinds[node.kind] || "其他"}节点`);
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = node.label;
    const shape = relationshipNodeShape(node.kind);
    shape.classList.add("relationship-node-shape");
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.classList.add("relationship-node-label");
    label.setAttribute("y", String(relationshipNodeSize(34)));
    const labelCharacters = Array.from(node.label);
    label.textContent = labelCharacters.length > 8 ? `${labelCharacters.slice(0, 7).join("")}…` : node.label;
    group.append(title, shape, label);
    group.addEventListener("pointerdown", beginRelationshipNodeDrag);
    group.addEventListener("pointerenter", () => highlightRelationshipNeighborhood(node.id));
    group.addEventListener("pointerleave", () => highlightRelationshipNeighborhood(state.relationship.selectedId));
    group.addEventListener("keydown", moveRelationshipNodeWithKeyboard);
    group.addEventListener("click", () => selectRelationshipNode(node.id));
    nodeRoot.append(group);
  });
}

function relationshipNodeShape(kind) {
  const ns = "http://www.w3.org/2000/svg";
  if (kind === "faction") {
    const halfSize = relationshipNodeSize(18);
    const shape = document.createElementNS(ns, "rect");
    shape.setAttribute("x", String(-halfSize)); shape.setAttribute("y", String(-halfSize));
    shape.setAttribute("width", String(halfSize * 2)); shape.setAttribute("height", String(halfSize * 2));
    shape.setAttribute("rx", String(relationshipNodeSize(5)));
    return shape;
  }
  if (kind === "place" || kind === "concept") {
    const shape = document.createElementNS(ns, "polygon");
    const halfWidth = relationshipNodeSize(kind === "place" ? 22 : 20);
    const halfHeight = relationshipNodeSize(kind === "place" ? 22 : 23);
    const shoulder = relationshipNodeSize(12);
    shape.setAttribute("points", kind === "place"
      ? `0,${-halfHeight} ${halfWidth},0 0,${halfHeight} ${-halfWidth},0`
      : `${-halfWidth},${-shoulder} 0,${-halfHeight} ${halfWidth},${-shoulder} ${halfWidth},${shoulder} 0,${halfHeight} ${-halfWidth},${shoulder}`);
    return shape;
  }
  const shape = document.createElementNS(ns, "circle");
  shape.setAttribute("r", String(relationshipNodeSize(kind === "character" ? 19 : 17)));
  return shape;
}

function relationshipNodeBoundaryRadius(node) {
  if (node?.kind === "place" || node?.kind === "concept") return relationshipNodeSize(23);
  if (node?.kind === "faction") return relationshipNodeSize(21);
  return relationshipNodeSize(node?.kind === "character" ? 19 : 17);
}

function relationshipEdgePath(edge, source, target, sourceNode, targetNode) {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.max(Math.hypot(dx, dy), 1);
  const ux = dx / distance;
  const uy = dy / distance;
  const sourceRadius = relationshipNodeBoundaryRadius(sourceNode) + 3;
  const targetRadius = relationshipNodeBoundaryRadius(targetNode) + 7;
  if (distance <= sourceRadius + targetRadius + 2) {
    return `M ${source.x} ${source.y} L ${target.x} ${target.y}`;
  }
  const startX = source.x + ux * sourceRadius;
  const startY = source.y + uy * sourceRadius;
  const endX = target.x - ux * targetRadius;
  const endY = target.y - uy * targetRadius;
  const hash = Array.from(String(edge.id || `${edge.source}:${edge.target}`))
    .reduce((value, char) => ((value * 33) ^ char.charCodeAt(0)) >>> 0, 5381);
  const direction = hash % 2 ? 1 : -1;
  const bendRatio = 0.075 + ((hash >>> 1) % 4) * 0.018;
  const bend = direction * Math.min(36, Math.max(6, distance * bendRatio));
  const controlX = (startX + endX) / 2 - uy * bend;
  const controlY = (startY + endY) / 2 + ux * bend;
  return `M ${startX.toFixed(2)} ${startY.toFixed(2)} Q ${controlX.toFixed(2)} ${controlY.toFixed(2)} ${endX.toFixed(2)} ${endY.toFixed(2)}`;
}

function updateRelationshipPositions() {
  const byId = state.relationship.positions;
  const nodeById = new Map(state.relationship.nodes.map((node) => [node.id, node]));
  $$(".relationship-edge").forEach((path, index) => {
    const edge = state.relationship.edges[index];
    const source = byId.get(edge?.source);
    const target = byId.get(edge?.target);
    if (!source || !target) return;
    path.setAttribute("d", relationshipEdgePath(
      edge,
      source,
      target,
      nodeById.get(edge.source),
      nodeById.get(edge.target),
    ));
  });
  $$(".relationship-node").forEach((group) => {
    const point = byId.get(group.dataset.nodeId);
    if (point) group.setAttribute("transform", `translate(${point.x} ${point.y})`);
  });
}

function startRelationshipSimulation() {
  if (state.relationship.frame || state.relationship.paused) return;
  state.relationship.ticks = 0;
  const tick = () => {
    state.relationship.frame = null;
    if (state.relationship.paused) return;
    simulateRelationshipStep();
    updateRelationshipPositions();
    state.relationship.ticks += 1;
    if (state.relationship.ticks < 360) state.relationship.frame = requestAnimationFrame(tick);
  };
  state.relationship.frame = requestAnimationFrame(tick);
}

function stopRelationshipSimulation() {
  if (state.relationship.frame) cancelAnimationFrame(state.relationship.frame);
  state.relationship.frame = null;
}

function simulateRelationshipStep() {
  const nodes = state.relationship.nodes;
  const positions = state.relationship.positions;
  const collisionWidths = nodes.map(relationshipNodeCollisionWidth);
  for (let i = 0; i < nodes.length; i += 1) {
    const a = positions.get(nodes[i].id);
    if (!a || a.fixed) continue;
    for (let j = i + 1; j < nodes.length; j += 1) {
      const b = positions.get(nodes[j].id);
      if (!b) continue;
      let dx = a.x - b.x; let dy = a.y - b.y;
      const distance2 = Math.max(dx * dx + dy * dy, 100);
      const distance = Math.sqrt(distance2);
      const force = Math.min(2.2, 2600 / distance2);
      dx /= distance; dy /= distance;
      a.vx += dx * force; a.vy += dy * force;
      if (!b.fixed) { b.vx -= dx * force; b.vy -= dy * force; }

      const minX = (collisionWidths[i] + collisionWidths[j]) / 2;
      const minY = relationshipNodeSize(58);
      const overlapX = minX - Math.abs(a.x - b.x);
      const overlapY = minY - Math.abs(a.y - b.y);
      if (overlapX > 0 && overlapY > 0) {
        const separateOnX = (overlapX / minX) < (overlapY / minY);
        const direction = separateOnX ? (a.x >= b.x ? 1 : -1) : (a.y >= b.y ? 1 : -1);
        const collisionForce = Math.min(3.2, (separateOnX ? overlapX : overlapY) * 0.08);
        if (separateOnX) {
          a.vx += direction * collisionForce;
          if (!b.fixed) b.vx -= direction * collisionForce;
        } else {
          a.vy += direction * collisionForce;
          if (!b.fixed) b.vy -= direction * collisionForce;
        }
      }
    }
    a.vx += (480 - a.x) * 0.0012; a.vy += (265 - a.y) * 0.0012;
  }
  state.relationship.edges.forEach((edge) => {
    const source = positions.get(edge.source); const target = positions.get(edge.target);
    if (!source || !target) return;
    const dx = target.x - source.x; const dy = target.y - source.y;
    const distance = Math.max(Math.hypot(dx, dy), 1);
    const force = (distance - 132) * 0.0025;
    if (!source.fixed) { source.vx += (dx / distance) * force; source.vy += (dy / distance) * force; }
    if (!target.fixed) { target.vx -= (dx / distance) * force; target.vy -= (dy / distance) * force; }
  });
  nodes.forEach((node, index) => {
    const point = positions.get(node.id);
    if (!point || point.fixed) return;
    point.vx *= 0.84; point.vy *= 0.84;
    const halfWidth = collisionWidths[index] / 2;
    const radiusX = Math.max(360, 442 - halfWidth);
    const radiusY = 222;
    const normalizedX = (point.x - 480) / radiusX;
    const normalizedY = (point.y - 265) / radiusY;
    const normalizedDistance = Math.hypot(normalizedX, normalizedY);
    if (normalizedDistance > 1) {
      const boundaryX = 480 + (normalizedX / normalizedDistance) * radiusX;
      const boundaryY = 265 + (normalizedY / normalizedDistance) * radiusY;
      point.vx += (boundaryX - point.x) * 0.045;
      point.vy += (boundaryY - point.y) * 0.045;
    }
    point.x += point.vx;
    point.y += point.vy;
    const nextNormalizedX = (point.x - 480) / radiusX;
    const nextNormalizedY = (point.y - 265) / radiusY;
    const nextDistance = Math.hypot(nextNormalizedX, nextNormalizedY);
    if (nextDistance > 1.12) {
      point.x = 480 + (nextNormalizedX / nextDistance) * radiusX * 1.12;
      point.y = 265 + (nextNormalizedY / nextDistance) * radiusY * 1.12;
      point.vx *= 0.35;
      point.vy *= 0.35;
    }
  });
}

function highlightRelationshipNeighborhood(id) {
  const connectedNodeIds = new Set(id ? [id] : []);
  const connectedEdgeIds = new Set();
  if (id) {
    state.relationship.edges.forEach((edge) => {
      if (edge.source !== id && edge.target !== id) return;
      connectedEdgeIds.add(edge.id);
      connectedNodeIds.add(edge.source);
      connectedNodeIds.add(edge.target);
    });
  }
  $$(".relationship-edge").forEach((path) => {
    const highlighted = Boolean(id) && connectedEdgeIds.has(path.dataset.edgeId);
    path.classList.toggle("is-highlighted", highlighted);
    path.classList.toggle("is-dimmed", Boolean(id) && !highlighted);
  });
  $$(".relationship-node").forEach((node) => {
    const nodeId = node.dataset.nodeId;
    node.classList.toggle("is-highlighted", Boolean(id) && nodeId === id);
    node.classList.toggle("is-neighbor", Boolean(id) && nodeId !== id && connectedNodeIds.has(nodeId));
    node.classList.toggle("is-dimmed", Boolean(id) && !connectedNodeIds.has(nodeId));
  });
}

function relationshipPoint(event) {
  const rect = $("#relationship-graph").getBoundingClientRect();
  const x = ((event.clientX - rect.left) / rect.width) * 960;
  const y = ((event.clientY - rect.top) / rect.height) * 560;
  return { x: (x - state.relationship.tx) / state.relationship.scale, y: (y - state.relationship.ty) / state.relationship.scale };
}

function beginRelationshipNodeDrag(event) {
  if (event.button !== 0) return;
  event.stopPropagation();
  const id = event.currentTarget.dataset.nodeId;
  const point = state.relationship.positions.get(id);
  if (!point) return;
  point.fixed = true;
  state.relationship.pointer = { type: "node", id, moved: false };
  event.currentTarget.setPointerCapture(event.pointerId);
  $("#relationship-graph").classList.add("dragging-node");
}

function moveRelationshipPointer(event) {
  const pointer = state.relationship.pointer;
  if (!pointer) return;
  if (pointer.type === "node") {
    const point = state.relationship.positions.get(pointer.id);
    const next = relationshipPoint(event);
    if (point) { point.x = next.x; point.y = next.y; point.vx = 0; point.vy = 0; }
    pointer.moved = true;
    updateRelationshipPositions();
    return;
  }
  const rect = $("#relationship-graph").getBoundingClientRect();
  state.relationship.tx = pointer.tx + ((event.clientX - pointer.x) / rect.width) * 960;
  state.relationship.ty = pointer.ty + ((event.clientY - pointer.y) / rect.height) * 560;
  applyRelationshipTransform();
}

function endRelationshipPointer() {
  const pointer = state.relationship.pointer;
  if (pointer?.type === "node") {
    const point = state.relationship.positions.get(pointer.id);
    if (point) point.fixed = false;
    if (!state.relationship.paused) startRelationshipSimulation();
  }
  state.relationship.pointer = null;
  $("#relationship-graph").classList.remove("dragging-node", "panning");
}

function beginRelationshipPan(event) {
  if (event.button !== 0 || event.target.closest(".relationship-node")) return;
  state.relationship.pointer = { type: "pan", x: event.clientX, y: event.clientY, tx: state.relationship.tx, ty: state.relationship.ty };
  event.currentTarget.setPointerCapture(event.pointerId);
  event.currentTarget.classList.add("panning");
}

function zoomRelationshipGraph(event) {
  event.preventDefault();
  const before = relationshipPoint(event);
  const factor = event.deltaY < 0 ? 1.12 : 0.89;
  state.relationship.scale = Math.max(0.35, Math.min(3, state.relationship.scale * factor));
  const rect = $("#relationship-graph").getBoundingClientRect();
  const svgX = ((event.clientX - rect.left) / rect.width) * 960;
  const svgY = ((event.clientY - rect.top) / rect.height) * 560;
  state.relationship.tx = svgX - before.x * state.relationship.scale;
  state.relationship.ty = svgY - before.y * state.relationship.scale;
  applyRelationshipTransform();
}

function applyRelationshipTransform() {
  $("#relationship-viewport").setAttribute("transform", `translate(${state.relationship.tx} ${state.relationship.ty}) scale(${state.relationship.scale})`);
}

function fitRelationshipGraph() {
  const points = state.relationship.nodes.map((node) => state.relationship.positions.get(node.id)).filter(Boolean);
  if (!points.length) return;
  const xs = points.map((point) => point.x); const ys = points.map((point) => point.y);
  const minX = Math.min(...xs) - 55; const maxX = Math.max(...xs) + 55;
  const minY = Math.min(...ys) - 55; const maxY = Math.max(...ys) + 55;
  state.relationship.scale = Math.max(0.35, Math.min(1.8, Math.min(900 / Math.max(1, maxX - minX), 500 / Math.max(1, maxY - minY))));
  state.relationship.tx = 480 - ((minX + maxX) / 2) * state.relationship.scale;
  state.relationship.ty = 280 - ((minY + maxY) / 2) * state.relationship.scale;
  applyRelationshipTransform();
}

function resetRelationshipLayout() {
  initializeRelationshipPositions(state.relationship.nodes, true);
  state.relationship.scale = 1; state.relationship.tx = 0; state.relationship.ty = 0;
  state.relationship.paused = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  updateRelationshipPauseButton(); applyRelationshipTransform(); updateRelationshipPositions();
  if (!state.relationship.paused) startRelationshipSimulation();
}

function toggleRelationshipSimulation() {
  state.relationship.paused = !state.relationship.paused;
  if (state.relationship.paused) stopRelationshipSimulation(); else startRelationshipSimulation();
  updateRelationshipPauseButton();
}

function updateRelationshipPauseButton() {
  const button = $("#relationship-layout");
  button.setAttribute("aria-pressed", String(state.relationship.paused));
  const label = state.relationship.paused ? "继续布局" : "暂停布局";
  button.setAttribute("aria-label", label);
  button.setAttribute("title", label);
  button.querySelector("use")?.setAttribute("href", state.relationship.paused ? "#icon-play" : "#icon-pause");
}

function moveRelationshipNodeWithKeyboard(event) {
  const deltas = { ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] };
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectRelationshipNode(event.currentTarget.dataset.nodeId); return; }
  if (!deltas[event.key]) return;
  event.preventDefault();
  const point = state.relationship.positions.get(event.currentTarget.dataset.nodeId);
  if (point) { point.x += deltas[event.key][0]; point.y += deltas[event.key][1]; updateRelationshipPositions(); }
}

function selectRelationshipNode(id) {
  state.relationship.selectedId = id;
  $$(".relationship-node").forEach((node) => node.classList.toggle("selected", node.dataset.nodeId === id));
  $$("#relationship-node-list button").forEach((button) => button.setAttribute("aria-current", String(button.dataset.nodeId === id)));
  highlightRelationshipNeighborhood(id);
  renderRelationshipDetail();
}

function focusRelationshipNode(id) {
  const point = state.relationship.positions.get(id);
  if (!point) return;
  selectRelationshipNode(id);
  state.relationship.scale = Math.max(state.relationship.scale, 1.15);
  state.relationship.tx = 480 - point.x * state.relationship.scale;
  state.relationship.ty = 280 - point.y * state.relationship.scale;
  applyRelationshipTransform();
  $$(".relationship-node").find((node) => node.dataset.nodeId === id)?.focus();
}

function renderRelationshipNodeList() {
  const root = $("#relationship-node-list");
  root.replaceChildren();
  const nodes = [...state.relationship.nodes].sort((a, b) => (
    Number(state.relationship.matchIds.has(b.id)) - Number(state.relationship.matchIds.has(a.id))
  ));
  nodes.forEach((node) => {
    const item = document.createElement("div");
    item.setAttribute("role", "listitem");
    const button = document.createElement("button");
    button.type = "button"; button.dataset.nodeId = node.id; button.dataset.kind = node.kind;
    button.setAttribute("aria-current", String(node.id === state.relationship.selectedId));
    const label = document.createElement("span"); label.textContent = node.label;
    const meta = document.createElement("small");
    const degree = state.relationship.edges.filter((edge) => edge.source === node.id || edge.target === node.id).length;
    const searchPrefix = state.relationship.query
      ? (state.relationship.matchIds.has(node.id) ? "匹配 · " : "相邻 · ")
      : "";
    meta.textContent = `${searchPrefix}${relationshipKinds[node.kind] || "其他"} · ${degree} 条相邻关系`;
    button.append(label, meta); button.addEventListener("click", () => focusRelationshipNode(node.id));
    item.append(button); root.append(item);
  });
  if (!state.relationship.nodes.length) root.textContent = "没有可列出的节点";
}

function renderRelationshipDetail() {
  const root = $("#relationship-detail");
  root.replaceChildren();
  const node = state.relationship.nodes.find((item) => item.id === state.relationship.selectedId);
  if (!node) { root.textContent = "选择图中节点或下方列表查看相邻关系。"; return; }
  const heading = document.createElement("strong"); heading.textContent = node.label;
  const meta = document.createElement("p"); meta.textContent = `${node.type || relationshipKinds[node.kind]} · ${node.status || "active"}`;
  const description = document.createElement("p"); description.textContent = node.description || "暂无摘要";
  root.append(heading, meta, description);
  if (node.source_path) {
    const source = document.createElement("button"); source.type = "button"; source.className = "relationship-source";
    source.textContent = node.source_path; source.title = `打开 ${node.source_path}`;
    source.addEventListener("click", () => openDocument(node.source_path)); root.append(source);
  }
  if (node.asset_kind) {
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "quiet-button relationship-edit-asset";
    edit.textContent = "在资料库中编辑";
    edit.addEventListener("click", () => openStructuredAsset({
      asset_kind: node.asset_kind,
      asset_id: node.id,
      path: node.source_path,
    }, true));
    root.append(edit);
  }
  const neighbors = state.relationship.edges.filter((edge) => edge.source === node.id || edge.target === node.id);
  const list = document.createElement("ul");
  neighbors.forEach((edge) => {
    const neighborId = edge.source === node.id ? edge.target : edge.source;
    const neighbor = state.relationship.nodes.find((item) => item.id === neighborId);
    const item = document.createElement("li");
    const text = document.createElement("span");
    text.textContent = `${neighbor?.label || neighborId}：${edge.label}`;
    const origin = document.createElement("small");
    origin.className = `relationship-edge-origin ${edge.origin || "annotation"}`;
    origin.textContent = edge.origin === "canonical" ? "资料字段" : (edge.source_label || "内联注册");
    item.append(text, origin);
    list.append(item);
  });
  if (neighbors.length) root.append(list); else { const empty = document.createElement("p"); empty.textContent = "当前筛选中没有相邻关系。"; root.append(empty); }
}

async function createForeshadowing(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const payload = await api("/api/foreshadowing", {
      method: "POST",
      body: JSON.stringify({
        action: "create",
        node_id: $("#foreshadow-id").value.trim(),
        content: $("#foreshadow-content").value.trim(),
        weight: Number($("#foreshadow-weight").value),
        target_chapter: $("#foreshadow-target").value.trim(),
        created_at: state.workspace.snapshot.current_chapter,
      }),
    });
    state.continuity = payload.continuity;
    state.workspace = payload.workspace;
    renderContinuity();
    renderWorkspace();
    form.reset();
    $("#foreshadow-weight").value = "5";
    showToast("伏笔已加入连续性系统");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function extractSource(event) {
  event.preventDefault();
  const file = $("#source-file").files[0];
  const text = file ? await file.text() : $("#source-content").value;
  $("#source-extract").disabled = true;
  $("#source-status").textContent = "正在创建证据分块…";
  try {
    await enqueueTask(
      "source_operation",
      {
        action: "analyze_v2",
        source_id: $("#source-id").value.trim(),
        relative_name: file?.name || "pasted-source.txt",
        focus: sourceFocusValues($("#source-focus").value),
        input_budget_tokens: Number($("#source-input-budget").value || 12000),
        content: text,
      },
      {
        label: "参考分析任务已加入队列",
        onComplete: async () => {
          await loadWorkspace();
          await runSourceAction("status_v2", $("#source-id").value.trim());
          $("#source-status").textContent = "参考分析已完成";
        },
      },
    );
    $("#source-status").textContent = "参考分析正在后台执行";
  } catch (error) {
    $("#source-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    $("#source-extract").disabled = false;
  }
}

async function runSourceAction(action, sourceId) {
  $("#source-status").textContent = "正在执行来源操作…";
  try {
    const payload = await api("/api/source", {
      method: "POST",
      body: JSON.stringify({ action, source_id: sourceId, target: "all" }),
    });
    state.workspace = payload.workspace;
    renderWorkspace();
    if (action === "review") {
      $("#source-report").textContent = payload.result.review_report || "无报告";
    } else if (action === "status_v2") {
      renderSourceAnalysis(payload.result);
    }
    $("#source-status").textContent = "来源报告已加载";
  } catch (error) {
    $("#source-status").textContent = error.message;
    showToast(error.message, true);
  }
}

async function retrySourceChunk(sourceId, chunkId) {
  $("#source-status").textContent = "正在重试失败分块…";
  try {
    await enqueueTask(
      "source_operation",
      { action: "retry_v2", source_id: sourceId, chunk_id: chunkId },
      {
        label: "分块重试已加入队列",
        onComplete: async () => {
          await loadWorkspace();
          await runSourceAction("status_v2", sourceId);
        },
      },
    );
  } catch (error) {
    $("#source-status").textContent = error.message;
    showToast(error.message, true);
  }
}

function renderReferenceProfile(profile) {
  const root = $("#source-report");
  root.replaceChildren();
  const summary = document.createElement("div");
  summary.className = "source-report-summary profile";
  const heading = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = "多来源综合画像";
  const badge = document.createElement("span");
  badge.className = "status-badge ready";
  badge.textContent = `${profile.source_ids?.length || 0} 个来源`;
  heading.append(title, badge);
  const sourceNames = document.createElement("p");
  sourceNames.textContent = (profile.source_ids || []).join("、");
  summary.append(heading, sourceNames);
  root.append(summary);

  [
    ["共通方法", profile.common_methods || []],
    ["差异", profile.differences || []],
    ["可选变体", profile.optional_variants || []],
  ].forEach(([label, items]) => {
    const section = document.createElement("section");
    section.className = "profile-section";
    const sectionTitle = document.createElement("h3");
    sectionTitle.textContent = `${label} · ${items.length}`;
    section.append(sectionTitle);
    items.forEach((entry) => {
      const row = document.createElement("div");
      row.className = "profile-item";
      const claim = document.createElement("strong");
      claim.textContent = entry.claim;
      const sources = document.createElement("span");
      sources.textContent = (entry.source_ids || []).join("、");
      row.append(claim, sources);
      section.append(row);
    });
    if (items.length) root.append(section);
  });

  if ((profile.conflicts || []).length || (profile.excluded_items || []).length) {
    const exclusions = document.createElement("section");
    exclusions.className = "profile-section exclusions";
    const title = document.createElement("h3");
    title.textContent = "冲突与排除";
    const list = document.createElement("ul");
    [...(profile.conflicts || []), ...(profile.excluded_items || [])].forEach((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      list.append(item);
    });
    exclusions.append(title, list);
    root.append(exclusions);
  }
}

async function synthesizeSelectedSources() {
  const sourceIds = Array.from(state.sourceAnalysis.selectedSourceIds);
  if (!sourceIds.length) return;
  $("#source-status").textContent = "正在综合所选来源…";
  try {
    const payload = await api("/api/source", {
      method: "POST",
      body: JSON.stringify({ action: "synthesize_v2", source_ids: sourceIds }),
    });
    state.sourceAnalysis.profile = payload.result;
    state.sourceAnalysis.promotionPreview = null;
    $("#source-report-actions").replaceChildren();
    renderReferenceProfile(payload.result);
    $("#source-status").textContent = "多来源画像已生成";
    syncSourceAnalysisControls();
  } catch (error) {
    $("#source-status").textContent = error.message;
    showToast(error.message, true);
  }
}

async function previewSourcePromotion() {
  const profile = state.sourceAnalysis.profile;
  if (!profile) return;
  try {
    const payload = await api("/api/source", {
      method: "POST",
      body: JSON.stringify({
        action: "promotion_preview_v2",
        profile_id: profile.profile_id,
        target: $("#source-promotion-target").value,
      }),
    });
    state.sourceAnalysis.promotionPreview = payload.result;
    $("#source-report-actions").replaceChildren();
    const root = $("#source-report");
    root.replaceChildren();
    const summary = document.createElement("div");
    summary.className = "source-report-summary";
    const heading = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `应用预览 · ${payload.result.target_ref}`;
    const badge = document.createElement("span");
    badge.className = "status-badge";
    badge.textContent = `${payload.result.included_claims?.length || 0} 条候选`;
    heading.append(title, badge);
    summary.append(heading);
    const diff = document.createElement("pre");
    diff.className = "context-preview promotion-diff";
    diff.textContent = payload.result.unified_diff || "目标内容无变化";
    root.append(summary, diff);
    $("#source-status").textContent = "应用差异已生成，尚未写入作品";
    syncSourceAnalysisControls();
  } catch (error) {
    $("#source-status").textContent = error.message;
    showToast(error.message, true);
  }
}

async function applySourcePromotion() {
  const preview = state.sourceAnalysis.promotionPreview;
  if (!preview) return;
  $("#source-promotion-apply").disabled = true;
  try {
    const payload = await api("/api/source", {
      method: "POST",
      body: JSON.stringify({
        action: "promote_v2",
        preview_id: preview.preview_id,
        confirm: true,
      }),
    });
    state.sourceAnalysis.promotionPreview = null;
    const root = $("#source-report");
    root.replaceChildren();
    const applied = document.createElement("div");
    applied.className = "source-application-success";
    const title = document.createElement("strong");
    title.textContent = "候选已应用";
    const path = document.createElement("code");
    path.textContent = payload.result.target_ref;
    applied.append(title, path);
    root.append(applied);
    $("#source-status").textContent = "晋升候选已确认应用";
    syncSourceAnalysisControls();
  } catch (error) {
    $("#source-status").textContent = error.message;
    showToast(error.message, true);
    syncSourceAnalysisControls();
  }
}

async function runWriter(event) {
  event.preventDefault();
  const submit = $("#write-submit");
  const progress = $("#write-progress");
  submit.disabled = true;
  $("#write-cancel").disabled = true;
  progress.classList.remove("error");
  progress.textContent = "正在组装上下文并执行写作、观察和状态结算…";
  try {
    await enqueueTask(
      "chapter_write",
      {
        chapter_id: $("#write-chapter-id").textContent,
        outline_revision: $("#write-outline-revision").value,
        guidance: $("#write-guidance").value,
        target_words: Number($("#write-words").value),
      },
      {
        label: "章节写作任务已加入队列",
        onComplete: async (task) => {
          await loadWorkspace();
          showToast(`${task.result.chapter_id} 已完成，${formatNumber(task.result.word_count)} 字`);
          const match = state.workspace.documents.chapters.find((item) =>
            item.path.endsWith(`/${task.result.chapter_id}.md`)
          );
          if (match) await openDocument(match.path, true);
        },
      },
    );
    $("#write-dialog").close();
    progress.textContent = "章节正在后台写作";
  } catch (error) {
    progress.classList.add("error");
    progress.textContent = error.message;
  } finally {
    submit.disabled = false;
    $("#write-cancel").disabled = false;
  }
}

async function runReview() {
  if (!state.document || state.dirty) {
    showToast(state.dirty ? "请先保存章节再审稿" : "未选择章节", true);
    return;
  }
  const dialog = $("#review-dialog");
  const loading = $("#review-loading");
  loading.hidden = false;
  loading.classList.remove("error");
  loading.textContent = "正在执行规则检查与深度审稿…";
  $("#review-result").hidden = true;
  try {
    await enqueueTask(
      "chapter_review",
      { path: state.document.path },
      {
        label: "章节审稿任务已加入队列",
        onComplete: async (task) => {
          await loadWorkspace();
          renderReview(task.result);
          if (!dialog.open) dialog.showModal();
        },
      },
    );
  } catch (error) {
    $("#review-loading").textContent = error.message;
    $("#review-loading").classList.add("error");
  }
}

function renderReviewWorkspace() {
  const chapters = state.workspace?.documents?.chapters || [];
  const reviewed = chapters.filter((chapter) => chapter.review);
  const allIssues = reviewed.flatMap((chapter) => chapter.review.issue_details || []);
  $("#review-workspace-count").textContent = String(reviewed.length);
  $("#review-blocker-count").textContent = String(
    allIssues.filter((issue) => issue.severity === "blocker").length,
  );
  $("#review-open-count").textContent = String(allIssues.length);
  $("#review-chapter-count").textContent = String(chapters.length);
  const root = $("#review-chapter-list");
  root.replaceChildren();
  if (!state.reviewChapterPath || !chapters.some((chapter) => chapter.path === state.reviewChapterPath)) {
    state.reviewChapterPath = reviewed[0]?.path || chapters[0]?.path || "";
  }
  chapters.forEach((chapter) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "review-chapter-item";
    button.classList.toggle("active", chapter.path === state.reviewChapterPath);
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(chapter.path === state.reviewChapterPath));
    const title = document.createElement("strong");
    title.textContent = chapter.title;
    const meta = document.createElement("span");
    meta.textContent = chapter.review
      ? `${Math.round(chapter.review.score)} 分 · ${chapter.review.issues} 个问题${chapter.review.stale ? " · 待复审" : ""}`
      : "尚未审稿";
    button.append(title, meta);
    button.addEventListener("click", () => {
      state.reviewChapterPath = chapter.path;
      renderReviewWorkspace();
    });
    root.append(button);
  });
  const selected = chapters.find((chapter) => chapter.path === state.reviewChapterPath);
  renderReviewWorkspaceIssues(selected);
}

function renderReviewWorkspaceIssues(chapter) {
  const root = $("#review-workspace-issues");
  root.replaceChildren();
  const dimensionSelect = $("#review-dimension-filter");
  const previousDimension = dimensionSelect.value;
  const rawIssues = chapter?.review?.issue_details || [];
  const dimensions = [...new Set(rawIssues.map((issue) => issue.dimension || issue.category || "general"))].sort();
  dimensionSelect.replaceChildren(new Option("全部维度", "all"));
  dimensions.forEach((dimension) => dimensionSelect.add(new Option(dimension, dimension)));
  dimensionSelect.value = dimensions.includes(previousDimension) ? previousDimension : "all";
  const severity = $("#review-severity-filter").value;
  const dimension = dimensionSelect.value;
  const fixableOnly = $("#review-fixable-filter").checked;
  const severityRank = { blocker: 0, high: 1, medium: 2, low: 3 };
  const issues = rawIssues
    .filter((issue) => severity === "all" || issue.severity === severity)
    .filter((issue) => dimension === "all" || (issue.dimension || issue.category) === dimension)
    .filter((issue) => !fixableOnly || issue.auto_fixable)
    .sort((left, right) => (severityRank[left.severity] ?? 9) - (severityRank[right.severity] ?? 9));
  const status = $("#review-workspace-status");
  if (!chapter) {
    status.textContent = "尚无正文章节";
    return;
  }
  if (!chapter.review) {
    status.textContent = "本章尚未审稿，可先打开章节后执行审稿。";
    return;
  }
  status.textContent = `${chapter.title} · ${issues.length} / ${rawIssues.length} 个问题`;
  if (!issues.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = rawIssues.length ? "当前筛选条件下没有问题" : "本章未发现需要处理的问题";
    root.append(empty);
    return;
  }
  const chapterId = chapter.path.match(/(ch_\d+)\.md$/)?.[1] || "";
  const delta = chapter.review.issue_delta || null;
  const remainingIds = new Set((delta?.remaining || []).map((issue) => issue.id));
  const newIds = new Set((delta?.new || []).map((issue) => issue.id));
  issues.forEach((issue) => {
    const item = document.createElement("article");
    item.className = `review-workspace-issue severity-${issue.severity || "medium"}`;
    const heading = document.createElement("div");
    heading.className = "review-issue-heading";
    const title = document.createElement("strong");
    title.textContent = issue.summary || issue.description || "未命名问题";
    const badge = document.createElement("span");
    badge.className = `severity ${issue.severity || "medium"}`;
    badge.textContent = issue.severity || "medium";
    heading.append(title, badge);
    if (newIds.has(issue.id) || remainingIds.has(issue.id)) {
      const change = document.createElement("span");
      change.className = `review-change ${newIds.has(issue.id) ? "new" : "remaining"}`;
      change.textContent = newIds.has(issue.id) ? "新增" : "仍存在";
      heading.append(change);
    }
    const meta = document.createElement("span");
    meta.className = "review-issue-dimension";
    meta.textContent = issue.dimension || issue.category || "general";
    const description = document.createElement("p");
    description.textContent = issue.description || issue.suggestion || "";
    const actions = document.createElement("div");
    actions.className = "review-issue-actions";
    const locate = document.createElement("button");
    locate.type = "button";
    locate.className = "quiet-button";
    locate.textContent = "定位原文";
    locate.addEventListener("click", () => locateReviewIssue(chapter.path, issue));
    actions.append(locate);
    item.append(heading, meta, description, actions);
    appendReviewIssueActions(item, issue, {
      chapter_id: chapterId,
      issue_details: rawIssues,
      ...chapter.review,
    });
    root.append(item);
  });
  (delta?.resolved || []).forEach((issue) => {
    const item = document.createElement("article");
    item.className = "review-workspace-issue resolved";
    const heading = document.createElement("div");
    heading.className = "review-issue-heading";
    const title = document.createElement("strong");
    title.textContent = issue.summary || issue.description || "已解决问题";
    const change = document.createElement("span");
    change.className = "review-change resolved";
    change.textContent = "已解决";
    heading.append(title, change);
    item.append(heading);
    root.append(item);
  });
}

async function locateReviewIssue(path, issue) {
  await openDocument(path, true);
  const editor = getPrimaryMarkdownEditor();
  const value = editor.getValue();
  const quote = String(issue.evidence?.quote || issue.quote || "");
  let start = Number(issue.anchor?.start_hint);
  let end = Number(issue.anchor?.end_hint);
  if (!Number.isInteger(start) || start < 0 || !Number.isInteger(end) || end <= start) {
    start = quote ? value.indexOf(quote) : -1;
    end = start >= 0 ? start + quote.length : -1;
  }
  if (start < 0 || end > value.length) {
    showToast("原文位置已变化，请重新审稿", true);
    return;
  }
  await editor.selectRange(start, end);
  syncRevisionControls();
}

async function reviewSelectedWorkspaceChapter() {
  const chapter = state.workspace?.documents?.chapters?.find((item) => item.path === state.reviewChapterPath);
  if (!chapter) {
    showToast("尚无可审查章节", true);
    return;
  }
  await openDocument(chapter.path, false);
  await runReview();
}

async function openStudioTaskResult(task) {
  if (["revision_selection", "revision_from_review"].includes(task.type)) {
    showRevisionPreview(task.result);
    return;
  }
  if (task.type === "chapter_review") {
    if ($("#task-center-dialog").open) $("#task-center-dialog").close();
    renderReview(task.result);
    if (!$("#review-dialog").open) $("#review-dialog").showModal();
    return;
  }
  if (task.type === "chapter_write" && task.result?.chapter_id) {
    await loadWorkspace();
    const match = state.workspace.documents.chapters.find((item) =>
      item.path.endsWith(`/${task.result.chapter_id}.md`)
    );
    if (match) await openDocument(match.path, true);
    return;
  }
  if (task.type === "research" && task.result?.report_id) {
    setView("research");
    await openResearchReport(task.result.report_id);
    return;
  }
  await loadWorkspace();
  showToast(task.result?.stop_reason || "任务结果已载入");
}

function renderReview(result) {
  $("#review-loading").hidden = true;
  $("#review-result").hidden = false;
  $("#review-score").textContent = String(Math.round(Number(result.score || 0)));
  const verdict = $("#review-verdict");
  verdict.textContent = result.passed ? "通过" : "需要修订";
  verdict.classList.toggle("ready", Boolean(result.passed));
  $("#review-summary").textContent = result.summary || `${result.issues || 0} 个问题`;
  const root = $("#review-issues");
  root.replaceChildren();
  const issues = result.issue_details || [];
  state.reviewChapterPath = state.workspace?.documents?.chapters?.find((chapter) =>
    chapter.path.endsWith(`/${result.chapter_id}.md`)
  )?.path || state.reviewChapterPath;
  if (state.view === "review") renderReviewWorkspace();
  if (!issues.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "未发现需要处理的问题";
    root.append(empty);
    return;
  }
  issues.forEach((issue) => {
    const item = document.createElement("article");
    item.className = "review-issue";
    const heading = document.createElement("div");
    heading.className = "review-issue-heading";
    const category = document.createElement("strong");
    category.textContent = issue.category || "未分类";
    const severity = document.createElement("span");
    const severityName = {
      blocker: "critical", high: "critical", medium: "warning", low: "info",
      critical: "critical", warning: "warning", info: "info",
    }[issue.severity] || "warning";
    severity.className = `severity ${severityName}`;
    severity.textContent = { critical: "严重", warning: "警告", info: "提示" }[severityName];
    heading.append(category, severity);
    const description = document.createElement("p");
    description.textContent = issue.description || "";
    item.append(heading, description);
    if (issue.suggestion) {
      const suggestion = document.createElement("p");
      suggestion.className = "review-suggestion";
      suggestion.textContent = `建议：${issue.suggestion}`;
      item.append(suggestion);
    }
    appendReviewIssueActions(item, issue, result);
    root.append(item);
  });
}

function switchInspectorTab(tab) {
  $$('[data-inspector-tab]').forEach((button) => {
    const active = button.dataset.inspectorTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $$('[data-inspector-pane]').forEach((pane) => {
    pane.hidden = pane.dataset.inspectorPane !== tab;
  });
}

function renderInspectorContext() {
  const title = state.document?.title || "尚未选择";
  $("#inspector-document-title").textContent = title;
  $("#inspector-document-units").textContent = `${countWritingUnits(state.document?.content || "")} 字`;
  $("#inspector-model-route").textContent = $("#model-topbar-name").textContent || "未配置";
  const chapter = state.workspace?.documents?.chapters?.find((item) => item.path === state.document?.path);
  const summary = $("#inspector-review-summary");
  const root = $("#inspector-review-issues");
  root.replaceChildren();
  if (!chapter?.review) {
    summary.textContent = "当前章节尚无审稿结果";
    return;
  }
  summary.textContent = `${Math.round(chapter.review.score)} 分 · ${chapter.review.issues} 个问题${chapter.review.stale ? " · 待复审" : ""}`;
  (chapter.review.issue_details || []).slice(0, 5).forEach((issue) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "inspector-review-item";
    button.textContent = `${issue.severity || "medium"} · ${issue.summary || issue.description || "问题"}`;
    button.addEventListener("click", () => locateReviewIssue(chapter.path, issue));
    root.append(button);
  });
}

function toggleInspector(open, restoreFocus = true) {
  const inspector = $("#inspector");
  const overlay = window.matchMedia("(max-width: 900px)").matches;
  const wasOpen = inspector.classList.contains("open");
  if (open && window.matchMedia("(max-width: 700px)").matches) {
    toggleMobileNavigation(false, false);
  }
  inspector.classList.toggle("open", open);
  $("#inspector-toggle").setAttribute("aria-expanded", String(open));
  $("#inspector-backdrop").hidden = !(open && overlay);
  if (open && overlay) {
    requestAnimationFrame(() => $("#inspector-close").focus());
  } else if (wasOpen && restoreFocus && inspector.contains(document.activeElement)) {
    $("#inspector-toggle").focus();
  }
}

function toggleInspectorCollapsed(collapsed, options = {}) {
  const persist = options.persist !== false;
  state.inspectorCollapsed = collapsed;
  $("#app").classList.toggle("inspector-collapsed", collapsed);
  $("#inspector-restore").hidden = !collapsed;
  $("#inspector-collapse").setAttribute("aria-expanded", String(!collapsed));
  if (persist) {
    state.outlineInspectorAutoCollapsed = false;
    writeLocalValue("openwrite-inspector-collapsed", collapsed ? "1" : "0");
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $(".brand-logo").src = theme === "dark" ? "/brand/logo-dark.svg" : "/brand/logo.svg";
  setMarkdownEditorTheme(theme);
  writeLocalValue("openwrite-theme", theme);
}

function applyShellTheme(theme) {
  // Embed mode (dsh shell): theme follows the shell and never touches the
  // standalone openwrite-theme preference.
  const normalized = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = normalized;
  $(".brand-logo").src = normalized === "dark" ? "/brand/logo-dark.svg" : "/brand/logo.svg";
  setMarkdownEditorTheme(normalized);
}

function setToolHelpExpanded(button, expanded) {
  const panel = document.getElementById(button.getAttribute("aria-controls") || "");
  if (!panel) return;
  button.setAttribute("aria-expanded", String(expanded));
  button.title = expanded ? "收起工具说明" : "查看工具说明";
  panel.hidden = !expanded;
}

function toggleToolHelp(button) {
  const shouldExpand = button.getAttribute("aria-expanded") !== "true";
  $$('[data-tool-help]').forEach((item) => setToolHelpExpanded(item, item === button && shouldExpand));
}

function closeOpenToolHelp(restoreFocus = false) {
  const button = $('[data-tool-help][aria-expanded="true"]');
  if (!button) return false;
  setToolHelpExpanded(button, false);
  if (restoreFocus) button.focus();
  return true;
}

function toggleMobileNavigation(open, restoreFocus = true) {
  const active = Boolean(open && window.matchMedia("(max-width: 700px)").matches);
  const sidebar = $("#studio-sidebar");
  const wasOpen = $("#app").classList.contains("mobile-nav-open");
  if (active) toggleInspector(false, false);
  $("#app").classList.toggle("mobile-nav-open", active);
  $("#mobile-nav-toggle").setAttribute("aria-expanded", String(active));
  $("#mobile-nav-backdrop").hidden = !active;
  if (active) {
    requestAnimationFrame(() => sidebar.querySelector(".nav-item")?.focus());
  } else if (wasOpen && restoreFocus && sidebar.contains(document.activeElement)) {
    $("#mobile-nav-toggle").focus();
  }
}

function bindEvents() {
  $("#bootstrap-retry")?.addEventListener("click", retryBootstrap);
  $("#bootstrap-open-project")?.addEventListener("click", openProjectDialog);
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.navCommand === "tasks") {
        $("#task-center-open").click();
        toggleMobileNavigation(false);
        return;
      }
      if (button.dataset.navCommand === "settings") {
        openModelProfilesDialog();
        toggleMobileNavigation(false);
        return;
      }
      if (button.dataset.agentTarget) chooseAgent(button.dataset.agentTarget);
      setView(button.dataset.view);
    });
  });
  $$('[data-switch-view]').forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.switchView));
  });
  $$('[data-tool-help]').forEach((button) => {
    button.addEventListener("click", () => toggleToolHelp(button));
  });
  $$('[data-library-view]').forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.libraryView));
  });
  $("#library-filter").addEventListener("input", (event) => {
    state.library.query = event.target.value;
    renderDocumentList(state.view);
  });
  $("#library-category-filter").addEventListener("change", (event) => {
    state.library.category = event.target.value;
    renderDocumentList(state.view);
  });
  $("#save-document").addEventListener("click", () => saveDocument());
  $("#delete-chapter").addEventListener("click", openChapterDeleteDialog);
  $("#chapter-delete-form").addEventListener("submit", deleteCurrentChapter);
  $("#chapter-delete-confirm").addEventListener("input", syncChapterDeleteConfirmation);
  $("#chapter-delete-close").addEventListener("click", () => $("#chapter-delete-dialog").close());
  $("#chapter-delete-cancel").addEventListener("click", () => $("#chapter-delete-dialog").close());
  $("#editor-find-toggle").addEventListener("click", () => toggleEditorFind());
  $("#editor-find-close").addEventListener("click", () => toggleEditorFind(false));
  $("#editor-find-panel").addEventListener("submit", (event) => {
    event.preventDefault();
    findNextEditorMatch();
  });
  $("#editor-find-next").addEventListener("click", findNextEditorMatch);
  $("#editor-replace-one").addEventListener("click", replaceEditorMatch);
  $("#editor-replace-all").addEventListener("click", replaceAllEditorMatches);
  $("#editor-find-query").addEventListener("input", () => {
    $("#editor-find-status").textContent = "按下回车查找下一处";
  });
  $("#editor-reading-toggle").addEventListener("click", toggleEditorReadingMode);
  $("#editor-focus-toggle").addEventListener("click", () => toggleEditorFocusMode());
  $("#editor-assistant-toggle").addEventListener("click", () => {
    toggleInspectorCollapsed(false);
    toggleInspector(true);
    switchInspectorTab("assistant");
    $("#inspector-assistant-input").focus();
  });
  $("#review-document").addEventListener("click", runReview);
  $("#reload-document").addEventListener("click", () => {
    if (state.document) openDocument(state.document.path, false);
  });
  $("#focus-form").addEventListener("submit", saveFocus);
  $("#model-state").addEventListener("click", () => openModelProfilesDialog());
  $("#model-settings-open").addEventListener("click", () => openModelProfilesDialog());
  $("#project-settings-open").addEventListener("click", openProjectDialog);
  $("#writing-targets-open").addEventListener("click", openWritingTargetsDialog);
  $("#writing-targets-form").addEventListener("submit", saveWritingTargets);
  $("#writing-targets-close").addEventListener("click", () => $("#writing-targets-dialog").close());
  $("#writing-targets-cancel").addEventListener("click", () => $("#writing-targets-dialog").close());
  bindModelProfilesUI();
  $("#project-form").addEventListener("submit", initializeProject);
  $("#open-project-form").addEventListener("submit", openProject);
  $("#onboarding-open").addEventListener("click", () => startProductTour("workspace"));
  $("#product-tour-skip").addEventListener("click", finishProductTour);
  $("#product-tour-back").addEventListener("click", goToPreviousProductTourStep);
  $("#product-tour-next").addEventListener("click", advanceProductTourManually);
  $("#search-form").addEventListener("submit", searchProject);
  $("#project-dialog").addEventListener("cancel", (event) => {
    if (!state.workspace?.initialized) event.preventDefault();
  });
  $("#write-open").addEventListener("click", () => openSmartWriteDialog());
  $("#outline-tree-back").addEventListener("click", () => setView("outline"));
  $("#outline-add-volume").addEventListener("click", () => openOutlineEditDialog("add_child"));
  $("#outline-source").addEventListener("click", () => openOutlineSource());
  $("#outline-refresh").addEventListener("click", () => loadOutline());
  $("#outline-smart-create").addEventListener("click", () => openSmartWriteDialog());
  $("#outline-search").addEventListener("input", (event) => {
    state.outlineQuery = event.target.value;
    renderOutlineTree();
  });
  $$("[data-outline-status]").forEach((button) => {
    button.addEventListener("click", () => {
      state.outlineStatusFilter = button.dataset.outlineStatus || "all";
      renderOutlineTree();
    });
  });
  $("#outline-expand-all").addEventListener("click", () => setAllOutlineExpanded(true));
  $("#outline-collapse-all").addEventListener("click", () => setAllOutlineExpanded(false));
  $$("[data-outline-pane]").forEach((button) => {
    button.addEventListener("click", () => setOutlineMobilePane(button.dataset.outlinePane));
  });
  $("#outline-node-source").addEventListener("click", () => openOutlineSource(selectedOutlineNode()?.line || 1));
  $("#outline-node-create").addEventListener("click", () => openSmartWriteDialog(selectedOutlineNode()?.id || ""));
  $("#outline-node-rename").addEventListener("click", () => openOutlineEditDialog("rename", selectedOutlineNode()));
  $("#outline-node-add-child").addEventListener("click", () => openOutlineEditDialog("add_child", selectedOutlineNode()));
  $("#outline-node-add-after").addEventListener("click", () => openOutlineEditDialog("add_after", selectedOutlineNode()));
  $("#outline-node-delete").addEventListener("click", () => openOutlineEditDialog("delete", selectedOutlineNode()));
  $("#outline-detail-title").addEventListener("keydown", handleOutlineDetailTitleKeydown);
  $("#outline-detail-title").addEventListener("paste", handleOutlineDetailTitlePaste);
  $("#outline-detail-title").addEventListener("blur", submitOutlineDetailTitle);
  $("#outline-edit-close").addEventListener("click", () => $("#outline-edit-dialog").close());
  $("#outline-edit-cancel").addEventListener("click", () => $("#outline-edit-dialog").close());
  $("#outline-edit-form").addEventListener("submit", submitOutlineEdit);
  $("#write-close").addEventListener("click", () => $("#write-dialog").close());
  $("#write-cancel").addEventListener("click", () => $("#write-dialog").close());
  $("#write-form").addEventListener("submit", runWriter);
  $("#review-close").addEventListener("click", () => $("#review-dialog").close());
  $("#review-current-chapter").addEventListener("click", reviewSelectedWorkspaceChapter);
  $("#review-severity-filter").addEventListener("change", renderReviewWorkspace);
  $("#review-dimension-filter").addEventListener("change", () => {
    const chapter = state.workspace?.documents?.chapters?.find((item) => item.path === state.reviewChapterPath);
    renderReviewWorkspaceIssues(chapter);
  });
  $("#review-fixable-filter").addEventListener("change", renderReviewWorkspace);
  $("#research-form").addEventListener("submit", submitResearch);
  $("#research-refresh").addEventListener("click", loadResearch);
  $("#research-settings-open").addEventListener("click", openResearchSettings);
  $("#research-settings-form").addEventListener("submit", saveResearchSettings);
  $("#research-settings-close").addEventListener("click", () => $("#research-settings-dialog").close());
  $("#research-settings-cancel").addEventListener("click", () => $("#research-settings-dialog").close());
  $("#research-settings-search").addEventListener("change", renderResearchSearchKeyState);
  $("#research-search-key-toggle").addEventListener("click", toggleResearchSearchKey);
  $("#research-search-key-clear").addEventListener("click", clearResearchSearchKey);
  $("#research-model-route-open").addEventListener("click", () => {
    $("#research-settings-dialog").close();
    openModelProfilesDialog("routes");
  });
  $("#research-search").addEventListener("change", renderResearchConfiguration);
  $("#sync-project").addEventListener("click", runSync);
  $("#context-form").addEventListener("submit", inspectContext);
  $("#import-form").addEventListener("submit", importText);
  $("#import-preview-button").addEventListener("click", previewImport);
  ["#import-file", "#import-arc", "#import-start", "#import-force"].forEach((selector) => {
    $(selector).addEventListener("change", invalidateImportPreview);
  });
  $$('input[name="export-format"]').forEach((input) => {
    input.addEventListener("change", syncExportFormat);
  });
  $("#export-download").addEventListener("click", () => {
    $("#export-status").textContent = "正在生成整书文件…";
  });
  $("#create-document-form").addEventListener("submit", createDocument);
  $("#chat-form").addEventListener("submit", submitChat);
  $$('[data-agent]').forEach((button) => button.addEventListener("click", () => chooseAgent(button.dataset.agent)));
  $("#agent-session-new").addEventListener("click", createAgentSession);
  $("#agent-session-delete").addEventListener("click", deleteAgentSession);
  $("#agent-history-refresh").addEventListener("click", () => loadAgentSurface(state.agent, activeAgentSessionId()));
  $("#continuity-refresh").addEventListener("click", loadContinuity);
  $("#relationship-filter").addEventListener("change", () => renderRelationshipGraph(state.continuity?.relationship_graph || {}));
  $("#relationship-origin").addEventListener("change", () => renderRelationshipGraph(state.continuity?.relationship_graph || {}));
  $("#relationship-search").addEventListener("input", () => renderRelationshipGraph(state.continuity?.relationship_graph || {}));
  $("#relationship-search").addEventListener("keydown", handleRelationshipSearchKeydown);
  $("#relationship-fit").addEventListener("click", fitRelationshipGraph);
  $("#relationship-layout").addEventListener("click", toggleRelationshipSimulation);
  $("#relationship-reset").addEventListener("click", resetRelationshipLayout);
  $("#relationship-graph").addEventListener("pointerdown", beginRelationshipPan);
  $("#relationship-graph").addEventListener("pointermove", moveRelationshipPointer);
  $("#relationship-graph").addEventListener("pointerup", endRelationshipPointer);
  $("#relationship-graph").addEventListener("pointercancel", endRelationshipPointer);
  $("#relationship-graph").addEventListener("wheel", zoomRelationshipGraph, { passive: false });
  $("#foreshadow-form").addEventListener("submit", createForeshadowing);
  $("#reference-form").addEventListener("submit", prepareReference);
  $("#reference-structure-confirm").addEventListener("click", confirmReferenceStructure);
  $("#reference-structure-cancel").addEventListener("click", () => {
    $("#reference-structure").hidden = true;
    state.referenceLibrary.pendingStructure = null;
    $("#reference-status").textContent = "可修改原文或分析配置后重新解析";
  });
  $("#reference-synthesize").addEventListener("click", synthesizeReferenceProfile);
  $("#reference-send-goethe").addEventListener("click", sendReferenceProfileToGoethe);
  $("#reference-adoption-preview").addEventListener("click", previewReferenceAdoption);
  $("#reference-adoption-apply").addEventListener("click", applyReferenceAdoption);
  $("#runtime-skill-resolve").addEventListener("click", resolveRuntimeSkills);
  $("#runtime-skill-diagnose").addEventListener("click", diagnoseRuntimeSkills);
  $("#runtime-rules-preview").addEventListener("click", previewRuntimeRules);
  $("#runtime-rules-apply").addEventListener("click", applyRuntimeRules);
  $("#chapter-run-select").addEventListener("change", (event) => {
    selectedChapterRun = chapterRunItems.find((run) => run.run_id === event.target.value) || null;
    renderSelectedChapterRun();
  });
  $("#chapter-intervention-form").addEventListener("submit", recordChapterIntervention);
  $("#chapter-intervention-advance").addEventListener("click", advanceChapterIntervention);
  $("#chapter-run-refresh").addEventListener("click", refreshChapterRuns);
  $("#rolling-plan-select").addEventListener("change", (event) => {
    selectedRollingPlan = rollingPlanItems.find((item) => item.candidate_id === event.target.value) || null;
    renderSelectedRollingPlan();
  });
  $("#rolling-plan-create").addEventListener("click", createRollingPlan);
  $("#rolling-plan-goethe").addEventListener("click", sendRollingPlanToGoethe);
  $("#narrative-forecast-select").addEventListener("change", (event) => {
    selectedNarrativeForecast = narrativeForecastItems.find(
      (item) => item.forecast_id === event.target.value,
    ) || null;
    activeNarrativeBranchId = selectedNarrativeForecast?.selected_branch_id || "";
    renderSelectedNarrativeForecast();
  });
  $("#narrative-forecast-create").addEventListener("click", createNarrativeForecast);
  $("#narrative-forecast-refresh").addEventListener("click", refreshNarrativeForecasts);
  $("#narrative-forecast-select-branch").addEventListener("click", selectNarrativeForecastBranch);
  $("#narrative-forecast-continue").addEventListener("click", continueSelectedNarrativeForecast);
  $("#reference-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (file) {
      $("#reference-content").value = await file.text();
      const stem = file.name.replace(/\.[^.]+$/, "");
      if (!$("#reference-title").value.trim()) $("#reference-title").value = stem;
      if (!$("#reference-id").value.trim()) {
        $("#reference-id").value = stem
          .replace(/\.[^.]+$/, "")
          .toLocaleLowerCase()
          .replace(/[^a-z0-9_-]+/g, "_")
          .replace(/^_+|_+$/g, "")
          .slice(0, 64) || `reference_${Date.now()}`;
      }
    }
  });
  $("#inspector-toggle").addEventListener("click", () => toggleInspector(true));
  $("#inspector-close").addEventListener("click", () => toggleInspector(false));
  $("#inspector-backdrop").addEventListener("click", () => toggleInspector(false));
  $("#inspector-collapse").addEventListener("click", () => toggleInspectorCollapsed(true));
  $("#inspector-restore").addEventListener("click", () => toggleInspectorCollapsed(false));
  $$('[data-inspector-tab]').forEach((button) => {
    button.addEventListener("click", () => switchInspectorTab(button.dataset.inspectorTab));
  });
  $("#inspector-context-open").addEventListener("click", () => {
    setView("tools");
    $("#context-chapter").focus();
  });
  $("#inspector-revision-history").addEventListener("click", () => {
    if (!state.document?.path.includes("/manuscript/")) {
      showToast("请先打开正文章节", true);
      return;
    }
    $("#revision-history").click();
  });
  $("#inspector-assistant-form").addEventListener("submit", submitInspectorAssistant);
  $$('[data-assistant-prompt]').forEach((button) => {
    button.addEventListener("click", () => {
      $("#inspector-assistant-input").value = button.dataset.assistantPrompt;
      submitInspectorAssistant();
    });
  });
  $("#mobile-nav-toggle").addEventListener("click", () => {
    toggleMobileNavigation(!$("#app").classList.contains("mobile-nav-open"));
  });
  $("#mobile-nav-backdrop").addEventListener("click", () => toggleMobileNavigation(false));
  $("#theme-toggle").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (state.library.editorMode === "asset") $("#asset-form").requestSubmit();
      else saveDocument();
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      setView("search");
      $("#search-query").focus();
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f" && state.document) {
      event.preventDefault();
      toggleEditorFind(true);
    }
    if (event.key === "Escape") {
      if (closeOpenToolHelp(true)) return;
      if (state.editorFocusMode) {
        toggleEditorFocusMode(false);
        return;
      }
      if (!$("#editor-find-panel").hidden) {
        toggleEditorFind(false);
        return;
      }
      if (state.productTour.active) finishProductTour();
      toggleInspector(false);
      toggleMobileNavigation(false);
    }
  });
  window.addEventListener("resize", renderProductTour);
  window.addEventListener("scroll", renderProductTour, true);
  window.addEventListener("beforeunload", (event) => {
    if (state.dirty || state.assets.dirty) event.preventDefault();
  });
  window.addEventListener("popstate", routeFromLocation);
  bindRevisionUI({
    refreshWorkspace: loadWorkspace,
    reopenDocument: (path) => openDocument(path, false),
  });
  bindTaskCenter({
    refreshWorkspace: loadWorkspace,
    openTaskResult: openStudioTaskResult,
  });
  bindAssetUI({
    refreshWorkspace: loadWorkspace,
    refreshContinuity: loadContinuity,
    activateAssetEditor: activateStructuredAssetEditor,
  });
}

async function routeFromLocation() {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash.startsWith("doc=")) {
    await openProjectPath(hash.slice(4), false);
  } else if (hash.startsWith("asset=")) {
    const [kind, id] = hash.slice(6).split(":", 2);
    const scope = kindLibraryView(kind);
    const summary = (state.workspace?.documents?.[scope] || []).find(
      (item) => item.asset_kind === kind && item.asset_id === id,
    ) || { kind, id, asset_kind: kind, asset_id: id, scope };
    await openStructuredAsset(summary, false);
  } else if (["search", "outline", "chapters", "review", "core", "story", "characters", "settings", "world", "assets", "agents", "continuity", "transfer", "deconstruct", "skills", "tools", "research"].includes(hash)) {
    setView(hash, false);
  } else {
    setView("dashboard", false);
  }
}

async function start() {
  const embedded = document.documentElement.dataset.embed === "dsh";
  if (embedded) {
    // Embed mode: the boot script already applied the shell's initial theme;
    // keep Vditor in sync and follow live shell theme switches.
    setMarkdownEditorTheme(document.documentElement.dataset.theme);
    $(".brand-logo").src = document.documentElement.dataset.theme === "dark"
      ? "/brand/logo-dark.svg"
      : "/brand/logo.svg";
    window.addEventListener("message", (event) => {
      const data = event.data;
      if (data && data.type === "studio-theme") applyShellTheme(data.theme);
    });
  } else {
    const storedTheme = readLocalValue("openwrite-theme");
    const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(storedTheme || (systemDark ? "dark" : "light"));
  }
  try {
    bindEvents();
  } catch (error) {
    showBootstrapError(new Error(`页面资源版本不一致：${error.message}`));
    return;
  }
  const inspectorPreference = readLocalValue("openwrite-inspector-collapsed");
  toggleInspectorCollapsed(inspectorPreference === null || inspectorPreference === "1");
  try {
    const editor = await initializePrimaryMarkdownEditor({
      onInput: () => markEditorDirty(),
      onSelection: () => syncRevisionControls(),
    });
    $("#editor-fallback-notice").hidden = editor.enhanced;
  } catch (error) {
    $("#editor-fallback-notice").hidden = false;
  }
  try {
    await loadWorkspace();
    await routeFromLocation();
    startProductTour();
  } catch (error) {
    showBootstrapError(error);
  }
}

start();
