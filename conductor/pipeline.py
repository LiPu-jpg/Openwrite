#!/usr/bin/env python3
"""dsh-novel conductor：按大纲连续写章 → 37 维评审 → 低于阈值回炉。

架构（对齐 DESIGN.md 的职责划分，v2 起全部长操作走 OpenWrite 后台任务系统）：

- 确定性循环在本文件；写章/评审/修订回炉都提交为 Studio 托管任务
  （POST /api/tasks → 轮询 GET /api/tasks/{id} → phase 进度 / result / 可取消 /
  recoverable 原生 retry）。同步端点 /api/write、/api/review 仅保留给交互式工具：
  它们把执行期耦合进 HTTP 请求生命周期，客户端超时即孤儿化服务端任务并占住
  项目写锁——这是 v1 在长评审上翻车的根因。托管任务由服务端持有生命周期。
- 创作推理归 OpenWrite 服务端章节流水线（模型路由由 novel_model_* 配置）。
- 回炉走修订闭环：revision_from_review 任务创建提案（客户端先做锚点预过滤，
  镜像 revision_service._resolve_issue_anchor 的唯一引用规则）→ regenerate → apply。
- 可选 --agent-guidance：用 dsh Python SDK 起 bundled 运行时会话，把评审 JSON
  综合成下一轮的改写指导（组合见 cordis.yml；需 DEEPSEEK_API_KEY）。

用法：
    uv sync                       # 或直接用 conductor/.venv
    .venv/bin/python pipeline.py --chapters next --limit 3
    .venv/bin/python pipeline.py --chapters ch_001,ch_002 --threshold 75
    .venv/bin/python pipeline.py --chapters ch_004 --review-only
    .venv/bin/python pipeline.py --chapters next --agent-guidance --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_STUDIO = os.environ.get("OPENWRITE_STUDIO", "http://127.0.0.1:4567")
WRITE_HEADER = "X-OpenWrite-Studio"
HTTP_TIMEOUT = 30.0
POLL_SECONDS = 10.0
# 评审按维度分批调模型，截断时服务端二分重试，最坏可达小时级：预算放宽到 90 分钟。
TASK_BUDGET = {"chapter_write": 2400.0, "chapter_review": 5400.0,
               "revision_from_review": 2400.0}
REGENERATE_TIMEOUT = 2400.0  # regenerate 是同步模型操作
RECOVERABLE_RETRIES = 2


class StudioError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"[{status}/{code}] {message}")
        self.status = status
        self.code = code


class Studio:
    """openwrite-bridge client.ts 的最小 Python 镜像（conductor 所需端点）。"""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        # 本机 Studio 不走系统代理：代理环境变量会劫持 127.0.0.1。
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path: str, *, method: str, body: dict | None,
                 timeout: float) -> dict:
        url = f"{self.base}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
            headers[WRITE_HEADER] = "1"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            code, message = "HTTP_ERROR", detail[:200]
            try:
                err = json.loads(detail)
                code = str(err.get("code") or code)
                message = str(err.get("error") or message)
            except json.JSONDecodeError:
                pass
            raise StudioError(exc.code, code, message) from exc
        except urllib.error.URLError as exc:
            raise StudioError(0, "UNREACHABLE", f"Studio 不可达 {self.base}: {exc.reason}") from exc
        # 部分路由包成功信封 {ok, data}；其余直接返回对象。
        if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
            return payload["data"]
        return payload

    def get(self, path: str, params: dict | None = None) -> dict:
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"
        return self._request(path, method="GET", body=None, timeout=HTTP_TIMEOUT)

    def post(self, path: str, body: dict | None = None,
             timeout: float = HTTP_TIMEOUT) -> dict:
        return self._request(path, method="POST", body=body or {}, timeout=timeout)

    # ── 领域操作 ──────────────────────────────────────────────────────────

    def recommendation(self, chapter: str | None = None) -> dict:
        outline = self.get("/api/outline", {"chapter": chapter} if chapter else None)
        rec = outline.get("recommendation")
        if not isinstance(rec, dict):
            raise StudioError(0, "NO_RECOMMENDATION", "大纲没有可写的章节推荐（可能已全部成稿）")
        return {"rec": rec, "outline_revision": outline.get("revision", "")}

    def document(self, chapter_id: str) -> str:
        """取章节正文。手稿路径含 arc 段（data/manuscript/arc_XXX/ch_NNN.md），
        从 workspace 快照解析真实路径，不假设 arc 编号。"""
        suffix = f"/{chapter_id}.md"
        found: list[str] = []

        def walk(node: object) -> None:
            if isinstance(node, str):
                if node.startswith("data/manuscript/") and node.endswith(suffix):
                    found.append(node)
            elif isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(self.get("/api/workspace"))
        if not found:
            raise StudioError(404, "NO_MANUSCRIPT",
                              f"workspace 中未找到 {chapter_id} 的手稿路径")
        doc = self.get("/api/document", {"path": found[0]})
        return str(doc.get("content") or "")

    def submit(self, task_type: str, input_payload: dict) -> dict:
        return self.post("/api/tasks", {"type": task_type, "input": input_payload})

    def wait_task(self, task_id: str, task_type: str) -> dict:
        """轮询到终态；超预算则取消服务端任务（不留孤儿）。"""
        budget = TASK_BUDGET.get(task_type, 2400.0)
        deadline = time.monotonic() + budget
        last_phase = ""
        while time.monotonic() < deadline:
            payload = self.get(f"/api/tasks/{task_id}")
            task = payload.get("task") or payload
            status = str(task.get("status") or "")
            if status in ("completed", "failed", "cancelled", "interrupted"):
                return task
            phase = str(task.get("phase") or status)
            if phase != last_phase:
                print(f"      {phase}", flush=True)
                last_phase = phase
            time.sleep(POLL_SECONDS)
        try:
            self.post(f"/api/tasks/{task_id}/cancel")
        except StudioError:
            pass
        raise StudioError(0, "TASK_BUDGET_EXCEEDED",
                          f"任务 {task_id} 超出 {budget:.0f}s 预算，已请求取消")

    def run_task(self, task_type: str, input_payload: dict) -> dict:
        """提交任务并等待终态；recoverable 失败走任务系统原生 retry。"""
        task = self.submit(task_type, input_payload)
        task_id = str(task.get("task_id") or "")
        if not task_id:
            raise StudioError(0, "NO_TASK_ID", f"任务提交失败: {str(task)[:150]}")
        for attempt in range(1 + RECOVERABLE_RETRIES):
            finished = self.wait_task(task_id, task_type)
            status = finished.get("status")
            if status == "cancelled":
                raise StudioError(0, "TASK_CANCELLED", f"任务 {task_id} 被取消")
            error = finished.get("error")
            failed = status == "failed" or (isinstance(error, dict) and bool(error))
            if not failed:
                return finished.get("result") or {}
            detail = error.get("message") if isinstance(error, dict) else str(error)
            recoverable = isinstance(error, dict) and bool(error.get("recoverable"))
            if not recoverable or attempt == RECOVERABLE_RETRIES:
                raise StudioError(0, "TASK_FAILED", f"{task_type} 失败: {detail}")
            print(f"    任务可恢复失败（{detail}），原生重试 {attempt + 1}/"
                  f"{RECOVERABLE_RETRIES}…", flush=True)
            self.post(f"/api/tasks/{task_id}/retry")
        raise StudioError(0, "TASK_FAILED", "unreachable")  # pragma: no cover

    def review(self, chapter_id: str) -> dict:
        return self.run_task("chapter_review", {"chapter_id": chapter_id})

    def write(self, chapter_id: str, guidance: str, target_words: int,
              outline_revision: str) -> dict:
        return self.run_task("chapter_write", {
            "chapter_id": chapter_id,
            "guidance": guidance,
            "target_words": target_words,
            "outline_revision": outline_revision,
        })

    def rework(self, chapter_id: str, issue_ids: list[str], instruction: str) -> dict:
        """修订闭环回炉：from-review 提案任务 → 重生成 → 应用。"""
        self.run_task("revision_from_review", {
            "chapter_id": chapter_id,
            "issue_ids": issue_ids,
            "instruction": instruction,
        })
        proposals = self.get("/api/revisions", {"chapter_id": chapter_id})
        items = proposals.get("proposals") or proposals.get("items") or []
        pending = next((p for p in items if str(p.get("status") or "")
                        not in ("applied", "rejected")), None)
        if pending:
            # regenerate 会派生新提案（旧的转 rejected，新的转 proposed）。
            self.post(f"/api/revisions/{pending['proposal_id']}/regenerate",
                      timeout=REGENERATE_TIMEOUT)
            proposals = self.get("/api/revisions", {"chapter_id": chapter_id})
            items = proposals.get("proposals") or proposals.get("items") or []
        proposed = [p for p in items if str(p.get("status") or "") == "proposed"]
        if not proposed:
            raise StudioError(0, "NO_PROPOSAL", "未找到待应用的修订提案")
        return self.post(f"/api/revisions/{proposed[0]['proposal_id']}/apply")


def guidance_from_issues(review: dict) -> str:
    """评审问题 → 确定性改写指导（无 agent 模式的回炉依据）。"""
    lines: list[str] = []
    for issue in review.get("issue_details") or []:
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity") or "medium")
        if severity == "low":
            continue
        dim = str(issue.get("dimension") or "general")
        summary = str(issue.get("summary") or "").strip()
        suggestion = str(issue.get("suggestion") or "").strip()
        line = f"[{severity}] {dim}: {summary}"
        if suggestion:
            line += f" → {suggestion}"
        lines.append(line[:300])
    return "\n".join(lines[:12])


def agent_guidance(review: dict, session_root: Path) -> str:
    """SDK bundled 会话把评审 JSON 综合成改写指导（--agent-guidance）。"""
    from deepseek_harness import DeepSeekHarness

    config_path = Path(__file__).with_name("cordis.yml").resolve()
    workspace = Path(__file__).resolve().parent
    prompt = (
        "以下是本章评审 JSON，请按要求输出改写指导：\n"
        + json.dumps(
            {k: review.get(k) for k in ("score", "passed", "issues", "issue_details", "summary")},
            ensure_ascii=False,
        )
    )
    with DeepSeekHarness(
        cwd=str(workspace),
        session_root=str(session_root),
        cordis=str(config_path),
    ) as harness:
        result = harness.run(prompt)
    return result.final_response.strip()


def anchored_ids(candidates: list[dict], content: str) -> list[str]:
    """锚点预过滤（镜像 revision_service._resolve_issue_anchor：
    evidence.quote 须在正文中唯一出现），避免 from-review 全有全无 400。"""
    ids: list[str] = []
    for issue in candidates:
        quote = str((issue.get("evidence") or {}).get("quote") or "")
        if not quote:
            continue
        first = content.find(quote)
        if first >= 0 and content.find(quote, first + 1) < 0:
            ids.append(str(issue["id"]))
    return ids


def review_gate(review: dict, threshold: int) -> bool:
    score = int(review.get("score") or 0)
    has_blocker = any(
        isinstance(i, dict) and str(i.get("severity")) == "blocker"
        for i in review.get("issue_details") or []
    )
    return score >= threshold and not has_blocker


def run_chapter(studio: Studio, chapter: str | None, args, session_root: Path) -> dict:
    """写一章并回炉至达标；返回结果记录。review_only 模式只评不写。"""
    started = time.monotonic()
    info = studio.recommendation(chapter)
    rec, outline_revision = info["rec"], info["outline_revision"]
    chapter_id = str(rec["chapter_id"])
    drafted = rec.get("status") == "drafted"

    if drafted and not args.review_only and not args.rework:
        return {"chapter": chapter_id, "title": rec.get("title", ""), "skipped": "已成形"}

    base_guidance = str(rec.get("guidance") or "")
    target_words = args.target_words or int(rec.get("target_words") or 3000)
    attempts: list[dict] = []
    final: dict = {}
    words: object = "?"

    for attempt in range(1 if args.review_only else 1 + args.max_retries):
        guidance = base_guidance
        prev_review = attempts[-1]["review"] if attempts else None
        if attempt == 0 and not drafted:
            print(f"    写章（目标 {target_words} 字）…", flush=True)
            write_result = studio.write(chapter_id, guidance, target_words,
                                        outline_revision)
            words = write_result.get("word_count", "?")
            print(f"    成稿 {words} 字，评审中…", flush=True)
        elif attempt > 0:
            mode = "agent" if args.agent_guidance else "rules"
            print(f"    修订回炉 #{attempt}（指导来源: {mode}）…", flush=True)
            guidance = base_guidance + "\n\n上一轮评审问题与修改方向：\n" + (
                agent_guidance(prev_review, session_root)
                if args.agent_guidance else guidance_from_issues(prev_review)
            )
            candidates = [
                i for i in prev_review.get("issue_details") or []
                if isinstance(i, dict) and i.get("id") and str(i.get("severity")) != "low"
            ]
            content = studio.document(chapter_id)
            issue_ids = anchored_ids(candidates, content)
            if not issue_ids:
                # 评审引用在正文中无可定位锚点（多为模型幻觉引用）：
                # 修订通道无法工作，如实保留未达标结果，不硬塞导致 400。
                print("    评审问题均无可定位正文锚点，跳过修订回炉（需人工处理）",
                      flush=True)
                break
            studio.rework(chapter_id, issue_ids, guidance)
            print("    修订已应用，复评中…", flush=True)

        review = studio.review(chapter_id)
        passed = review_gate(review, args.threshold)
        attempts.append({"score": review.get("score"), "passed": passed, "review": review})
        print(f"    评分 {review.get('score')}（阈值 {args.threshold}）→ "
              f"{'通过' if passed else '未达标'}", flush=True)
        final = {"score": review.get("score"), "passed": passed}
        if passed:
            break

    return {
        "chapter": chapter_id,
        "title": str(rec.get("title") or ""),
        "words": words,
        "score": final.get("score"),
        "passed": final.get("passed"),
        "attempts": len(attempts),
        "seconds": round(time.monotonic() - started, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chapters", default="next",
                        help="章节 id 逗号列表（ch_001）或 'next'（跟随大纲推荐）")
    parser.add_argument("--limit", type=int, default=1, help="'next' 模式最多写几章")
    parser.add_argument("--threshold", type=int, default=70, help="评审达标分数（默认 70）")
    parser.add_argument("--max-retries", type=int, default=1, help="未达标回炉次数（默认 1）")
    parser.add_argument("--target-words", type=int, default=None, help="覆盖目标字数（默认取大纲）")
    parser.add_argument("--studio", default=DEFAULT_STUDIO, help="Studio 地址")
    parser.add_argument("--agent-guidance", action="store_true",
                        help="回炉指导用 dsh SDK 会话综合（需 DEEPSEEK_API_KEY）")
    parser.add_argument("--review-only", action="store_true",
                        help="对已成稿章节只跑评审门（不写章）")
    parser.add_argument("--rework", action="store_true",
                        help="对已成稿章节强制回炉：基线评审 → 修订闭环 → 复评")
    parser.add_argument("--dry-run", action="store_true", help="只解析推荐与计划，不写章")
    args = parser.parse_args()

    studio = Studio(args.studio)
    session_root = Path(__file__).parent / ".sessions"

    if args.chapters.strip().lower() == "next":
        queue: list[str | None] = [None] * max(1, args.limit)
    else:
        queue = [c.strip() or None for c in args.chapters.split(",")]

    mode = "仅评审" if args.review_only else "写+评"
    print(f"==> 计划 {len(queue)} 章（{mode}） · 阈值 {args.threshold} · "
          f"回炉 ≤{args.max_retries} · 指导 {'agent' if args.agent_guidance else 'rules'}")
    results = []
    for i, chapter in enumerate(queue, 1):
        info = studio.recommendation(chapter)
        rec = info["rec"]
        print(f"[{i}/{len(queue)}] {rec['chapter_id']} {rec.get('title', '')}"
              f"（status={rec.get('status')}）", flush=True)
        if args.dry_run:
            continue
        try:
            results.append(run_chapter(studio, chapter, args, session_root))
        except StudioError as exc:
            print(f"    章节失败：{exc}", flush=True)
            results.append({"chapter": rec["chapter_id"], "title": rec.get("title", ""),
                            "error": str(exc), "passed": False})

    if args.dry_run:
        print("==> dry-run 完成，未写入任何内容")
        return 0

    print("\n==> 结果汇总")
    failed = 0
    for r in results:
        if r.get("skipped"):
            print(f"  SKIP  {r['chapter']} {r['title']}（{r['skipped']}）")
            continue
        mark = "PASS" if r["passed"] else "FAIL"
        if not r["passed"]:
            failed += 1
        if r.get("error"):
            print(f"  {mark}  {r['chapter']} {r['title']}  错误 {r['error']}")
            continue
        print(f"  {mark}  {r['chapter']} {r['title']}  评分 {r['score']}"
              f"  {r['words']} 字  {r['attempts']} 次尝试  {r['seconds']}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
