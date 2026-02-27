/**
 * OpenWrite — 前端工具库
 * 封装 API 调用、Toast 提示、模态框、SSE、Markdown 渲染
 */

// ── API 封装 ──────────────────────────────────────────────────────
const api = {
  async _fetch(url, options = {}) {
    const defaults = {
      headers: { 'Content-Type': 'application/json' },
    };
    const opts = { ...defaults, ...options };
    if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
      opts.body = JSON.stringify(opts.body);
    }
    try {
      const resp = await fetch(url, opts);
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.error || data.detail || `HTTP ${resp.status}`);
      }
      return data;
    } catch (e) {
      toast(e.message || '请求失败', 'error');
      throw e;
    }
  },
  get(url) { return this._fetch(url); },
  post(url, body) { return this._fetch(url, { method: 'POST', body }); },
  put(url, body) { return this._fetch(url, { method: 'PUT', body }); },
  del(url) { return this._fetch(url, { method: 'DELETE' }); },
};

// ── Toast 提示 ─────────────────────────────────────────────────────
function toast(message, type = 'success', duration = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ── 模态框 ──────────────────────────────────────────────────────────
function modal(title, contentHtml, onConfirm) {
  const overlay = document.getElementById('modal-overlay');
  if (!overlay) return;
  overlay.innerHTML = `
    <div class="modal-box">
      <div class="modal-header">
        <h3>${title}</h3>
        <button class="modal-close" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">${contentHtml}</div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="closeModal()">取消</button>
        <button class="btn btn-primary" id="modal-confirm">确认</button>
      </div>
    </div>
  `;
  overlay.classList.add('active');
  if (onConfirm) {
    document.getElementById('modal-confirm').addEventListener('click', () => {
      onConfirm();
      closeModal();
    });
  }
}

function closeModal() {
  const overlay = document.getElementById('modal-overlay');
  if (overlay) {
    overlay.classList.remove('active');
    overlay.innerHTML = '';
  }
}

// ── SSE 封装 ────────────────────────────────────────────────────────
function connectSSE(url, onMessage, onDone) {
  const source = new EventSource(url);
  source.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
      if (data.stage === 'completed' || data.stage === 'error') {
        source.close();
        if (onDone) onDone(data);
      }
    } catch (e) {
      console.error('SSE parse error:', e);
    }
  };
  source.onerror = () => {
    source.close();
    if (onDone) onDone({ stage: 'error', error: '连接中断' });
  };
  return source;
}

// ── Markdown 渲染 ───────────────────────────────────────────────────
function renderMarkdown(text) {
  if (typeof marked !== 'undefined') {
    return marked.parse(text);
  }
  // Fallback: 简单转义 + 换行
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\n/g, '<br>');
}

// ── 通用表单收集 ────────────────────────────────────────────────────
function collectFormData(formId) {
  const form = document.getElementById(formId);
  if (!form) return {};
  const data = {};
  form.querySelectorAll('input, select, textarea').forEach(el => {
    if (el.name) {
      if (el.type === 'checkbox') {
        data[el.name] = el.checked;
      } else if (el.type === 'number') {
        data[el.name] = parseInt(el.value, 10) || 0;
      } else {
        data[el.name] = el.value;
      }
    }
  });
  return data;
}

// ── 管线进度条 ───────────────────────────────────────────────────────
const STAGE_LABELS = {
  queued: '排队中',
  initializing: '初始化',
  director: 'Director 组装上下文',
  writer: 'Writer 生成草稿',
  reviewer: 'Reviewer 审查',
  user_review: '用户确认',
  stylist: 'Stylist 润色',
  director_planning: 'Director 规划',
  librarian_writing: 'Librarian 写作',
  lore_checking: 'LoreChecker 审查',
  stylist_polishing: 'Stylist 润色',
  style_analysis: '风格分析',
  completed: '完成',
  failed: '出错',
  error: '出错',
};

function updateProgressBar(containerId, data) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const pct = Math.max(0, Math.min(100, data.progress || 0));
  const label = STAGE_LABELS[data.stage] || data.stage;
  container.innerHTML = `
    <div class="pipeline-progress">
      <div class="pipeline-bar" style="width:${pct}%"></div>
    </div>
    <div class="pipeline-label">${label} (${pct}%)</div>
  `;
  if (data.stage === 'error') {
    container.innerHTML += `<div class="pipeline-error">${data.error || '未知错误'}</div>`;
  }
}
