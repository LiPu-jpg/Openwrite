const VDITOR_CDN = `${location.origin}/vendor/vditor`;

const editors = new Set();
const editorsByHost = new WeakMap();
let primaryEditor = null;
let activeTheme = document.documentElement.dataset.theme || "light";

const fullToolbar = [
  "undo", "redo", "|", "headings", "bold", "italic", "strike", "|",
  "list", "ordered-list", "check", "quote", "link", "inline-code", "code",
  "table", "|", "edit-mode",
];

const compactToolbar = [
  "undo", "redo", "|", "bold", "italic", "|", "list", "ordered-list",
  "quote", "link",
];

function editorSurface(host) {
  return host.querySelector(
    ".vditor-ir [contenteditable], .vditor-wysiwyg [contenteditable], .vditor-sv[contenteditable]",
  );
}

function textNodesWithin(root) {
  if (!root) return [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  return nodes;
}

function nodePosition(nodes, target) {
  let offset = Math.max(0, target);
  for (const node of nodes) {
    const length = node.textContent?.length || 0;
    if (offset <= length) return [node, offset];
    offset -= length;
  }
  const last = nodes[nodes.length - 1];
  return last ? [last, last.textContent?.length || 0] : [null, 0];
}

function allOccurrences(text, query) {
  const positions = [];
  if (!query) return positions;
  let offset = 0;
  while (offset <= text.length) {
    const found = text.indexOf(query, offset);
    if (found < 0) break;
    positions.push(found);
    offset = found + Math.max(1, query.length);
  }
  return positions;
}

export class MarkdownEditor {
  constructor(host, options = {}) {
    if (!host) throw new Error("Markdown 编辑器挂载点不存在");
    this.host = host;
    this.options = options;
    this.value = String(options.value || "");
    const initialSource = this.value;
    let inputObserved = false;
    const observeInput = () => { inputObserved = true; };
    host.addEventListener("input", observeInput, {once: true});
    this.cancelSerializationCapture = () => host.removeEventListener("input", observeInput);
    this.serialization = undefined;
    this.lastSelection = { start: 0, end: 0, text: "" };
    this.suppressInput = false;
    this.pendingInput = false;
    this.notifiedValue = this.value;
    this.observePendingInput = () => { if (!this.suppressInput) this.pendingInput = true; };
    host.addEventListener("input", this.observePendingInput, true);
    this.onBackground = () => { if (document.visibilityState === "hidden") this.flush(); };
    this.onPageHide = () => this.flush();
    host.addEventListener("focusout", this.onPageHide);
    document.addEventListener("visibilitychange", this.onBackground);
    window.addEventListener("pagehide", this.onPageHide);
    this.destroyed = false;
    this.enhanced = Boolean(window.Vditor);
    this.fallback = null;
    this.ready = new Promise((resolve) => { this.resolveReady = resolve; });
    host.classList.add("markdown-editor-host");
    if (options.compact) host.classList.add("compact");
    editors.add(this);
    editorsByHost.set(host, this);
    if (!this.enhanced) {
      this.mountFallback();
      this.cancelSerializationCapture();
      this.resolveReady(this);
      options.onReady?.(this);
      return;
    }
    this.instance = new window.Vditor(host, {
      value: this.value,
      cdn: VDITOR_CDN,
      lang: "zh_CN",
      icon: "",
      mode: "ir",
      theme: activeTheme === "dark" ? "dark" : "classic",
      cache: { enable: false },
      height: "auto",
      minHeight: options.minHeight || (options.compact ? 180 : 520),
      placeholder: options.placeholder || "开始写作…",
      tab: "    ",
      typewriterMode: !options.compact,
      toolbar: options.toolbar || (options.compact ? compactToolbar : fullToolbar),
      toolbarConfig: { pin: !options.compact },
      counter: { enable: false },
      resize: { enable: false },
      outline: { enable: false },
      preview: {
        actions: [],
        hljs: { enable: false, lineNumber: false, style: "github" },
        markdown: { codeBlockPreview: false, mathBlockPreview: false },
        theme: {
          current: activeTheme === "dark" ? "dark" : "light",
          path: `${VDITOR_CDN}/dist/css/content-theme`,
        },
      },
      input: (value) => {
        this.value = value;
        if (!this.suppressInput) {
          this.pendingInput = false;
          this.notifiedValue = value;
          this.options.onInput?.(value, this);
        }
      },
      select: () => this.syncSelection(),
      unSelect: () => this.syncSelection(),
      keydown: (event) => {
        this.options.onKeydown?.(event, this);
        queueMicrotask(() => this.syncSelection());
      },
      blur: () => this.syncSelection(),
      after: () => {
        this.cancelSerializationCapture();
        if (this.destroyed) return;
        this.serialization = inputObserved ? undefined : {source: initialSource, value: this.instance.getValue()};
        this.value = this.instance.getValue();
        const surface = editorSurface(this.host);
        surface?.addEventListener("mouseup", () => this.syncSelection());
        surface?.addEventListener("keyup", () => this.syncSelection());
        this.resolveReady(this);
        this.options.onReady?.(this);
      },
    });
  }

  mountFallback() {
    const textarea = document.createElement("textarea");
    textarea.className = "markdown-editor-fallback";
    textarea.value = this.value;
    textarea.placeholder = this.options.placeholder || "开始写作…";
    textarea.spellcheck = true;
    textarea.setAttribute("aria-label", this.host.getAttribute("aria-label") || "Markdown 编辑器");
    textarea.addEventListener("input", () => {
      this.value = textarea.value;
      if (!this.suppressInput) {
        this.pendingInput = false;
        this.notifiedValue = this.value;
        this.options.onInput?.(this.value, this);
      }
      this.syncSelection();
    });
    textarea.addEventListener("select", () => this.syncSelection());
    textarea.addEventListener("click", () => this.syncSelection());
    textarea.addEventListener("keyup", () => this.syncSelection());
    textarea.addEventListener("keydown", (event) => this.options.onKeydown?.(event, this));
    this.host.replaceChildren(textarea);
    this.host.classList.add("fallback");
    this.fallback = textarea;
  }

  getValue() {
    if (this.destroyed) return this.value;
    if (this.fallback) {
      this.value = this.fallback.value;
      return this.value;
    }
    try {
      this.value = this.instance.getValue();
    } catch (error) {
      // Vditor initializes asynchronously; the last known value remains authoritative.
    }
    return this.value;
  }

  getSerialization() { return this.serialization; }

  flush() {
    if (this.destroyed || this.suppressInput || !this.pendingInput) return;
    const value = this.getValue();
    this.pendingInput = false;
    if (value === this.notifiedValue) return;
    this.notifiedValue = value;
    this.options.onInput?.(value, this);
  }

  async setValue(value, clearHistory = true) {
    const source = String(value || "");
    this.pendingInput = false;
    this.notifiedValue = source;
    this.value = source;
    await this.ready;
    if (this.destroyed) return;
    if (this.fallback) {
      this.suppressInput = true;
      this.fallback.value = this.value;
      this.suppressInput = false;
      this.lastSelection = { start: 0, end: 0, text: "" };
      return;
    }
    this.suppressInput = true;
    this.instance.setValue(this.value, clearHistory);
    this.serialization = {source, value: this.instance.getValue()};
    this.suppressInput = false;
    this.lastSelection = { start: 0, end: 0, text: "" };
  }

  async focus() {
    await this.ready;
    if (this.destroyed) return;
    if (this.fallback) this.fallback.focus();
    else this.instance.focus();
  }

  async setDisabled(disabled) {
    await this.ready;
    if (this.destroyed) return;
    if (this.fallback) {
      this.fallback.disabled = disabled;
      return;
    }
    if (disabled) this.instance.disabled();
    else this.instance.enable();
  }

  selection() {
    this.syncSelection(false);
    return { ...this.lastSelection };
  }

  syncSelection(notify = true) {
    if (this.destroyed) return this.lastSelection;
    const value = this.getValue();
    if (this.fallback) {
      const start = this.fallback.selectionStart || 0;
      const end = this.fallback.selectionEnd || start;
      this.lastSelection = { start, end, text: value.slice(start, end) };
      if (notify) this.options.onSelection?.({ ...this.lastSelection }, this);
      return this.lastSelection;
    }
    const selectedText = this.instance.getSelection?.() || "";
    if (selectedText) {
      const positions = allOccurrences(value, selectedText);
      if (positions.length) {
        const previous = this.lastSelection.start || this.domCaretOffset();
        const start = positions.reduce((nearest, item) => (
          Math.abs(item - previous) < Math.abs(nearest - previous) ? item : nearest
        ), positions[0]);
        this.lastSelection = { start, end: start + selectedText.length, text: selectedText };
      }
    } else {
      const cursor = this.domCaretOffset();
      this.lastSelection = { start: cursor, end: cursor, text: "" };
    }
    if (notify) this.options.onSelection?.({ ...this.lastSelection }, this);
    return this.lastSelection;
  }

  domCaretOffset() {
    if (this.fallback) return this.fallback.selectionEnd || 0;
    const surface = editorSurface(this.host);
    const selection = window.getSelection();
    if (!surface || !selection?.rangeCount) return this.lastSelection.end || 0;
    const range = selection.getRangeAt(0);
    if (!surface.contains(range.startContainer)) return this.lastSelection.end || 0;
    const block = range.startContainer.nodeType === Node.ELEMENT_NODE
      ? range.startContainer.closest?.("[data-block]")
      : range.startContainer.parentElement?.closest("[data-block]");
    if (!block) return this.lastSelection.end || 0;
    const blockRange = document.createRange();
    blockRange.selectNodeContents(block);
    blockRange.setEnd(range.startContainer, range.startOffset);
    const prefix = blockRange.toString();
    const blockText = block.textContent || "";
    const value = this.getValue();
    const candidates = allOccurrences(value, blockText);
    if (!candidates.length) return this.lastSelection.end || 0;
    const previous = this.lastSelection.end || 0;
    const blockStart = candidates.reduce((nearest, item) => (
      Math.abs(item - previous) < Math.abs(nearest - previous) ? item : nearest
    ), candidates[0]);
    return Math.min(value.length, blockStart + prefix.length);
  }

  async selectRange(start, end) {
    await this.ready;
    const value = this.getValue();
    const safeStart = Math.max(0, Math.min(value.length, Number(start) || 0));
    const safeEnd = Math.max(safeStart, Math.min(value.length, Number(end) || 0));
    const target = value.slice(safeStart, safeEnd);
    if (this.fallback) {
      await this.focus();
      this.fallback.setSelectionRange(safeStart, safeEnd);
      this.lastSelection = { start: safeStart, end: safeEnd, text: target };
      this.options.onSelection?.({ ...this.lastSelection }, this);
      return true;
    }
    const surface = editorSurface(this.host);
    if (!surface) return false;
    await this.focus();
    const nodes = textNodesWithin(surface);
    const rendered = nodes.map((node) => node.textContent || "").join("");
    let renderedStart = target ? rendered.indexOf(target) : safeStart;
    if (target && renderedStart < 0) {
      const visibleTarget = target.replace(/^\s{0,3}#{1,6}\s+/, "").replace(/^>\s?/gm, "");
      renderedStart = rendered.indexOf(visibleTarget);
    }
    if (renderedStart < 0) return false;
    const renderedEnd = renderedStart + (target ? target.replace(/^\s{0,3}#{1,6}\s+/, "").replace(/^>\s?/gm, "").length : 0);
    const [startNode, startOffset] = nodePosition(nodes, renderedStart);
    const [endNode, endOffset] = nodePosition(nodes, renderedEnd);
    if (!startNode || !endNode) return false;
    const range = document.createRange();
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    this.lastSelection = { start: safeStart, end: safeEnd, text: target };
    startNode.parentElement?.scrollIntoView({ block: "center", behavior: "smooth" });
    this.options.onSelection?.({ ...this.lastSelection }, this);
    return true;
  }

  setTheme(theme) {
    if (this.destroyed || this.fallback) return;
    this.instance.setTheme(theme === "dark" ? "dark" : "classic");
  }

  destroy() {
    if (this.destroyed) return;
    if (this.options.flushOnLeave) this.flush();
    this.host.removeEventListener("input", this.observePendingInput, true);
    this.host.removeEventListener("focusout", this.onPageHide);
    document.removeEventListener("visibilitychange", this.onBackground);
    window.removeEventListener("pagehide", this.onPageHide);
    this.cancelSerializationCapture();
    this.destroyed = true;
    editors.delete(this);
    editorsByHost.delete(this.host);
    if (this.fallback) {
      this.fallback.remove();
      this.fallback = null;
      this.host.classList.remove("fallback");
    } else {
      this.instance.destroy?.();
    }
  }
}

export async function initializePrimaryMarkdownEditor(options = {}) {
  if (!primaryEditor) {
    primaryEditor = new MarkdownEditor(document.querySelector("#document-editor"), options);
  }
  await primaryEditor.ready;
  return primaryEditor;
}

export function getPrimaryMarkdownEditor() {
  if (!primaryEditor) throw new Error("主 Markdown 编辑器尚未初始化");
  return primaryEditor;
}

export function mountMarkdownEditor(host, options = {}) {
  const existing = editorsByHost.get(host);
  if (existing) existing.destroy();
  return new MarkdownEditor(host, options);
}

export function markdownEditorFor(host) {
  return editorsByHost.get(host) || null;
}

export function destroyMarkdownEditorsWithin(root) {
  if (!root) return;
  Array.from(editors).forEach((editor) => {
    if (editor !== primaryEditor && (editor.host === root || root.contains(editor.host))) {
      editor.destroy();
    }
  });
}

export function setMarkdownEditorTheme(theme) {
  activeTheme = theme === "dark" ? "dark" : "light";
  editors.forEach((editor) => editor.setTheme(activeTheme));
}
