"""OpenWrite CLI - 命令行接口

用法:
    openwrite init <novel_id>     # 初始化项目
    openwrite sync                # 同步 src -> data
    openwrite write <chapter>     # 写章节
    openwrite review <chapter>    # 审查章节
    openwrite context <chapter>   # 构建上下文
    openwrite style extract       # 提取风格
    openwrite status             # 查看状态
    openwrite --help            # 显示帮助
"""

import argparse
import json
import logging
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import yaml

from tools.context_schema import normalize_truth_file_key
from tools.source_sync import (
    collect_sync_status as _shared_collect_sync_status,
)
from tools.source_sync import (
    run_sync as _shared_run_sync,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """CLI 主入口"""
    from tools.version import __version__

    parser = argparse.ArgumentParser(
        prog="openwrite",
        description="OpenWrite 长篇小说创作引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"OpenWrite {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    _add_init_command(subparsers)
    _add_goethe_command(subparsers)
    _add_dante_command(subparsers)
    _add_sync_command(subparsers)
    _add_write_command(subparsers)
    _add_multi_write_command(subparsers)
    _add_review_command(subparsers)
    _add_context_command(subparsers)
    _add_assemble_command(subparsers)
    _add_style_command(subparsers)
    _add_setting_command(subparsers)
    _add_source_command(subparsers)
    _add_skill_command(subparsers)
    _add_rule_command(subparsers)
    _add_run_command(subparsers)
    _add_diagnose_command(subparsers)
    _add_planning_command(subparsers)
    _add_version_command(subparsers)
    _add_annotation_command(subparsers)
    _add_radar_command(subparsers)
    _add_status_command(subparsers)
    _add_focus_command(subparsers)
    _add_import_command(subparsers)
    _add_export_command(subparsers)
    _add_asset_command(subparsers)
    _add_desk_command(subparsers)
    _add_studio_command(subparsers)
    _add_doctor_command(subparsers)
    _add_agent_command(subparsers)
    _add_project_arguments(subparsers)

    args = parser.parse_args()

    if not args.command:
        if (Path.cwd() / "novel_config.yaml").exists():
            return _cmd_desk(argparse.Namespace(json=False))
        parser.print_help()
        return 0

    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        logger.info("操作已取消")
        return 130
    except Exception as e:
        logger.error(f"错误: {e}")
        return 1


def _dispatch(args) -> int:
    """Resolve an optional project root, then dispatch one CLI command."""

    raw_project = str(getattr(args, "project", "") or "").strip()
    if not raw_project or args.command == "studio":
        return _dispatch_in_project(args)

    project_root = Path(raw_project).expanduser().resolve()
    if args.command == "init":
        project_root.mkdir(parents=True, exist_ok=True)
    elif not project_root.is_dir():
        logger.error(f"作品项目目录不存在: {project_root}")
        return 1

    args.project = str(project_root)
    previous_root = Path.cwd()
    try:
        os.chdir(project_root)
        return _dispatch_in_project(args)
    finally:
        os.chdir(previous_root)


def _dispatch_in_project(args) -> int:
    """Dispatch after the process is positioned at the selected project."""

    if args.command == "init":
        return _cmd_init(args)
    elif args.command == "sync":
        return _cmd_sync(args)
    elif args.command == "write":
        return _cmd_write(args)
    elif args.command == "multi-write":
        return _cmd_multi_write(args)
    elif args.command == "review":
        return _cmd_review(args)
    elif args.command == "context":
        return _cmd_context(args)
    elif args.command == "assemble":
        return _cmd_assemble(args)
    elif args.command == "style":
        return _cmd_style(args)
    elif args.command == "setting":
        return _cmd_setting(args)
    elif args.command == "source":
        return _cmd_source(args)
    elif args.command == "skill":
        return _cmd_skill(args)
    elif args.command == "rule":
        return _cmd_rule(args)
    elif args.command == "run":
        return _cmd_run(args)
    elif args.command == "diagnose":
        return _cmd_diagnose(args)
    elif args.command == "planning":
        return _cmd_planning(args)
    elif args.command == "version":
        return _cmd_version(args)
    elif args.command == "annotation":
        return _cmd_annotation(args)
    elif args.command == "radar":
        return _cmd_radar(args)
    elif args.command == "goethe":
        return _cmd_goethe(args)
    elif args.command == "dante":
        return _cmd_dante(args)
    elif args.command == "status":
        return _cmd_status(args)
    elif args.command == "focus":
        return _cmd_focus(args)
    elif args.command == "import":
        return _cmd_import(args)
    elif args.command == "export":
        return _cmd_export(args)
    elif args.command == "asset":
        return _cmd_asset(args)
    elif args.command == "desk":
        return _cmd_desk(args)
    elif args.command == "studio":
        return _cmd_studio(args)
    elif args.command == "doctor":
        return _cmd_doctor(args)
    elif args.command == "agent":
        return _cmd_agent(args)
    else:
        logger.error(f"未知命令: {args.command}")
        return 1


def _add_project_arguments(subparsers) -> None:
    """Expose one project selector consistently on every top-level command."""

    for command_parser in subparsers.choices.values():
        if "--project" in command_parser._option_string_actions:
            continue
        command_parser.add_argument(
            "--project",
            help="作品项目目录；省略时使用当前目录",
        )


def _add_init_command(subparsers):
    """init 命令"""
    p = subparsers.add_parser("init", help="初始化新项目")
    p.add_argument("novel_id", help="小说 ID")
    p.add_argument("--title", default="", help="小说标题（可选）")
    p.add_argument(
        "--template",
        "-t",
        default="default",
        help="模板：default 或 demo_short（带示范资产）",
    )


def _add_goethe_command(subparsers):
    """goethe 命令 - 长期会话规划入口"""
    p = subparsers.add_parser(
        "goethe",
        help="长期会话规划入口：启动 Goethe 持续规划 shell",
        description="长期会话规划入口：启动 Goethe 持续规划 shell。",
    )
    p.add_argument("--novel-id", help="小说 ID（默认从 novel_config.yaml 读取）")


def _add_dante_command(subparsers):
    """dante 命令 - 长期会话主入口"""
    subparsers.add_parser(
        "dante",
        help="长期会话主入口：启动 Dante 持续对话 shell",
        description="长期会话主入口：启动 Dante 持续对话 shell。",
    )


def _add_sync_command(subparsers):
    """sync 命令"""
    p = subparsers.add_parser("sync", help="同步 src 到 data（大纲/角色）")
    p.add_argument("--novel-id", help="小说 ID（默认从 novel_config.yaml 读取）")
    p.add_argument("--check", action="store_true", help="仅检查是否存在未同步变更")
    p.add_argument("--json", action="store_true", help="输出 JSON 结果（便于脚本/Agent 解析）")


def _add_write_command(subparsers):
    """write 命令"""
    p = subparsers.add_parser("write", help="写章节")
    p.add_argument("chapter", nargs="?", default="next", help="章节 ID 或 'next'")
    p.add_argument("--no-review", action="store_true", help="跳过审查")
    p.add_argument("--temperature", "-T", type=float, default=0.7, help="写作温度")
    p.add_argument("--resume-run", help="从指定 Chapter Run V2 的安全阶段恢复")


def _add_multi_write_command(subparsers):
    """multi-write 命令"""
    p = subparsers.add_parser("multi-write", help="使用多 Agent 编排写章节")
    p.add_argument("chapter", nargs="?", default="next", help="章节 ID 或 'next'")
    p.add_argument("--temperature", "-T", type=float, default=0.7, help="写作温度")
    p.add_argument("--no-review", action="store_true", help="跳过审查")
    p.add_argument("--strict", action="store_true", help="严格审稿（警告也不通过）")
    p.add_argument(
        "--dimensions",
        nargs="+",
        type=int,
        help="仅审查指定维度（1-37）",
    )
    p.add_argument("--target-words", type=int, default=0, help="临时目标字数")
    p.add_argument("--guidance", default="", help="本次额外写作要求")
    p.add_argument("--show-packet", action="store_true", help="先输出组装包")
    p.add_argument("--packet-output-dir", help="组装包测试输出目录（自动命名）")


def _add_review_command(subparsers):
    """review 命令"""
    p = subparsers.add_parser("review", help="审查章节")
    p.add_argument("chapter", nargs="?", default="latest", help="章节 ID 或 'latest'")
    p.add_argument("--strict", action="store_true", help="严格模式")


def _add_context_command(subparsers):
    """context 命令"""
    p = subparsers.add_parser("context", help="构建上下文")
    p.add_argument("chapter", nargs="?", default="next", help="章节 ID")
    p.add_argument("--show", action="store_true", help="显示上下文内容")
    p.add_argument(
        "--agent",
        choices=["canonical", "writer", "reviewer", "dante", "goethe"],
        default="canonical",
        help="检查指定 Agent 的实际首轮输入（默认 canonical）",
    )
    p.add_argument("--instruction", default="", help="Dante/Goethe 的首轮用户指令")
    p.add_argument("--guidance", default="", help="Writer 的额外写作要求")
    p.add_argument("--target-words", type=int, default=0, help="Writer 临时目标字数")
    p.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="检查结果格式",
    )
    p.add_argument("--output", "-o", help="将完整检查结果写入文件")


def _add_assemble_command(subparsers):
    """assemble 命令"""
    p = subparsers.add_parser("assemble", help="按 V2 规则组装章节上下文包")
    p.add_argument("chapter", nargs="?", default="next", help="章节 ID 或 'next'")
    p.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="输出格式（默认 markdown）",
    )
    p.add_argument("--output", "-o", help="输出文件路径")
    p.add_argument("--output-dir", help="测试输出目录（自动命名文件）")
    p.add_argument("--no-print", action="store_true", help="不在终端打印结果")


def _add_style_command(subparsers):
    """style 命令"""
    p = subparsers.add_parser("style", help="风格管理")
    sub = p.add_subparsers(dest="style_action")

    extract = sub.add_parser("extract", help="从用户提供文本提取风格与设定")
    extract.add_argument(
        "source_id",
        help="来源 ID（写入 data/novels/{id}/data/sources/{source_id}/）",
    )
    extract.add_argument("--source", required=True, help="源文本路径")
    extract.add_argument("--chunk-size", type=int, default=30000, help="分块字数（默认30000）")

    synthesize = sub.add_parser("synthesize", help="合成风格")
    synthesize.add_argument("--novel-id", default="current", help="小说 ID")


def _add_setting_command(subparsers):
    """setting 命令"""
    p = subparsers.add_parser("setting", help="设定来源管理")
    sub = p.add_subparsers(dest="setting_action")

    extract = sub.add_parser("extract", help="从用户提供文本提取设定与世界信息")
    extract.add_argument(
        "source_id",
        help="来源 ID（写入 data/novels/{id}/data/sources/{source_id}/）",
    )
    extract.add_argument("--source", required=True, help="源文本路径")
    extract.add_argument("--chunk-size", type=int, default=30000, help="分块字数（默认30000）")


def _add_source_command(subparsers):
    """source 命令"""
    p = subparsers.add_parser("source", help="来源文本 source pack 管理")
    sub = p.add_subparsers(dest="source_action")

    analyze = sub.add_parser("analyze", help="执行证据化 Source Analysis V2")
    analyze.add_argument("source_id", help="来源 ID")
    analyze.add_argument("--source", required=True, help="源文本路径")
    analyze.add_argument(
        "--focus",
        nargs="+",
        choices=[
            "promise",
            "structure",
            "character",
            "world",
            "relationship",
            "progression",
            "timeline",
            "conflict",
            "hook",
            "thread",
            "arc_summary",
            "chapter_summary",
            "pacing",
            "voice",
            "reader_drive",
            "method",
            "risk",
        ],
        default=None,
        help="分析重点；默认覆盖全部维度",
    )
    analyze.add_argument(
        "--input-budget",
        type=int,
        default=12000,
        help="每个分块的保守输入 token 预算",
    )
    analyze.add_argument("--novel-id", default="current", help="小说 ID")

    status = sub.add_parser("status", help="查看 Source Analysis V2 状态")
    status.add_argument("source_id", help="来源 ID")
    status.add_argument("--novel-id", default="current", help="小说 ID")

    retry = sub.add_parser("retry", help="重试一个失败或过时分块")
    retry.add_argument("source_id", help="来源 ID")
    retry.add_argument("chunk_id", help="分块 ID")
    retry.add_argument("--novel-id", default="current", help="小说 ID")

    synthesize = sub.add_parser("synthesize", help="综合多个完整 V2 来源")
    synthesize.add_argument("source_ids", nargs="+", help="来源 ID 列表")
    synthesize.add_argument("--novel-id", default="current", help="小说 ID")

    profile = sub.add_parser("profile", help="查看参考方法画像")
    profile_sub = profile.add_subparsers(dest="source_profile_action")
    profile_show = profile_sub.add_parser("show", help="显示画像 JSON")
    profile_show.add_argument("profile_id", help="画像 ID")
    profile_show.add_argument("--novel-id", default="current", help="小说 ID")

    promotion_preview = sub.add_parser(
        "promotion-preview", help="生成可确认的晋升 diff"
    )
    promotion_preview.add_argument("profile_id", help="画像 ID")
    promotion_preview.add_argument(
        "--target",
        choices=["style", "rules", "inspiration", "setting_candidates"],
        required=True,
    )
    promotion_preview.add_argument("--novel-id", default="current", help="小说 ID")

    review = sub.add_parser("review", help="审阅提取后的 source pack")
    review.add_argument("source_id", help="来源 ID")
    review.add_argument(
        "--novel-id",
        default="current",
        help="小说 ID（默认从 novel_config.yaml 读取）",
    )

    promote = sub.add_parser("promote", help="将 source pack 晋升到当前项目")
    promote.add_argument("identifier", help="V1 来源 ID 或 V2 promotion_ 预览 ID")
    promote.add_argument(
        "--novel-id",
        default="current",
        help="小说 ID（默认从 novel_config.yaml 读取）",
    )
    promote.add_argument(
        "--target",
        choices=["style", "setting", "world", "all"],
        default="all",
        help="晋升目标",
    )
    promote.add_argument(
        "--confirm",
        action="store_true",
        help="确认并应用 V2 晋升预览；V1 晋升不使用此参数",
    )


def _add_radar_command(subparsers):
    """radar 命令 - 市场分析"""
    p = subparsers.add_parser("radar", help="市场趋势分析")
    p.add_argument("--platform", "-p", nargs="+", help="平台列表（默认全部）")
    p.add_argument("--top", "-n", type=int, default=5, help="每个平台推荐数")
    p.add_argument("--output", "-o", help="保存结果到文件")


def _add_skill_command(subparsers):
    """Runtime Skill inspection and resolution."""
    parser = subparsers.add_parser("skill", help="查看 Runtime Skill 与权限解析")
    sub = parser.add_subparsers(dest="skill_action")
    sub.add_parser("list", help="列出三层合并后的 Runtime Skill")
    resolve = sub.add_parser("resolve", help="解析一次 Agent Runtime Skill")
    resolve.add_argument(
        "--agent",
        choices=["dante", "goethe", "writer", "reviewer", "cli", "studio"],
        required=True,
    )
    resolve.add_argument("--task", default="")
    resolve.add_argument("--intent", default="")
    resolve.add_argument("--document-type", default="")
    resolve.add_argument("--skill", action="append", default=[])
    sub.add_parser("diagnose", help="检查坏 manifest、依赖和冲突")


def _add_rule_command(subparsers):
    """Project Rule preview and confirmation."""
    parser = subparsers.add_parser("rule", help="编译项目级声明式规则")
    sub = parser.add_subparsers(dest="rule_action")
    sub.add_parser("preview", help="生成规则 diff，不启用")
    apply = sub.add_parser("apply", help="确认并启用规则预览")
    apply.add_argument("preview_id")
    apply.add_argument("--confirm", action="store_true")
    sub.add_parser("status", help="查看当前已确认规则")


def _add_run_command(subparsers):
    """Chapter Run V2 inspection and intervention."""
    parser = subparsers.add_parser("run", help="查看 Chapter Run V2 与管理干预")
    sub = parser.add_subparsers(dest="run_action")
    listing = sub.add_parser("list", help="列出 Chapter Run V2")
    listing.add_argument("--chapter-id", default="")
    listing.add_argument("--status", action="append", default=[])
    listing.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show", help="显示一个 Chapter Run V2")
    show.add_argument("run_id")
    intervene = sub.add_parser("intervene", help="记录一个创作干预")
    intervene.add_argument("run_id")
    intervene.add_argument("revision")
    intervene.add_argument("request")
    intervene.add_argument(
        "--scope", choices=["project", "arc", "chapter", "asset"], default="chapter"
    )
    intervene.add_argument(
        "--risk", choices=["low", "medium", "high", "blocker"], default="medium"
    )
    intervene.add_argument("--affected-item", action="append", default=[])
    intervene.add_argument("--rewrite-required", action="store_true")
    transition = sub.add_parser("transition", help="推进干预状态")
    transition.add_argument("run_id")
    transition.add_argument("revision")
    transition.add_argument("intervention_id")
    transition.add_argument("state")
    transition.add_argument("--facts-revision")
    transition.add_argument("--impact", action="append", default=[])
    transition.add_argument("--proposal")
    transition.add_argument("--confirm", action="store_true")
    cancel = sub.add_parser("cancel", help="取消 Chapter Run V2")
    cancel.add_argument("run_id")
    cancel.add_argument("revision")
    cancel.add_argument("--reason", default="user_cancelled")


def _add_diagnose_command(subparsers):
    parser = subparsers.add_parser("diagnose", help="运行统一项目诊断")
    parser.add_argument("--stuck-minutes", type=int, default=30)


def _add_planning_command(subparsers):
    parser = subparsers.add_parser("planning", help="管理 revision 绑定的滚动规划候选")
    sub = parser.add_subparsers(dest="planning_action")
    listing = sub.add_parser("list")
    listing.add_argument("--limit", type=int, default=20)
    create = sub.add_parser("create")
    create.add_argument("--current-arc", default="")
    create.add_argument("--window-size", type=int, default=50)
    show = sub.add_parser("show")
    show.add_argument("candidate_id")
    stage = sub.add_parser("stage")
    stage.add_argument("candidate_id")
    stage.add_argument("revision")
    stage.add_argument("proposal_file")


def _add_version_command(subparsers):
    parser = subparsers.add_parser("version", help="管理正文 checkpoint")
    sub = parser.add_subparsers(dest="version_action")
    listing = sub.add_parser("list", help="列出一章的正文版本")
    listing.add_argument("chapter_id")
    show = sub.add_parser("show", help="读取一个正文版本")
    show.add_argument("chapter_id")
    show.add_argument("version_id")
    checkpoint = sub.add_parser("checkpoint", help="手动创建正文 checkpoint")
    checkpoint.add_argument("chapter_id")
    checkpoint.add_argument("--label", default="")
    restore = sub.add_parser("restore", help="恢复正文版本并自动备份当前正文")
    restore.add_argument("chapter_id")
    restore.add_argument("version_id")
    restore.add_argument("revision", help="当前正文 sha256 revision")
    restore.add_argument("--confirm", action="store_true")


def _add_annotation_command(subparsers):
    parser = subparsers.add_parser("annotation", help="管理 revision 绑定的正文批注")
    sub = parser.add_subparsers(dest="annotation_action")
    listing = sub.add_parser("list", help="列出一章的批注")
    listing.add_argument("chapter_id")
    create = sub.add_parser("create", help="为当前正文字符区间创建批注")
    create.add_argument("chapter_id")
    create.add_argument("revision", help="当前正文 sha256 revision")
    create.add_argument("start", type=int)
    create.add_argument("end", type=int)
    create.add_argument("note")
    resolve = sub.add_parser("resolve", help="将批注标记为完成")
    resolve.add_argument("chapter_id")
    resolve.add_argument("annotation_id")


def _add_status_command(subparsers):
    """status 命令"""
    p = subparsers.add_parser("status", help="查看项目状态")
    p.add_argument("--json", action="store_true", help="输出结构化 JSON")


def _add_focus_command(subparsers):
    """focus 命令 - 管理近期创作罗盘。"""
    p = subparsers.add_parser("focus", help="查看或设置近期创作罗盘")
    sub = p.add_subparsers(dest="focus_action")
    sub.add_parser("show", help="显示当前创作罗盘")
    set_cmd = sub.add_parser("set", help="设置当前阶段目标与硬约束")
    set_cmd.add_argument("goal", help="当前阶段最重要的叙事目标")
    set_cmd.add_argument("--keep", action="append", default=[], help="必须保留，可重复")
    set_cmd.add_argument("--avoid", action="append", default=[], help="必须避免，可重复")
    set_cmd.add_argument("--note", action="append", default=[], help="写作备注，可重复")
    sub.add_parser("clear", help="清空近期创作罗盘")


def _add_import_command(subparsers):
    """import 命令 - 导入已有小说正文。"""
    p = subparsers.add_parser("import", help="从 TXT/Markdown 导入已有小说章节")
    p.add_argument("source", help="源文件路径")
    p.add_argument("--arc", help="导入到指定篇，默认使用 current_arc")
    p.add_argument("--start", type=int, help="指定起始章节号；默认追加到现有正文后")
    p.add_argument("--force", action="store_true", help="允许覆盖同名目标章节")


def _add_export_command(subparsers):
    """export 命令 - 导出整书。"""
    p = subparsers.add_parser("export", help="按章节顺序导出整书")
    p.add_argument(
        "--format", choices=["md", "txt", "epub"], default="md", help="导出格式"
    )
    p.add_argument("--output", "-o", help="输出路径")
    p.add_argument("--title", help="覆盖导出书名")
    p.add_argument("--author", default="", help="EPUB 作者")
    p.add_argument("--language", default="zh-CN", help="EPUB 语言")
    p.add_argument("--cover", help="项目目录内的 EPUB 封面图片")


def _add_asset_command(subparsers):
    """asset 命令 - 结构化资产与 OpenWrite Asset Package。"""
    parser = subparsers.add_parser("asset", help="管理结构化资产与跨项目资产包")
    commands = parser.add_subparsers(dest="asset_action")
    list_cmd = commands.add_parser("list", help="列出可导出的资产")
    list_cmd.add_argument("--kind", choices=["character", "world", "progression"])
    list_cmd.add_argument("--json", action="store_true")
    export_cmd = commands.add_parser("export", help="导出 .owasset.zip")
    export_cmd.add_argument("output")
    export_cmd.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="KIND:ID",
        help="选择资产，可重复；省略时导出全部",
    )
    preview_cmd = commands.add_parser("preview", help="校验并预览资产包")
    preview_cmd.add_argument("package")
    preview_cmd.add_argument("--json", action="store_true")
    import_cmd = commands.add_parser("import", help="预览或明确应用资产包")
    import_cmd.add_argument("package")
    import_cmd.add_argument("--apply", action="store_true", help="确认执行导入")
    import_cmd.add_argument("--replace", action="append", default=[], metavar="ID")
    import_cmd.add_argument("--rename", action="append", default=[], metavar="OLD:NEW")
    import_cmd.add_argument("--skip", action="append", default=[], metavar="ID")
    import_cmd.add_argument("--allow-missing-dependencies", action="store_true")
    import_cmd.add_argument("--json", action="store_true")


def _add_desk_command(subparsers):
    """desk 命令 - 小说工作台。"""
    p = subparsers.add_parser("desk", help="打开小说专用终端工作台")
    p.add_argument("--json", action="store_true", help="输出结构化 JSON")


def _add_studio_command(subparsers):
    """studio 命令 - 本地 Web 小说工作台。"""
    p = subparsers.add_parser("studio", help="启动本地 Web 小说工作台")
    p.add_argument("--port", "-p", type=int, default=4567, help="监听端口（默认 4567）")
    p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    p.add_argument("--project", help="作品项目目录；可与框架代码目录分离")
    p.add_argument("--debug", action="store_true", help="启用 Studio 后台 debug 日志")


def _add_doctor_command(subparsers):
    """doctor 命令"""
    subparsers.add_parser("doctor", help="环境与路径自检")


def _add_agent_command(subparsers):
    """agent 命令 - 已退役"""
    subparsers.add_parser(
        "agent",
        help="已退役：请改用 openwrite dante",
        description="已退役：请改用 openwrite dante",
    )


def _cmd_init(args) -> int:
    """初始化项目"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    novel_id = args.novel_id
    project_root = Path.cwd()
    title = str(getattr(args, "title", "") or "").strip() or None
    template = str(getattr(args, "template", "default") or "default").strip()

    logger.info(f"初始化项目: {novel_id}")
    if template not in {"default", "demo_short"}:
        logger.warning("未知模板，将按 default 处理。")
        template = "default"

    try:
        NovelApplicationService.initialize(
            project_root, novel_id, title, template=template
        )
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1
    return 0


def _cmd_write(args) -> int:
    """写章节"""
    project_root = Path.cwd()
    from tools.novel_service import NovelApplicationService, NovelServiceError

    service = None
    chapter = str(args.chapter)
    try:
        service = NovelApplicationService(project_root)
        chapter = service.resolve_chapter_id(args.chapter)
        logger.info(f"写章节: {chapter}")
        result = service.write_chapter(
            {
                "chapter_id": chapter,
                "guidance": "",
                "target_words": 0,
                "temperature": args.temperature,
                "run_id_v2": str(getattr(args, "resume_run", "") or ""),
            }
        )
    except NovelServiceError as exc:
        logger.error(str(exc))
        if getattr(args, "show", False) and service is not None:
            try:
                preview = service.context_preview(chapter)
                print(str(preview.get("markdown") or ""))
            except NovelServiceError:
                pass
        return 1

    logger.info(f"章节已生成: {result.get('title', '')}")
    logger.info(f"字数: {result.get('word_count', 0)}")
    truth_updates = result.get("truth_updates", {})
    if truth_updates:
        logger.info(f"真相文件已更新: {', '.join(truth_updates.keys())}")
    else:
        logger.info("本章未产生可写入的真相增量")
    return 0


def _cmd_sync(args) -> int:
    """同步 src -> data（outline/character）"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    project_root = Path.cwd()
    try:
        service = NovelApplicationService(project_root)
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1
    if args.novel_id and args.novel_id not in {"current", service.novel_id}:
        logger.error("--novel-id 必须与当前 novel_config.yaml 一致")
        return 1

    before = service.sync_status()
    suggestions = _build_sync_suggestions(before)
    before_actions = _build_sync_actions(before)

    if not args.json:
        _print_sync_status(before)
        for msg in suggestions:
            logger.info(f"  建议: {msg}")

    if args.check:
        code = 2 if before["needs_sync"] else 0
        if args.json:
            print(
                json.dumps(
                    {
                        "mode": "check",
                        "status": before,
                        "suggestions": suggestions,
                        "actions": before_actions,
                        "ok": not before["needs_sync"],
                        "exit_code": code,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        if before["needs_sync"]:
            if not args.json:
                logger.warning("检测到未同步项（仅检查模式，未执行写入）")
            return code
        if not args.json:
            logger.info("同步状态正常")
        return code

    try:
        after = service.sync()["after"]
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1
    after_suggestions = _build_sync_suggestions(after)
    after_actions = _build_sync_actions(after)
    code = 0 if not after["needs_sync"] else 1

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "apply",
                    "before": before,
                    "after": after,
                    "suggestions": after_suggestions,
                    "actions": after_actions,
                    "ok": not after["needs_sync"],
                    "exit_code": code,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return code

    _print_sync_status(after)
    for msg in after_suggestions:
        logger.info(f"  建议: {msg}")

    if after["needs_sync"]:
        logger.warning("同步执行后仍存在未同步项，请检查输入文件格式")
        return code

    logger.info("同步完成")
    return code


def _cmd_multi_write(args) -> int:
    """使用统一章节管线执行多 Agent 写作。"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    try:
        result = NovelApplicationService(Path.cwd()).multi_write(
            {
                "chapter_id": args.chapter,
                "temperature": args.temperature,
                "no_review": bool(args.no_review),
                "strict": bool(getattr(args, "strict", False)),
                "dimensions": getattr(args, "dimensions", None),
                "target_words": int(getattr(args, "target_words", 0) or 0),
                "guidance": str(getattr(args, "guidance", "") or ""),
                "show_packet": bool(args.show_packet),
                "packet_output_dir": args.packet_output_dir,
            }
        )
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1

    if result.get("packet_path"):
        logger.info(f"组装包快照: {result['packet_path']}")
    if result.get("packet_markdown"):
        print(result["packet_markdown"])
    logger.info(f"章节已保存: {result['chapter_id']}")
    review = result.get("review")
    if isinstance(review, dict):
        logger.info(f"审查得分: {float(review.get('score', 0)):.0f}/100")
        logger.info(f"审查问题数: {int(review.get('issues', 0))}")
    updates = result.get("applied_state_updates") or {}
    if isinstance(updates, dict) and updates:
        logger.info(f"已更新状态文件: {', '.join(updates)}")
    concepts = result.get("new_concepts") or []
    if isinstance(concepts, list) and concepts:
        logger.info(f"已新增概念文档: {', '.join(str(item) for item in concepts)}")
    return 0


def _cmd_review(args) -> int:
    """审查章节"""
    project_root = Path.cwd()
    from tools.novel_service import NovelApplicationService, NovelServiceError

    try:
        service = NovelApplicationService(project_root)
        chapter = service.resolve_chapter_id(args.chapter, latest=True)
        logger.info(f"审查章节: {chapter}")
        result = service.review_chapter(chapter)
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1

    logger.info(f"审查结果: {'通过' if result.get('passed') else '未通过'}")
    logger.info(f"得分: {float(result.get('score', 0)):.0f}/100")
    logger.info(f"问题数: {int(result.get('issues', 0))}")

    return 0


def _cmd_context(args) -> int:
    """构建上下文"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    project_root = Path.cwd()
    agent = str(getattr(args, "agent", "canonical") or "canonical")
    try:
        service = NovelApplicationService(project_root)
        preview = service.context_preview(args.chapter)
        inspection = None
        if agent != "canonical" or getattr(args, "output", None):
            from tools.agent_context_inspector import AgentContextInspector

            inspector = AgentContextInspector(project_root)
            inspection = inspector.inspect(
                args.chapter,
                agent=agent,
                instruction=str(getattr(args, "instruction", "") or ""),
                guidance=str(getattr(args, "guidance", "") or ""),
                target_words=int(getattr(args, "target_words", 0) or 0),
            )
    except (NovelServiceError, RuntimeError, ValueError) as exc:
        logger.error(str(exc))
        return 1

    if agent == "canonical" and inspection is None and args.show:
        print(preview["markdown"])
        return 0

    if inspection is None:
        sections = preview["packet"].get("prompt_sections", {})
        logger.info(f"上下文 ({len(sections)} 个段落):")
        for name in sections:
            logger.info(f"  - {name}")
        logger.info("检查实际 Agent 输入: openwrite context <chapter> --agent writer --show")
        return 0

    from tools.agent_context_inspector import AgentContextInspector

    rendered = (
        json.dumps(inspection, ensure_ascii=False, indent=2)
        if getattr(args, "format", "markdown") == "json"
        else AgentContextInspector(project_root).render_markdown(inspection)
    )
    output = str(getattr(args, "output", "") or "").strip()
    if output:
        output_path = Path(output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        logger.info(f"Agent 上下文检查已输出: {output_path}")
    if args.show or not output:
        print(rendered)

    return 0


def _cmd_assemble(args) -> int:
    """按 V2 规则组装章节上下文包"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    project_root = Path.cwd()
    try:
        service = NovelApplicationService(project_root)
        chapter = service.resolve_chapter_id(args.chapter)
        packet = service.assemble_packet(chapter)
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1

    if args.format == "json":
        rendered = json.dumps(packet, ensure_ascii=False, indent=2)
        ext = "json"
    else:
        rendered = str(packet.get("outline") or "")
        ext = "md"

    # 为调试/验收固定保存一份上下文快照，便于回看组装效果。
    target_dir = (
        Path(args.output_dir)
        if args.output_dir
        else _get_test_output_dir(project_root, service.novel_id, "context_packets")
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = target_dir / f"{chapter}_{stamp}.{ext}"
    snapshot_path.write_text(rendered, encoding="utf-8")
    logger.info(f"组装结果快照: {snapshot_path}")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        logger.info(f"组装结果已输出: {output_path}")

    if not args.no_print and not args.output:
        print(rendered)

    return 0


def _cmd_style(args) -> int:
    """风格管理"""
    if args.style_action == "extract":
        return _cmd_style_extract(args)
    elif args.style_action == "synthesize":
        return _cmd_style_synthesize(args)
    else:
        logger.error("请指定 style 子命令: extract, synthesize")
        return 1


def _cmd_setting(args) -> int:
    """设定来源管理。"""
    if args.setting_action == "extract":
        return _run_source_extract(args, focus="setting")
    logger.error("请指定 setting 子命令: extract")
    return 1


def _cmd_source(args) -> int:
    """来源文本 source pack 管理。"""
    if args.source_action == "analyze":
        return _cmd_source_analyze_v2(args)
    if args.source_action == "status":
        return _cmd_source_status_v2(args)
    if args.source_action == "retry":
        return _cmd_source_retry_v2(args)
    if args.source_action == "synthesize":
        return _cmd_source_synthesize_v2(args)
    if args.source_action == "profile":
        return _cmd_source_profile_v2(args)
    if args.source_action == "promotion-preview":
        return _cmd_source_promotion_preview_v2(args)
    if args.source_action == "review":
        return _cmd_source_review(args)
    if args.source_action == "promote":
        return _cmd_source_promote(args)
    logger.error(
        "请指定 source 子命令: analyze, status, retry, synthesize, profile, "
        "promotion-preview, review, promote"
    )
    return 1


def _runtime_baseline(agent: str) -> set[str]:
    from tools.agent.tool_runtime import build_tool_executors
    from tools.agent.toolkits import (
        DANTE_ACTION_TOOLKIT,
        DANTE_DIRECT_TOOLKIT,
        GOETHE_ACTION_TOOLKIT,
        GOETHE_DIRECT_TOOLKIT,
        ORCHESTRATOR_TOOLKIT,
        WRITING_TOOLKIT,
    )

    if agent == "dante":
        return set(DANTE_DIRECT_TOOLKIT) | set(DANTE_ACTION_TOOLKIT)
    if agent == "goethe":
        return set(GOETHE_DIRECT_TOOLKIT) | set(GOETHE_ACTION_TOOLKIT)
    if agent == "writer":
        return set(WRITING_TOOLKIT)
    if agent == "reviewer":
        return set(ORCHESTRATOR_TOOLKIT) | {"review_chapter"}
    return set(build_tool_executors(Path.cwd()))


def _cmd_skill(args) -> int:
    from tools.runtime_skills import RuntimeSkillResolver

    resolver = RuntimeSkillResolver(Path.cwd())
    if args.skill_action == "list":
        payload = resolver.list_skills()
    elif args.skill_action == "diagnose":
        payload = resolver.diagnose()
    elif args.skill_action == "resolve":
        resolution = resolver.resolve(
            agent=args.agent,
            base_tools=_runtime_baseline(args.agent),
            task=args.task,
            intent=args.intent,
            document_type=args.document_type,
            explicit_skills=args.skill or None,
        )
        payload = resolution.model_dump(mode="json")
    else:
        logger.error("请指定 skill 子命令: list, resolve, diagnose")
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_rule(args) -> int:
    from tools.runtime_skills import RuleCompiler
    from tools.runtime_skills.resolver import RuntimeSkillError

    compiler = RuleCompiler(Path.cwd())
    try:
        if args.rule_action == "preview":
            payload: object = compiler.preview().model_dump(mode="json")
        elif args.rule_action == "apply":
            payload = compiler.apply(
                args.preview_id, confirm=bool(args.confirm)
            ).model_dump(mode="json")
        elif args.rule_action == "status":
            active = compiler.active()
            payload = active.model_dump(mode="json") if active else {"active": False}
        else:
            logger.error("请指定 rule 子命令: preview, apply, status")
            return 1
    except RuntimeSkillError as exc:
        logger.error(f"{exc.code}: {exc}")
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_run(args) -> int:
    from tools.chapter_run_v2 import ChapterRunV2Error, chapter_run_v2_action

    config = _load_config(Path.cwd()) or {}
    novel_id = str(config.get("novel_id") or "")
    if not novel_id:
        logger.error("未找到有效的 novel_config.yaml")
        return 1
    action = str(args.run_action or "")
    if action == "list":
        payload = {
            "action": "list",
            "chapter_id": args.chapter_id,
            "statuses": args.status,
            "limit": args.limit,
        }
    elif action == "show":
        payload = {"action": "get", "run_id": args.run_id}
    elif action == "intervene":
        payload = {
            "action": "record_intervention",
            "run_id": args.run_id,
            "revision": args.revision,
            "request": args.request,
            "scope": args.scope,
            "risk": args.risk,
            "affected_items": args.affected_item,
            "rewrite_required": args.rewrite_required,
        }
    elif action == "transition":
        payload = {
            "action": "update_intervention",
            "run_id": args.run_id,
            "revision": args.revision,
            "intervention_id": args.intervention_id,
            "state": args.state,
            "impact": args.impact,
            "confirm": args.confirm,
        }
        if args.facts_revision is not None:
            payload["facts_revision"] = args.facts_revision
        if args.proposal is not None:
            payload["proposal"] = args.proposal
    elif action == "cancel":
        payload = {
            "action": "cancel",
            "run_id": args.run_id,
            "revision": args.revision,
            "reason": args.reason,
        }
    else:
        logger.error("请指定 run 子命令: list, show, intervene, transition, cancel")
        return 1
    try:
        result = chapter_run_v2_action(Path.cwd(), novel_id, payload)
    except ChapterRunV2Error as exc:
        logger.error(f"{exc.code}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_diagnose(args) -> int:
    from tools.runtime_diagnostics import RuntimeDiagnosticsService

    config = _load_config(Path.cwd()) or {}
    novel_id = str(config.get("novel_id") or "")
    if not novel_id:
        logger.error("未找到有效的 novel_config.yaml")
        return 1
    report = RuntimeDiagnosticsService(Path.cwd(), novel_id).run(
        stuck_minutes=args.stuck_minutes
    )
    print(report.model_dump_json(indent=2))
    return 0


def _cmd_planning(args) -> int:
    from tools.rolling_planning import RollingPlanningError, rolling_plan_action

    config = _load_config(Path.cwd()) or {}
    novel_id = str(config.get("novel_id") or "")
    if not novel_id:
        logger.error("未找到有效的 novel_config.yaml")
        return 1
    action = str(args.planning_action or "")
    if action == "list":
        payload = {"action": "list", "limit": args.limit}
    elif action == "create":
        payload = {
            "action": "create",
            "current_arc": args.current_arc,
            "window_size": args.window_size,
        }
    elif action == "show":
        payload = {"action": "get", "candidate_id": args.candidate_id}
    elif action == "stage":
        try:
            proposal = Path(args.proposal_file).read_text(encoding="utf-8")
        except OSError as exc:
            logger.error(f"无法读取提案文件: {exc}")
            return 1
        payload = {
            "action": "stage",
            "candidate_id": args.candidate_id,
            "revision": args.revision,
            "proposal": proposal,
        }
    else:
        logger.error("请指定 planning 子命令: list, create, show, stage")
        return 1
    try:
        result = rolling_plan_action(Path.cwd(), novel_id, payload)
    except RollingPlanningError as exc:
        logger.error(f"{exc.code}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _manuscript_editing_command(payload: dict[str, object]) -> int:
    from tools.manuscript_editing import ManuscriptEditingError, manuscript_editing_action

    config = _load_config(Path.cwd()) or {}
    novel_id = str(config.get("novel_id") or "")
    if not novel_id:
        logger.error("未找到有效的 novel_config.yaml")
        return 1
    try:
        result = manuscript_editing_action(Path.cwd(), novel_id, payload)
    except ManuscriptEditingError as exc:
        logger.error(f"{exc.code}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_version(args) -> int:
    action = str(args.version_action or "")
    if action == "list":
        payload = {"action": "versions", "chapter_id": args.chapter_id}
    elif action == "show":
        payload = {
            "action": "version",
            "chapter_id": args.chapter_id,
            "version_id": args.version_id,
        }
    elif action == "checkpoint":
        payload = {
            "action": "checkpoint",
            "chapter_id": args.chapter_id,
            "label": args.label,
        }
    elif action == "restore":
        payload = {
            "action": "restore",
            "chapter_id": args.chapter_id,
            "version_id": args.version_id,
            "revision": args.revision,
            "confirm": args.confirm,
        }
    else:
        logger.error("请指定 version 子命令: list, show, checkpoint, restore")
        return 1
    return _manuscript_editing_command(payload)


def _cmd_annotation(args) -> int:
    action = str(args.annotation_action or "")
    if action == "list":
        payload = {"action": "annotations", "chapter_id": args.chapter_id}
    elif action == "create":
        from tools.manuscript_editing import ManuscriptEditingError, ManuscriptVersionStore

        if args.start < 0 or args.end <= args.start:
            logger.error("批注字符区间无效")
            return 1
        config = _load_config(Path.cwd()) or {}
        novel_id = str(config.get("novel_id") or "")
        if not novel_id:
            logger.error("未找到有效的 novel_config.yaml")
            return 1
        try:
            content = ManuscriptVersionStore(Path.cwd(), novel_id).chapter_path(
                args.chapter_id
            ).read_text(encoding="utf-8")
        except (OSError, ManuscriptEditingError) as exc:
            logger.error(str(exc))
            return 1
        payload = {
            "action": "annotate",
            "chapter_id": args.chapter_id,
            "revision": args.revision,
            "quote": content[args.start : args.end],
            "start_hint": args.start,
            "end_hint": args.end,
            "note": args.note,
        }
    elif action == "resolve":
        payload = {
            "action": "resolve_annotation",
            "chapter_id": args.chapter_id,
            "annotation_id": args.annotation_id,
        }
    else:
        logger.error("请指定 annotation 子命令: list, create, resolve")
        return 1
    return _manuscript_editing_command(payload)


def _cmd_style_synthesize(args) -> int:
    """合成作品级风格文档。

    这一步不是再次调用 LLM 做“对话式风格导演”，而是把已经落盘的
    风格来源重新编译成单份 ``data/style/composed.md``：

    1. 读取作品自己的 ``fingerprint.yaml``
    2. 读取当前 ``style_id`` 对应 source pack 下的 ``style/*.md``
    3. 叠加 ``craft/`` 里的通用规则与禁用短语
    4. 输出给 ContextBuilder / ChapterAssembler 消费的最终风格文档
    """
    project_root = Path.cwd()
    config = _load_config(project_root)
    if not config and getattr(args, "novel_id", "current") == "current":
        logger.error("未找到 novel_config.yaml，请先运行 openwrite init")
        return 1

    novel_id = (
        config.get("novel_id", "")
        if getattr(args, "novel_id", "current") == "current"
        else getattr(args, "novel_id", "")
    )
    if not novel_id:
        logger.error("无法确定 novel_id")
        return 1

    style_id = config.get("style_id", novel_id) if config else novel_id
    from tools.novel_service import NovelApplicationService, NovelServiceError

    try:
        result = NovelApplicationService(project_root).synthesize_style(style_id)
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1
    logger.info(
        f"合成风格文档已写入: {result['composed_path']} (mode={result['mode']})"
    )
    return 0


def _cmd_style_extract(args) -> int:
    """从用户提供文本提取风格与设定（AI 批量提取）。"""
    return _run_source_extract(args, focus="style")


def _extract_source_pack(
    project_root: Path,
    novel_id: str,
    source_id: str,
    source_file: Path,
    *,
    focus: str,
    chunk_size: int = 30000,
) -> dict[str, object]:
    """兼容入口：来源提取由 SourcePackService 执行。"""
    from tools.source_pack import SourcePackService

    return SourcePackService(project_root, novel_id).extract(
        source_id,
        source_file,
        focus=focus,
        chunk_size=chunk_size,
    )


def _run_source_extract(args, *, focus: str) -> int:
    """从用户提供文本提取 source pack。"""
    source_file = Path(args.source)
    if not source_file.exists():
        logger.error(f"源文件不存在: {source_file}")
        return 1

    source_id = args.source_id
    project_root = Path.cwd()
    from tools.novel_service import NovelApplicationService, NovelServiceError

    try:
        NovelApplicationService(project_root).extract_source(
            source_id=source_id,
            source_file=source_file,
            focus=focus,
            chunk_size=args.chunk_size,
        )
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1

    return 0


def _cmd_goethe(args) -> int:
    """Goethe 长期会话规划入口。"""
    from tools.goethe import run_goethe

    return run_goethe()


def _cmd_dante(args) -> int:
    """Dante 长会话主入口。"""
    _ = args
    try:
        from tools.agent.dante import run_dante

        return run_dante()
    except ImportError as e:
        logger.error(f"Dante 模块未安装: {e}")
        return 1
    except Exception as e:
        logger.error(f"Dante 启动失败: {e}")
        return 1


def _cmd_radar(args) -> int:
    """运行小说市场分析并渲染结果。"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    try:
        result = NovelApplicationService(Path.cwd()).market_radar(
            platforms=args.platform,
            top_n=args.top,
        )
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1

    print("\n" + "=" * 50)
    print("   市场分析结果")
    print("=" * 50)
    for index, item in enumerate(result["recommendations"], 1):
        print(
            f"\n{index}. [{float(item['confidence']):.0%}] "
            f"{item['platform']}/{item['genre']}"
        )
        print(f"   创意: {item['concept']}")
        print(f"   理由: {item['reasoning']}")
        if item["benchmarks"]:
            print(f"   参考: {', '.join(item['benchmarks'][:3])}")
    if result["trends"]:
        print("\n" + "-" * 50)
        print("趋势:")
        for trend in result["trends"]:
            print(f"  - {trend}")
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        sections = ["# 市场分析结果", ""]
        for item in result["recommendations"]:
            sections.append(
                f"## {item['platform']}/{item['genre']}\n\n"
                f"- 置信度: {float(item['confidence']):.0%}\n"
                f"- 创意: {item['concept']}\n"
                f"- 理由: {item['reasoning']}\n"
            )
        output.write_text("\n".join(sections), encoding="utf-8")
        print(f"\n已保存到: {output}")
    return 0


def _cmd_status(args) -> int:
    """查看状态"""
    from tools.agent.tool_runtime import build_tool_executors
    from tools.novel_service import NovelApplicationService, NovelServiceError

    project_root = Path.cwd()
    try:
        service = NovelApplicationService(project_root)
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1

    if getattr(args, "json", False):
        print(
            json.dumps(
                service.workspace_snapshot(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    status = build_tool_executors(project_root)["get_status"]({})
    logger.info(f"项目: {status['novel_id']}")
    logger.info(f"当前篇: {status['current_arc']}")
    logger.info(f"当前章: {status['current_chapter']}")
    logger.info(f"已写章节: {status['chapters_written']}")
    logger.info(f"快照数: {status['snapshots']}")

    return 0


def _cmd_focus(args) -> int:
    """查看或更新近期创作罗盘。"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    project_root = Path.cwd()
    action = getattr(args, "focus_action", None) or "show"
    try:
        service = NovelApplicationService(project_root)
        if action == "set":
            path = service.update_focus(
                goal=args.goal,
                must_keep=args.keep,
                must_avoid=args.avoid,
                notes=args.note,
            )
            logger.info(f"创作罗盘已更新: {path}")
            logger.info("后续章节上下文会优先携带这些约束")
            return 0
        if action == "clear":
            service.clear_focus()
            logger.info("创作罗盘已清空")
            return 0
        print(service.render_focus())
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1
    return 0


def _cmd_import(args) -> int:
    """导入已有 TXT/Markdown 小说正文。"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    project_root = Path.cwd()
    try:
        result = NovelApplicationService(project_root).import_book(
            Path(args.source).expanduser(),
            arc_id=args.arc,
            start_number=args.start,
            force=bool(args.force),
        )
    except NovelServiceError as exc:
        logger.error(f"导入失败: {exc}")
        return 1

    logger.info(f"已导入 {len(result['imported'])} 章到 {result['arc_id']}")
    logger.info(f"合计字数: {result['writing_units']}")
    logger.info(f"下一章: {result['next_chapter']}")
    return 0


def _cmd_export(args) -> int:
    """导出完整小说正文。"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    project_root = Path.cwd()
    service = None
    try:
        service = NovelApplicationService(project_root)
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1
    format_name = args.format
    output = (
        Path(args.output).expanduser()
        if args.output
        else project_root / "exports" / f"{service.novel_id}.{format_name}"
    )
    try:
        path = service.export_book(
            output,
            format_name=format_name,
            title=args.title,
            author=args.author,
            language=args.language,
            cover=Path(args.cover).expanduser() if args.cover else None,
        )
    except NovelServiceError as exc:
        logger.error(f"导出失败: {exc}")
        return 1
    logger.info(f"整书已导出: {path}")
    return 0


def _cmd_asset(args) -> int:
    """Manage structured assets and portable packages."""
    from tools.asset_package import AssetPackageError, AssetPackageService
    from tools.novel_service import NovelApplicationService, NovelServiceError
    from tools.structured_assets import StructuredAssetError, StructuredAssetService

    try:
        novel_id = NovelApplicationService(Path.cwd()).novel_id
        assets = StructuredAssetService(Path.cwd(), novel_id)
        packages = AssetPackageService(Path.cwd(), novel_id)
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1
    action = str(getattr(args, "asset_action", "") or "list")
    try:
        if action == "list":
            result = assets.list(str(getattr(args, "kind", "") or ""))
        elif action == "export":
            selections = [
                _parse_asset_selection(value)
                for value in getattr(args, "select", [])
            ]
            result = packages.export(
                Path(args.output),
                selections=selections or None,
            )
        elif action == "preview":
            result = packages.preview_import(Path(args.package))
        elif action == "import":
            preview = packages.preview_import(Path(args.package))
            if not bool(args.apply):
                result = preview
            else:
                resolutions: dict[str, dict[str, str]] = {
                    str(asset_id): {"action": "replace"}
                    for asset_id in args.replace
                }
                resolutions.update(
                    {
                        str(asset_id): {"action": "skip"}
                        for asset_id in args.skip
                    }
                )
                for value in args.rename:
                    old_id, new_id = _parse_asset_rename(value)
                    resolutions[old_id] = {"action": "rename", "new_id": new_id}
                result = packages.import_package(
                    Path(args.package),
                    expected_sha256=preview["package_sha256"],
                    resolutions=resolutions,
                    allow_missing_dependencies=bool(args.allow_missing_dependencies),
                )
        else:
            logger.error("请指定 asset list/export/preview/import")
            return 1
    except (AssetPackageError, StructuredAssetError, OSError, ValueError) as exc:
        logger.error(str(exc))
        return 1
    if bool(getattr(args, "json", False)):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).rstrip())
    return 0


def _parse_asset_selection(value: str) -> dict[str, str]:
    kind, separator, asset_id = str(value or "").partition(":")
    if not separator or kind not in {"character", "world", "progression"} or not asset_id:
        raise ValueError("资产选择必须形如 character:char_id")
    return {"kind": kind, "id": asset_id}


def _parse_asset_rename(value: str) -> tuple[str, str]:
    old_id, separator, new_id = str(value or "").partition(":")
    if not separator or not old_id or not new_id:
        raise ValueError("重命名必须形如 old_id:new_id")
    return old_id, new_id


def _cmd_desk(args) -> int:
    """显示小说专用终端工作台。"""
    from tools.novel_service import NovelApplicationService, NovelServiceError

    project_root = Path.cwd()
    try:
        snapshot = NovelApplicationService(project_root).workspace_state()
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1
    if getattr(args, "json", False):
        print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2))
        return 0

    width = 66
    target = snapshot.target_units
    percent = min(100, round(snapshot.writing_units / target * 100)) if target else 0
    filled = round(percent / 5)
    progress = "#" * filled + "-" * (20 - filled)
    readiness_labels = {
        "author_intent": "作者意图",
        "background": "故事背景",
        "foundation": "基础设定",
        "characters": "主要人物",
        "outline": "可写大纲",
        "creative_focus": "创作罗盘",
    }

    print("=" * width)
    print(f"  OPENWRITE  /  {snapshot.title}")
    print("  长篇小说创作工作台")
    print("=" * width)
    print(
        f"  进度  [{progress}] {percent:>3}%   "
        f"{snapshot.chapters} 章 / {snapshot.writing_units:,} 字"
    )
    print(
        f"  当前  {snapshot.current_arc} · {snapshot.current_chapter}   "
        f"阶段: {snapshot.stage}"
    )
    print(
        f"  资产  {snapshot.characters} 人物 · {snapshot.world_documents} 设定文档 · "
        f"{snapshot.pending_foreshadowing} 待处理伏笔"
    )
    print(
        f"  质量  {snapshot.reviewed_chapters} 章已审 · "
        f"均分 {snapshot.average_review_score:.1f} · {snapshot.total_tokens:,} tokens"
    )
    print("-" * width)
    print("  创作罗盘")
    goal = snapshot.creative_focus.goal or "尚未设置；先明确这一阶段最重要的叙事目标。"
    print(f"  {goal[: width - 4]}")
    if snapshot.creative_focus.must_keep:
        print(f"  必须保留: {'；'.join(snapshot.creative_focus.must_keep)[: width - 12]}")
    if snapshot.creative_focus.must_avoid:
        print(f"  必须避免: {'；'.join(snapshot.creative_focus.must_avoid)[: width - 12]}")
    print("-" * width)
    readiness = "  ".join(
        f"[{'OK' if snapshot.readiness[key] else '--'}] {label}"
        for key, label in readiness_labels.items()
    )
    # Keep the dashboard legible in narrow terminals without relying on an
    # optional rendering package.
    for start in range(0, len(readiness), width - 2):
        print(f"  {readiness[start:start + width - 2]}")
    print("-" * width)
    print("  下一步")
    for action in snapshot.next_actions:
        print(f"  > {action}")
    print("=" * width)
    return 0


def _cmd_studio(args) -> int:
    """启动仅绑定本机回环地址的 Studio。"""
    from tools.studio import StudioError, run_studio

    if not 0 <= args.port <= 65535:
        logger.error("端口必须在 0 到 65535 之间")
        return 1
    try:
        return run_studio(
            Path(args.project).expanduser() if args.project else Path.cwd(),
            port=args.port,
            open_browser=not bool(args.no_open),
            debug=bool(args.debug),
        )
    except (OSError, StudioError) as exc:
        logger.error(f"Studio 启动失败: {exc}")
        return 1


def _cmd_doctor(args) -> int:
    """环境与路径自检"""
    project_root = Path.cwd()
    config = _load_config(project_root)
    if not config:
        logger.error("未找到 novel_config.yaml")
        return 1

    novel_id = config.get("novel_id", "unknown")
    novel_root = project_root / "data" / "novels" / novel_id
    src_root = novel_root / "src"
    runtime_root = novel_root / "data"
    packet_dir = _get_test_output_dir(project_root, novel_id, "context_packets")

    logger.info(f"工作目录: {project_root}")
    logger.info(f"小说 ID: {novel_id}")
    logger.info(f"源目录: {src_root} ({'存在' if src_root.exists() else '缺失'})")
    logger.info(f"运行目录: {runtime_root} ({'存在' if runtime_root.exists() else '缺失'})")
    logger.info(f"测试输出目录: {packet_dir}")

    model = (os.environ.get("LLM_MODEL") or "").strip()
    provider = (os.environ.get("LLM_PROVIDER") or "").strip()
    api_key = (os.environ.get("LLM_API_KEY") or "").strip()
    masked = "<missing>"
    if api_key:
        masked = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"

    logger.info(f"LLM_PROVIDER: {provider or '<missing>'}")
    logger.info(f"LLM_MODEL: {model or '<missing>'}")
    logger.info(f"LLM_API_KEY: {masked}")

    return 0


def _cmd_agent(args) -> int:
    """agent 命令 - 已退役"""
    logger.error("openwrite agent 已退役，请改用 openwrite dante。")
    return 1


def build_cli_tool_executors(project_root: Path) -> dict[str, Callable[[dict], dict]]:
    """兼容入口：返回统一 action surface 的工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)


def build_dante_tool_layers(project_root: Path) -> dict[str, object]:
    """兼容入口：实际工具分层由 agent action surface 构建。"""
    from tools.agent.tool_layers import build_dante_tool_layers as build_layers

    return build_layers(project_root)


def build_goethe_tool_layers(project_root: Path, novel_id: str | None = None) -> dict[str, object]:
    """兼容入口：实际工具分层由 agent action surface 构建。"""
    from tools.agent.tool_layers import build_goethe_tool_layers as build_layers

    return build_layers(project_root, novel_id)


















def _build_reviewer_context_payload(context_packet: dict) -> dict:
    """兼容入口：构造审稿上下文由统一章节管线负责。"""
    from tools.chapter_pipeline import build_review_payload

    return build_review_payload(context_packet)














def _build_writer_context_payload(
    *,
    context,
    truth,
    context_packet: dict,
    guidance: str,
    target_words: int,
) -> dict:
    """兼容入口：构造写章上下文由统一章节管线负责。"""
    from tools.chapter_pipeline import build_writer_payload

    return build_writer_payload(
        context=context,
        truth=truth,
        packet=context_packet,
        guidance=guidance,
        target_words=target_words,
    )


def _exec_write_chapter(project_root: Path, args: dict) -> dict:
    """兼容入口：章节写作由统一管线执行。"""
    from tools.chapter_pipeline import execute_write_chapter

    return execute_write_chapter(project_root, args)


def _exec_review_chapter(project_root: Path, args: dict) -> dict:
    """兼容入口：章节审稿由统一管线执行。"""
    from tools.chapter_pipeline import execute_review_chapter

    return execute_review_chapter(project_root, args)


def _exec_get_status(project_root: Path) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["get_status"]({})


def _exec_get_context(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["get_context"](args)


def _exec_list_chapters(project_root: Path) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["list_chapters"]({})


def _exec_create_outline(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["create_outline"](args)


def _exec_create_character(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["create_character"](args)


def _exec_get_truth_files(project_root: Path) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["get_truth_files"]({})


def _exec_update_truth_file(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["update_truth_file"](args)




def _safe_stem(value: str) -> str:
    """将用户输入规范化为安全文件名（不含路径成分）。"""
    text = (value or "").strip()
    # 拦截显式路径成分与目录跳转。
    if any(x in text for x in ("/", "\\")) or ".." in text:
        return ""
    # 允许中文、字母数字、下划线、中划线，空白转下划线。
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "", text)
    return text[:64]


def _collect_truth_updates(state_updates: dict) -> dict[str, str]:
    """从 Agent 结算输出中提取可落盘的真相字段。"""
    if not isinstance(state_updates, dict):
        return {}

    file_map = {
        "current_state": "current_state",
        "ledger": "ledger",
        "relationships": "relationships",
    }
    out: dict[str, str] = {}

    for key, value in state_updates.items():
        if not isinstance(value, str) or not value.strip():
            continue
        canonical = normalize_truth_file_key(key)
        attr = file_map.get(canonical)
        if attr:
            out[attr] = value

    return out
















def _resolve_novel_id(project_root: Path, requested: str) -> str:
    if requested and requested != "current":
        return requested
    config = _load_config(project_root) or {}
    return str(config.get("novel_id", "")).strip()




















def _refresh_source_pack_documents(
    project_root: Path,
    novel_id: str,
    source_id: str,
) -> None:
    """兼容入口：刷新来源文档由 SourcePackService 执行。"""
    from tools.source_pack import SourcePackService

    SourcePackService(project_root, novel_id).refresh_documents(source_id)


def _render_source_review(
    project_root: Path,
    novel_id: str,
    source_id: str,
) -> str:
    """兼容入口：来源审阅由 SourcePackService 渲染。"""
    from tools.source_pack import SourcePackService

    return SourcePackService(project_root, novel_id).render_review(source_id)










def _cmd_source_review(args) -> int:
    project_root = Path.cwd()
    novel_id = _resolve_novel_id(project_root, getattr(args, "novel_id", "current"))
    if not novel_id:
        logger.error("未找到 novel_config.yaml，请指定 --novel-id")
        return 1

    from tools.novel_service import NovelApplicationService, NovelServiceError

    try:
        result = NovelApplicationService(project_root).review_source(args.source_id)
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1
    print(result["review_report"])
    return 0


def _source_v2_service(args):
    project_root = Path.cwd()
    novel_id = _resolve_novel_id(project_root, getattr(args, "novel_id", "current"))
    if not novel_id:
        raise ValueError("未找到 novel_config.yaml，请指定 --novel-id")
    from tools.source_pack import SourcePackService

    return SourcePackService(project_root, novel_id)


def _print_source_v2(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_source_analyze_v2(args) -> int:
    source_path = Path(args.source).expanduser()
    if not source_path.is_file():
        logger.error(f"源文件不存在: {source_path}")
        return 1
    try:
        content = source_path.read_text(encoding="utf-8")
        service = _source_v2_service(args)
        prepared = service.prepare_v2(
            args.source_id,
            content,
            relative_name=source_path.name,
            focus=args.focus,
            input_budget_tokens=args.input_budget,
        )
        result = service.analyze_v2(args.source_id)
    except Exception as exc:
        logger.error(str(exc))
        return 1
    return _print_source_v2(
        {
            "prepared": {
                "reused_chunks": prepared["reused_chunks"],
                "pending_chunks": prepared["pending_chunks"],
                "model_calls_needed": prepared["model_calls_needed"],
            },
            **result,
        }
    )


def _cmd_source_status_v2(args) -> int:
    try:
        return _print_source_v2(_source_v2_service(args).status_v2(args.source_id))
    except Exception as exc:
        logger.error(str(exc))
        return 1


def _cmd_source_retry_v2(args) -> int:
    try:
        result = _source_v2_service(args).retry_v2(args.source_id, args.chunk_id)
        return _print_source_v2(result)
    except Exception as exc:
        logger.error(str(exc))
        return 1


def _cmd_source_synthesize_v2(args) -> int:
    try:
        result = _source_v2_service(args).synthesize_v2(args.source_ids)
        return _print_source_v2(result)
    except Exception as exc:
        logger.error(str(exc))
        return 1


def _cmd_source_profile_v2(args) -> int:
    if getattr(args, "source_profile_action", "") != "show":
        logger.error("请指定 source profile show")
        return 1
    try:
        result = _source_v2_service(args).profile_v2(args.profile_id)
        return _print_source_v2(result)
    except Exception as exc:
        logger.error(str(exc))
        return 1


def _cmd_source_promotion_preview_v2(args) -> int:
    try:
        result = _source_v2_service(args).preview_promotion_v2(
            args.profile_id, args.target
        )
        return _print_source_v2(result)
    except Exception as exc:
        logger.error(str(exc))
        return 1


def _promote_source_style(
    project_root: Path,
    novel_id: str,
    source_id: str,
) -> None:
    """兼容入口：晋升风格来源由 SourcePackService 执行。"""
    from tools.source_pack import SourcePackService

    SourcePackService(project_root, novel_id).promote(source_id, "style")


def _promote_source_setting(
    project_root: Path,
    novel_id: str,
    source_id: str,
) -> None:
    """兼容入口：晋升基础设定由 SourcePackService 执行。"""
    from tools.source_pack import SourcePackService

    SourcePackService(project_root, novel_id).promote(source_id, "setting")


def _promote_source_world(
    project_root: Path,
    novel_id: str,
    source_id: str,
) -> None:
    """兼容入口：晋升世界设定由 SourcePackService 执行。"""
    from tools.source_pack import SourcePackService

    SourcePackService(project_root, novel_id).promote(source_id, "world")


def _cmd_source_promote(args) -> int:
    project_root = Path.cwd()
    novel_id = _resolve_novel_id(project_root, getattr(args, "novel_id", "current"))
    if not novel_id:
        logger.error("未找到 novel_config.yaml，请指定 --novel-id")
        return 1

    identifier = str(
        getattr(args, "identifier", "") or getattr(args, "source_id", "")
    )
    if identifier.startswith("promotion_"):
        try:
            result = _source_v2_service(args).apply_promotion_v2(
                identifier,
                confirm=bool(getattr(args, "confirm", False)),
            )
            return _print_source_v2(result)
        except Exception as exc:
            logger.error(str(exc))
            return 1
    if getattr(args, "confirm", False):
        logger.error("--confirm 仅用于 promotion_ V2 预览")
        return 1

    from tools.novel_service import NovelApplicationService, NovelServiceError

    try:
        NovelApplicationService(project_root).promote_source(identifier, args.target)
    except NovelServiceError as exc:
        logger.error(str(exc))
        return 1

    logger.info(f"source promote 完成: {identifier} -> {args.target}")
    return 0


def _collect_sync_status(project_root: Path, novel_id: str) -> dict:
    """收集 src/data 同步状态。"""
    return _shared_collect_sync_status(project_root, novel_id)


def _print_sync_status(status: dict) -> None:
    logger.info(f"同步检查: {status['novel_id']}")
    logger.info(f"  大纲同步待处理: {'是' if status['outline_pending'] else '否'}")
    logger.info(f"  角色档案/卡片: {status['profiles']}/{status['cards']}")
    if status["missing_cards"]:
        logger.info(f"  缺失卡片: {', '.join(status['missing_cards'])}")
    if status.get("stale_cards"):
        logger.info(f"  过期卡片: {', '.join(status['stale_cards'])}")
    if status["extra_cards"]:
        logger.info(f"  额外卡片(可选清理): {', '.join(status['extra_cards'])}")


def _build_sync_suggestions(status: dict) -> list[str]:
    """根据同步状态生成下一步建议。"""
    messages: list[str] = []

    if status["outline_pending"]:
        messages.append("大纲源文件有更新，运行 `openwrite sync` 以刷新 data/hierarchy.yaml")

    if status["missing_cards"]:
        preview = ", ".join(status["missing_cards"][:5])
        messages.append(
            f"存在缺失角色卡片（{preview}），运行 `openwrite sync` "
            "生成 data/characters/cards/*.yaml"
        )

    if status.get("stale_cards"):
        preview = ", ".join(status["stale_cards"][:5])
        messages.append(
            f"存在过期角色卡片（{preview}），运行 `openwrite sync` "
            "刷新 data/characters/cards/*.yaml"
        )

    if status["extra_cards"]:
        preview = ", ".join(status["extra_cards"][:5])
        messages.append(f"检测到未对应的历史角色卡片（{preview}），可按需手工清理")

    if not messages:
        messages.append("src 与 data 同步状态良好，可直接继续写作")

    return messages


def _build_sync_actions(status: dict) -> list[dict[str, str]]:
    """根据同步状态生成可执行动作列表（供 JSON 输出）。"""
    actions: list[dict[str, str]] = []

    if status["outline_pending"] or status["missing_cards"] or status.get("stale_cards"):
        actions.append(
            {
                "type": "command",
                "name": "run_sync",
                "command": "openwrite sync",
                "reason": "将 src 的 outline/characters 同步到 data",
            }
        )

    if status["extra_cards"]:
        actions.append(
            {
                "type": "manual",
                "name": "review_extra_cards",
                "reason": "存在未对应档案的历史卡片，按需清理 data/characters/cards/*.yaml",
            }
        )

    if not actions:
        actions.append(
            {
                "type": "noop",
                "name": "continue_writing",
                "reason": "src 与 data 已同步，可直接继续写作流程",
            }
        )

    return actions


def _run_sync(project_root: Path, novel_id: str) -> None:
    """执行 src -> data 同步。"""
    _shared_run_sync(project_root, novel_id)


def _exec_create_foreshadowing(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["create_foreshadowing"](args)


def _exec_list_foreshadowing(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["list_foreshadowing"](args)


def _exec_update_foreshadowing(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["update_foreshadowing"](args)


def _exec_validate_foreshadowing(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["validate_foreshadowing"](args)


def _load_config(project_root: Path) -> dict | None:
    """加载项目配置"""
    config_path = project_root / "novel_config.yaml"
    if not config_path.exists():
        return None

    import yaml

    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_test_output_dir(project_root: Path, novel_id: str, category: str) -> Path:
    """获取测试输出目录。"""
    return project_root / "data" / "novels" / novel_id / "data" / "test_outputs" / category






def _get_current_arc(project_root: Path) -> str:
    """读取当前篇章目录，默认回退到 arc_001。"""
    config = _load_config(project_root) or {}
    return config.get("current_arc") or "arc_001"


def _manuscript_dir(project_root: Path, novel_id: str) -> Path:
    """获取当前支持的手稿根目录。"""
    return project_root / "data" / "novels" / novel_id / "data" / "manuscript"


def _load_chapter(
    project_root: Path,
    novel_id: str,
    chapter_id: str,
) -> str | None:
    """兼容入口：从统一章节管线读取正文。"""
    from tools.chapter_pipeline import load_chapter

    return load_chapter(project_root, novel_id, chapter_id)


def _save_chapter(
    project_root: Path,
    novel_id: str,
    chapter_id: str,
    title: str,
    content: str,
) -> Path:
    """兼容入口：通过统一章节管线原子保存正文。"""
    from tools.chapter_pipeline import save_chapter

    return save_chapter(project_root, novel_id, chapter_id, title, content)


def _chapter_file_path(project_root: Path, novel_id: str, chapter_id: str) -> Path:
    config = _load_config(project_root) or {}
    current_arc = config.get("current_arc", "arc_001")
    return (
        project_root
        / "data"
        / "novels"
        / novel_id
        / "data"
        / "manuscript"
        / current_arc
        / f"{chapter_id}.md"
    )






def _atomic_write_bytes(path: Path, content: bytes) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = type(path)(handle.name)
    temp_path.replace(path)


def _get_next_chapter(project_root: Path, novel_id: str) -> str:
    """获取下一个章节 ID"""
    chapter_ids = _list_chapter_ids(project_root, novel_id)
    if not chapter_ids:
        return "ch_001"
    latest = max(_parse_chapter_no(chid) for chid in chapter_ids)
    return f"ch_{latest + 1:03d}"


def _get_latest_chapter(project_root: Path, novel_id: str) -> str:
    """获取最新章节"""
    chapter_ids = _list_chapter_ids(project_root, novel_id)
    if not chapter_ids:
        return "ch_001"
    latest_id = max(chapter_ids, key=_parse_chapter_no)
    return latest_id


def _list_chapter_ids(project_root: Path, novel_id: str) -> list[str]:
    """从手稿目录扫描章节 ID。"""
    manuscript_root = project_root / "data" / "novels" / novel_id / "data" / "manuscript"
    if not manuscript_root.exists():
        return []

    chapter_ids: set[str] = set()
    for path in manuscript_root.glob("**/ch_*.md"):
        stem = path.stem
        if re.match(r"^ch_\d+$", stem):
            chapter_ids.add(stem)
    return sorted(chapter_ids, key=_parse_chapter_no)


def _parse_chapter_no(chapter_id: str) -> int:
    m = re.search(r"(\d+)", chapter_id)
    return int(m.group(1)) if m else 0


# ── 世界查询 ────────────────────────────────────────────────


def _exec_query_world(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["query_world"](args)


def _exec_get_world_relations(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["get_world_relations"](args)


# ── 状态验证 ────────────────────────────────────────────────


def _exec_validate_truth(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["validate_truth"](args)


# ── 对话质量 ────────────────────────────────────────────────


def _exec_extract_dialogue_fingerprint(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["extract_dialogue_fingerprint"](args)


# ── 后置验证 ────────────────────────────────────────────────


def _exec_validate_post_write(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["validate_post_write"](args)


if __name__ == "__main__":
    sys.exit(main())


# ── 工作流调度 ────────────────────────────────────────────────


def _exec_get_workflow_status(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["get_workflow_status"](args)


def _exec_start_workflow(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["start_workflow"](args)


def _exec_advance_workflow(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["advance_workflow"](args)


# ── 文本处理 ────────────────────────────────────────────────


def _exec_chunk_text(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["chunk_text"](args)


def _exec_compress_section(project_root: Path, args: dict) -> dict:
    """兼容入口：委托给统一小说工具注册表。"""
    from tools.agent.tool_runtime import build_tool_executors

    return build_tool_executors(project_root)["compress_section"](args)


if __name__ == "__main__":
    sys.exit(main())
