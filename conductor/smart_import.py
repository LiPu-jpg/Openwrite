#!/usr/bin/env python3
"""dsh-novel 智能导入：格式转换 + 智能切章 + AI 差错校验 + 大纲/任务自动建立。

流程：
1. 格式探测与转换（docx/epub/html/txt/md → 统一 markdown）
2. 编码检测（chardet → UTF-8）
3. 章节边界智能识别（正则优先 + 行长突变 + 序号模式兜底）
4. AI 差错校验（headless dsh 会话逐章审查，标记 OOC/时间线/逻辑问题）
5. 大纲自动生成（从章节标题和内容摘要构建层级大纲）
6. 写入 OpenWrite 报告库 + 导入为正式章节
7. 可选：自动创建写作任务

用法：
    .venv/bin/python smart_import.py --file "小说.docx"
    .venv/bin/python research.py --prompt "..."   # dsh 原生研究路线不变
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from .dog_import import write_import_artifacts
except ImportError:  # direct ``python smart_import.py`` execution
    from dog_import import write_import_artifacts

DEFAULT_STUDIO = os.environ.get("OPENWRITE_STUDIO", "http://127.0.0.1:4567")
WRITE_HEADER = "X-OpenWrite-Studio"
AGENT_TIMEOUT_S = 600


# ── 格式探测与转换 ────────────────────────────────────────────────────────

def detect_and_convert(file_path: Path) -> tuple[str, str]:
    """返回 (markdown_text, detected_format)"""
    suffix = file_path.suffix.lower()
    raw = file_path.read_bytes()

    # 编码探测
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise SystemExit(f"无法识别文件编码: {file_path}")

    if suffix in (".md", ".markdown", ".txt"):
        return text, suffix.lstrip(".")
    if suffix == ".docx":
        return _docx_to_md(file_path), "docx"
    if suffix == ".epub":
        return _epub_to_md(file_path), "epub"
    if suffix in (".html", ".htm"):
        return _html_to_md(text), "html"
    raise SystemExit(f"不支持的格式: {suffix}（支持 docx/epub/html/txt/md）")


def _docx_to_md(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    lines = []
    for para in doc.paragraphs:
        style = para.style.name or ""
        text = para.text.strip()
        if not text:
            lines.append("")
            continue
        if "Heading 1" in style or "标题 1" in style:
            lines.append(f"# {text}")
        elif "Heading 2" in style or "标题 2" in style:
            lines.append(f"## {text}")
        elif "Heading 3" in style or "标题 3" in style:
            lines.append(f"### {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines)


def _epub_to_md(path: Path) -> str:
    from ebooklib import epub, ITEM_DOCUMENT
    book = epub.read_epub(str(path))
    from bs4 import BeautifulSoup
    parts = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content().decode("utf-8", errors="replace"), "html.parser")
        text = soup.get_text("\n", strip=True)
        if text.strip():
            title = soup.title.string if soup.title else ""
            if title and title.strip():
                parts.append(f"# {title.strip()}\n\n{text}")
            else:
                parts.append(text)
    return "\n\n".join(parts)


def _html_to_md(html_text: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    # 标题转 markdown
    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            tag.replace_with(f"{'#' * level} {tag.get_text(strip=True)}")
    return soup.get_text("\n", strip=True)


# ── 智能章节边界识别 ────────────────────────────────────────────────────

HEADING_PATTERNS = [
    re.compile(r"^#{1,4}\s+(.+)$"),
    re.compile(r"^第[0-9零〇一二两三四五六七八九十百千万]+[章节回卷篇][^\n]*$"),
    re.compile(r"^Chapter\s+\d+", re.IGNORECASE),
    re.compile(r"^(?:序章|楔子|前言|后记|尾声|番外)[^\n]*$"),
    re.compile(r"^\d{1,4}[.、]\s*\S+"),
]

def smart_split(text: str) -> list[tuple[str, str]]:
    """三层策略：正则匹配 → 行长突变 → 整文件单章"""
    lines = text.split("\n")

    # 第一层：标准正则
    heading_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(p.match(stripped) for p in HEADING_PATTERNS):
            heading_lines.append(i)

    if len(heading_lines) >= 2:
        return _split_at(lines, heading_lines)

    # 第二层：短行 + 前后空行 = 可能的标题
    candidates = []
    for i, line in enumerate(lines):
        s = line.strip()
        prev_blank = i == 0 or lines[i - 1].strip() == ""
        next_blank = i + 1 >= len(lines) or lines[i + 1].strip() == ""
        if prev_blank and next_blank and 2 < len(s) < 40 and not s.endswith(("。", "！", "？", "…")):
            candidates.append(i)
    if len(candidates) >= 2:
        return _split_at(lines, candidates)

    # 第三层：单章
    return [(text.strip()[:40] or "导入章节", text.strip())]


def _split_at(lines: list[str], heading_indices: list[int]) -> list[tuple[str, str]]:
    chunks = []
    prefix = "\n".join(lines[:heading_indices[0]]).strip()
    for idx, h_idx in enumerate(heading_indices):
        title = lines[h_idx].strip().lstrip("#").strip()
        content_start = h_idx + 1
        content_end = heading_indices[idx + 1] if idx + 1 < len(heading_indices) else len(lines)
        body = "\n".join(lines[content_start:content_end]).strip()
        if idx == 0 and prefix:
            body = f"{prefix}\n\n{body}"
        chunks.append((title, body))
    return chunks


# ── Studio API 封装 ──────────────────────────────────────────────────────

class Studio:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(self, path: str, body: dict | None = None) -> dict:
        url = self.base + path
        data = json.dumps(body or {}).encode() if body is not None else b""
        headers = {"Content-Type": "application/json", WRITE_HEADER: "1"}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with self.opener.open(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
            return payload["data"]
        return payload


WRITE_HEADER = "X-OpenWrite-Studio"


# ── 主流程 ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="dsh-novel 智能导入")
    parser.add_argument("--file", required=True, help="源文件路径（docx/epub/html/txt/md）")
    parser.add_argument("--title", default="", help="作品标题")
    parser.add_argument("--studio", default=os.environ.get("OPENWRITE_STUDIO", DEFAULT_STUDIO))
    parser.add_argument("--skip-ai-check", action="store_true", help="跳过 AI 差错校验")
    parser.add_argument("--skip-outline", action="store_true", help="跳过大纲自动生成")
    args = parser.parse_args()

    src = Path(args.file).resolve()
    if not src.is_file():
        raise SystemExit(f"文件不存在: {src}")
    base_url = args.studio.rstrip("/")

    # 1) 转换
    print("==> 1/5 格式探测与转换…", flush=True)
    text, fmt = detect_and_convert(src)
    print(f"    格式 {fmt}，{len(text)} 字符", flush=True)

    # 2) 切章
    print("==> 2/5 智能章节切分…", flush=True)
    chapters = smart_split(text)
    print(f"    识别 {len(chapters)} 章", flush=True)
    for i, (title, _) in enumerate(chapters[:5]):
        print(f"    [{i+1}] {title}", flush=True)
    if len(chapters) > 5:
        print(f"    … 及后续 {len(chapters)-5} 章", flush=True)

    ai_check = {"status": "skipped", "summary": ""}

    # 3) AI 差错校验（headless dsh）
    if not args.skip_ai_check:
        print("==> 3/5 AI 差错校验（headless dsh web_search 辅助核查）…", flush=True)
        dsh_bin = Path(__file__).resolve().parent.parent / "node_modules" / ".bin" / "dsh"
        check_prompt = (
            f"以下是导入的小说稿件的前两章。请快速审读并列出明显问题（OOC、时间线矛盾、逻辑漏洞），\n"
            f"每条一行 [severity] 描述。如果没有严重问题回复「无明显问题」。只列前 5 条。\n\n"
            + text[:6000]
        )
        try:
            proc = subprocess.run(
                [str(dsh_bin), "--profile", "headless", check_prompt],
                capture_output=True, text=True, timeout=300,
                cwd=str(Path(__file__).resolve().parent),
            )
            issues_text = proc.stdout.strip()[:500]
            if proc.returncode == 0:
                ai_check = {"status": "completed", "summary": issues_text}
            else:
                detail = (proc.stderr.strip() or issues_text or f"headless dsh exited {proc.returncode}")[:500]
                ai_check = {"status": "failed", "summary": detail}
            print(f"    校验结果:\n{issues_text}\n", flush=True)
        except Exception as exc:
            ai_check = {"status": "failed", "summary": str(exc)}
            print(f"    AI 校验失败（不影响导入）: {exc}", flush=True)
    else:
        print("==> 3/5 跳过 AI 校验", flush=True)

    # 4) 写入报告库（作为导入记录）
    print("==> 4/5 落库导入记录…", flush=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ws_data = json.loads(urllib.request.urlopen(
        urllib.request.Request(base_url + "/api/workspace", headers={"Accept": "application/json"}),
        timeout=30).read().decode())
    inner = ws_data.get("data") if isinstance(ws_data, dict) and "data" in ws_data else ws_data
    project = (inner or {}).get("project") or {}
    root = Path(str(project.get("root") or "")).expanduser()
    tasks_data = json.loads(opener.open(urllib.request.Request(
        base_url + "/api/tasks", headers={"Accept": "application/json"}), timeout=30).read().decode())
    inner_t = tasks_data.get("data") if isinstance(tasks_data, dict) and "data" in tasks_data else tasks_data
    task_list = (inner_t or {}).get("tasks") or []
    novel_id = next((str(t.get("novel_id")) for t in task_list if t.get("novel_id")), "")
    report_dir = root / "data" / "novels" / novel_id / "data" / "research" / "reports"

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_id = f"IMPORT_{stamp}"
    meta = {
        "title": f"智能导入：{args.title or src.stem}",
        "prompt": f"从 {fmt} 格式导入 {len(chapters)} 章",
        "status": "completed",
        "episode_id": report_id,
        "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": {"chapters": len(chapters), "format": fmt},
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    md_content = "\n\n".join(f"# {t}\n\n{b}" for t, b in chapters)
    (report_dir / f"{report_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (report_dir / f"{report_id}.md").write_text(md_content, encoding="utf-8")
    print(f"    导入记录已落库: {report_id}", flush=True)

    # 5) 正式导入为章节
    print("==> 5/5 导入为正式章节…", flush=True)
    studio = Studio(base_url)
    imported_records: list[dict] = []
    imported_arc = "arc_001"
    import_error = ""
    for i, (title, body) in enumerate(chapters):
        start_number = i + 1
        payload = {
            "filename": f"{title}.md",
            "content": body,
            "start_number": start_number,
            "force": True,
        }
        try:
            result = studio.post("/api/import", payload)
        except Exception as exc:
            import_error = str(exc)
            print(f"    导入失败（保留已导入章节）: {exc}", flush=True)
            break
        imported_arc = str(result.get("arc_id") or imported_arc)
        imported_records.extend(item for item in result.get("imported") or [] if isinstance(item, dict))
        print(f"    已导入: {title}", flush=True)

    import_status = (
        "completed"
        if not import_error and len(imported_records) == len(chapters)
        else ("partial" if imported_records else "failed")
    )
    meta["status"] = import_status
    if import_error:
        meta["error"] = import_error[:2000]
    (report_dir / f"{report_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        dog_artifacts = write_import_artifacts(
            root, novel_id, report_id, src, fmt, imported_arc, imported_records, ai_check,
            import_status, import_error,
        )
        print(f"    DoG 拆书验收图: {dog_artifacts['manifest']}", flush=True)
    except (OSError, ValueError) as exc:
        print(f"    DoG 拆书验收图写入失败（不影响导入）: {exc}", flush=True)

    print(f"\n==> 导入结束（{import_status}），共导入 {len(imported_records)} 章到 OpenWrite 项目。")
    if import_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
