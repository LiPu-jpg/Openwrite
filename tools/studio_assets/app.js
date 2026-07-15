"use strict";

const state = {
  workspace: null,
  view: "dashboard",
  document: null,
  dirty: false,
  saving: false,
  agent: "goethe",
  continuity: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const labels = {
  story: "故事资产",
  characters: "人物档案",
  world: "世界设定",
  chapters: "正文章节",
};
const readinessLabels = {
  author_intent: "作者意图",
  background: "故事背景",
  foundation: "基础设定",
  characters: "主要人物",
  outline: "可写大纲",
  creative_focus: "创作罗盘",
};

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    headers["X-OpenWrite-Studio"] = "1";
  }
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("Content-Type") || "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const error = new Error(body?.error || `请求失败 (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
}

function countWritingUnits(text) {
  const withoutHeadings = text.replace(/^\s{0,3}#{1,6}\s+.*$/gm, "");
  const cjk = withoutHeadings.match(/[\u3400-\u4dbf\u4e00-\u9fff]/g) || [];
  const words = withoutHeadings
    .replace(/[\u3400-\u4dbf\u4e00-\u9fff]/g, " ")
    .match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g) || [];
  return cjk.length + words.length;
}

function showToast(message, error = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2600);
}

function setSaveState(message, dirty = false) {
  $("#save-state").textContent = message;
  $("#save-document").disabled = !dirty || state.saving;
}

async function loadWorkspace() {
  state.workspace = await api("/api/workspace");
  renderWorkspace();
  document.querySelector("#app").setAttribute("aria-busy", "false");
  if (!state.workspace.initialized && !$("#project-dialog").open) {
    $("#project-dialog").showModal();
  }
}

function renderWorkspace() {
  const { snapshot, model } = state.workspace;
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

  const modelState = $("#model-state");
  modelState.textContent = model.configured ? model.name : "模型未配置";
  modelState.classList.toggle("ready", model.configured);
  if (model.configured && !$("#model-name").value) $("#model-name").value = model.name;
  $("#write-open").disabled = !model.configured;
  $("#write-open").title = model.configured ? "" : "请通过环境变量配置 LLM_API_KEY";

  renderReadiness(snapshot.readiness);
  renderRecentChapters();
  renderNextActions(snapshot.next_actions);
  fillFocus(snapshot.creative_focus);
  $("#fact-arc").textContent = snapshot.current_arc;
  $("#fact-chapter").textContent = snapshot.current_chapter;
  $("#fact-stage").textContent = snapshot.stage;
  $("#fact-world").textContent = String(snapshot.world_documents);
  $("#fact-tokens").textContent = formatNumber(snapshot.total_tokens);
  $("#fact-review-score").textContent = snapshot.reviewed_chapters
    ? `${snapshot.average_review_score} / 100`
    : "-";
  renderDocumentList(state.view === "dashboard" ? "chapters" : state.view);
  renderOperations();
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
  actions.forEach((action) => {
    const span = document.createElement("span");
    span.className = "next-action";
    span.textContent = action;
    root.append(span);
  });
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
  const documents = state.workspace?.documents[group] || [];
  $("#document-group-title").textContent = labels[group] || "最近章节";
  $("#document-count").textContent = String(documents.length);
  if (!documents.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = group === "chapters" ? "尚无正文" : "暂无文档";
    root.append(empty);
    return;
  }
  documents.forEach((doc) => {
    const button = document.createElement("button");
    button.className = "document-item";
    button.classList.toggle("active", state.document?.path === doc.path);
    button.type = "button";
    button.setAttribute("role", "listitem");
    const title = document.createElement("strong");
    title.textContent = doc.title;
    const subtitle = document.createElement("span");
    subtitle.textContent = doc.subtitle;
    button.append(title, subtitle);
    button.addEventListener("click", () => openDocument(doc.path, true));
    root.append(button);
  });
}

function setView(view, pushHistory = true) {
  state.view = view;
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  const dashboard = view === "dashboard";
  const documentView = ["chapters", "story", "characters", "world"].includes(view);
  $("#dashboard-view").hidden = !dashboard;
  $("#editor-view").hidden = !documentView;
  $("#agents-view").hidden = view !== "agents";
  $("#continuity-view").hidden = view !== "continuity";
  $("#tools-view").hidden = view !== "tools";
  renderDocumentList(dashboard || !documentView ? "chapters" : view);
  if (documentView && (!state.document || documentGroup(state.document.path) !== view)) {
    const first = state.workspace.documents[view]?.[0];
    if (first) openDocument(first.path, false);
  }
  if (view === "continuity") loadContinuity();
  if (pushHistory) {
    history.pushState({ view }, "", dashboard ? "/" : `/#${encodeURIComponent(view)}`);
  }
}

async function openDocument(path, pushHistory) {
  if (state.dirty && !window.confirm("当前文档尚未保存，仍要离开吗？")) return;
  try {
    const doc = await api(`/api/document?path=${encodeURIComponent(path)}`);
    state.document = doc;
    state.dirty = false;
    const group = documentGroup(path);
    state.view = group;
    $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === group));
    $("#dashboard-view").hidden = true;
    $("#editor-view").hidden = false;
    $("#agents-view").hidden = true;
    $("#continuity-view").hidden = true;
    $("#tools-view").hidden = true;
    $("#editor-path").textContent = doc.path;
    $("#editor-title").value = doc.title;
    $("#document-editor").value = doc.content;
    $("#review-document").hidden = group !== "chapters" || !state.workspace.model.configured;
    updateEditorCount();
    setSaveState("已保存", false);
    renderDocumentList(group);
    if (pushHistory) {
      history.pushState({ path }, "", `/#doc=${encodeURIComponent(path)}`);
    }
    $("#document-editor").focus();
  } catch (error) {
    showToast(error.message, true);
  }
}

function documentGroup(path) {
  if (path.startsWith("data/manuscript/")) return "chapters";
  if (path.startsWith("src/characters/")) return "characters";
  if (path.startsWith("src/world/")) return "world";
  return "story";
}

function updateEditorCount() {
  const count = countWritingUnits($("#document-editor").value);
  $("#editor-word-count").textContent = `${formatNumber(count)} 字`;
}

async function saveDocument() {
  if (!state.document || !state.dirty || state.saving) return;
  state.saving = true;
  setSaveState("保存中", true);
  try {
    const saved = await api("/api/document", {
      method: "PUT",
      body: JSON.stringify({
        path: state.document.path,
        content: $("#document-editor").value,
        version: state.document.version,
      }),
    });
    state.document = saved;
    state.dirty = false;
    setSaveState("已保存", false);
    showToast("文档已保存");
    await loadWorkspace();
  } catch (error) {
    setSaveState("保存失败", true);
    showToast(error.message, true);
  } finally {
    state.saving = false;
    $("#save-document").disabled = !state.dirty;
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

async function saveModel(event) {
  event.preventDefault();
  const submit = $("#model-submit");
  submit.disabled = true;
  $("#model-progress").textContent = "正在应用模型配置…";
  try {
    state.workspace = await api("/api/model", {
      method: "POST",
      body: JSON.stringify({
        provider: $("#model-provider").value,
        base_url: $("#model-base-url").value.trim(),
        model: $("#model-name").value.trim(),
        api_key: $("#model-api-key").value.trim(),
        api_format: $("#model-api-format").value,
      }),
    });
    $("#model-api-key").value = "";
    renderWorkspace();
    $("#model-dialog").close();
    showToast(`模型已切换为 ${state.workspace.model.name}`);
  } catch (error) {
    $("#model-progress").textContent = error.message;
  } finally {
    submit.disabled = false;
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
        novel_id: $("#project-id").value.trim(),
        title: $("#project-title").value.trim(),
      }),
    });
    renderWorkspace();
    $("#project-dialog").close();
    showToast("小说工作区已创建");
  } catch (error) {
    $("#project-progress").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

function renderOperations() {
  const operations = state.workspace?.operations || {};
  const diagnostics = operations.diagnostics || [];
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
  const sync = operations.sync || {};
  $("#sync-status").textContent = sync.needs_sync
    ? `待同步：大纲 ${sync.outline_pending ? "有变更" : "已同步"}，角色卡 ${sync.cards || 0}/${sync.profiles || 0}`
    : "src 与 data 已同步";
  renderSourcePacks(operations.source_packs || []);
}

function renderSourcePacks(packs) {
  const root = $("#source-list");
  root.replaceChildren();
  $("#source-count").textContent = String(packs.length);
  if (!packs.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "尚无来源包";
    root.append(empty);
    return;
  }
  packs.forEach((pack) => {
    const row = document.createElement("article");
    row.className = "source-row";
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = pack.source_id;
    const meta = document.createElement("span");
    meta.textContent = [pack.style_ready ? "风格" : "", pack.setting_ready ? "设定" : ""]
      .filter(Boolean).join(" + ") || "提取中";
    copy.append(title, meta);
    const actions = document.createElement("div");
    actions.className = "row-actions";
    [["审阅", "review"], ["全部晋升", "promote"], ["合成风格", "synthesize"]].forEach(([label, action]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "text-button";
      button.textContent = label;
      button.addEventListener("click", () => runSourceAction(action, pack.source_id));
      actions.append(button);
    });
    row.append(copy, actions);
    root.append(row);
  });
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
    $("#context-meta").textContent = `${payload.chapter_id} · 目标 ${formatNumber(payload.target_words)} 字 · ${payload.characters.length} 位相关人物`;
    $("#context-preview").textContent = payload.markdown || "上下文为空";
  } catch (error) {
    $("#context-meta").textContent = error.message;
    showToast(error.message, true);
  }
}

async function importText(event) {
  event.preventDefault();
  const file = $("#import-file").files[0];
  if (!file) return;
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  $("#import-status").textContent = "正在解析并导入章节…";
  try {
    const payload = await api("/api/import", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content: await file.text(),
        arc_id: $("#import-arc").value.trim(),
        start_number: $("#import-start").value,
        force: $("#import-force").checked,
      }),
    });
    state.workspace = payload.workspace;
    renderWorkspace();
    $("#import-status").textContent = `已导入 ${payload.imported.length} 章`;
    showToast(`已导入 ${payload.imported.length} 章正文`);
  } catch (error) {
    $("#import-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
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
    await openDocument(payload.document.path, true);
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
  appendChatMessage("user", "你", message);
  input.value = "";
  $("#chat-submit").disabled = true;
  $("#chat-status").textContent = `${state.agent === "goethe" ? "Goethe" : "Dante"} 正在读取项目并思考…`;
  try {
    const payload = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ agent: state.agent, message }),
    });
    appendChatMessage("assistant", state.agent === "goethe" ? "Goethe" : "Dante", payload.content || "本轮已执行完成。");
    state.workspace = payload.workspace;
    renderWorkspace();
  } catch (error) {
    appendChatMessage("assistant error", "系统", error.message);
  } finally {
    $("#chat-submit").disabled = false;
    $("#chat-status").textContent = "";
    input.focus();
  }
}

function appendChatMessage(role, author, content) {
  const item = document.createElement("article");
  item.className = `chat-message ${role}`;
  const name = document.createElement("strong");
  name.textContent = author;
  const body = document.createElement("p");
  body.textContent = content;
  item.append(name, body);
  $("#chat-log").append(item);
  item.scrollIntoView({ block: "end", behavior: "smooth" });
}

function chooseAgent(agent) {
  state.agent = agent;
  $$('[data-agent]').forEach((button) => button.classList.toggle("active", button.dataset.agent === agent));
  $("#chat-submit").textContent = `发送给 ${agent === "goethe" ? "Goethe" : "Dante"}`;
  $("#chat-input").placeholder = agent === "goethe"
    ? "例如：检查现有资产，帮我把第一篇推进到可写状态。"
    : "例如：写下一章，控制在 3000 字，保持当前创作罗盘。";
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
  $("#source-status").textContent = "正在分块、提取并合并来源信号…";
  try {
    const payload = await api("/api/source", {
      method: "POST",
      body: JSON.stringify({ action: "extract", source_id: $("#source-id").value.trim(), focus: $("#source-focus").value, content: text }),
    });
    state.workspace = payload.workspace;
    renderWorkspace();
    $("#source-status").textContent = "来源包提取完成，可以审阅或晋升";
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
    if (action === "review") $("#source-report").textContent = payload.result.review_report || "无报告";
    $("#source-status").textContent = action === "promote" ? "已晋升到当前作品" : action === "synthesize" ? "合成风格已刷新" : "来源报告已生成";
  } catch (error) {
    $("#source-status").textContent = error.message;
    showToast(error.message, true);
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
    const payload = await api("/api/write", {
      method: "POST",
      body: JSON.stringify({
        guidance: $("#write-guidance").value,
        target_words: Number($("#write-words").value),
      }),
    });
    state.workspace = payload.workspace;
    renderWorkspace();
    $("#write-dialog").close();
    showToast(`${payload.result.chapter_id} 已完成，${formatNumber(payload.result.word_count)} 字`);
    if (payload.result.draft_path) {
      const match = state.workspace.documents.chapters.find((item) =>
        item.path.endsWith(`/${payload.result.chapter_id}.md`)
      );
      if (match) await openDocument(match.path, true);
    }
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
  dialog.showModal();
  try {
    const payload = await api("/api/review", {
      method: "POST",
      body: JSON.stringify({ path: state.document.path }),
    });
    state.workspace = payload.workspace;
    renderWorkspace();
    renderReview(payload.result);
  } catch (error) {
    $("#review-loading").textContent = error.message;
    $("#review-loading").classList.add("error");
  }
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
    const severityName = ["critical", "warning", "info"].includes(issue.severity)
      ? issue.severity : "warning";
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
    root.append(item);
  });
}

function toggleInspector(open) {
  const inspector = $("#inspector");
  inspector.classList.toggle("open", open);
  $("#inspector-toggle").setAttribute("aria-expanded", String(open));
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $(".brand-logo").src = theme === "dark" ? "/brand/logo-dark.svg" : "/brand/logo.svg";
  localStorage.setItem("openwrite-theme", theme);
}

function bindEvents() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  $$('[data-switch-view]').forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.switchView));
  });
  $("#document-editor").addEventListener("input", () => {
    state.dirty = true;
    setSaveState("未保存", true);
    updateEditorCount();
  });
  $("#save-document").addEventListener("click", saveDocument);
  $("#review-document").addEventListener("click", runReview);
  $("#reload-document").addEventListener("click", () => {
    if (state.document) openDocument(state.document.path, false);
  });
  $("#focus-form").addEventListener("submit", saveFocus);
  $("#model-state").addEventListener("click", () => $("#model-dialog").showModal());
  $("#model-close").addEventListener("click", () => $("#model-dialog").close());
  $("#model-cancel").addEventListener("click", () => $("#model-dialog").close());
  $("#model-form").addEventListener("submit", saveModel);
  $("#project-form").addEventListener("submit", initializeProject);
  $("#project-dialog").addEventListener("cancel", (event) => {
    if (!state.workspace?.initialized) event.preventDefault();
  });
  $("#write-open").addEventListener("click", () => $("#write-dialog").showModal());
  $("#write-close").addEventListener("click", () => $("#write-dialog").close());
  $("#write-cancel").addEventListener("click", () => $("#write-dialog").close());
  $("#write-form").addEventListener("submit", runWriter);
  $("#review-close").addEventListener("click", () => $("#review-dialog").close());
  $("#sync-project").addEventListener("click", runSync);
  $("#context-form").addEventListener("submit", inspectContext);
  $("#import-form").addEventListener("submit", importText);
  $("#create-document-form").addEventListener("submit", createDocument);
  $("#chat-form").addEventListener("submit", submitChat);
  $$('[data-agent]').forEach((button) => button.addEventListener("click", () => chooseAgent(button.dataset.agent)));
  $("#continuity-refresh").addEventListener("click", loadContinuity);
  $("#foreshadow-form").addEventListener("submit", createForeshadowing);
  $("#source-form").addEventListener("submit", extractSource);
  $("#source-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (file) $("#source-content").value = await file.text();
  });
  $("#inspector-toggle").addEventListener("click", () => toggleInspector(true));
  $("#inspector-close").addEventListener("click", () => toggleInspector(false));
  $("#theme-toggle").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveDocument();
    }
    if (event.key === "Escape") toggleInspector(false);
  });
  window.addEventListener("beforeunload", (event) => {
    if (state.dirty) event.preventDefault();
  });
  window.addEventListener("popstate", routeFromLocation);
}

async function routeFromLocation() {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash.startsWith("doc=")) {
    await openDocument(hash.slice(4), false);
  } else if (["chapters", "story", "characters", "world", "agents", "continuity", "tools"].includes(hash)) {
    setView(hash, false);
  } else {
    setView("dashboard", false);
  }
}

async function start() {
  const storedTheme = localStorage.getItem("openwrite-theme");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(storedTheme || (systemDark ? "dark" : "light"));
  bindEvents();
  try {
    await loadWorkspace();
    await routeFromLocation();
  } catch (error) {
    document.querySelector("#app").setAttribute("aria-busy", "false");
    showToast(error.message, true);
  }
}

start();
