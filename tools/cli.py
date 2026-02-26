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
    from tools.agents.simulator import AgentSimulator
    from tools.character_state_manager import CharacterStateManager
    from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
    from tools.queries.character_query import CharacterQuery
    from tools.world_graph_manager import WorldGraphManager
except ImportError:  # pragma: no cover - supports legacy path injection
    from agents.simulator import AgentSimulator
    from character_state_manager import CharacterStateManager
    from graph.foreshadowing_dag import ForeshadowingDAGManager
    from queries.character_query import CharacterQuery
    from world_graph_manager import WorldGraphManager


app = typer.Typer(help="OpenWrite - AI辅助小说创作系统")
character_app = typer.Typer(help="人物相关命令")
outline_app = typer.Typer(help="大纲相关命令")
world_app = typer.Typer(help="世界观图谱命令")
simulate_app = typer.Typer(help="多Agent模拟命令")
app.add_typer(character_app, name="character")
app.add_typer(outline_app, name="outline")
app.add_typer(world_app, name="world")
app.add_typer(simulate_app, name="simulate")
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
    forbidden: list[str] = typer.Option([], "--forbidden", help="禁用词/设定，可重复"),
    required: list[str] = typer.Option([], "--required", help="必须出现要素，可重复"),
    use_stylist: bool = typer.Option(False, "--use-stylist", help="启用文风处理"),
    strict_lore: bool = typer.Option(False, "--strict-lore", help="启用严格逻辑检查"),
    max_rewrites: int = typer.Option(0, "--max-rewrites", min=0, help="Lore失败后最多重写次数"),
):
    """模拟一章多Agent工作流（默认跳过文风处理）。"""
    final_novel_id = novel_id or _detect_novel_id(Path.cwd())
    simulator = AgentSimulator(project_dir=Path.cwd(), novel_id=final_novel_id)
    result = simulator.simulate_chapter(
        chapter_id=chapter_id,
        objective=objective,
        forbidden=forbidden,
        required=required,
        use_stylist=use_stylist,
        strict_lore=strict_lore,
        max_rewrites=max_rewrites,
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


if __name__ == "__main__":
    app()
