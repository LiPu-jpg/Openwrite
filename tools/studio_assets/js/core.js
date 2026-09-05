export const state = {
  workspace: null,
  view: "dashboard",
  document: null,
  dirty: false,
  saving: false,
  autoSaveTimer: null,
  editorTargetWords: 0,
  editorReadingMode: false,
  editorFocusMode: false,
  assistantSubmitting: false,
  agent: "goethe",
  agentSessionId: { goethe: "default", dante: "default" },
  agentSessions: { goethe: [], dante: [] },
  agentActivity: {
    timer: null,
    startedAt: 0,
    agentLabel: "AI",
    baseNote: "",
    runId: "",
    pollPromise: null,
    serverTitle: "",
    serverNote: "",
    root: null,
    eventList: null,
    lastSequence: 0,
    eventCount: 0,
    lastEventName: "",
  },
  inspectorCollapsed: false,
  continuity: null,
  outline: null,
  outlineSelectedId: null,
  outlineRenamingId: null,
  outlineExpandedIds: new Set(),
  outlineExpansionInitialized: false,
  outlineExpansionKey: "",
  outlineQuery: "",
  outlineStatusFilter: "all",
  outlineMobilePane: "tree",
  outlineInspectorAutoCollapsed: false,
  productTour: { active: false, step: "" },
  revisionProposal: null,
  revisionHunkSelection: new Set(),
  contextPreviewRevisions: {},
  reviewChapterPath: "",
  tasks: [],
  research: { status: null, selectedReportId: "", searchProviderInitialized: false },
  sourceAnalysis: {
    selectedSourceIds: new Set(),
    profile: null,
    promotionPreview: null,
    activeSourceId: "",
  },
  referenceLibrary: {
    selectedSourceIds: new Set(),
    activeSourceId: "",
    pendingStructure: null,
    profile: null,
    adoptionPreview: null,
  },
  library: {
    query: "",
    category: "all",
    editorMode: "document",
  },
  runtimeSkill: { resolution: null, rulePreview: null, skills: [], diagnostics: [] },
  transfer: { importPreview: null, importContent: "" },
  assets: {
    kind: "character",
    items: [],
    selected: null,
    selectedForExport: new Set(),
    mode: "structured",
    draft: null,
    dirty: false,
    packagePreview: null,
  },
  relationship: {
    nodes: [], edges: [], positions: new Map(), selectedId: null,
    matchIds: new Set(), query: "",
    scale: 1, tx: 0, ty: 0, paused: false, frame: null, ticks: 0, pointer: null,
  },
};

export const $ = (selector) => document.querySelector(selector);
export const $$ = (selector) => Array.from(document.querySelectorAll(selector));

export const labels = {
  outline: "可写大纲",
  core: "作品核心",
  characters: "角色",
  settings: "设定",
  chapters: "正文章节",
};

export const readinessLabels = {
  author_intent: "作者意图",
  background: "故事背景",
  foundation: "基础设定",
  characters: "主要人物",
  outline: "可写大纲",
  creative_focus: "创作罗盘",
};

export const modelPresets = {
  openai: {
    provider: "openai",
    base_url: "https://api.openai.com/v1",
    model: "gpt-5.6-sol",
    api_format: "chat",
    context_tokens: 1050000,
    max_tokens: 128000,
  },
  anthropic: {
    provider: "anthropic",
    base_url: "https://api.anthropic.com",
    model: "claude-sonnet-5",
    api_format: "chat",
    context_tokens: 1000000,
    max_tokens: 128000,
  },
  custom: {
    provider: "custom",
    base_url: "",
    model: "",
    api_format: "chat",
    context_tokens: 64000,
    max_tokens: 24000,
  },
};

export async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    headers["X-OpenWrite-Studio"] = "1";
  }
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("Content-Type") || "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const message = typeof body?.error === "string"
      ? body.error
      : (body?.error?.message || `请求失败 (${response.status})`);
    const error = new Error(message);
    error.status = response.status;
    error.code = body?.code || body?.error?.code || "HTTP_ERROR";
    error.recoverable = Boolean(body?.recoverable ?? body?.error?.recoverable);
    error.details = body?.details || body?.error?.details || {};
    error.requestId = body?.request_id || response.headers.get("X-Request-ID") || "";
    throw error;
  }
  return body;
}

export function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
}

export function countWritingUnits(text) {
  const withoutHeadings = text.replace(/^\s{0,3}#{1,6}\s+.*$/gm, "");
  const cjk = withoutHeadings.match(/[\u3400-\u4dbf\u4e00-\u9fff]/g) || [];
  const words = withoutHeadings
    .replace(/[\u3400-\u4dbf\u4e00-\u9fff]/g, " ")
    .match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g) || [];
  return cjk.length + words.length;
}

export function showToast(message, error = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2600);
}

export function setSaveState(message, dirty = false) {
  $("#save-state").textContent = message;
  $("#save-document").disabled = !dirty || state.saving;
}
