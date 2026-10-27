import { $, api, formatNumber, showToast, state } from "/js/core.js";
import { enqueueTask } from "/js/tasks.js";
import { getPrimaryMarkdownEditor } from "/js/markdown-editor.js";
import { mapEditorRange } from "/js/selection-coordinates.js";

let refreshWorkspace = async () => {};
let reopenDocument = async () => {};
let pendingAnnotation = null;
let pendingRevisionSelection = null;

export function bindRevisionUI(callbacks = {}) {
  refreshWorkspace = callbacks.refreshWorkspace || refreshWorkspace;
  reopenDocument = callbacks.reopenDocument || reopenDocument;
  $("#revision-selection").addEventListener("click", () => openRevisionRequest(false));
  $("#revision-full-chapter").addEventListener("click", () => openRevisionRequest(true));
  $("#revision-history").addEventListener("click", openRevisionHistory);
  $("#revision-request-close").addEventListener("click", closeRevisionRequest);
  $("#revision-request-cancel").addEventListener("click", closeRevisionRequest);
  $("#revision-request-form").addEventListener("submit", submitRevisionRequest);
  $("#revision-preview-close").addEventListener("click", closeRevisionPreview);
  $("#revision-apply").addEventListener("click", applyCurrentRevision);
  $("#revision-hunks-all").addEventListener("click", () => selectAllRevisionHunks(true));
  $("#revision-hunks-none").addEventListener("click", () => selectAllRevisionHunks(false));
  $("#revision-reject").addEventListener("click", rejectCurrentRevision);
  $("#revision-regenerate").addEventListener("click", regenerateCurrentRevision);
  $("#revision-history-close").addEventListener("click", () => $("#revision-history-dialog").close());
  $("#manuscript-checkpoint").addEventListener("click", createManuscriptCheckpoint);
  $("#manuscript-annotate").addEventListener("click", createManuscriptAnnotation);
  $("#manuscript-annotation-close").addEventListener("click", closeManuscriptAnnotation);
  $("#manuscript-annotation-cancel").addEventListener("click", closeManuscriptAnnotation);
  $("#manuscript-annotation-form").addEventListener("submit", submitManuscriptAnnotation);
}

export function syncRevisionControls() {
  const chapter = state.document && state.document.path.startsWith("data/manuscript/");
  const configured = Boolean(state.workspace?.model?.configured);
  const selection = getPrimaryMarkdownEditor().selection();
  const hasSelection = chapter && selection.end > selection.start;
  $("#revision-selection").hidden = !chapter;
  $("#revision-selection").disabled = !configured || !hasSelection || state.dirty;
  $("#revision-full-chapter").hidden = !chapter;
  $("#revision-full-chapter").disabled = !configured || state.dirty;
  $("#revision-history").hidden = !chapter;
  $("#revision-history").disabled = !chapter || state.dirty;
}

export function appendReviewIssueActions(container, issue, reviewResult) {
  const actions = document.createElement("div");
  actions.className = "review-issue-actions";
  const locate = document.createElement("button");
  locate.type = "button";
  locate.className = "quiet-button";
  locate.textContent = "定位原文";
  locate.disabled = !issueAnchor(issue);
  locate.addEventListener("click", () => locateIssue(issue));
  const revise = document.createElement("button");
  revise.type = "button";
  revise.className = "quiet-button";
  revise.textContent = "生成修订提案";
  revise.disabled = !issue.auto_fixable || !issueAnchor(issue) || !state.workspace?.model?.configured;
  revise.addEventListener("click", () => createReviewRevision(issue, reviewResult));
  actions.append(locate, revise);
  container.append(actions);
}

function openRevisionRequest(fullChapter) {
  if (!state.document || state.dirty) {
    showToast(state.dirty ? "请先保存当前章节" : "请先打开章节", true);
    return;
  }
  const editor = getPrimaryMarkdownEditor();
  const value = editor.getValue();
  const selection = editor.selection();
  const start = fullChapter ? 0 : selection.start;
  const end = fullChapter ? value.length : selection.end;
  if (end <= start) {
    showToast("请先选择需要修改的文字", true);
    return;
  }
  const mapped = mapEditorRange(state.document.content, value, start, end);
  if (!mapped) { showToast("选区与当前原文不一致，请保存或重新读取后选择", true); return; }
  pendingRevisionSelection = { ...mapped, revision: state.document.revision };
  $("#revision-full-mode").value = fullChapter ? "1" : "0";
  $("#revision-selection-start").value = String(mapped.start);
  $("#revision-selection-end").value = String(mapped.end);
  $("#revision-original-text").value = mapped.text;
  $("#revision-request-title").textContent = fullChapter ? "整章修订" : "修订所选文字";
  $("#revision-selection-preview").textContent = value.slice(start, end);
  $("#revision-request-status").textContent = fullChapter
    ? "整章修订可能影响后续连续性，应用前请逐段检查差异。"
    : "提案不会直接覆盖正文，生成后需要再次确认。";
  $("#revision-request-dialog").showModal();
}

function closeRevisionRequest() {
  pendingRevisionSelection = null;
  $("#revision-request-dialog").close();
}

async function submitRevisionRequest(event) {
  event.preventDefault();
  const button = $("#revision-request-submit");
  button.disabled = true;
  $("#revision-request-status").textContent = "正在生成修订提案…";
  try {
    const selection = pendingRevisionSelection;
    if (!selection || selection.revision !== state.document?.revision) throw new Error("原文已变化，请重新选择修订范围");
    await enqueueTask(
      "revision_selection",
      {
        chapter_id: chapterId(),
        start: selection.start,
        end: selection.end,
        original_text: selection.text,
        expected_document_revision: selection.revision,
        action: $("#revision-action").value,
        instruction: $("#revision-instruction").value,
        target_units: Number($("#revision-target-units").value || 0),
        full_chapter: $("#revision-full-mode").value === "1",
      },
      {
        label: "修订提案任务已加入队列",
        onComplete: (task) => showRevisionPreview(task.result),
      },
    );
    closeRevisionRequest();
  } catch (error) {
    $("#revision-request-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function createReviewRevision(issue, reviewResult) {
  const chapter = reviewResult.chapter_id || chapterId();
  try {
    await enqueueTask(
      "revision_from_review",
      { chapter_id: chapter, issue_ids: [issue.id] },
      {
        label: "审稿修订任务已加入队列",
        onComplete: (task) => showRevisionPreview(task.result),
      },
    );
    $("#review-dialog").close();
  } catch (error) {
    showToast(error.message, true);
  }
}

export function showRevisionPreview(proposal) {
  if ($("#task-center-dialog")?.open) $("#task-center-dialog").close();
  state.revisionProposal = proposal;
  $("#revision-preview-title").textContent = revisionKindLabel(proposal.kind);
  $("#revision-preview-status").textContent = statusLabel(proposal.status);
  $("#revision-before").textContent = proposal.selection?.original_text || "";
  state.revisionHunkSelection = new Set((proposal.diff?.hunks || []).map((hunk) => hunk.id));
  renderRevisionHunks(proposal);
  $("#revision-rationale").textContent = proposal.rationale || "未提供修改说明";
  const risks = proposal.risk_flags || [];
  $("#revision-risks").textContent = risks.length ? `风险提示：${risks.join("；")}` : "未标记额外风险";
  const stats = proposal.diff?.stats || {};
  $("#revision-stats").textContent = `${formatNumber(stats.removed_units)} → ${formatNumber(stats.added_units)} 字符`;
  $("#revision-unified-diff").textContent = proposal.diff?.unified || "没有文本差异";
  const proposed = proposal.status === "proposed";
  $("#revision-apply").disabled = !proposed || !state.revisionHunkSelection.size;
  $("#revision-reject").disabled = !["proposed", "stale"].includes(proposal.status);
  $("#revision-regenerate").disabled = proposal.status === "applied";
  $("#revision-preview-dialog").showModal();
}

function renderRevisionHunks(proposal) {
  const root = $("#revision-hunks-list");
  const hunks = proposal.diff?.hunks || [];
  root.replaceChildren();
  $("#revision-hunks-section").hidden = !hunks.length;
  if (!hunks.length) {
    $("#revision-after").textContent = proposal.replacement_text || "";
    return;
  }
  hunks.forEach((hunk, index) => {
    const label = document.createElement("label");
    label.className = "revision-hunk";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.revisionHunkSelection.has(hunk.id);
    checkbox.disabled = proposal.status !== "proposed";
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.revisionHunkSelection.add(hunk.id);
      else state.revisionHunkSelection.delete(hunk.id);
      syncRevisionHunkPreview();
    });
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `修改 ${index + 1} · ${hunkKindLabel(hunk.tag)}`;
    const before = document.createElement("pre");
    before.className = "removed";
    before.textContent = hunk.before || "（新增内容）";
    const after = document.createElement("pre");
    after.className = "added";
    after.textContent = hunk.after || "（删除内容）";
    copy.append(title, before, after);
    label.append(checkbox, copy);
    root.append(label);
  });
  syncRevisionHunkPreview();
}

function hunkKindLabel(tag) {
  return { replace: "替换", insert: "新增", delete: "删除" }[tag] || "修改";
}

function selectedRevisionReplacement() {
  const segments = state.revisionProposal?.diff?.segments || [];
  return segments.map((segment) => {
    if (segment.tag === "equal") return segment.after;
    return state.revisionHunkSelection.has(segment.id) ? segment.after : segment.before;
  }).join("");
}

function syncRevisionHunkPreview() {
  const proposal = state.revisionProposal;
  if (!proposal) return;
  const total = proposal.diff?.hunks?.length || 0;
  const selected = state.revisionHunkSelection.size;
  $("#revision-after").textContent = total ? selectedRevisionReplacement() : (proposal.replacement_text || "");
  $("#revision-hunks-status").textContent = `已选 ${selected} / ${total}`;
  $("#revision-apply").disabled = proposal.status !== "proposed" || selected === 0;
}

function selectAllRevisionHunks(selected) {
  const proposal = state.revisionProposal;
  if (!proposal || proposal.status !== "proposed") return;
  state.revisionHunkSelection = new Set(
    selected ? (proposal.diff?.hunks || []).map((hunk) => hunk.id) : [],
  );
  renderRevisionHunks(proposal);
}

function closeRevisionPreview() {
  $("#revision-preview-dialog").close();
}

async function applyCurrentRevision() {
  const proposal = state.revisionProposal;
  if (!proposal) return;
  const button = $("#revision-apply");
  button.disabled = true;
  $("#revision-preview-status").textContent = "正在校验并应用…";
  try {
    const payload = await api(`/api/revisions/${encodeURIComponent(proposal.proposal_id)}/apply`, {
      method: "POST",
      body: JSON.stringify({
        replacement_text: selectedRevisionReplacement(),
        selected_hunk_ids: Array.from(state.revisionHunkSelection),
      }),
    });
    state.revisionProposal = payload.data.proposal;
    state.dirty = false;
    closeRevisionPreview();
    await refreshWorkspace();
    await reopenDocument(payload.data.proposal.document.path);
    showToast("修订已应用，原审稿结果已标记待刷新");
  } catch (error) {
    $("#revision-preview-status").textContent = error.code === "DOCUMENT_CONFLICT"
      ? "原文已变化，请重新生成提案"
      : error.message;
    showToast(error.message, true);
    if (error.code === "DOCUMENT_CONFLICT") button.disabled = true;
  }
}

async function rejectCurrentRevision() {
  const proposal = state.revisionProposal;
  if (!proposal) return;
  try {
    const payload = await api(`/api/revisions/${encodeURIComponent(proposal.proposal_id)}/reject`, {
      method: "POST",
      body: "{}",
    });
    closeRevisionPreview();
    showToast(payload.data.status === "rejected" ? "修订提案已放弃" : "提案状态已更新");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function regenerateCurrentRevision() {
  const proposal = state.revisionProposal;
  if (!proposal) return;
  $("#revision-preview-status").textContent = "正在重新生成…";
  try {
    const payload = await api(`/api/revisions/${encodeURIComponent(proposal.proposal_id)}/regenerate`, {
      method: "POST",
      body: "{}",
    });
    closeRevisionPreview();
    showRevisionPreview(payload.data);
  } catch (error) {
    $("#revision-preview-status").textContent = error.message;
    showToast(error.message, true);
  }
}

async function openRevisionHistory() {
  if (!state.document) return;
  if (state.dirty) {
    showToast("请先保存当前章节", true);
    return;
  }
  const dialog = $("#revision-history-dialog");
  if (!dialog.open) dialog.showModal();
  await reloadRevisionHistory();
}

async function reloadRevisionHistory() {
  const root = $("#revision-history-list");
  root.textContent = "正在读取提案…";
  try {
    const [payload, versions, annotations] = await Promise.all([
      api(`/api/revisions?chapter=${encodeURIComponent(chapterId())}`),
      manuscriptEditing({action: "versions"}),
      manuscriptEditing({action: "annotations"}),
    ]);
    renderRevisionHistory(payload.data.proposals || []);
    renderManuscriptVersions(versions.versions || []);
    renderManuscriptAnnotations(annotations.annotations || []);
  } catch (error) {
    root.textContent = error.message;
  }
}

async function manuscriptEditing(payload) {
  return api("/api/manuscript-editing", {
    method: "POST",
    body: JSON.stringify({...payload, chapter_id: chapterId()}),
  });
}

async function createManuscriptCheckpoint() {
  try {
    await manuscriptEditing({action: "checkpoint", label: "手动 checkpoint"});
    showToast("正文 checkpoint 已创建");
    await reloadRevisionHistory();
  } catch (error) { showToast(error.message, true); }
}

function createManuscriptAnnotation() {
  if (state.dirty) { showToast("请先保存当前章节", true); return; }
  const editor = getPrimaryMarkdownEditor();
  const value = editor.getValue();
  const selection = editor.selection();
  const start = selection.start;
  const end = selection.end;
  const mapped = mapEditorRange(state.document?.content || "", value, start, end);
  if (!mapped) { showToast("请重新读取原文并选择要批注的文字", true); return; }
  const quote = mapped.text;
  pendingAnnotation = {
    revision: state.document.revision,
    quote,
    start_hint: mapped.start,
    end_hint: mapped.end,
  };
  $("#revision-history-dialog").close();
  $("#manuscript-annotation-quote").textContent = quote;
  $("#manuscript-annotation-note").value = "";
  $("#manuscript-annotation-status").textContent = "批注会绑定当前正文版本与选区。";
  $("#manuscript-annotation-dialog").showModal();
  $("#manuscript-annotation-note").focus();
}

function closeManuscriptAnnotation() {
  $("#manuscript-annotation-dialog").close();
  pendingAnnotation = null;
  openRevisionHistory();
}

async function submitManuscriptAnnotation(event) {
  event.preventDefault();
  if (!pendingAnnotation) return;
  const note = $("#manuscript-annotation-note").value.trim();
  if (!note) return;
  const button = $("#manuscript-annotation-submit");
  button.disabled = true;
  try {
    await manuscriptEditing({
      action: "annotate", ...pendingAnnotation, note,
    });
    showToast("批注已保存");
    $("#manuscript-annotation-dialog").close();
    pendingAnnotation = null;
    await openRevisionHistory();
  } catch (error) {
    $("#manuscript-annotation-status").textContent = error.message;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function renderManuscriptVersions(versions) {
  const root = $("#manuscript-version-list");
  root.replaceChildren();
  if (!versions.length) { root.textContent = "本章还没有 checkpoint。"; return; }
  versions.forEach((version) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "revision-history-item";
    const title = document.createElement("strong");
    title.textContent = version.label || version.reason;
    const meta = document.createElement("span");
    meta.textContent = `${new Date(version.created_at).toLocaleString("zh-CN")} · ${version.writing_units} 字`;
    button.append(title, meta);
    button.addEventListener("click", async () => {
      if (!window.confirm("恢复这个版本？当前正文会先自动创建 checkpoint。")) return;
      try {
        await manuscriptEditing({action: "restore", version_id: version.version_id, revision: state.document.revision, confirm: true});
        $("#revision-history-dialog").close();
        await reopenDocument(state.document.path);
        showToast("正文版本已恢复");
      } catch (error) { showToast(error.message, true); }
    });
    root.append(button);
  });
}

function renderManuscriptAnnotations(annotations) {
  const root = $("#manuscript-annotation-list");
  root.replaceChildren();
  if (!annotations.length) { root.textContent = "本章还没有批注。"; return; }
  annotations.forEach((annotation) => {
    const item = document.createElement("article");
    item.className = "annotation-history-item";
    const title = document.createElement("strong");
    title.textContent = annotation.anchor_state === "detached" ? "已脱离原文" : annotation.quote;
    const note = document.createElement("span");
    note.textContent = annotation.note;
    const meta = document.createElement("small");
    meta.textContent = `${annotation.anchor_state} · ${annotation.status}`;
    const actions = document.createElement("div");
    actions.className = "annotation-history-actions";
    const locate = document.createElement("button");
    locate.type = "button";
    locate.className = "quiet-button";
    locate.textContent = "定位";
    locate.disabled = annotation.anchor_state === "detached";
    locate.addEventListener("click", async () => {
      $("#revision-history-dialog").close();
      await getPrimaryMarkdownEditor().selectRange(annotation.current_start, annotation.current_end);
    });
    actions.append(locate);
    if (annotation.status === "open") {
      const resolve = document.createElement("button");
      resolve.type = "button";
      resolve.className = "quiet-button";
      resolve.textContent = "标记完成";
      resolve.addEventListener("click", async () => {
        try {
          await manuscriptEditing({
            action: "resolve_annotation", annotation_id: annotation.annotation_id,
          });
          await reloadRevisionHistory();
        } catch (error) { showToast(error.message, true); }
      });
      actions.append(resolve);
    }
    item.append(title, note, meta, actions);
    root.append(item);
  });
}

function renderRevisionHistory(proposals) {
  const root = $("#revision-history-list");
  root.replaceChildren();
  if (!proposals.length) {
    root.textContent = "本章还没有修订提案。";
    return;
  }
  proposals.forEach((proposal) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "revision-history-item";
    const title = document.createElement("strong");
    title.textContent = revisionKindLabel(proposal.kind);
    const meta = document.createElement("span");
    meta.textContent = `${statusLabel(proposal.status)} · ${new Date(proposal.created_at).toLocaleString("zh-CN")}`;
    button.append(title, meta);
    button.addEventListener("click", () => {
      $("#revision-history-dialog").close();
      showRevisionPreview(proposal);
    });
    root.append(button);
  });
}

function locateIssue(issue) {
  const anchor = issueAnchor(issue);
  if (!anchor) {
    showToast("该问题没有可定位的正文证据", true);
    return;
  }
  const [start, end] = anchor;
  $("#review-dialog").close();
  getPrimaryMarkdownEditor().selectRange(start, end);
  syncRevisionControls();
}

function issueAnchor(issue) {
  if (!state.document) return null;
  const content = getPrimaryMarkdownEditor().getValue();
  const quote = issue.evidence?.quote || "";
  const start = Number(issue.anchor?.start_hint);
  const end = Number(issue.anchor?.end_hint);
  if (Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start) {
    const jsStart = utf16Offset(content, start);
    const jsEnd = utf16Offset(content, end);
    if (!quote || content.slice(jsStart, jsEnd) === quote) return [jsStart, jsEnd];
  }
  if (quote) {
    const found = content.indexOf(quote);
    if (found >= 0 && content.indexOf(quote, found + 1) < 0) return [found, found + quote.length];
  }
  return null;
}

function codePointOffset(text, utf16Index) {
  return Array.from(text.slice(0, utf16Index)).length;
}

function utf16Offset(text, codePointIndex) {
  return Array.from(text).slice(0, codePointIndex).join("").length;
}

function chapterId() {
  return state.document?.path.match(/\/(ch_\d+)\.md$/)?.[1] || "";
}

function revisionKindLabel(kind) {
  return {
    selection_rewrite: "局部修订提案",
    review_fix: "审稿问题修订",
    full_chapter_revision: "整章修订提案",
  }[kind] || "修订提案";
}

function statusLabel(status) {
  return { proposed: "待确认", applied: "已应用", rejected: "已放弃", stale: "已失效" }[status] || status;
}
