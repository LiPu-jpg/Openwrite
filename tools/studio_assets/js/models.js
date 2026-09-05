import { $, $$, api, formatNumber, modelPresets, showToast, state } from "/js/core.js";

const routeLabels = {
  goethe: "Goethe 规划",
  dante: "Dante 正文",
  chapter_write: "章节写作",
  review: "章节审稿",
  source_extract: "来源提取",
  revision: "修订生成",
  search: "项目搜索",
  research: "深度研究",
};

let selectedProfileId = "";
let profileSavedCallback = null;

const embeddingPresets = {
  local: [
    { id: "local-bge-small-zh", group: "中文与多语种", label: "BGE Small 中文（推荐）", model: "BAAI/bge-small-zh-v1.5", dimension: 512, maxTokens: 512, meta: "中文 · 约 90 MB · 速度优先" },
    { id: "local-jina-v2-zh", group: "中文与多语种", label: "Jina v2 中文长文本", model: "jinaai/jina-embeddings-v2-base-zh", dimension: 768, maxTokens: 8192, meta: "中英混合 · 约 640 MB · 长文本" },
    { id: "local-multilingual-minilm", group: "中文与多语种", label: "MiniLM 多语种轻量版", model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", dimension: 384, maxTokens: 512, meta: "约 50 种语言 · 约 220 MB · 轻量" },
    { id: "local-multilingual-mpnet", group: "中文与多语种", label: "MPNet 多语种质量版", model: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2", dimension: 768, maxTokens: 384, meta: "约 50 种语言 · 约 1 GB · 质量优先" },
    { id: "local-multilingual-e5", group: "中文与多语种", label: "E5 Large 多语种", model: "intfloat/multilingual-e5-large", dimension: 1024, maxTokens: 512, meta: "约 100 种语言 · 约 2.24 GB · 高质量" },
    { id: "local-bge-small-en", group: "英文", label: "BGE Small 英文", model: "BAAI/bge-small-en-v1.5", dimension: 384, maxTokens: 512, meta: "英文 · 约 67 MB · 速度优先" },
    { id: "local-mxbai-large", group: "英文", label: "Mixedbread Large", model: "mixedbread-ai/mxbai-embed-large-v1", dimension: 1024, maxTokens: 512, meta: "英文 · 约 640 MB · 检索质量" },
    { id: "local-snowflake-long", group: "英文", label: "Snowflake Arctic Long", model: "snowflake/snowflake-arctic-embed-m-long", dimension: 768, maxTokens: 2048, meta: "英文 · 约 540 MB · 较长上下文" },
    { id: "local-jina-v2-en", group: "英文", label: "Jina v2 英文长文本", model: "jinaai/jina-embeddings-v2-base-en", dimension: 768, maxTokens: 8192, meta: "英文 · 约 520 MB · 长文本" },
    { id: "local-nomic-q", group: "英文", label: "Nomic v1.5 量化版", model: "nomic-ai/nomic-embed-text-v1.5-Q", dimension: 768, maxTokens: 8192, meta: "英文 · 约 130 MB · 长文本量化" },
  ],
  openai: [
    { id: "cloud-openai-small", group: "OpenAI", label: "OpenAI · text-embedding-3-small", model: "text-embedding-3-small", dimension: 1536, maxTokens: 8191, baseUrl: "https://api.openai.com/v1", meta: "多语种 · 成本优先" },
    { id: "cloud-openai-large", group: "OpenAI", label: "OpenAI · text-embedding-3-large", model: "text-embedding-3-large", dimension: 3072, maxTokens: 8191, baseUrl: "https://api.openai.com/v1", meta: "多语种 · 质量优先" },
    { id: "cloud-openai-ada", group: "OpenAI", label: "OpenAI · ada-002（兼容旧索引）", model: "text-embedding-ada-002", dimension: 1536, maxTokens: 8191, baseUrl: "https://api.openai.com/v1", meta: "多语种 · 旧项目兼容" },
    { id: "cloud-dashscope-v3", group: "国内兼容接口", label: "阿里云百炼 · text-embedding-v3", model: "text-embedding-v3", dimension: 1024, maxTokens: 8192, baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", meta: "中文与多语种 · 通义兼容接口" },
    { id: "cloud-zhipu-v3", group: "国内兼容接口", label: "智谱 · embedding-3", model: "embedding-3", dimension: 2048, maxTokens: 8192, baseUrl: "https://open.bigmodel.cn/api/paas/v4", meta: "中文与多语种 · 可调维度" },
    { id: "cloud-siliconflow-bge-m3", group: "国内兼容接口", label: "硅基流动 · BGE-M3", model: "BAAI/bge-m3", dimension: 1024, maxTokens: 8192, baseUrl: "https://api.siliconflow.cn/v1", meta: "中文与多语种 · 检索增强" },
    { id: "cloud-siliconflow-qwen3", group: "国内兼容接口", label: "硅基流动 · Qwen3 Embedding 0.6B", model: "Qwen/Qwen3-Embedding-0.6B", dimension: 1024, maxTokens: 32768, baseUrl: "https://api.siliconflow.cn/v1", meta: "中文与多语种 · 长上下文" },
    { id: "cloud-jina-v3", group: "国际兼容接口", label: "Jina AI · embeddings-v3", model: "jina-embeddings-v3", dimension: 1024, maxTokens: 8192, baseUrl: "https://api.jina.ai/v1", meta: "多语种 · 多任务检索" },
    { id: "cloud-voyage-35", group: "国际兼容接口", label: "Voyage AI · voyage-3.5", model: "voyage-3.5", dimension: 1024, maxTokens: 32000, baseUrl: "https://api.voyageai.com/v1", meta: "多语种 · 长上下文" },
    { id: "cloud-together-bge", group: "国际兼容接口", label: "Together AI · BGE Large EN", model: "BAAI/bge-large-en-v1.5", dimension: 1024, maxTokens: 512, baseUrl: "https://api.together.xyz/v1", meta: "英文 · BGE 托管接口" },
  ],
};

function embeddingPreset(provider, presetId) {
  return (embeddingPresets[provider] || []).find((preset) => preset.id === presetId) || null;
}

function detectEmbeddingPreset(provider, model, baseUrl = "") {
  const normalizedModel = String(model || "").trim().toLowerCase();
  const normalizedBase = String(baseUrl || "").trim().replace(/\/$/, "").toLowerCase();
  const candidates = (embeddingPresets[provider] || []).filter(
    (preset) => preset.model.toLowerCase() === normalizedModel,
  );
  if (provider === "local" || !normalizedBase) return candidates[0] || null;
  return candidates.find((preset) => preset.baseUrl?.toLowerCase() === normalizedBase)
    || candidates[0]
    || null;
}

function renderEmbeddingPresetOptions(selectedId = "custom") {
  const provider = $("#model-embedding-provider").value || "openai";
  const select = $("#model-embedding-preset");
  select.replaceChildren();
  const groups = new Map();
  (embeddingPresets[provider] || []).forEach((preset) => {
    if (!groups.has(preset.group)) {
      const group = document.createElement("optgroup");
      group.label = preset.group;
      groups.set(preset.group, group);
      select.append(group);
    }
    const option = document.createElement("option");
    option.value = preset.id;
    option.textContent = preset.label;
    groups.get(preset.group).append(option);
  });
  const custom = document.createElement("option");
  custom.value = "custom";
  custom.textContent = "自定义模型";
  select.append(custom);
  select.value = embeddingPreset(provider, selectedId) ? selectedId : "custom";
}

function renderEmbeddingPresetHelp(preset) {
  $("#model-embedding-preset-help").textContent = preset
    ? `${preset.meta} · ${formatNumber(preset.dimension)} 维 · ${formatNumber(preset.maxTokens)} tokens`
    : "自定义 · 参数以模型服务实际返回为准";
}

function applyEmbeddingPreset() {
  const provider = $("#model-embedding-provider").value || "openai";
  const preset = embeddingPreset(provider, $("#model-embedding-preset").value);
  if (!preset) {
    renderEmbeddingPresetHelp(null);
    return;
  }
  $("#model-embedding-name").value = preset.model;
  $("#model-embedding-dimension").value = String(preset.dimension);
  $("#model-embedding-max-tokens").value = String(preset.maxTokens);
  if (provider === "openai" && preset.baseUrl) {
    $("#model-embedding-base-url").value = preset.baseUrl;
  }
  renderEmbeddingPresetHelp(preset);
}

function syncEmbeddingPreset() {
  const provider = $("#model-embedding-provider").value || "openai";
  const preset = detectEmbeddingPreset(
    provider,
    $("#model-embedding-name").value,
    $("#model-embedding-base-url").value,
  );
  $("#model-embedding-preset").value = preset?.id || "custom";
  renderEmbeddingPresetHelp(preset);
}

function surface() {
  return state.workspace?.model_profiles
    || { profiles: [], presets: [], routes: {}, default_profile_id: "default" };
}

function presetCatalog() {
  const dynamic = Object.fromEntries(
    (surface().presets || []).map((preset) => [preset.id, preset]),
  );
  return { ...modelPresets, ...dynamic };
}

function renderPresetOptions(selected = "") {
  const select = $("#model-preset");
  const current = selected || select.value;
  const groups = new Map();
  (surface().presets || []).forEach((preset) => {
    const family = preset.family || "常用模型";
    if (!groups.has(family)) groups.set(family, []);
    groups.get(family).push(preset);
  });
  const interfacePresets = [
    { id: "openai", label: "OpenAI 格式接口" },
    { id: "anthropic", label: "Anthropic 格式接口" },
    { id: "custom", label: "自定义 OpenAI-compatible 接口" },
  ];
  select.replaceChildren();
  groups.forEach((presets, family) => {
    const group = document.createElement("optgroup");
    group.label = family;
    presets.forEach((preset) => {
      const option = document.createElement("option");
      option.value = preset.id;
      option.textContent = preset.label;
      group.append(option);
    });
    select.append(group);
  });
  const interfaces = document.createElement("optgroup");
  interfaces.label = "接口模板";
  interfacePresets.forEach((preset) => {
    const option = document.createElement("option");
    option.value = preset.id;
    option.textContent = preset.label;
    interfaces.append(option);
  });
  select.append(interfaces);
  select.value = presetCatalog()[current] ? current : "custom";
}

function renderPresetHelp(preset) {
  const help = $("#model-preset-help");
  if (!preset) {
    help.textContent = "自定义参数；请以模型服务的当前限制为准";
    return;
  }
  if (!preset.id) {
    help.textContent = "接口模板；当前容量以下方数值为准";
    return;
  }
  const sourceNote = preset.metadata_status === "conflict"
    ? " · LiteLLM 本地元数据较旧，当前按官方规格"
    : "";
  const outputNote = preset.output_limit_known === false ? "（保守预设）" : "";
  help.textContent = `${preset.description ? `${preset.description} · ` : ""}`
    + `上下文 ${formatNumber(preset.context_tokens)} · 最大输出 ${formatNumber(preset.max_tokens)}${outputNote}`
    + sourceNote;
}

function operationForCurrentView() {
  if (state.view === "agents") return state.agent;
  return {
    chapters: "chapter_write",
    review: "review",
    tools: "source_extract",
    search: "search",
    research: "research",
  }[state.view] || "goethe";
}

function profileForOperation(operation) {
  const models = surface();
  const profileId = models.routes?.[operation] || models.default_profile_id;
  return models.profiles.find((profile) => profile.id === profileId) || null;
}

function profileReadyForOperation(profile, operation) {
  if (!profile) return false;
  if (operation === "search" && (profile.search_mode || "vector") === "vector") {
    return Boolean(profile.embedding_configured);
  }
  return Boolean(profile.configured);
}

export function updateRoutedModelIndicator() {
  const operation = operationForCurrentView();
  const profile = profileForOperation(operation);
  const ready = profileReadyForOperation(profile, operation);
  const label = profile ? `${routeLabels[operation]} · ${profile.label}` : "未配置";
  $("#model-topbar-name").textContent = label;
  $("#model-connection-dot").classList.toggle("ready", ready);
  const button = $("#model-settings-open");
  button.title = profile
    ? `${routeLabels[operation]}使用 ${
        operation === "search" && (profile.search_mode || "vector") === "vector"
          ? profile.embedding_model
          : profile.model
      }${ready ? "" : "（配置未就绪）"}`
    : "打开模型设置";
  const writer = profileForOperation("chapter_write");
  $("#write-open").disabled = !writer?.configured;
  $("#write-open").title = writer?.configured ? "" : "请先配置章节写作路由的模型档案";
}

export function renderModelProfilesUI() {
  const models = surface();
  renderPresetOptions();
  if (!models.profiles.some((profile) => profile.id === selectedProfileId)) {
    selectedProfileId = models.default_profile_id || models.profiles[0]?.id || "";
  }
  renderProfileList();
  renderRouteGrid();
  updateRoutedModelIndicator();
  if ($("#model-dialog").open) fillProfileForm(selectedProfile());
}

function selectedProfile() {
  return surface().profiles.find((profile) => profile.id === selectedProfileId) || null;
}

function renderProfileList() {
  const root = $("#model-profile-list");
  root.replaceChildren();
  const models = surface();
  models.profiles.forEach((profile) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "model-profile-item";
    button.classList.toggle("active", profile.id === selectedProfileId);
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(profile.id === selectedProfileId));
    const name = document.createElement("strong");
    name.textContent = profile.label;
    const meta = document.createElement("span");
    meta.textContent = `${profile.model} · ${profile.configured ? "已配置" : "缺少 Key"}`;
    button.append(name, meta);
    button.addEventListener("click", () => {
      selectedProfileId = profile.id;
      renderProfileList();
      fillProfileForm(profile);
    });
    root.append(button);
  });
  if (!models.profiles.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "尚无模型档案";
    root.append(empty);
  }
}

function emptyProfile() {
  const defaults = presetCatalog()["openai-gpt-5.6-terra"] || presetCatalog().openai;
  return {
    id: "",
    label: "",
    provider: "openai",
    base_url: defaults.base_url,
    model: defaults.model,
    api_format: "chat",
    context_tokens: defaults.context_tokens,
    max_output_tokens: defaults.max_tokens,
    temperature: 0.7,
    timeout_seconds: 120,
    embedding_provider: "openai",
    embedding_base_url: "",
    embedding_model: "text-embedding-3-small",
    embedding_dimension: 1536,
    embedding_max_tokens: 8192,
    search_mode: "vector",
    configured: false,
  };
}

function detectPreset(profile) {
  const base = String(profile?.base_url || "").toLowerCase();
  const name = String(profile?.model || "").toLowerCase();
  const exact = (surface().presets || []).find((preset) => (
    String(preset.model || "").toLowerCase() === name
    && String(preset.base_url || "").toLowerCase().replace(/\/$/, "") === base.replace(/\/$/, "")
    && String(preset.api_format || "chat") === String(profile?.api_format || "chat")
    && Number(preset.context_tokens) === Number(profile?.context_tokens)
    && Number(preset.max_tokens) === Number(profile?.max_output_tokens)
  ));
  if (exact) return exact.id;
  if (profile?.provider === "anthropic") return "anthropic";
  if (profile?.provider === "openai" || base.includes("api.openai.com")) return "openai";
  return "custom";
}

function fillProfileForm(value) {
  const profile = value || emptyProfile();
  $("#model-profile-id").value = profile.id || "";
  $("#model-profile-id").readOnly = Boolean(profile.id);
  $("#model-profile-label").value = profile.label || "";
  const preset = detectPreset(profile);
  renderPresetOptions(preset);
  $("#model-preset").value = preset;
  renderPresetHelp(presetCatalog()[preset]);
  $("#model-base-url").value = profile.base_url || "";
  $("#model-name").value = profile.model || "";
  $("#model-api-format").value = profile.api_format || "chat";
  $("#model-context-tokens").value = String(profile.context_tokens || 64000);
  $("#model-max-tokens").value = String(profile.max_output_tokens || 24000);
  $("#model-temperature").value = String(profile.temperature ?? 0.7);
  $("#model-timeout").value = String(profile.timeout_seconds || 120);
  $("#model-embedding-provider").value = profile.embedding_provider || "openai";
  $("#model-embedding-base-url").value = profile.embedding_base_url || "";
  $("#model-embedding-name").value = profile.embedding_model || "text-embedding-3-small";
  $("#model-embedding-dimension").value = String(profile.embedding_dimension || 1536);
  $("#model-embedding-max-tokens").value = String(profile.embedding_max_tokens || 8192);
  $("#model-search-mode").value = profile.search_mode || "vector";
  $("#model-api-key").value = "";
  $("#model-embedding-api-key").value = "";
  $("#model-key-state").textContent = profile.configured
    ? "本机已有凭据；留空即可沿用"
    : "此档案尚未保存 Key";
  $("#model-embedding-key-state").textContent = profile.embedding_key_configured
    ? "本机已有独立 Embedding Key；留空即可沿用"
    : "留空时沿用主模型 API Key";
  $("#model-dialog-current").textContent = profile.id
    ? `${profile.label} · ${formatNumber(profile.context_tokens)} 上下文`
    : "新建模型档案";
  $("#model-dialog-status-dot").classList.toggle("ready", Boolean(profile.configured));
  updateEmbeddingFields(false);
  renderDeleteFallback(profile.id || "");
}

function updateEmbeddingFields(applyDefaults = true) {
  const provider = $("#model-embedding-provider").value || "openai";
  const local = provider === "local";
  $$('[data-embedding-cloud]').forEach((field) => { field.hidden = local; });
  $("#model-embedding-base-url").disabled = local;
  $("#model-embedding-api-key").disabled = local;
  if (applyDefaults) {
    const preset = embeddingPresets[provider]?.[0] || null;
    renderEmbeddingPresetOptions(preset?.id || "custom");
    applyEmbeddingPreset();
  } else {
    const preset = detectEmbeddingPreset(
      provider,
      $("#model-embedding-name").value,
      $("#model-embedding-base-url").value,
    );
    renderEmbeddingPresetOptions(preset?.id || "custom");
    renderEmbeddingPresetHelp(preset);
  }
  if (local) {
    $("#model-embedding-key-state").textContent = "本地运行无需 API Key";
  }
}

function renderDeleteFallback(profileId) {
  const select = $("#model-delete-fallback");
  select.replaceChildren();
  surface().profiles.filter((profile) => profile.id !== profileId).forEach((profile) => {
    const option = document.createElement("option");
    option.value = profile.id;
    option.textContent = `回退到 ${profile.label}`;
    select.append(option);
  });
  $("#model-profile-delete").disabled = !profileId || surface().profiles.length <= 1;
  select.hidden = !profileId || surface().profiles.length <= 1;
}

function profilePayload() {
  const preset = presetCatalog()[$("#model-preset").value] || modelPresets.custom;
  const existing = selectedProfile();
  return {
    id: $("#model-profile-id").value.trim(),
    label: $("#model-profile-label").value.trim(),
    provider: preset.provider,
    base_url: $("#model-base-url").value.trim(),
    model: $("#model-name").value.trim(),
    api_key: $("#model-api-key").value.trim(),
    api_format: $("#model-api-format").value,
    context_tokens: Number($("#model-context-tokens").value),
    max_output_tokens: Number($("#model-max-tokens").value),
    temperature: Number($("#model-temperature").value),
    timeout_seconds: Number($("#model-timeout").value),
    embedding_provider: $("#model-embedding-provider").value,
    embedding_base_url: $("#model-embedding-base-url").value.trim(),
    embedding_model: $("#model-embedding-name").value.trim(),
    embedding_dimension: Number($("#model-embedding-dimension").value),
    embedding_max_tokens: Number($("#model-embedding-max-tokens").value),
    search_mode: $("#model-search-mode").value,
    embedding_api_key: $("#model-embedding-api-key").value.trim(),
    credential_ref: existing?.credential_ref || "",
    remember_api_key: $("#model-remember-key").checked,
  };
}

async function saveProfile(event) {
  event.preventDefault();
  const submit = $("#model-submit");
  submit.disabled = true;
  $("#model-progress").textContent = "正在保存模型档案…";
  try {
    const result = await api("/api/model/profiles", {
      method: "POST",
      body: JSON.stringify(profilePayload()),
    });
    const saved = result.data || result;
    state.workspace.model_profiles = saved.model_profiles;
    if (saved.workspace) state.workspace = saved.workspace;
    selectedProfileId = saved.profile.id;
    renderModelProfilesUI();
    if (profileSavedCallback) profileSavedCallback(saved);
    $("#model-progress").textContent = "档案已保存，任务路由立即生效。";
    showToast(`已保存模型档案 ${saved.profile.label}`);
  } catch (error) {
    $("#model-progress").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

async function testConnection() {
  const button = $("#model-test");
  button.disabled = true;
  $("#model-progress").textContent = "正在发送最小连接测试…";
  try {
    const result = await api("/api/model/test", {
      method: "POST",
      body: JSON.stringify(profilePayload()),
    });
    $("#model-progress").textContent = `连接成功 · ${result.data.model} · ${formatNumber(result.data.latency_ms)} ms`;
  } catch (error) {
    $("#model-progress").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function testEmbeddingConnection() {
  const button = $("#model-embedding-test");
  button.disabled = true;
  const provider = $("#model-embedding-provider").value;
  $("#model-progress").textContent = provider === "local"
    ? "正在加载本地 Embedding 模型…"
    : "正在测试 Embedding 端点…";
  try {
    const result = await api("/api/model/embedding/test", {
      method: "POST",
      body: JSON.stringify(profilePayload()),
    });
    $("#model-progress").textContent = `Embedding 可用 · ${result.data.model} · ${result.data.dimension} 维 · ${formatNumber(result.data.latency_ms)} ms`;
  } catch (error) {
    $("#model-progress").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function deleteProfile() {
  const profile = selectedProfile();
  if (!profile) return;
  if (!window.confirm(`删除模型档案“${profile.label}”？`)) return;
  try {
    const result = await api("/api/model/profiles/delete", {
      method: "POST",
      body: JSON.stringify({
        profile_id: profile.id,
        fallback_id: $("#model-delete-fallback").value,
      }),
    });
    state.workspace.model_profiles = result.data.model_profiles;
    selectedProfileId = result.data.model_profiles.default_profile_id;
    renderModelProfilesUI();
    showToast("模型档案已删除");
  } catch (error) {
    $("#model-progress").textContent = error.message;
  }
}

function renderRouteGrid() {
  const root = $("#model-route-grid");
  root.replaceChildren();
  const models = surface();
  Object.entries(routeLabels).forEach(([route, label]) => {
    const field = document.createElement("label");
    field.className = "model-route-field";
    const title = document.createElement("span");
    title.textContent = label;
    const select = document.createElement("select");
    select.dataset.modelRoute = route;
    models.profiles.forEach((profile) => {
      const option = document.createElement("option");
      option.value = profile.id;
      option.textContent = `${profile.label} · ${profile.model}`;
      select.append(option);
    });
    select.value = models.routes?.[route] || models.default_profile_id;
    field.append(title, select);
    root.append(field);
  });
}

async function saveRoutes() {
  const routes = {};
  $$('[data-model-route]').forEach((select) => { routes[select.dataset.modelRoute] = select.value; });
  try {
    const result = await api("/api/model/routes", {
      method: "POST",
      body: JSON.stringify({ routes }),
    });
    state.workspace.model_profiles = result.data.model_profiles;
    renderModelProfilesUI();
    $("#model-progress").textContent = "任务路由已保存，下一次操作立即生效。";
    showToast("任务路由已更新");
  } catch (error) {
    $("#model-progress").textContent = error.message;
  }
}

function switchTab(tab) {
  $$('[data-model-tab]').forEach((button) => {
    const active = button.dataset.modelTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#model-profiles-pane").hidden = tab !== "profiles";
  $("#model-routes-pane").hidden = tab !== "routes";
}

function applyPreset() {
  const preset = presetCatalog()[$("#model-preset").value];
  if (!preset) return;
  $("#model-base-url").value = preset.base_url;
  $("#model-name").value = preset.model;
  $("#model-api-format").value = preset.api_format;
  $("#model-context-tokens").value = String(preset.context_tokens);
  $("#model-max-tokens").value = String(preset.max_tokens);
  renderPresetHelp(preset);
}

function toggleKey() {
  const input = $("#model-api-key");
  const visible = input.type === "text";
  input.type = visible ? "password" : "text";
  $("#model-key-toggle").textContent = visible ? "显示" : "隐藏";
  $("#model-key-toggle").setAttribute("aria-pressed", String(!visible));
}

export function openModelProfilesDialog(tab = "profiles") {
  renderModelProfilesUI();
  fillProfileForm(selectedProfile());
  switchTab(tab);
  $("#model-progress").textContent = "";
  $("#model-dialog").showModal();
}

export function bindModelProfilesUI(options = {}) {
  profileSavedCallback = typeof options.onProfileSaved === "function"
    ? options.onProfileSaved
    : null;
  $("#model-form").addEventListener("submit", saveProfile);
  $("#model-profile-new").addEventListener("click", () => {
    selectedProfileId = "";
    renderProfileList();
    fillProfileForm(null);
    $("#model-profile-id").focus();
  });
  $("#model-profile-delete").addEventListener("click", deleteProfile);
  $("#model-route-save").addEventListener("click", saveRoutes);
  $("#model-test").addEventListener("click", testConnection);
  $("#model-embedding-test").addEventListener("click", testEmbeddingConnection);
  $("#model-key-toggle").addEventListener("click", toggleKey);
  $("#model-preset").addEventListener("change", applyPreset);
  $("#model-embedding-provider").addEventListener("change", () => updateEmbeddingFields(true));
  $("#model-embedding-preset").addEventListener("change", applyEmbeddingPreset);
  $("#model-embedding-name").addEventListener("input", syncEmbeddingPreset);
  $("#model-embedding-base-url").addEventListener("input", syncEmbeddingPreset);
  $$('[data-model-tab]').forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.modelTab)));
  $("#model-close").addEventListener("click", () => $("#model-dialog").close());
  $("#model-cancel").addEventListener("click", () => $("#model-dialog").close());
}
