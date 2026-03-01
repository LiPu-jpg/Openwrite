"""叙事线 HTML 可视化渲染器 — 生成自包含的交互式 HTML 文件。

使用 D3.js 渲染叙事线为平行泳道图：
- 每条叙事线一行泳道
- 事件节点按章节排列
- 连接线表达汇合/分离/跳转/伏笔/引用
- 支持 hover 提示、点击聚焦、张力热力图
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from tools.models.narrative import NarrativeTimeline


def render_html(
    timeline: NarrativeTimeline,
    output_path: Optional[Path] = None,
) -> str:
    """将 NarrativeTimeline 渲染为自包含 HTML 字符串。

    Args:
        timeline: 叙事时间线数据。
        output_path: 可选输出路径，传入则同时写入文件。

    Returns:
        完整 HTML 字符串。
    """
    # 序列化数据给 JS 使用
    data_json = json.dumps(
        timeline.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )

    html = _build_html(data_json, timeline.title or timeline.novel_id)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")

    return html


def _build_html(data_json: str, title: str) -> str:
    """构建完整 HTML 文档。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — 叙事线</title>
<style>
{_CSS}
</style>
</head>
<body>
<div id="app">
  <header>
    <h1>{title}</h1>
    <div class="controls">
      <label><input type="checkbox" id="showLinks" checked> 显示连接</label>
      <label><input type="checkbox" id="showTension" checked> 张力热力图</label>
      <select id="linkFilter">
        <option value="all">全部连接</option>
        <option value="converge">汇合</option>
        <option value="diverge">分离</option>
        <option value="jump">跳转</option>
        <option value="foreshadow">伏笔</option>
        <option value="reference">引用</option>
      </select>
      <button id="resetView">重置视图</button>
    </div>
  </header>
  <div id="timeline-container">
    <svg id="timeline-svg"></svg>
  </div>
  <div id="tooltip" class="tooltip"></div>
  <div id="detail-panel" class="detail-panel hidden">
    <button class="close-btn" onclick="document.getElementById('detail-panel').classList.add('hidden')">&times;</button>
    <div id="detail-content"></div>
  </div>
</div>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const DATA = {data_json};
{_JS}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: "Noto Serif SC", "Source Han Serif SC", Georgia, serif;
  background: #F5F1E8;
  color: #1A1A18;
  overflow: hidden;
}
#app { display: flex; flex-direction: column; height: 100vh; }
header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 24px;
  background: #FBF9F4;
  border-bottom: 1px solid #C8C0B0;
  flex-shrink: 0;
}
header h1 { font-size: 18px; font-weight: 600; color: #2B5A8C; }
.controls { display: flex; gap: 16px; align-items: center; font-size: 13px; }
.controls label { cursor: pointer; user-select: none; }
.controls select, .controls button {
  background: #E8E4D9; color: #1A1A18; border: 1px solid #C8C0B0;
  padding: 4px 10px; border-radius: 2px; font-size: 13px; cursor: pointer;
}
.controls button:hover { background: #DDD6C8; }
#timeline-container { flex: 1; overflow: hidden; position: relative; }
#timeline-svg { width: 100%; height: 100%; }

/* 泳道 */
.lane-bg { fill: transparent; }
.lane-bg:hover { fill: rgba(0,0,0,0.03); }
.lane-label {
  font-size: 13px; font-weight: 500; fill: #4A4740;
  dominant-baseline: middle; cursor: default;
}
.chapter-label {
  font-size: 11px; fill: #7A766D;
  text-anchor: middle; dominant-baseline: hanging;
}
.chapter-line { stroke: #DDD6C8; stroke-width: 1; stroke-dasharray: 2,4; }

/* 事件节点 */
.event-node { cursor: pointer; transition: r 0.15s; }
.event-node:hover { filter: brightness(0.9); }

/* 连接线 */
.link-path { fill: none; opacity: 0.7; cursor: pointer; }
.link-path:hover { opacity: 1; stroke-width: 3 !important; }
.link-path.converge { stroke: #2D6A4F; }
.link-path.diverge { stroke: #8B4049; }
.link-path.jump { stroke: #8B6B4A; }
.link-path.foreshadow { stroke: #5C4B6B; }
.link-path.reference { stroke: #3A6B8C; }

/* Tooltip */
.tooltip {
  position: fixed; pointer-events: none;
  background: #FBF9F4; border: 1px solid #C8C0B0;
  border-radius: 2px; padding: 10px 14px;
  font-size: 13px; line-height: 1.5;
  max-width: 320px; z-index: 100;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  opacity: 0; transition: opacity 0.15s;
}
.tooltip.visible { opacity: 1; }
.tooltip .tt-title { font-weight: 600; color: #2B5A8C; margin-bottom: 4px; }
.tooltip .tt-meta { color: #7A766D; font-size: 12px; }

/* 详情面板 */
.detail-panel {
  position: fixed; right: 0; top: 0; bottom: 0; width: 340px;
  background: #FBF9F4; border-left: 1px solid #C8C0B0;
  padding: 20px; overflow-y: auto; z-index: 50;
  transition: transform 0.2s;
}
.detail-panel.hidden { transform: translateX(100%); }
.close-btn {
  position: absolute; top: 10px; right: 14px;
  background: none; border: none; color: #7A766D;
  font-size: 22px; cursor: pointer;
}
.close-btn:hover { color: #1A1A18; }

/* 张力条 */
.tension-bar {
  display: inline-block; height: 4px; border-radius: 2px;
  vertical-align: middle; margin-left: 6px;
}

/* 线程线 */
.thread-line { fill: none; stroke-width: 2; opacity: 0.5; }

/* 图例 */
.legend { font-size: 12px; }
.legend rect { rx: 2; }
.legend text { fill: #4A4740; dominant-baseline: middle; }
"""


# ---------------------------------------------------------------------------
# JavaScript (D3.js 渲染逻辑)
# ---------------------------------------------------------------------------
_JS = """\
(function() {
  "use strict";

  // ---- 布局常量 ----
  const MARGIN = { top: 60, right: 40, bottom: 40, left: 160 };
  const LANE_HEIGHT = 60;
  const NODE_RADIUS = 7;
  const LINK_TYPE_CN = {
    converge: "汇合", diverge: "分离", jump: "跳转",
    foreshadow: "伏笔", reference: "引用"
  };
  const LINK_DASH = {
    solid: "", dashed: "6,4", dotted: "2,3"
  };

  // ---- 数据准备 ----
  const chapters = DATA.chapters || [];
  const threads = DATA.threads || [];
  const links = DATA.links || [];

  if (!chapters.length && threads.length) {
    // 从事件中收集章节
    const chSet = new Set();
    threads.forEach(t => t.events.forEach(e => chSet.add(e.chapter_id)));
    chapters.push(...[...chSet].sort((a, b) => {
      const na = parseInt(a.replace(/\\D/g, "")) || 0;
      const nb = parseInt(b.replace(/\\D/g, "")) || 0;
      return na - nb;
    }));
  }

  const chapterIndex = {};
  chapters.forEach((ch, i) => chapterIndex[ch] = i);

  // 构建事件查找表: threadId -> chapterId -> event
  const eventMap = {};
  threads.forEach(t => {
    eventMap[t.id] = {};
    t.events.forEach(e => {
      eventMap[t.id][e.chapter_id] = e;
    });
  });

  const threadIndex = {};
  threads.forEach((t, i) => threadIndex[t.id] = i);

  // ---- SVG 尺寸 ----
  const svgEl = document.getElementById("timeline-svg");
  const containerEl = document.getElementById("timeline-container");
  const totalWidth = Math.max(
    containerEl.clientWidth,
    MARGIN.left + MARGIN.right + chapters.length * 100
  );
  const totalHeight = Math.max(
    containerEl.clientHeight,
    MARGIN.top + MARGIN.bottom + threads.length * LANE_HEIGHT + 60
  );

  const svg = d3.select("#timeline-svg")
    .attr("width", totalWidth)
    .attr("height", totalHeight);

  // 缩放
  const g = svg.append("g");
  const zoom = d3.zoom()
    .scaleExtent([0.3, 4])
    .on("zoom", (event) => g.attr("transform", event.transform));
  svg.call(zoom);

  document.getElementById("resetView").addEventListener("click", () => {
    svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
  });

  // ---- 比例尺 ----
  const xScale = d3.scaleLinear()
    .domain([0, chapters.length - 1])
    .range([MARGIN.left, MARGIN.left + (chapters.length - 1) * 100]);

  const yScale = (threadIdx) => MARGIN.top + threadIdx * LANE_HEIGHT + LANE_HEIGHT / 2;

  // 张力颜色
  const tensionColor = d3.scaleSequential(d3.interpolateYlOrRd).domain([1, 10]);

  // ---- 绘制章节网格 ----
  const chapterGroup = g.append("g").attr("class", "chapters");
  chapters.forEach((ch, i) => {
    const x = xScale(i);
    chapterGroup.append("line")
      .attr("class", "chapter-line")
      .attr("x1", x).attr("y1", MARGIN.top - 20)
      .attr("x2", x).attr("y2", MARGIN.top + threads.length * LANE_HEIGHT);
    chapterGroup.append("text")
      .attr("class", "chapter-label")
      .attr("x", x).attr("y", MARGIN.top - 30)
      .text(ch.replace("ch_", "第").replace(/^第0+/, "第") + "章");
  });

  // ---- 绘制泳道 ----
  const laneGroup = g.append("g").attr("class", "lanes");
  threads.forEach((t, i) => {
    const y = yScale(i);
    // 泳道背景
    laneGroup.append("rect")
      .attr("class", "lane-bg")
      .attr("x", MARGIN.left - 10)
      .attr("y", y - LANE_HEIGHT / 2)
      .attr("width", totalWidth - MARGIN.left - MARGIN.right + 20)
      .attr("height", LANE_HEIGHT);
    // 泳道标签
    laneGroup.append("text")
      .attr("class", "lane-label")
      .attr("x", 16).attr("y", y)
      .text(t.name);
    // 线程连线（贯穿有事件的章节）
    const chIds = t.events.map(e => chapterIndex[e.chapter_id]).filter(v => v !== undefined).sort((a,b) => a-b);
    if (chIds.length >= 2) {
      const lineData = chIds.map(ci => [xScale(ci), y]);
      laneGroup.append("path")
        .attr("class", "thread-line")
        .attr("stroke", t.color || "#666")
        .attr("d", d3.line().curve(d3.curveMonotoneX)(lineData));
    }
  });

  // ---- 绘制连接线 ----
  const linkGroup = g.append("g").attr("class", "links");

  function renderLinks(filter) {
    linkGroup.selectAll("*").remove();
    const filtered = filter === "all" ? links : links.filter(l => l.link_type === filter);
    filtered.forEach(lk => {
      const si = threadIndex[lk.source_thread];
      const ti = threadIndex[lk.target_thread];
      const sci = chapterIndex[lk.source_chapter];
      const tci = chapterIndex[lk.target_chapter];
      if (si === undefined || sci === undefined) return;
      if (tci === undefined && lk.target_chapter) return;

      const x1 = xScale(sci), y1 = yScale(si);
      const x2 = tci !== undefined ? xScale(tci) : x1 + 50;
      const y2 = ti !== undefined ? yScale(ti) : y1;

      // 曲线路径
      const midX = (x1 + x2) / 2;
      const curveOffset = (si === ti) ? -30 : 0;
      const path = `M${x1},${y1} C${midX},${y1 + curveOffset} ${midX},${y2 + curveOffset} ${x2},${y2}`;

      const strokeW = Math.max(1, Math.min(lk.weight / 3, 4));
      const dash = LINK_DASH[lk.style] || "";

      linkGroup.append("path")
        .attr("class", `link-path ${lk.link_type}`)
        .attr("d", path)
        .attr("stroke-width", strokeW)
        .attr("stroke-dasharray", dash)
        .on("mouseover", (event) => showTooltip(event, linkTooltip(lk)))
        .on("mouseout", hideTooltip);
    });
  }

  // ---- 绘制事件节点 ----
  const nodeGroup = g.append("g").attr("class", "nodes");
  const showTensionCb = document.getElementById("showTension");

  function renderNodes() {
    nodeGroup.selectAll("*").remove();
    const useTension = showTensionCb.checked;
    threads.forEach((t, i) => {
      const y = yScale(i);
      t.events.forEach(e => {
        const ci = chapterIndex[e.chapter_id];
        if (ci === undefined) return;
        const x = xScale(ci);
        const color = useTension ? tensionColor(e.tension) : (t.color || "#666");
        const r = NODE_RADIUS + (e.tension - 5) * 0.5;

        nodeGroup.append("circle")
          .attr("class", "event-node")
          .attr("cx", x).attr("cy", y)
          .attr("r", Math.max(4, r))
          .attr("fill", color)
          .attr("stroke", "#fff").attr("stroke-width", 1.5)
          .on("mouseover", (event) => showTooltip(event, eventTooltip(t, e)))
          .on("mouseout", hideTooltip)
          .on("click", () => showDetail(t, e));
      });
    });
  }

  // ---- 图例 ----
  const legendData = [
    { type: "converge", label: "汇合", color: "#4ECDC4" },
    { type: "diverge", label: "分离", color: "#FF6B6B" },
    { type: "jump", label: "跳转", color: "#FFEAA7" },
    { type: "foreshadow", label: "伏笔", color: "#DDA0DD" },
    { type: "reference", label: "引用", color: "#85C1E9" },
  ];
  const legend = g.append("g").attr("class", "legend")
    .attr("transform", `translate(${MARGIN.left}, ${MARGIN.top + threads.length * LANE_HEIGHT + 20})`);
  legendData.forEach((d, i) => {
    const gItem = legend.append("g").attr("transform", `translate(${i * 90}, 0)`);
    gItem.append("rect").attr("width", 14).attr("height", 14).attr("fill", d.color);
    gItem.append("text").attr("x", 18).attr("y", 7).text(d.label);
  });

  // ---- Tooltip ----
  const tooltipEl = document.getElementById("tooltip");

  function showTooltip(event, html) {
    tooltipEl.innerHTML = html;
    tooltipEl.classList.add("visible");
    const x = Math.min(event.clientX + 12, window.innerWidth - 340);
    const y = Math.min(event.clientY + 12, window.innerHeight - 200);
    tooltipEl.style.left = x + "px";
    tooltipEl.style.top = y + "px";
  }
  function hideTooltip() {
    tooltipEl.classList.remove("visible");
  }

  function eventTooltip(thread, event) {
    const tensionBar = `<span class="tension-bar" style="width:${event.tension * 10}px;background:${tensionColor(event.tension)}"></span>`;
    const tags = event.tags.length ? `<div class="tt-meta">标签: ${event.tags.join(", ")}</div>` : "";
    return `<div class="tt-title">${thread.name} · ${event.label}</div>
      <div class="tt-meta">${event.chapter_id} | 张力 ${event.tension}/10 ${tensionBar}</div>
      ${event.detail ? `<div style="margin-top:4px">${event.detail}</div>` : ""}
      ${tags}`;
  }

  function linkTooltip(lk) {
    const srcName = threads.find(t => t.id === lk.source_thread)?.name || lk.source_thread;
    const tgtName = threads.find(t => t.id === lk.target_thread)?.name || lk.target_thread;
    return `<div class="tt-title">${LINK_TYPE_CN[lk.link_type] || lk.link_type}</div>
      <div>${srcName} (${lk.source_chapter}) → ${tgtName} (${lk.target_chapter || "?"})</div>
      ${lk.label ? `<div style="margin-top:4px">${lk.label}</div>` : ""}`;
  }

  // ---- 详情面板 ----
  function showDetail(thread, event) {
    const panel = document.getElementById("detail-panel");
    const content = document.getElementById("detail-content");
    // 找到该事件相关的连接
    const relLinks = links.filter(lk =>
      (lk.source_thread === thread.id && lk.source_chapter === event.chapter_id) ||
      (lk.target_thread === thread.id && lk.target_chapter === event.chapter_id)
    );
    const linksHtml = relLinks.map(lk => {
      const srcName = threads.find(t => t.id === lk.source_thread)?.name || lk.source_thread;
      const tgtName = threads.find(t => t.id === lk.target_thread)?.name || lk.target_thread;
      return `<div style="margin:6px 0;padding:6px;background:#E8E4D9;border-radius:2px">
        <span style="color:${getTypeColor(lk.link_type)}">[${LINK_TYPE_CN[lk.link_type]}]</span>
        ${srcName} (${lk.source_chapter}) → ${tgtName} (${lk.target_chapter || "?"})
        ${lk.label ? `<div style="color:#7A766D;font-size:12px">${lk.label}</div>` : ""}
      </div>`;
    }).join("");

    content.innerHTML = `
      <h3 style="color:${thread.color || '#2B5A8C'};margin-bottom:12px">${thread.name}</h3>
      <div style="margin-bottom:8px">
        <strong>${event.label}</strong>
        <span style="color:#7A766D;margin-left:8px">${event.chapter_id}</span>
      </div>
      <div style="margin-bottom:8px">张力: ${event.tension}/10
        <span class="tension-bar" style="width:${event.tension * 10}px;background:${tensionColor(event.tension)}"></span>
      </div>
      ${event.detail ? `<div style="margin-bottom:12px;color:#4A4740">${event.detail}</div>` : ""}
      ${event.tags.length ? `<div style="margin-bottom:12px">标签: ${event.tags.map(t => `<span style="background:#E8E4D9;padding:2px 8px;border-radius:2px;margin:2px;display:inline-block;font-size:12px;color:#4A4740">${t}</span>`).join("")}</div>` : ""}
      ${relLinks.length ? `<h4 style="margin:12px 0 6px;color:#2B5A8C">相关连接 (${relLinks.length})</h4>${linksHtml}` : "<div style='color:#7A766D;margin-top:12px'>无相关连接</div>"}
    `;
    panel.classList.remove("hidden");
  }

  function getTypeColor(type) {
    const map = { converge:"#2D6A4F", diverge:"#8B4049", jump:"#8B6B4A", foreshadow:"#5C4B6B", reference:"#3A6B8C" };
    return map[type] || "#7A766D";
  }

  // ---- 控件绑定 ----
  document.getElementById("showLinks").addEventListener("change", (e) => {
    linkGroup.style("display", e.target.checked ? "block" : "none");
  });
  showTensionCb.addEventListener("change", () => renderNodes());
  document.getElementById("linkFilter").addEventListener("change", (e) => {
    renderLinks(e.target.value);
  });

  // ---- 初始渲染 ----
  renderLinks("all");
  renderNodes();

  // 自动居中
  if (threads.length && chapters.length) {
    const initScale = Math.min(
      1,
      (containerEl.clientWidth - 40) / totalWidth,
      (containerEl.clientHeight - 40) / totalHeight
    );
    const tx = (containerEl.clientWidth - totalWidth * initScale) / 2;
    const ty = 20;
    svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(initScale));
  }
})();
"""
