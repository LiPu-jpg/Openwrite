#!/usr/bin/env python3
"""dsh-novel 深度研究的 dsh 原生路线：headless 会话检索 + 综合成报告，
落库到 OpenWrite 报告目录（研究 tab 直接可见）。

与 Studio 自带 DeepResearch（pnpm 子进程、需要博查/Bing/Jina Key）的区别：
检索环节由 dsh agent 的原生 web_search 承担（deepseek-official 路由，
复用 DEEPSEEK_API_KEY，零额外凭据）；报告格式与报告库完全兼容。

用法：
    .venv/bin/python research.py --prompt "明清漕运制度的运作与衰落"
    .venv/bin/python research.py --prompt "…" --title "漕运制度考"
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_STUDIO = os.environ.get("OPENWRITE_STUDIO", "http://127.0.0.1:4567")
AGENT_TIMEOUT_S = 900


def http_json(base: str, path: str) -> dict:
    url = f"{base.rstrip('/')}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
        return payload["data"]
    return payload


def resolve_novel_root(studio: str) -> tuple[Path, str]:
    """(项目根, novel_id)：root 来自 workspace.project.root，
    novel_id 来自任一任务行的 novel_id 字段。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers = {"Accept": "application/json"}

    def get_json(path: str) -> dict:
        req = urllib.request.Request(f"{studio.rstrip('/')}{path}", headers=headers)
        with opener.open(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        return payload.get("data") if isinstance(payload, dict) and payload.get("ok") is True else payload

    ws = get_json("/api/workspace") or {}
    project = ws.get("project") or {}
    root = Path(str(project.get("root") or "")).expanduser()
    tasks = (get_json("/api/tasks") or {}).get("tasks") or []
    novel_id = next((str(t.get("novel_id")) for t in tasks if t.get("novel_id")), "")
    if not root.is_dir() or not novel_id:
        raise SystemExit("无法确定小说根/novel_id：请确认 Studio 已打开该项目")
    return root, novel_id


def resolve_report_dir(studio: str) -> Path:
    """从任一既有报告的相对路径推导报告库绝对目录；无历史报告时经 workspace 推导。"""
    try:
        surface = http_json(studio, "/api/research")
        reports = surface.get("reports") or []
        if reports:
            rel = str(reports[0].get("path") or "")
            if rel:
                # 形如 data/novels/mujianzhe/data/research/reports/EP_xxx.md
                p = Path(rel.replace("data/research/reports", ""))
                # 重新精确拼：找 workspace 里的项目根
        # 统一走 workspace：snapshot/project 提供根信息
    except Exception:
        pass

    ws = http_json(studio, "/api/workspace")
    project = ws.get("project") or {}
    root = Path(str(project.get("root") or "")).expanduser()
    novel_id = str(project.get("novel_id") or "")
    if not root.is_dir() or not novel_id:
        raise SystemExit("无法确定小说项目根（workspace 缺 project.root/novel_id）")
    return root / "data" / "novels" / novel_id / "data" / "research" / "reports"


def build_agent_prompt(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "请用 web_search 工具做联网调研（至少 3 次不同角度的搜索），然后输出一份中文 Markdown 研究报告：\n"
        "- 开头一段执行摘要（≤150 字）\n"
        "- 正文分 3-5 个小节展开，标注关键事实与数字\n"
        "- 结尾附「参考来源」清单（真实 URL 列表）\n"
        "- 只输出报告本身，不要额外说明"
    )


def run_headless_research(prompt: str, workspace_cwd: str) -> tuple[str, float]:
    """跑一次 headless dsh 联网调研会话，返回 (最终报告文本, 用时秒)。"""
    started = time.monotonic()
    dsh = Path(__file__).resolve().parent.parent / "node_modules" / ".bin" / "dsh"
    result = subprocess.run(
        [str(dsh), "--profile", "headless", build_agent_prompt(prompt)],
        capture_output=True,
        text=True,
        timeout=AGENT_TIMEOUT_S,
        cwd=workspace_cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"headless 会话失败(exit={result.returncode}): {result.stderr[-300:]}")
    return result.stdout.strip(), time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="dsh 原生深度研究：headless 检索综合 → 报告库落库")
    parser.add_argument("--prompt", required=True, help="研究问题")
    parser.add_argument("--title", default="", help="报告标题（默认取问题前 40 字）")
    parser.add_argument("--studio", default=os.environ.get("OPENWRITE_STUDIO", DEFAULT_STUDIO))
    args = parser.parse_args()

    base = args.studio.rstrip("/")

    # 推导报告库目录
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(f"{base}/api/research", headers={"Accept": "application/json"})
    with opener.open(req, timeout=30) as resp:
        surface = json.loads(resp.read().decode())
    envelope = surface.get("data") if isinstance(surface, dict) else None
    surface_data = envelope if isinstance(envelope, dict) else surface
    reports = surface_data.get("reports") or []

    # 报告库绝对目录：列表里的 path 是相对路径（相对 {root}/data/novels/{id}/），
    # 需要项目根 + novel_id 拼接；novel_id 从任务行取（workspace 不带）。
    root, novel_id = resolve_novel_root(base)
    report_dir = root / "data" / "novels" / novel_id / "data" / "research" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    title = args.title.strip() or (args.prompt.strip()[:40] + ("…" if len(args.prompt.strip()) > 40 else ""))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_id = f"DSH_{stamp}"

    started = time.monotonic()
    print(f"==> 研究问题: {title}")
    print("==> headless dsh 联网调研中（最长 {}s）…".format(AGENT_TIMEOUT_S), flush=True)

    elapsed = 0.0
    dsh_bin = Path(__file__).resolve().parent.parent / "node_modules" / ".bin" / "dsh"
    proc = subprocess.run(
        [str(dsh_bin), "--profile", "headless", build_agent_prompt(args.prompt)],
        capture_output=True, text=True, timeout=AGENT_TIMEOUT_S,
        cwd=str(Path(__file__).resolve().parent),
    )
    answer = proc.stdout.strip()
    elapsed = round(time.monotonic() - started, 1)
    if proc.returncode != 0:
        print(f"headless 会话失败: {proc.stderr[-300:]}", file=sys.stderr)
        return 1
    if answer == "":
        print("headless 会话返回空内容", file=sys.stderr)
        return 1

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "title": title,
        "prompt": args.prompt,
        "status": "completed",
        "episode_id": report_id,
        "created_at": now,
        "artifact_ref": "",
        "metrics": {"engine": "dsh-headless-websearch", "elapsedSeconds": elapsed},
    }
    (report_dir / f"{report_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / f"{report_id}.md").write_text(answer, encoding="utf-8")
    print(f"==> 已落库: {report_dir}/{report_id}.md（{len(answer)} 字）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
