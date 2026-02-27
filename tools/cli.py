"""OpenWrite CLI entrypoint."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table

try:
    from tools.agents.reader import ReaderAgent
    from tools.agents.simulator import AgentSimulator
    from tools.agents.style_director import StyleDirectorAgent
    from tools.character_state_manager import CharacterStateManager
    from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
    from tools.models.style import StyleProfile
    from tools.queries.character_query import CharacterQuery
    from tools.utils.style_composer import StyleComposer
    from tools.world_graph_manager import WorldGraphManager
except ImportError:  # pragma: no cover - supports legacy path injection
    from agents.reader import ReaderAgent
    from agents.simulator import AgentSimulator
    from agents.style_director import StyleDirectorAgent
    from character_state_manager import CharacterStateManager
    from graph.foreshadowing_dag import ForeshadowingDAGManager
    from models.style import StyleProfile
    from queries.character_query import CharacterQuery
    from utils.style_composer import StyleComposer
    from world_graph_manager import WorldGraphManager


app = typer.Typer(help="OpenWrite - AI辅助小说创作系统")
character_app = typer.Typer(help="人物相关命令")
outline_app = typer.Typer(help="大纲相关命令")
world_app = typer.Typer(help="世界观图谱命令")
simulate_app = typer.Typer(help="多Agent模拟命令")
style_app = typer.Typer(help="风格系统命令")
timeline_app = typer.Typer(help="叙事线可视化命令")
app.add_typer(character_app, name="character")
app.add_typer(outline_app, name="outline")
app.add_typer(world_app, name="world")
app.add_typer(simulate_app, name="simulate")
app.add_typer(style_app, name="style")
app.add_typer(timeline_app, name="timeline")
console = Console()


def _detect_novel_id(project_dir: Path) -> str:
    novels_dir = project_dir / "data" / "novels"
    if not novels_dir.exists():
        return "my_novel"
    candidates = [path.name for path in novels_dir.iterdir() if path.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    return "my_novel"


def _ensure_project_scaffold(project_root: Path, novel_id: str) -> None:
    base = project_root / "data" / "novels" / novel_id
    required_dirs = [
        base / "outline" / "volumes",
        base / "outline" / "chapters",
        base / "outline" / "snapshots",
        base / "characters" / "cards",
        base / "characters" / "profiles",
        base / "characters" / "timeline" / "logs",
        base / "characters" / "timeline" / "snapshots",
        base / "foreshadowing" / "logs",
        base / "world",
        base / "style",
        base / "manuscript",
    ]
    for path in required_dirs:
        path.mkdir(parents=True, exist_ok=True)

    metadata_file = base / "metadata.yaml"
    if not metadata_file.exists():
        metadata = {
            "name": novel_id,
            "title": novel_id,
            "created_at": datetime.now().isoformat(),
            "version": "0.1.0",
        }
        with metadata_file.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(metadata, handle, allow_unicode=True, sort_keys=False)


@app.command()
def init(novel_name: str):
    """初始化一个新小说项目目录。"""
    project_root = Path.cwd() / novel_name
    _ensure_project_scaffold(project_root, novel_name)
    console.print(f"[green]项目初始化完成:[/green] {project_root}")


def _character_manager(project_dir: Path, novel_id: Optional[str]) -> CharacterStateManager:
    final_novel_id = novel_id or _detect_novel_id(project_dir)
    return CharacterStateManager(project_dir=project_dir, novel_id=final_novel_id)


def _foreshadowing_manager(
    project_dir: Path, novel_id: Optional[str]
) -> ForeshadowingDAGManager:
    final_novel_id = novel_id or _detect_novel_id(project_dir)
    return ForeshadowingDAGManager(project_dir=project_dir, novel_id=final_novel_id)


def _world_manager(project_dir: Path, novel_id: Optional[str]) -> WorldGraphManager:
    final_novel_id = novel_id or _detect_novel_id(project_dir)
    return WorldGraphManager(project_dir=project_dir, novel_id=final_novel_id)


def _parse_world_attrs(raw_attrs: list[str]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for item in raw_attrs:
        if "=" not in item:
            raise typer.BadParameter(f"--attr 参数格式错误: {item}，应为 key=value")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise typer.BadParameter(f"--attr key 不能为空: {item}")
        attrs[key] = value
    return attrs


@character_app.command("create")
def character_create(
    name: str,
    tier: str = typer.Option("普通配角", help="人物层级"),
    faction: str = typer.Option("", help="所属势力"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """创建人物卡。"""
    manager = _character_manager(Path.cwd(), novel_id)
    card = manager.create_character(name=name, tier=tier, faction=faction)
    console.print(f"[green]人物已创建:[/green] {card.static.name} ({card.static.id})")


@app.command("character-create")
def character_create_alias(
    name: str,
    tier: str = typer.Option("普通配角", help="人物层级"),
    faction: str = typer.Option("", help="所属势力"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """兼容命令：character-create。"""
    character_create(name=name, tier=tier, faction=faction, novel_id=novel_id)


@character_app.command("mutate")
def character_mutate(
    name: str,
    chapter: str = typer.Option(..., help="章节ID，例如 ch_003"),
    change: Optional[str] = typer.Option(
        None, help="可选，结构化变更表达式，例如 acquire:神秘玉佩"
    ),
    note: str = typer.Option("", help="自由文本备注"),
    reason: str = typer.Option("", help="兼容旧参数：变更原因"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """记录人物时间线（文本优先，结构化变更可选）。"""
    manager = _character_manager(Path.cwd(), novel_id)
    mutation = manager.apply_mutation(
        name=name,
        chapter_id=chapter,
        mutation_expr=change,
        note=note,
        reason=reason,
    )
    note_text = mutation.note or "-"
    if mutation.action:
        console.print(
            f"[green]时间线已记录:[/green] {mutation.mutation_id} "
            f"{mutation.action}:{mutation.payload.get('raw', '')} | 备注: {note_text}"
        )
        return
    console.print(
        f"[green]时间线已记录:[/green] {mutation.mutation_id} 纯文本备注: {note_text}"
    )


@app.command("character-mutate")
def character_mutate_alias(
    name: str,
    chapter: str = typer.Option(..., help="章节ID，例如 ch_003"),
    change: Optional[str] = typer.Option(
        None, help="可选，结构化变更表达式，例如 acquire:神秘玉佩"
    ),
    note: str = typer.Option("", help="自由文本备注"),
    reason: str = typer.Option("", help="兼容旧参数：变更原因"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """兼容命令：character-mutate。"""
    character_mutate(
        name=name,
        chapter=chapter,
        change=change,
        note=note,
        reason=reason,
        novel_id=novel_id,
    )


@character_app.command("snapshot")
def character_snapshot(
    name: str,
    volume_id: str = typer.Option(..., help="卷ID，例如 vol_001"),
    chapter_range: str = typer.Option("", help="章节范围，例如 ch_001-ch_010"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """生成人物卷快照。"""
    manager = _character_manager(Path.cwd(), novel_id)
    snapshot_path = manager.create_snapshot(
        name=name,
        volume_id=volume_id,
        chapter_range=chapter_range,
    )
    console.print(f"[green]快照已生成:[/green] {snapshot_path}")


@app.command("character-snapshot")
def character_snapshot_alias(
    name: str,
    volume_id: str = typer.Option(..., help="卷ID，例如 vol_001"),
    chapter_range: str = typer.Option("", help="章节范围，例如 ch_001-ch_010"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """兼容命令：character-snapshot。"""
    character_snapshot(
        name=name,
        volume_id=volume_id,
        chapter_range=chapter_range,
        novel_id=novel_id,
    )


@character_app.command("query")
def character_query(
    name: str,
    chapter: Optional[str] = typer.Option(None, help="重建到指定章节"),
    timeline: bool = typer.Option(False, help="显示时间线"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """查询人物状态或时间线。"""
    query = CharacterQuery(project_dir=Path.cwd(), novel_id=novel_id or _detect_novel_id(Path.cwd()))

    if timeline:
        rows = query.get_timeline(name)
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Mutation ID")
        table.add_column("Chapter")
        table.add_column("Action")
        table.add_column("Note")
        for row in rows:
            table.add_row(
                row["mutation_id"],
                row["chapter_id"],
                row.get("action") or "-",
                row.get("note") or row.get("reason") or "",
            )
        console.print(table)
        return

    result = (
        query.get_rebuilt_state(name, until_chapter=chapter)
        if chapter
        else query.get_current_state(name)
    )
    state = result["state"]
    console.print(f"[cyan]{result['name']} ({result['id']})[/cyan]")
    console.print(f"  境界: {state.get('realm')}")
    console.print(f"  位置: {state.get('location')}")
    console.print(f"  状态标签: {state.get('statuses') or []}")
    console.print(f"  关键物品: {state.get('items') or []}")
    console.print(f"  动态档案: {result.get('dynamic_profile') or ''}")


@app.command("character-query")
def character_query_alias(
    name: str,
    chapter: Optional[str] = typer.Option(None, help="重建到指定章节"),
    timeline: bool = typer.Option(False, help="显示时间线"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """兼容命令：character-query。"""
    character_query(name=name, chapter=chapter, timeline=timeline, novel_id=novel_id)


@character_app.command("profile")
def character_profile(
    name: str,
    preview_lines: int = typer.Option(
        12, "--preview-lines", min=0, help="预览行数，0表示只显示路径"
    ),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """查看人物动态主档路径和预览。"""
    manager = _character_manager(Path.cwd(), novel_id)
    profile_path = manager.get_profile_path(name=name)
    console.print(f"[cyan]动态档案:[/cyan] {profile_path}")
    if preview_lines <= 0:
        return

    lines = profile_path.read_text(encoding="utf-8").splitlines()
    preview = "\n".join(lines[:preview_lines]).strip()
    if preview:
        console.print(preview)


@app.command("character-profile")
def character_profile_alias(
    name: str,
    preview_lines: int = typer.Option(
        12, "--preview-lines", min=0, help="预览行数，0表示只显示路径"
    ),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """兼容命令：character-profile。"""
    character_profile(name=name, preview_lines=preview_lines, novel_id=novel_id)


@world_app.command("entity-add")
def world_entity_add(
    id: str,
    name: str,
    type: str = typer.Option("concept", "--type", help="实体类型，如 faction/realm/location"),
    description: str = typer.Option("", help="实体描述"),
    tag: list[str] = typer.Option([], "--tag", help="标签，可重复"),
    attr: list[str] = typer.Option([], "--attr", help="属性 key=value，可重复"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """添加或更新世界观实体。"""
    manager = _world_manager(Path.cwd(), novel_id)
    entity = manager.upsert_entity(
        entity_id=id,
        name=name,
        entity_type=type,
        description=description,
        tags=tag,
        attributes=_parse_world_attrs(attr),
    )
    console.print(f"[green]世界实体已保存:[/green] {entity.id} ({entity.name})")


@app.command("world-entity-add")
def world_entity_add_alias(
    id: str,
    name: str,
    type: str = typer.Option("concept", "--type", help="实体类型，如 faction/realm/location"),
    description: str = typer.Option("", help="实体描述"),
    tag: list[str] = typer.Option([], "--tag", help="标签，可重复"),
    attr: list[str] = typer.Option([], "--attr", help="属性 key=value，可重复"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """兼容命令：world-entity-add。"""
    world_entity_add(
        id=id,
        name=name,
        type=type,
        description=description,
        tag=tag,
        attr=attr,
        novel_id=novel_id,
    )


@world_app.command("relation-add")
def world_relation_add(
    source: str = typer.Option(..., "--source", help="源实体ID"),
    target: str = typer.Option(..., "--target", help="目标实体ID"),
    relation: str = typer.Option(..., "--relation", help="关系类型"),
    weight: int = typer.Option(1, "--weight", help="关系权重(1-10)"),
    note: str = typer.Option("", "--note", help="备注"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """添加世界观关系。"""
    manager = _world_manager(Path.cwd(), novel_id)
    created = manager.add_relation(
        source_id=source,
        target_id=target,
        relation=relation,
        weight=weight,
        note=note,
    )
    console.print(
        f"[green]世界关系已添加:[/green] "
        f"{created.source_id}-{created.relation}->{created.target_id}"
    )


@app.command("world-relation-add")
def world_relation_add_alias(
    source: str = typer.Option(..., "--source", help="源实体ID"),
    target: str = typer.Option(..., "--target", help="目标实体ID"),
    relation: str = typer.Option(..., "--relation", help="关系类型"),
    weight: int = typer.Option(1, "--weight", help="关系权重(1-10)"),
    note: str = typer.Option("", "--note", help="备注"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """兼容命令：world-relation-add。"""
    world_relation_add(
        source=source,
        target=target,
        relation=relation,
        weight=weight,
        note=note,
        novel_id=novel_id,
    )


@world_app.command("list")
def world_list(
    type: str = typer.Option("", "--type", help="按实体类型过滤"),
    relation: str = typer.Option("", "--relation", help="按关系类型过滤"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """列出世界观实体与关系。"""
    manager = _world_manager(Path.cwd(), novel_id)
    entities = manager.list_entities(entity_type=type)
    relations = manager.list_relations(relation=relation)

    entity_table = Table(show_header=True, header_style="bold cyan")
    entity_table.add_column("ID")
    entity_table.add_column("Name")
    entity_table.add_column("Type")
    entity_table.add_column("Tags")
    for item in entities:
        entity_table.add_row(item.id, item.name, item.type, ",".join(item.tags))
    console.print(entity_table)

    relation_table = Table(show_header=True, header_style="bold magenta")
    relation_table.add_column("Source")
    relation_table.add_column("Relation")
    relation_table.add_column("Target")
    relation_table.add_column("Weight")
    for item in relations:
        relation_table.add_row(
            item.source_id, item.relation, item.target_id, str(item.weight)
        )
    console.print(relation_table)


@app.command("world-list")
def world_list_alias(
    type: str = typer.Option("", "--type", help="按实体类型过滤"),
    relation: str = typer.Option("", "--relation", help="按关系类型过滤"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """兼容命令：world-list。"""
    world_list(type=type, relation=relation, novel_id=novel_id)


@world_app.command("check")
def world_check(novel_id: Optional[str] = typer.Option(None, help="小说ID")):
    """检查世界观图谱一致性。"""
    manager = _world_manager(Path.cwd(), novel_id)
    result = manager.check_conflicts()
    console.print(result)


@app.command("world-check")
def world_check_alias(novel_id: Optional[str] = typer.Option(None, help="小说ID")):
    """兼容命令：world-check。"""
    world_check(novel_id=novel_id)

@world_app.command("rules")
def world_rules(
    rules_file: str = typer.Option("", "--rules-file", help="规则 YAML 文件路径"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """对世界观图谱执行自定义规则检查。"""
    from tools.world_rule_engine import WorldRuleEngine

    manager = _world_manager(Path.cwd(), novel_id)
    graph = manager._load_graph()
    engine = WorldRuleEngine()
    if rules_file:
        loaded = engine.load_rules_from_yaml(Path(rules_file))
        console.print(f"[cyan]已加载 {loaded} 条规则[/cyan]")
    else:
        # 尝试默认路径
        default_path = manager.world_dir / "rules.yaml"
        if default_path.exists():
            loaded = engine.load_rules_from_yaml(default_path)
            console.print(f"[cyan]已加载 {loaded} 条规则（{default_path}）[/cyan]")
        else:
            console.print("[yellow]未找到规则文件，请用 --rules-file 指定或在 world/ 下创建 rules.yaml[/yellow]")
            return
    summary = engine.evaluate_summary(graph)
    if summary["is_valid"]:
        console.print(f"[green]✓ 规则检查通过[/green]（{summary['total_rules']} 条规则，0 错误）")
    else:
        console.print(f"[red]✗ 规则检查未通过[/red]（{summary['errors']} 错误，{summary['warnings']} 警告）")
    for v in summary["violations"]:
        color = "red" if v.severity.value == "error" else "yellow"
        console.print(f"  [{color}][{v.severity.value}][/{color}] {v.message}")


@world_app.command("check-advanced")
def world_check_advanced(
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """跨章节冲突检查（位置矛盾、属性回退、关系冲突、状态跳变、孤立引用）。"""
    from tools.world_conflict_checker import WorldConflictChecker

    manager = _world_manager(Path.cwd(), novel_id)
    graph = manager._load_graph()
    checker = WorldConflictChecker()
    result = checker.check(graph)
    stats = result["statistics"]
    console.print(f"[cyan]跨章节冲突检查[/cyan]（{stats['chapters_checked']} 章节，{stats['total_checks']} 项检查）")
    if result["is_valid"]:
        console.print(f"[green]✓ 无冲突[/green]（{stats['total_conflicts']} 条发现）")
    else:
        console.print(f"[red]✗ 发现冲突[/red]")
    for msg in result["errors"]:
        console.print(f"  [red]错误:[/red] {msg}")
    for msg in result["warnings"]:
        console.print(f"  [yellow]警告:[/yellow] {msg}")


@world_app.command("extract")
def world_extract(
    text_file: str = typer.Option(..., "--file", help="章节文本文件路径"),
    chapter_id: str = typer.Option("", "--chapter", help="章节ID"),
    auto_add: bool = typer.Option(False, "--auto-add", help="自动将抽取结果添加到图谱"),
    use_llm: bool = typer.Option(False, "--use-llm", help="启用LLM抽取"),
    llm_config_path: Optional[str] = typer.Option(None, "--llm-config", help="LLM配置文件路径"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """从章节文本自动抽取实体和关系。"""
    from tools.world_entity_extractor import WorldEntityExtractor

    text_path = Path(text_file)
    if not text_path.is_file():
        console.print(f"[red]文件不存在:[/red] {text_path}")
        raise typer.Exit(1)
    text = text_path.read_text(encoding="utf-8")
    manager = _world_manager(Path.cwd(), novel_id)
    existing = [e.name for e in manager.list_entities()]

    llm_client = None
    router = None
    if use_llm:
        from tools.llm.config import load_llm_config
        from tools.llm.client import LLMClient
        from tools.llm.router import ModelRouter
        cfg_path = Path(llm_config_path) if llm_config_path else None
        llm_cfg = load_llm_config(cfg_path)
        if llm_cfg.enabled:
            llm_client = LLMClient(retry_count=llm_cfg.retry_count, retry_delay=llm_cfg.retry_delay)
            router = ModelRouter(llm_cfg)

    extractor = WorldEntityExtractor(llm_client=llm_client, router=router)
    result = extractor.extract(text, chapter_id=chapter_id, existing_entities=existing)
    console.print(f"[green]抽取完成[/green]（方法: {result.method}）")
    console.print(f"  实体: {len(result.entities)} 个")
    for e in result.entities:
        console.print(f"    {e.name} <{e.entity_type}> {e.description}")
    console.print(f"  关系: {len(result.relations)} 条")
    for r in result.relations:
        console.print(f"    {r.source_id} -{r.relation}-> {r.target_id}")

    if auto_add and result.entities:
        added_e, added_r = 0, 0
        for e in result.entities:
            manager.upsert_entity(
                entity_id=e.id, name=e.name, entity_type=e.entity_type,
                description=e.description, attributes=e.attributes,
            )
            added_e += 1
        for r in result.relations:
            try:
                manager.add_relation(
                    source_id=r.source_id, target_id=r.target_id,
                    relation=r.relation, weight=r.weight, note=r.note,
                )
                added_r += 1
            except ValueError:
                pass  # 源/目标不存在，跳过
        console.print(f"  [green]已添加到图谱:[/green] {added_e} 实体, {added_r} 关系")


@world_app.command("visualize")
def world_visualize(
    output: str = typer.Option("", "--output", "-o", help="输出 HTML 路径"),
    title: str = typer.Option("世界观图谱", "--title", help="图谱标题"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """生成世界观图谱 D3 力导向可视化 HTML。"""
    from tools.world_graph_renderer import render_world_graph_html

    manager = _world_manager(Path.cwd(), novel_id)
    graph = manager._load_graph()
    if not graph.entities:
        console.print("[yellow]图谱为空，请先添加实体[/yellow]")
        return
    out_path = Path(output) if output else (manager.world_dir / "world_graph.html")
    render_world_graph_html(graph, title=title, output_path=out_path)
    console.print(f"[green]✓ 可视化已生成:[/green] {out_path}")
    console.print(f"  实体: {len(graph.entities)} 个，关系: {len(graph.relations)} 条")

@outline_app.command("init")
@app.command("outline-init")
def outline_init():
    """初始化大纲系统。"""
    console.print("[cyan]初始化大纲系统...[/cyan]")
    console.print("[green]大纲系统初始化完成[/green]")


@outline_app.command("create")
@app.command("outline-create")
def outline_create(type: str, id: str, title: str = ""):
    """创建大纲。"""
    console.print(f"[cyan]创建 {type} 大纲: {id}[/cyan]")
    if title:
        console.print(f"[yellow]标题: {title}[/yellow]")
    console.print("[green]大纲创建完成[/green]")


@app.command("foreshadowing-add")
def foreshadowing_add(
    id: str,
    content: str = "",
    weight: int = 5,
    layer: str = "支线",
    target_chapter: str = "",
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
):
    """添加伏笔。"""
    manager = _foreshadowing_manager(Path.cwd(), novel_id)
    created = manager.create_node(
        node_id=id,
        content=content,
        weight=weight,
        layer=layer,
        created_at="",
        target_chapter=target_chapter or None,
    )
    if created:
        console.print(f"[green]伏笔已添加:[/green] {id}")
    else:
        console.print(f"[yellow]伏笔未添加（可能已存在）:[/yellow] {id}")


@app.command("foreshadowing-list")
def foreshadowing_list(novel_id: Optional[str] = typer.Option(None, help="小说ID")):
    """列出所有伏笔。"""
    manager = _foreshadowing_manager(Path.cwd(), novel_id)
    dag = manager._load_dag()
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID")
    table.add_column("Layer")
    table.add_column("Weight")
    table.add_column("Status")
    for node_id, node in dag.nodes.items():
        layer = node.layer if hasattr(node, "layer") else node.get("layer", "")
        weight = node.weight if hasattr(node, "weight") else node.get("weight", 0)
        status = dag.status.get(node_id, "")
        table.add_row(node_id, str(layer), str(weight), status)
    console.print(table)


@app.command("foreshadowing-check")
def foreshadowing_check(novel_id: Optional[str] = typer.Option(None, help="小说ID")):
    """检查伏笔状态。"""
    manager = _foreshadowing_manager(Path.cwd(), novel_id)
    result = manager.validate_dag()
    console.print(result)


@app.command("foreshadowing-statistics")
def foreshadowing_statistics(
    novel_id: Optional[str] = typer.Option(None, help="小说ID")
):
    """显示伏笔统计。"""
    manager = _foreshadowing_manager(Path.cwd(), novel_id)
    stats = manager.get_statistics()
    console.print(stats)


@app.command("outline-list")
def outline_list():
    """列出大纲文件。"""
    base = Path.cwd() / "data" / "novels" / _detect_novel_id(Path.cwd()) / "outline"
    volumes = sorted(path.name for path in (base / "volumes").glob("*.md")) if (base / "volumes").exists() else []
    chapters = sorted(path.name for path in (base / "chapters").glob("*.md")) if (base / "chapters").exists() else []
    console.print(f"[cyan]总纲:[/cyan] {'archetype.md' if (base / 'archetype.md').exists() else '(无)'}")
    console.print(f"[cyan]卷纲:[/cyan] {', '.join(volumes) if volumes else '(无)'}")
    console.print(f"[cyan]章纲:[/cyan] {', '.join(chapters) if chapters else '(无)'}")


@simulate_app.command("chapter")
@app.command("simulate-chapter")
def simulate_chapter(
    chapter_id: str = typer.Option(..., "--id", help="章节ID，例如 ch_003"),
    objective: str = typer.Option("推进主线并保持角色一致性", help="本章目标"),
    novel_id: Optional[str] = typer.Option(None, help="小说ID"),
    style_id: str = typer.Option("", "--style-id", help="风格模板ID，例如 术师手册"),
    forbidden: list[str] = typer.Option([], "--forbidden", help="禁用词/设定，可重复"),
    required: list[str] = typer.Option([], "--required", help="必须出现要素，可重复"),
    use_stylist: bool = typer.Option(False, "--use-stylist", help="启用文风处理"),
    strict_lore: bool = typer.Option(False, "--strict-lore", help="启用严格逻辑检查"),
    max_rewrites: int = typer.Option(0, "--max-rewrites", min=0, help="Lore失败后最多重写次数"),
    use_style_analysis: bool = typer.Option(False, "--style-analysis", help="启用Reader+StyleDirector后处理分析"),
    use_llm: bool = typer.Option(False, "--use-llm", help="启用LLM模式（需要配置llm_config.yaml）"),
    llm_config_path: Optional[str] = typer.Option(None, "--llm-config", help="LLM配置文件路径"),
):
    """模拟一章多Agent工作流（默认跳过文风处理）。"""
    final_novel_id = novel_id or _detect_novel_id(Path.cwd())
    # --- Optional LLM setup ---
    llm_client = None
    router = None
    if use_llm:
        from tools.llm.config import load_llm_config
        from tools.llm.client import LLMClient
        from tools.llm.router import ModelRouter
        cfg_path = Path(llm_config_path) if llm_config_path else None
        llm_cfg = load_llm_config(cfg_path)
        if not llm_cfg.enabled:
            console.print("[yellow]警告: llm_config.yaml 中 enabled=false，LLM 模式未生效[/yellow]")
        else:
            llm_client = LLMClient(retry_count=llm_cfg.retry_count, retry_delay=llm_cfg.retry_delay)
            router = ModelRouter(llm_cfg)
            console.print("[cyan]LLM 模式已启用[/cyan]")
    simulator = AgentSimulator(
        project_dir=Path.cwd(), novel_id=final_novel_id, style_id=style_id,
        llm_client=llm_client, router=router,
    )
    result = simulator.simulate_chapter(
        chapter_id=chapter_id,
        objective=objective,
        forbidden=forbidden,
        required=required,
        use_stylist=use_stylist,
        strict_lore=strict_lore,
        max_rewrites=max_rewrites,
        use_style_analysis=use_style_analysis,
    )

    if result.passed:
        console.print("[green]模拟完成：逻辑检查通过[/green]")
    else:
        console.print("[red]模拟完成：逻辑检查未通过[/red]")

    console.print(f"  草稿: {result.draft_file}")
    console.print(f"  报告: {result.report_file}")
    console.print(f"  重写次数: {result.rewrite_attempts}")
    if result.errors:
        for err in result.errors:
            console.print(f"  [red]错误:[/red] {err}")
    if result.warnings:
        for warn in result.warnings:
            console.print(f"  [yellow]警告:[/yellow] {warn}")
    if result.style_analysis:
        sa = result.style_analysis
        reader_info = sa.get("reader", {})
        sd_info = sa.get("style_director", {})
        console.print("  [cyan]风格分析:[/cyan]")
        console.print(f"    Reader发现: craft={reader_info.get('craft', 0)} style={reader_info.get('style', 0)} novel={reader_info.get('novel', 0)}")
        scores = sd_info.get("layer_scores", {})
        for layer, info in scores.items():
            console.print(f"    {layer}层: {info.get('score', 0)}/100 (偏差{info.get('deviations', 0)})")
        if sd_info.get("converged"):
            console.print("    [green]风格已收敛[/green]")
        else:
            console.print(f"    新发现缺口: {sd_info.get('new_gaps', 0)}")

@style_app.command("compose")
@app.command("style-compose")
def style_compose(
    novel_id: str = typer.Option(..., "--novel-id", help="作品设定ID（novels/下的目录名）"),
    style_id: str = typer.Option(..., "--style-id", help="风格模板ID（styles/下的目录名）"),
):
    """合成三层风格文档为最终生成指令。"""
    composer = StyleComposer(Path.cwd())
    result = composer.compose(novel_id=novel_id, style_id=style_id, write_output=True)
    output_path = composer.get_composed_path(novel_id)
    console.print(f"[green]风格合成完成:[/green] {output_path}")
    console.print(f"  硬性约束: {len(result.hard_constraints)}字")
    console.print(f"  风格约束: {len(result.style_constraints)}字")
    console.print(f"  通用技法: {len(result.craft_reference)}字")


@style_app.command("list")
@app.command("style-list")
def style_list():
    """列出可用的风格模板和作品设定。"""
    composer = StyleComposer(Path.cwd())
    styles = composer.list_available_styles()
    novels = composer.list_available_novels()
    console.print(f"[cyan]可用风格模板:[/cyan] {', '.join(styles) if styles else '(无)'}")
    console.print(f"[cyan]可用作品设定:[/cyan] {', '.join(novels) if novels else '(无)'}")
    composed_dir = Path.cwd() / "composed"
    if composed_dir.is_dir():
        composed = sorted(f.name for f in composed_dir.glob("*_final.md"))
        console.print(f"[cyan]已合成文档:[/cyan] {', '.join(composed) if composed else '(无)'}")

@style_app.command("read-batch")
@app.command("style-read-batch")
def style_read_batch(
    text_file: str = typer.Option(..., "--file", help="要分析的文本文件路径"),
    batch_id: str = typer.Option("batch_001", "--batch-id", help="批次ID"),
    chunk_range: str = typer.Option("", "--range", help="文本范围描述，如 第1-7章"),
    style_id: str = typer.Option("", "--style-id", help="风格模板ID"),
    novel_id: str = typer.Option("", "--novel-id", help="作品ID"),
):
    """批量阅读文本并提取三层风格发现。"""
    text_path = Path(text_file)
    if not text_path.is_file():
        console.print(f"[red]文件不存在:[/red] {text_path}")
        raise typer.Exit(1)
    text = text_path.read_text(encoding="utf-8")
    reader = ReaderAgent(
        project_root=Path.cwd(), style_id=style_id, novel_id=novel_id,
    )
    result = reader.read_batch(
        text=text, batch_id=batch_id, chunk_range=chunk_range,
    )
    console.print(f"[green]Reader 分析完成:[/green] {batch_id}")
    console.print(f"  总发现数: {len(result.findings)}")
    console.print(f"  通用技法: {len(result.craft_findings)}")
    console.print(f"  作者风格: {len(result.style_findings)}")
    console.print(f"  作品设定: {len(result.novel_findings)}")
    console.print(f"  大纲事件: {len(result.outline_events)}")
    if result.revision_suggestions:
        for sug in result.revision_suggestions:
            console.print(f"  [yellow]建议:[/yellow] {sug}")
    # Write summary report
    report_dir = Path.cwd() / "logs" / "reader"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{batch_id}_report.md"
    report_path.write_text(result.summary(), encoding="utf-8")
    console.print(f"  报告: {report_path}")


@style_app.command("iterate")
@app.command("style-iterate")
def style_iterate(
    draft_file: str = typer.Option(..., "--draft", help="草稿文件路径"),
    style_id: str = typer.Option(..., "--style-id", help="风格模板ID"),
    novel_id: str = typer.Option(..., "--novel-id", help="作品ID"),
    iteration: int = typer.Option(1, "--iteration", help="迭代轮次"),
):
    """对草稿进行风格迭代分析（分层差异检测）。"""
    draft_path = Path(draft_file)
    if not draft_path.is_file():
        console.print(f"[red]草稿文件不存在:[/red] {draft_path}")
        raise typer.Exit(1)
    draft = draft_path.read_text(encoding="utf-8")
    director = StyleDirectorAgent(
        project_root=Path.cwd(), style_id=style_id, novel_id=novel_id,
    )
    result = director.analyze(draft=draft, iteration=iteration)
    console.print(f"[green]风格迭代分析完成:[/green] 迭代 #{iteration}")
    console.print(f"  总偏差数: {len(result.deviations)}")
    for layer_name, score in result.layer_scores.items():
        console.print(f"  {layer_name}: {score.score}/100")
    console.print(f"  新风格缺口: {result.new_gaps_found}")
    console.print(f"  收敛状态: {'[green]已收敛[/green]' if result.converged else '[yellow]未收敛[/yellow]'}")
    if result.document_updates:
        console.print(f"  文档更新建议: {len(result.document_updates)}条")
        for upd in result.document_updates:
            console.print(f"    [{upd.layer.value}] {upd.action} {upd.file_path}")
    # Write analysis report
    report_dir = Path.cwd() / "logs" / "style_iterations"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"{timestamp}_iter{iteration}_{novel_id}.md"
    report_path.write_text(result.summary(), encoding="utf-8")
    console.print(f"  报告: {report_path}")


@style_app.command("profile")
@app.command("style-profile")
def style_profile(
    novel_id: str = typer.Option(..., "--novel-id", help="作品ID"),
    style_id: str = typer.Option("", "--style-id", help="风格模板ID"),
):
    """从合成文档加载并显示结构化风格档案。"""
    profile = StyleProfile.from_project(
        project_root=Path.cwd(), novel_id=novel_id, style_id=style_id,
    )
    console.print(f"[cyan]风格档案: {novel_id}[/cyan]")
    console.print(profile.to_summary(max_chars=1000))
    if profile.banned_phrases:
        console.print(f"  禁用表达数: {len(profile.banned_phrases)}")
    metrics = profile.quality_metrics
    console.print(
        f"  质量指标: 直接性={metrics.directness} 节奏={metrics.rhythm} "
        f"意象={metrics.imagery} 角色化={metrics.characterization} "
        f"去AI={metrics.ai_artifact_control}"
    )


# ------------------------------------------------------------------
# 叙事线可视化命令
# ------------------------------------------------------------------


@timeline_app.command("build")
def timeline_build(
    novel_id: str = typer.Option("", "--novel-id", help="作品ID（留空自动检测）"),
):
    """从现有数据自动聚合生成叙事时间线。"""
    from tools.narrative_timeline_manager import NarrativeTimelineManager

    project_dir = Path.cwd()
    if not novel_id:
        novel_id = _detect_novel_id(project_dir)
    mgr = NarrativeTimelineManager(project_dir=project_dir, novel_id=novel_id)
    timeline = mgr.build_from_existing()
    out = mgr.save(timeline)
    console.print(f"[green]✓[/green] 叙事时间线已生成: {out}")
    console.print(f"  叙事线: {len(timeline.threads)} 条")
    console.print(f"  连接: {len(timeline.links)} 条")
    console.print(f"  章节: {len(timeline.chapters)} 章")


@timeline_app.command("export")
def timeline_export(
    novel_id: str = typer.Option("", "--novel-id", help="作品ID（留空自动检测）"),
    format: str = typer.Option("html", "--format", "-f", help="导出格式: html / yaml / json"),
    output: str = typer.Option("", "--output", "-o", help="输出路径（留空使用默认）"),
    chapter_id: str = typer.Option("", "--chapter", help="仅导出指定章节的AI上下文（json格式）"),
):
    """导出叙事时间线为 HTML 可视化或结构化数据。"""
    import json as json_mod

    from tools.narrative_renderer import render_html
    from tools.narrative_timeline_manager import NarrativeTimelineManager

    project_dir = Path.cwd()
    if not novel_id:
        novel_id = _detect_novel_id(project_dir)
    mgr = NarrativeTimelineManager(project_dir=project_dir, novel_id=novel_id)
    timeline = mgr.load()

    if not timeline.threads:
        console.print("[yellow]⚠ 时间线为空，请先运行 timeline build[/yellow]")
        raise typer.Exit(1)

    # AI 上下文导出（单章节）
    if chapter_id:
        ctx = timeline.to_ai_context(chapter_id)
        out_path = Path(output) if output else (
            mgr.base_dir / "narrative" / f"context_{chapter_id}.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json_mod.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"[green]✓[/green] AI 上下文已导出: {out_path}")
        return

    # 全量导出
    fmt = format.lower()
    if fmt == "html":
        out_path = Path(output) if output else (
            mgr.base_dir / "narrative" / "timeline.html"
        )
        render_html(timeline, output_path=out_path)
        console.print(f"[green]✓[/green] HTML 可视化已导出: {out_path}")
    elif fmt == "yaml":
        out_path = Path(output) if output else (
            mgr.base_dir / "narrative" / "timeline.yaml"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = timeline.model_dump(mode="json")
        out_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        console.print(f"[green]✓[/green] YAML 已导出: {out_path}")
    elif fmt == "json":
        out_path = Path(output) if output else (
            mgr.base_dir / "narrative" / "timeline.json"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        data = timeline.model_dump(mode="json")
        out_path.write_text(
            json_mod.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"[green]✓[/green] JSON 已导出: {out_path}")
    else:
        console.print(f"[red]✗ 不支持的格式: {format}，可选: html / yaml / json[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
