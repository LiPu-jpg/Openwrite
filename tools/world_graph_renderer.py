"""世界观图谱 D3 力导向可视化渲染器 — 生成自包含的交互式 HTML 文件。

使用 D3.js 力导向图渲染：
- 节点按实体类型着色，大小按关系数量
- 边按关系类型着色，粗细按权重
- 支持拖拽、缩放、hover 提示、点击详情
- 搜索过滤、类型筛选
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.models.world import WorldGraph


def render_world_graph_html(
    graph: WorldGraph,
    title: str = "世界观图谱",
    output_path: Optional[Path] = None,
) -> str:
    """将 WorldGraph 渲染为自包含 HTML 字符串。"""
    nodes = []
    for eid, entity in graph.entities.items():
        nodes.append(
            {
                "id": eid,
                "name": entity.name,
                "type": entity.type,
                "description": entity.description,
                "tags": entity.tags,
                "attributes": entity.attributes,
            }
        )

    edges = []
    for rel in graph.relations:
        edges.append(
            {
                "source": rel.source_id,
                "target": rel.target_id,
                "relation": rel.relation,
                "weight": rel.weight,
                "note": rel.note,
                "chapter_id": getattr(rel, "chapter_id", ""),
            }
        )

    data_json = json.dumps(
        {"nodes": nodes, "edges": edges},
        ensure_ascii=False,
        indent=2,
    )

    html = _build_html(data_json, title)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")

    return html


def _build_html(data_json: str, title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
{_CSS}
</style>
</head>
<body>
<div id="app">
  <header>
    <h1>{title}</h1>
    <div class="controls">
      <input type="text" id="search" placeholder="搜索实体..." />
      <select id="typeFilter"><option value="all">全部类型</option></select>
      <label><input type="checkbox" id="showLabels" checked> 显示标签</label>
      <button id="resetView">重置</button>
    </div>
  </header>
  <div id="graph-container">
    <svg id="graph-svg"></svg>
  </div>
  <div id="tooltip" class="tooltip"></div>
  <div id="detail-panel" class="detail-panel hidden">
    <button class="close-btn" onclick="document.getElementById('detail-panel').classList.add('hidden')">&times;</button>
    <div id="detail-content"></div>
  </div>
  <div id="legend"></div>
</div>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const DATA = {data_json};
{_JS}
</script>
</body>
</html>"""


_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #0a0a1a;
  color: #e0e0e0;
  overflow: hidden;
}
#app { display: flex; flex-direction: column; height: 100vh; }
header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 24px;
  background: #12122e;
  border-bottom: 1px solid #2a2a5e;
  flex-shrink: 0;
}
header h1 { font-size: 18px; font-weight: 600; color: #7eb8ff; }
.controls { display: flex; gap: 12px; align-items: center; font-size: 13px; }
.controls input[type="text"] {
  background: #1e1e4e; color: #e0e0e0; border: 1px solid #3a3a7e;
  padding: 5px 12px; border-radius: 4px; width: 180px; font-size: 13px;
}
.controls select, .controls button {
  background: #1e1e4e; color: #e0e0e0; border: 1px solid #3a3a7e;
  padding: 5px 12px; border-radius: 4px; font-size: 13px; cursor: pointer;
}
.controls button:hover { background: #3a3a7e; }
.controls label { cursor: pointer; user-select: none; }
#graph-container { flex: 1; overflow: hidden; position: relative; }
#graph-svg { width: 100%; height: 100%; }

.node-circle { cursor: pointer; stroke: #fff; stroke-width: 1.5; }
.node-circle:hover { stroke-width: 3; filter: brightness(1.3); }
.node-label { font-size: 11px; fill: #c0c0c0; pointer-events: none; text-anchor: middle; }
.edge-line { stroke-opacity: 0.5; }
.edge-line:hover { stroke-opacity: 1; }
.edge-label { font-size: 9px; fill: #808080; pointer-events: none; text-anchor: middle; }

.tooltip {
  position: fixed; pointer-events: none;
  background: #12122e; border: 1px solid #3a3a7e;
  border-radius: 6px; padding: 10px 14px;
  font-size: 13px; line-height: 1.5;
  max-width: 320px; z-index: 100;
  box-shadow: 0 4px 20px rgba(0,0,0,0.5);
  opacity: 0; transition: opacity 0.15s;
}
.tooltip.visible { opacity: 1; }
.tooltip .tt-title { font-weight: 600; color: #7eb8ff; margin-bottom: 4px; }
.tooltip .tt-type { color: #808080; font-size: 12px; }

.detail-panel {
  position: fixed; right: 0; top: 0; bottom: 0; width: 340px;
  background: #12122e; border-left: 1px solid #2a2a5e;
  padding: 20px; overflow-y: auto; z-index: 50;
  transition: transform 0.2s;
}
.detail-panel.hidden { transform: translateX(100%); }
.close-btn {
  position: absolute; top: 10px; right: 14px;
  background: none; border: none; color: #808080;
  font-size: 22px; cursor: pointer;
}
.close-btn:hover { color: #e0e0e0; }

#legend {
  position: fixed; bottom: 16px; left: 16px;
  background: rgba(18,18,46,0.9); border: 1px solid #2a2a5e;
  border-radius: 6px; padding: 10px 14px; font-size: 12px;
  z-index: 40;
}
.legend-item { display: flex; align-items: center; gap: 6px; margin: 3px 0; }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; }
"""


_JS = """\
(function() {
  "use strict";

  const TYPE_COLORS = {
    character: "#FF6B6B",
    location: "#4ECDC4",
    organization: "#FFEAA7",
    item: "#DDA0DD",
    concept: "#85C1E9",
    event: "#F0B27A",
  };
  const DEFAULT_COLOR = "#AED6F1";
  const RELATION_COLORS = {
    belongs_to: "#4ECDC4",
    located_at: "#45B7D1",
    ally: "#96CEB4",
    enemy: "#FF6B6B",
    master_of: "#FFEAA7",
    owns: "#DDA0DD",
    above: "#F7DC6F",
    related_to: "#85C1E9",
  };
  const TYPE_CN = {
    character: "人物", location: "地点", organization: "组织",
    item: "物品", concept: "概念", event: "事件",
  };

  const nodes = DATA.nodes;
  const edges = DATA.edges;

  // 计算节点度数
  const degreeMap = {};
  edges.forEach(e => {
    degreeMap[e.source] = (degreeMap[e.source] || 0) + 1;
    degreeMap[e.target] = (degreeMap[e.target] || 0) + 1;
  });

  // 类型筛选
  const types = [...new Set(nodes.map(n => n.type))].sort();
  const typeSelect = document.getElementById("typeFilter");
  types.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = TYPE_CN[t] || t;
    typeSelect.appendChild(opt);
  });

  // 图例
  const legendEl = document.getElementById("legend");
  types.forEach(t => {
    const color = TYPE_COLORS[t] || DEFAULT_COLOR;
    legendEl.innerHTML += `<div class="legend-item"><span class="legend-dot" style="background:${color}"></span>${TYPE_CN[t] || t}</div>`;
  });

  // SVG
  const container = document.getElementById("graph-container");
  const width = container.clientWidth;
  const height = container.clientHeight;

  const svg = d3.select("#graph-svg")
    .attr("width", width)
    .attr("height", height);

  const g = svg.append("g");
  const zoom = d3.zoom()
    .scaleExtent([0.2, 5])
    .on("zoom", (event) => g.attr("transform", event.transform));
  svg.call(zoom);

  document.getElementById("resetView").addEventListener("click", () => {
    svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
  });

  // 力模拟
  const simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id(d => d.id).distance(100))
    .force("charge", d3.forceManyBody().strength(-300))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide().radius(30));

  // 边
  const edgeGroup = g.append("g").attr("class", "edges");
  const edgeLines = edgeGroup.selectAll("line")
    .data(edges)
    .join("line")
    .attr("class", "edge-line")
    .attr("stroke", d => RELATION_COLORS[d.relation] || "#555")
    .attr("stroke-width", d => Math.max(1, d.weight / 2))
    .on("mouseover", (event, d) => showTooltip(event, edgeTooltip(d)))
    .on("mouseout", hideTooltip);

  // 边标签
  const edgeLabels = edgeGroup.selectAll("text")
    .data(edges)
    .join("text")
    .attr("class", "edge-label")
    .text(d => d.relation);

  // 节点
  const nodeGroup = g.append("g").attr("class", "nodes");
  const nodeCircles = nodeGroup.selectAll("circle")
    .data(nodes)
    .join("circle")
    .attr("class", "node-circle")
    .attr("r", d => Math.max(8, Math.min(20, 6 + (degreeMap[d.id] || 0) * 2)))
    .attr("fill", d => TYPE_COLORS[d.type] || DEFAULT_COLOR)
    .on("mouseover", (event, d) => showTooltip(event, nodeTooltip(d)))
    .on("mouseout", hideTooltip)
    .on("click", (event, d) => showDetail(d))
    .call(d3.drag()
      .on("start", dragStart)
      .on("drag", dragging)
      .on("end", dragEnd));

  // 节点标签
  const nodeLabels = nodeGroup.selectAll("text")
    .data(nodes)
    .join("text")
    .attr("class", "node-label")
    .attr("dy", d => Math.max(8, 6 + (degreeMap[d.id] || 0) * 2) + 14)
    .text(d => d.name);

  // Tick
  simulation.on("tick", () => {
    edgeLines
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);
    edgeLabels
      .attr("x", d => (d.source.x + d.target.x) / 2)
      .attr("y", d => (d.source.y + d.target.y) / 2);
    nodeCircles
      .attr("cx", d => d.x)
      .attr("cy", d => d.y);
    nodeLabels
      .attr("x", d => d.x)
      .attr("y", d => d.y);
  });

  // 拖拽
  function dragStart(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart();
    d.fx = d.x; d.fy = d.y;
  }
  function dragging(event, d) { d.fx = event.x; d.fy = event.y; }
  function dragEnd(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null; d.fy = null;
  }

  // Tooltip
  const tooltipEl = document.getElementById("tooltip");
  function showTooltip(event, html) {
    tooltipEl.innerHTML = html;
    tooltipEl.classList.add("visible");
    tooltipEl.style.left = Math.min(event.clientX + 12, window.innerWidth - 340) + "px";
    tooltipEl.style.top = Math.min(event.clientY + 12, window.innerHeight - 200) + "px";
  }
  function hideTooltip() { tooltipEl.classList.remove("visible"); }

  function nodeTooltip(d) {
    const attrs = Object.entries(d.attributes || {}).map(([k,v]) => `${k}: ${v}`).join(", ");
    return `<div class="tt-title">${d.name}</div>
      <div class="tt-type">${TYPE_CN[d.type] || d.type} | 关系数: ${degreeMap[d.id] || 0}</div>
      ${d.description ? `<div style="margin-top:4px">${d.description}</div>` : ""}
      ${attrs ? `<div style="margin-top:4px;color:#808080">${attrs}</div>` : ""}`;
  }
  function edgeTooltip(d) {
    const src = typeof d.source === "object" ? d.source.name : d.source;
    const tgt = typeof d.target === "object" ? d.target.name : d.target;
    return `<div class="tt-title">${d.relation}</div>
      <div>${src} → ${tgt}</div>
      ${d.note ? `<div style="margin-top:4px">${d.note}</div>` : ""}
      <div class="tt-type">权重: ${d.weight}${d.chapter_id ? ` | 章节: ${d.chapter_id}` : ""}</div>`;
  }

  // 详情面板
  function showDetail(d) {
    const panel = document.getElementById("detail-panel");
    const content = document.getElementById("detail-content");
    const rels = edges.filter(e => {
      const sid = typeof e.source === "object" ? e.source.id : e.source;
      const tid = typeof e.target === "object" ? e.target.id : e.target;
      return sid === d.id || tid === d.id;
    });
    const relsHtml = rels.map(e => {
      const src = typeof e.source === "object" ? e.source : nodes.find(n => n.id === e.source);
      const tgt = typeof e.target === "object" ? e.target : nodes.find(n => n.id === e.target);
      return `<div style="margin:4px 0;padding:6px;background:#0a0a1a;border-radius:4px">
        <span style="color:${RELATION_COLORS[e.relation] || '#555'}">[${e.relation}]</span>
        ${src?.name || "?"} → ${tgt?.name || "?"}
        ${e.note ? `<div style="color:#808080;font-size:12px">${e.note}</div>` : ""}
      </div>`;
    }).join("");
    const attrs = Object.entries(d.attributes || {}).map(([k,v]) =>
      `<div style="margin:2px 0"><span style="color:#808080">${k}:</span> ${v}</div>`
    ).join("");
    const tags = (d.tags || []).map(t =>
      `<span style="background:#1e1e4e;padding:2px 8px;border-radius:3px;margin:2px;display:inline-block;font-size:12px">${t}</span>`
    ).join("");

    content.innerHTML = `
      <h3 style="color:${TYPE_COLORS[d.type] || DEFAULT_COLOR};margin-bottom:12px">${d.name}</h3>
      <div style="margin-bottom:8px;color:#808080">${TYPE_CN[d.type] || d.type}</div>
      ${d.description ? `<div style="margin-bottom:12px">${d.description}</div>` : ""}
      ${attrs ? `<div style="margin-bottom:12px">${attrs}</div>` : ""}
      ${tags ? `<div style="margin-bottom:12px">${tags}</div>` : ""}
      <h4 style="margin:12px 0 6px;color:#7eb8ff">关系 (${rels.length})</h4>
      ${relsHtml || "<div style='color:#808080'>无关系</div>"}
    `;
    panel.classList.remove("hidden");
  }

  // 搜索
  document.getElementById("search").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    nodeCircles.attr("opacity", d => !q || d.name.toLowerCase().includes(q) ? 1 : 0.15);
    nodeLabels.attr("opacity", d => !q || d.name.toLowerCase().includes(q) ? 1 : 0.15);
    edgeLines.attr("opacity", 0.3);
  });

  // 类型筛选
  typeSelect.addEventListener("change", (e) => {
    const t = e.target.value;
    nodeCircles.attr("opacity", d => t === "all" || d.type === t ? 1 : 0.1);
    nodeLabels.attr("opacity", d => t === "all" || d.type === t ? 1 : 0.1);
    edgeLines.attr("opacity", e2 => {
      if (t === "all") return 0.5;
      const src = typeof e2.source === "object" ? e2.source : nodes.find(n => n.id === e2.source);
      const tgt = typeof e2.target === "object" ? e2.target : nodes.find(n => n.id === e2.target);
      return (src?.type === t || tgt?.type === t) ? 0.5 : 0.05;
    });
  });

  // 标签显隐
  document.getElementById("showLabels").addEventListener("change", (e) => {
    nodeLabels.attr("display", e.target.checked ? "block" : "none");
    edgeLabels.attr("display", e.target.checked ? "block" : "none");
  });
})();
"""
