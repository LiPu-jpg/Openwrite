"""openwrite-mcp: OpenWrite 小说引擎的 openJiuwen 原生工具面。

以 MCP server（stdio）形式把 OpenWrite native-core 的领域能力注册进
JiuwenSwarm / openJiuwen Agent 运行时，供创作蜂群的 teammate 原生调用。

启动前设置 OPENWRITE_CORE 指向 OpenWrite native-core 仓库根目录
（包含 tools/ 与 models/ 的检出）。Python 环境需能导入引擎模块
（pydantic、pyyaml 等，jiuwenswarm 虚拟环境即可）。

运行:  python server.py            （stdio，供 mcp.servers 注册）
        python server.py --smoke   （无 MCP 客户端的自检）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

CORE = os.environ.get("OPENWRITE_CORE", "").strip()
if CORE:
    sys.path.insert(0, CORE)

def _engine_ready() -> bool:
    if not CORE:
        return False
    return (Path(CORE) / "tools" / "chapter_assembler.py").is_file()

try:
    if not _engine_ready():
        raise ImportError("OPENWRITE_CORE 未设置或不含 tools/chapter_assembler.py")
    from tools.chapter_assembler import ChapterAssemblerV2
    from tools.foreshadowing_manager import ForeshadowingDAGManager
    from tools.outline_tree import build_outline_structure
    from tools.review_dag_framework import review_dag_framework
    from tools.truth_manager import TruthFilesManager
    _ENGINE_ERROR = None
except Exception as exc:  # 延迟到工具调用时给出友好错误
    _ENGINE_ERROR = str(exc)

from fastmcp import FastMCP

mcp = FastMCP("openwrite")


def _engine_guard() -> None:
    if _ENGINE_ERROR:
        raise RuntimeError(
            "OpenWrite 引擎不可用："
            + _ENGINE_ERROR
            + "。请设置 OPENWRITE_CORE 环境变量指向 native-core 检出根目录。"
        )


def _novel_root(project_root: str, novel_id: str) -> Path:
    return Path(project_root).expanduser().resolve() / "data" / "novels" / novel_id


@mcp.tool()
def list_projects(project_root: str) -> str:
    """列出作品目录下的小说项目及其章级进度。"""
    _engine_guard()
    novels_dir = Path(project_root).expanduser().resolve() / "data" / "novels"
    if not novels_dir.is_dir():
        return json.dumps({"novels": [], "note": "data/novels 不存在：" + str(novels_dir)},
                          ensure_ascii=False)
    novels = []
    for novel_dir in sorted(novels_dir.iterdir()):
        if not novel_dir.is_dir():
            continue
        structure = build_outline_structure(novel_dir)
        counts = structure.get("counts", {})
        novels.append({
            "novel_id": novel_dir.name,
            "chapters_planned": counts.get("chapter", 0),
            "chapters_drafted": structure.get("drafted_chapters", []),
            "next_recommendation": structure.get("recommendation", {}),
        })
    return json.dumps({"novels": novels}, ensure_ascii=False, indent=2)


@mcp.tool()
def get_outline(project_root: str, novel_id: str) -> str:
    """读取作品的分层大纲（卷/幕/节/章树，含已写标记与字数目标）。"""
    _engine_guard()
    structure = build_outline_structure(_novel_root(project_root, novel_id))
    return json.dumps(structure, ensure_ascii=False, indent=2)


@mcp.tool()
def get_context_packet(project_root: str, novel_id: str, chapter_id: str, style_id: str = "") -> str:
    """组装指定章节的 canonical context packet（正文基线/章节记忆/风格指纹/伏笔待办/truth 状态）。

    这是主笔写章与评审员核对的全量上下文，OpenWrite ChapterAssemblerV2 权威输出。
    """
    _engine_guard()
    assembler = ChapterAssemblerV2(
        project_root=Path(project_root).expanduser().resolve(),
        novel_id=novel_id,
        style_id=style_id or novel_id,
    )
    packet = assembler.assemble(chapter_id)
    return packet.to_markdown()


@mcp.tool()
def get_review_framework() -> str:
    """获取六域评审 DAG 蓝图（review-dag-framework.v1）：节点、依赖、评分准则与修订号。

    评审员据此获得与引擎实例化完全一致的拓扑与 rubric，保证蜂群评审与 OpenWrite 评审同构。
    """
    _engine_guard()
    framework = review_dag_framework()
    topology = framework.get("topology", {})
    nodes = topology.get("nodes", {})
    summary = {
        "framework_id": framework.get("id"),
        "version": framework.get("version"),
        "revision": framework.get("revision"),
        "rubric_version": framework.get("rubric_version"),
        "title": framework.get("title"),
        "node_count": len(nodes),
        "edge_count": len(topology.get("contains", [])) + len(topology.get("dependsOn", [])),
        "topology_locked": framework.get("topology_locked"),
        "extension_points": framework.get("extension_points", []),
        "rubric": framework.get("rubric", {}),
        "nodes": nodes,
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


@mcp.tool()
def list_foreshadowing(project_root: str, novel_id: str, status: str = "") -> str:
    """列出伏笔 DAG 节点（可按状态过滤：planted/active/paid_off 等）及 DAG 健康检查。"""
    _engine_guard()
    manager = ForeshadowingDAGManager(
        project_dir=Path(project_root).expanduser().resolve(),
        novel_id=novel_id,
    )
    nodes = manager.get_nodes(status=status or None)
    ok, problems = manager.validate_dag()
    return json.dumps({
        "dag_valid": ok,
        "dag_problems": problems,
        "nodes": [n.__dict__ if hasattr(n, "__dict__") else str(n) for n in nodes],
    }, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def update_foreshadowing_status(project_root: str, novel_id: str, node_id: str, new_status: str) -> str:
    """更新伏笔节点状态（如 planted -> active -> paid_off），写回伏笔 DAG。"""
    _engine_guard()
    manager = ForeshadowingDAGManager(
        project_dir=Path(project_root).expanduser().resolve(),
        novel_id=novel_id,
    )
    changed = manager.update_node_status(node_id, new_status)
    return json.dumps({"updated": changed, "node_id": node_id, "status": new_status},
                      ensure_ascii=False)


@mcp.tool()
def get_truth(project_root: str, novel_id: str) -> str:
    """读取运行态真相文件：world/current_state.md、ledger.md、relationships.md。"""
    _engine_guard()
    manager = TruthFilesManager(
        project_root=Path(project_root).expanduser().resolve(),
        novel_id=novel_id,
    )
    truth = manager.load_truth_files()
    return json.dumps({
        "current_state": getattr(truth, "current_state", ""),
        "ledger": getattr(truth, "ledger", ""),
        "relationships": getattr(truth, "relationships", ""),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def get_chapter_foreshadowing(project_root: str, novel_id: str, chapter_id: str) -> str:
    """查询指定章节关联的伏笔节点（本章应推进/回收的伏笔待办）。"""
    _engine_guard()
    manager = ForeshadowingDAGManager(
        project_dir=Path(project_root).expanduser().resolve(),
        novel_id=novel_id,
    )
    nodes = manager.get_nodes_for_chapter(chapter_id)
    return json.dumps({
        "chapter_id": chapter_id,
        "nodes": [n.__dict__ if hasattr(n, "__dict__") else str(n) for n in nodes],
    }, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# 写路径工具（第三期）：全部经引擎既有确认门，不绕门
# ---------------------------------------------------------------------------

def _result(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def save_external_chapter(
    project_root: str,
    novel_id: str,
    chapter_id: str,
    title: str,
    content: str,
) -> str:
    """把蜂群产出的章节正文写入引擎书稿并自动启动事实接纳流程（agent 源）。

    写入后立即触发 ManuscriptAcceptance 指纹登记；后续事实结算需经
    manuscript_status 查看、accept_manuscript(confirm=true) 显式确认。
    """
    _engine_guard()
    from tools.chapter_pipeline import save_chapter
    root = Path(project_root).expanduser().resolve()
    try:
        path = save_chapter(root, novel_id, chapter_id, title, content)
    except Exception as exc:
        return _result({"ok": False, "code": "SAVE_FAILED", "error": str(exc)})
    return _result({
        "ok": True,
        "chapter_id": chapter_id,
        "path": str(path),
        "chars": len(content),
        "note": "已启动接纳流程；请调 manuscript_status 查看，accept_manuscript 确认",
    })


@mcp.tool()
def manuscript_status(project_root: str, novel_id: str) -> str:
    """查看书稿接纳门状态：逐章指纹、accepted/pending 版本、external_change 标记。"""
    _engine_guard()
    from tools.manuscript_acceptance import ManuscriptAcceptanceService
    root = Path(project_root).expanduser().resolve()
    try:
        state = ManuscriptAcceptanceService(root, novel_id).inspect()
    except Exception as exc:
        return _result({"ok": False, "code": "INSPECT_FAILED", "error": str(exc)})
    return _result({"ok": True, **state})


@mcp.tool()
def accept_manuscript(project_root: str, novel_id: str, chapter_id: str, confirm: bool = False) -> str:
    """确认接纳外部（蜂群）改稿：confirm=false 预览要求，confirm=true 显式生效。

    两阶段门控：先以 confirm=false 调用查看要求，再由人类/作者以
    confirm=true 调用生效；引擎内部做 revision 重验，冲突即拒绝。
    """
    _engine_guard()
    from tools.manuscript_acceptance import (
        ManuscriptAcceptanceError,
        ManuscriptAcceptanceService,
    )
    root = Path(project_root).expanduser().resolve()
    try:
        result = ManuscriptAcceptanceService(root, novel_id).accept_external(
            chapter_id, confirm=confirm
        )
    except ManuscriptAcceptanceError as exc:
        return _result({"ok": False, "code": getattr(exc, "code", "ACCEPT_FAILED"),
                        "error": str(exc), "two_phase": True})
    except Exception as exc:
        return _result({"ok": False, "code": "ACCEPT_FAILED", "error": str(exc)})
    return _result({"ok": True, "chapter_id": chapter_id, "result": result})


@mcp.tool()
async def resume_acceptance(project_root: str, novel_id: str, operation_id: str) -> str:
    """执行接纳操作的事实重建（分析 → 事实重算 → 传播，引擎托管运行时同步执行）。

    完成后各影响域（章节记忆/真相/人物状态/正典/评审/规划）从 stale 转为
    current 或 needs_review；needs_review 的域需经 acknowledge_impacts 复核。
    引擎内部使用 asyncio.run，故在独立线程中执行（MCP 运行时已持有事件循环）。
    """
    _engine_guard()
    from tools.manuscript_acceptance import (
        ManuscriptAcceptanceError,
        ManuscriptAcceptanceService,
    )
    root = Path(project_root).expanduser().resolve()

    def _resume():
        return ManuscriptAcceptanceService(root, novel_id).resume(operation_id)

    try:
        operation = await asyncio.to_thread(_resume)
    except ManuscriptAcceptanceError as exc:
        return _result({"ok": False, "code": getattr(exc, "code", "RESUME_FAILED"),
                        "error": str(exc)})
    except Exception as exc:
        return _result({"ok": False, "code": "RESUME_FAILED", "error": str(exc)})
    return _result({"ok": True, "status": operation.get("status"),
                    "operation_id": operation.get("operation_id"),
                    "impacts": operation.get("impacts")})


@mcp.tool()
def acknowledge_impacts(
    project_root: str,
    novel_id: str,
    operation_id: str,
    domains: str,
    confirm: bool = False,
) -> str:
    """作者复核确认：把 needs_review 的影响域标记为 acknowledged。

    domains 为 JSON 数组字符串；confirm=false 预览要求，confirm=true 生效。
    """
    _engine_guard()
    from tools.manuscript_acceptance import (
        ManuscriptAcceptanceError,
        ManuscriptAcceptanceService,
    )
    root = Path(project_root).expanduser().resolve()
    try:
        parsed = json.loads(domains) if domains.strip() else []
        operation = ManuscriptAcceptanceService(root, novel_id).acknowledge(
            operation_id, domains=parsed, confirm=confirm
        )
    except ManuscriptAcceptanceError as exc:
        return _result({"ok": False, "code": getattr(exc, "code", "ACK_FAILED"),
                        "error": str(exc), "two_phase": True})
    except Exception as exc:
        return _result({"ok": False, "code": "ACK_FAILED", "error": str(exc)})
    return _result({"ok": True, "operation_id": operation_id,
                    "impacts": operation.get("impacts")})


@mcp.tool()
async def write_chapter(
    project_root: str,
    chapter_id: str,
    guidance: str = "",
    target_words: int = 0,
) -> str:
    """引擎原生写章（引擎内部：上下文组装 → 写作 → 事实结算，含全部确认门）。

    需要进程环境提供引擎 LLM 变量（LLM_API_KEY/LLM_BASE_URL/LLM_MODEL）。
    耗时较长（分钟级）；require_current 门会拒绝存在未接纳外部改动的章节。
    引擎内部使用 asyncio.run，故在独立线程中执行（MCP 运行时已持有事件循环）。
    """
    _engine_guard()
    from tools.chapter_pipeline import execute_write_chapter
    root = Path(project_root).expanduser().resolve()
    args = {"chapter_id": chapter_id}
    if guidance.strip():
        args["guidance"] = guidance.strip()
    if int(target_words) > 0:
        args["target_words"] = int(target_words)
    try:
        result = await asyncio.to_thread(execute_write_chapter, root, args)
    except Exception as exc:
        return _result({"ok": False, "code": "WRITE_FAILED", "error": str(exc)})
    return _result(result)


@mcp.tool()
async def review_chapter(
    project_root: str,
    chapter_id: str,
    dimensions: str = "",
) -> str:
    """引擎原生六域评审执行（引擎 review_v2 + canon 门）。

    dimensions 为 JSON 数组字符串（1-37 的整数），空串表示全维度。
    引擎内部使用 asyncio.run，故在独立线程中执行（MCP 运行时已持有事件循环）。
    """
    _engine_guard()
    from tools.chapter_pipeline import execute_review_chapter
    root = Path(project_root).expanduser().resolve()
    args = {"chapter_id": chapter_id}
    if dimensions.strip():
        try:
            parsed = json.loads(dimensions)
        except json.JSONDecodeError:
            return _result({"ok": False, "code": "INVALID_INPUT",
                            "error": "dimensions 必须是 JSON 数组字符串，如 \"[1,2,3]\""})
        args["dimensions"] = parsed
    try:
        result = await asyncio.to_thread(execute_review_chapter, root, args)
    except Exception as exc:
        return _result({"ok": False, "code": "REVIEW_FAILED", "error": str(exc)})
    return _result(result)


@mcp.tool()
def export_book(
    project_root: str,
    novel_id: str,
    output: str,
    title: str = "",
    author: str = "",
) -> str:
    """导出 EPUB 成书（引擎 epub_export，含导出前校验 validate_epub）。"""
    _engine_guard()
    from tools.epub_export import EpubExportError, export_epub, validate_epub
    root = Path(project_root).expanduser().resolve()
    out = Path(output).expanduser()
    try:
        path = export_epub(root, novel_id, out, title=title or novel_id, author=author)
        validation = validate_epub(path)
    except EpubExportError as exc:
        return _result({"ok": False, "code": "EXPORT_FAILED", "error": str(exc)})
    except Exception as exc:
        return _result({"ok": False, "code": "EXPORT_FAILED", "error": str(exc)})
    return _result({"ok": True, "path": str(path), "validation": validation})


@mcp.tool()
def list_revision_proposals(
    project_root: str,
    novel_id: str,
    chapter_id: str = "",
    status: str = "",
) -> str:
    """列出章节修订提案（引擎 RevisionService，proposed/applied/rejected/stale 状态过滤）。"""
    _engine_guard()
    from tools.revision_service import RevisionError, RevisionService
    root = Path(project_root).expanduser().resolve()
    try:
        proposals = RevisionService(root, novel_id).list(
            chapter_id=chapter_id or "", status=status or ""
        )
    except RevisionError as exc:
        return _result({"ok": False, "code": getattr(exc, "code", "LIST_FAILED"),
                        "error": str(exc)})
    except Exception as exc:
        return _result({"ok": False, "code": "LIST_FAILED", "error": str(exc)})
    return _result({"ok": True, "count": len(proposals), "proposals": proposals})


@mcp.tool()
def apply_revision_proposal(
    project_root: str,
    novel_id: str,
    proposal_id: str,
    confirm: bool = False,
) -> str:
    """应用修订提案（两阶段门）：confirm=false 预览提案内容，confirm=true 生效。

    生效时引擎做冲突重验（正文指纹比对）+ 写锁；正文被外部改动过即拒绝。
    """
    _engine_guard()
    from tools.revision_service import RevisionError, RevisionService
    root = Path(project_root).expanduser().resolve()
    svc = RevisionService(root, novel_id)
    try:
        proposal = svc.get(proposal_id)
    except RevisionError as exc:
        return _result({"ok": False, "code": getattr(exc, "code", "GET_FAILED"),
                        "error": str(exc)})
    if not confirm:
        return _result({"ok": True, "two_phase": True, "preview": proposal,
                        "note": "确认后请以 confirm=true 重新调用应用"})
    try:
        result = svc.apply(proposal_id)
    except RevisionError as exc:
        return _result({"ok": False, "code": getattr(exc, "code", "APPLY_FAILED"),
                        "error": str(exc), "two_phase": True})
    except Exception as exc:
        return _result({"ok": False, "code": "APPLY_FAILED", "error": str(exc)})
    return _result({"ok": True, "result": result})


@mcp.tool()
def reject_revision_proposal(project_root: str, novel_id: str, proposal_id: str) -> str:
    """拒绝修订提案（标记 rejected，正文不变）。"""
    _engine_guard()
    from tools.revision_service import RevisionError, RevisionService
    root = Path(project_root).expanduser().resolve()
    try:
        proposal = RevisionService(root, novel_id).reject(proposal_id)
    except RevisionError as exc:
        return _result({"ok": False, "code": getattr(exc, "code", "REJECT_FAILED"),
                        "error": str(exc)})
    except Exception as exc:
        return _result({"ok": False, "code": "REJECT_FAILED", "error": str(exc)})
    return _result({"ok": True, "proposal": proposal})


# ---------------------------------------------------------------------------
# 规划写路径（第三期补齐）：蜂群规划产物写回引擎成为真书
# ---------------------------------------------------------------------------

@mcp.tool()
def create_project(
    project_root: str,
    novel_id: str,
    title: str,
    template: str = "default",
    author: str = "",
) -> str:
    """创建 OpenWrite 书稿项目（引擎 init_project：novel_config + 目录树 + 内容 Git）。

    novel_id 限 2-64 位字母/数字/下划线/连字符；项目已绑定其他 ID 时拒绝。
    """
    _engine_guard()
    from tools.init_project import init_project, validate_novel_id
    root = Path(project_root).expanduser().resolve()
    try:
        validate_novel_id(novel_id)
        result = init_project(root, novel_id, title, template=template, author=author)
    except ValueError as exc:
        return _result({"ok": False, "code": "INVALID_INPUT", "error": str(exc)})
    except Exception as exc:
        return _result({"ok": False, "code": "CREATE_FAILED", "error": str(exc)})
    return _result({"ok": True, "novel_id": novel_id, "title": title,
                    "result": result if isinstance(result, dict) else str(result)})


@mcp.tool()
def save_foundation_draft(
    project_root: str,
    novel_id: str,
    background: str,
    foundation: str,
    volume_outline: str = "",
    current_state: str = "",
    foreshadowing: str = "",
) -> str:
    """保存基础设定草案（背景/人物设定/卷级大纲/真相运行态/伏笔图），确认前不改 canonical。

    foreshadowing 为 YAML 或 JSON 字符串（引擎伏笔图），空串表示不携带。
    """
    _engine_guard()
    from tools.story_planning import StoryPlanningStore
    root = Path(project_root).expanduser().resolve()
    try:
        store = StoryPlanningStore(root, novel_id)
        store.save_foundation_draft(
            background,
            foundation,
            volume_outline=volume_outline,
            current_state=current_state,
            foreshadowing=foreshadowing or None,
        )
    except Exception as exc:
        return _result({"ok": False, "code": "SAVE_FAILED", "error": str(exc)})
    return _result({"ok": True, "novel_id": novel_id,
                    "note": "草案已暂存；promote_foundation(confirm=true) 确认后写入 src/story"})


@mcp.tool()
def promote_foundation(project_root: str, novel_id: str, confirm: bool = False) -> str:
    """确认收口基础设定（两阶段门）：confirm=false 预览，confirm=true 原子写入 src/story。"""
    _engine_guard()
    from tools.story_planning import StoryPlanningStore
    root = Path(project_root).expanduser().resolve()
    store = StoryPlanningStore(root, novel_id)
    if not confirm:
        has_draft = store.background_draft_path.exists() and store.foundation_draft_path.exists()
        return _result({"ok": True, "two_phase": True, "draft_ready": has_draft,
                        "note": "确认后请以 confirm=true 重新调用收口"})
    try:
        ok = store.promote_foundation()
    except Exception as exc:
        return _result({"ok": False, "code": "PROMOTE_FAILED", "error": str(exc)})
    if not ok:
        return _result({"ok": False, "code": "PROMOTE_REJECTED",
                        "error": "草案校验未通过（伏笔图非法或草案缺失），canonical 未修改"})
    return _result({"ok": True, "novel_id": novel_id, "promoted": True})


@mcp.tool()
def save_outline_draft(
    project_root: str,
    novel_id: str,
    content: str,
    mode: str = "generated",
) -> str:
    """保存大纲草案（首版或整版替换草稿）；确认前不改 canonical src/outline.md。"""
    _engine_guard()
    from tools.story_planning import StoryPlanningStore
    root = Path(project_root).expanduser().resolve()
    try:
        store = StoryPlanningStore(root, novel_id)
        store.save_outline_draft(content, mode=mode)
        revision = store.outline_source_revision() if store.outline_src_path.exists() else ""
    except Exception as exc:
        return _result({"ok": False, "code": "SAVE_FAILED", "error": str(exc)})
    return _result({"ok": True, "novel_id": novel_id, "mode": mode,
                    "canonical_revision": revision,
                    "note": "草案已暂存；promote_outline(confirm=true) 确认后写入 canonical"})


@mcp.tool()
def promote_outline(project_root: str, novel_id: str, confirm: bool = False) -> str:
    """确认收口大纲（两阶段门，revision 重验）：confirm=false 预览，confirm=true 原子写入。

    存在分批暂存补丁时要求批次完整且 base/draft revision 均未漂移。
    """
    _engine_guard()
    from tools.story_planning import StoryPlanningStore
    root = Path(project_root).expanduser().resolve()
    store = StoryPlanningStore(root, novel_id)
    if not confirm:
        draft = store.read_outline_draft() if store.outline_draft_path.exists() else ""
        pending = store.pending_outline_edit() if store.outline_edit_state_path.exists() else {}
        return _result({"ok": True, "two_phase": True,
                        "draft_chars": len(draft),
                        "pending_batches": pending.get("batch_count", 0) if isinstance(pending, dict) else 0,
                        "note": "确认后请以 confirm=true 重新调用收口"})
    try:
        ok = store.promote_outline(confirmed=True)
    except Exception as exc:
        return _result({"ok": False, "code": "PROMOTE_FAILED", "error": str(exc)})
    if not ok:
        return _result({"ok": False, "code": "PROMOTE_REJECTED",
                        "error": "revision 冲突或补丁批次不完整，canonical 未修改"})
    return _result({"ok": True, "novel_id": novel_id, "promoted": True,
                    "revision": store.outline_source_revision()})


@mcp.tool()
def stage_outline_edits(
    project_root: str,
    novel_id: str,
    base_revision: str,
    edits: str,
    batch_label: str = "",
    final_batch: bool = True,
) -> str:
    """按 Markdown 章节或精确文本分批暂存大纲补丁（不写 canonical）。

    edits 为 JSON 数组字符串，元素形如
    {"kind": "section", "heading": "...", "content": "..."} 或
    {"kind": "text", "old_text": "...", "new_text": "..."}；
    引擎校验 base_revision，漂移即拒绝（stale_outline_revision）。
    """
    _engine_guard()
    from tools.story_planning import StoryPlanningStore
    root = Path(project_root).expanduser().resolve()
    try:
        parsed_edits = json.loads(edits) if edits.strip() else []
        if not isinstance(parsed_edits, list):
            raise ValueError("edits 必须是 JSON 数组")
    except (json.JSONDecodeError, ValueError) as exc:
        return _result({"ok": False, "code": "INVALID_INPUT", "error": str(exc)})
    try:
        store = StoryPlanningStore(root, novel_id)
        result = store.stage_outline_edits(
            base_revision=base_revision,
            edits=parsed_edits,
            batch_label=batch_label,
            final_batch=final_batch,
        )
    except Exception as exc:
        return _result({"ok": False, "code": "STAGE_FAILED", "error": str(exc)})
    return _result(result if isinstance(result, dict) else {"ok": True, "result": str(result)})


def _smoke() -> int:
    """无 MCP 客户端自检：导入、引擎可用性、蓝图与空项目扫描。"""
    if _ENGINE_ERROR:
        print("SMOKE FAIL: " + _ENGINE_ERROR)
        return 1
    framework = review_dag_framework()
    print("SMOKE OK engine imports")
    print("framework: " + str(framework.get("id"))
          + " v" + str(framework.get("version"))
          + " nodes=" + str(len(framework.get("topology", {}).get("nodes", {}))))
    import asyncio
    tools = asyncio.run(mcp._tool_manager.get_tools())
    print("tools registered: " + ",".join(sorted(tools)))
    return 0


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        sys.exit(_smoke())
    mcp.run()
