#!/usr/bin/env python3
"""项目初始化脚本

创建必需的目录结构和初始文件

目录结构:
- src/ - 人类编辑的 source of truth
    - outline.md - 大纲源文件
  - characters/*.md - 角色源文件
  - world/*.md - 世界源文件
- data/ - 机器生成的运行时文件
  - hierarchy.yaml - 从 src/outline.md 生成
  - characters/cards/*.yaml - 从 src/characters/*.md 生成
  - foreshadowing/, workflows/, world/, compressed/, snapshots/
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tools.frontmatter import compose_toml_document

NOVEL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}")
PROJECT_TEMPLATES = {"default", "demo_short"}


def validate_novel_id(novel_id: str) -> str:
    """Return a normalized project ID or reject unsafe filesystem input."""
    value = str(novel_id or "").strip()
    if not NOVEL_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "小说 ID 必须为 2-64 位字母、数字、下划线或连字符，且不能包含路径"
        )
    return value


def init_project(
    project_root: Path,
    novel_id: str,
    title: str | None = None,
    *,
    template: str = "default",
):
    """Validate and initialize a project with best-effort failure rollback."""
    root = Path(project_root)
    clean_id = validate_novel_id(novel_id)
    if template not in PROJECT_TEMPLATES:
        raise ValueError(f"不支持的项目模板: {template}")

    config_path = root / "novel_config.yaml"
    if config_path.is_file():
        try:
            existing_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError("现有 novel_config.yaml 无法读取") from exc
        existing_id = (
            str(existing_config.get("novel_id") or "").strip()
            if isinstance(existing_config, dict)
            else ""
        )
        if existing_id and existing_id != clean_id:
            raise ValueError(
                f"项目已经绑定小说 ID {existing_id}，不能初始化为 {clean_id}"
            )

    snapshot = _initialization_snapshot(root, clean_id)
    try:
        result = _init_project_impl(root, clean_id, title, template=template)
        from tools.project_registry import initialize_content_git

        initialize_content_git(root)
        return result
    except Exception:
        _rollback_initialization(root, clean_id, snapshot)
        raise


def _initialization_snapshot(
    project_root: Path, novel_id: str
) -> dict[str, object]:
    novel_root = project_root / "data" / "novels" / novel_id
    targets = _initialization_targets(project_root, novel_id)
    files: dict[Path, bytes | None] = {}
    for path in targets:
        files[path] = path.read_bytes() if path.is_file() else None
    existing_dirs = (
        {path for path in novel_root.rglob("*") if path.is_dir()} | {novel_root}
        if novel_root.is_dir()
        else set()
    )
    return {
        "files": files,
        "existing_dirs": existing_dirs,
        "metadata_dir_existed": (project_root / ".openwrite").is_dir(),
        "container_dirs": {
            path: path.is_dir()
            for path in (
                project_root,
                project_root / "data",
                project_root / "data" / "novels",
            )
        },
    }


def _initialization_targets(project_root: Path, novel_id: str) -> list[Path]:
    novel_root = project_root / "data" / "novels" / novel_id
    return [
        project_root / "novel_config.yaml",
        project_root / ".openwrite" / "project.yaml",
        novel_root / "src" / "outline.md",
        novel_root / "src" / "story" / "author_intent.md",
        novel_root / "src" / "story" / "background.md",
        novel_root / "src" / "story" / "foundation.md",
        novel_root / "src" / "story" / "current_focus.md",
        novel_root / "src" / "characters" / "lin_zhou.md",
        novel_root / "src" / "world" / "rules.md",
        novel_root / "src" / "world" / "timeline.md",
        novel_root / "src" / "world" / "terminology.md",
        novel_root / "data" / "hierarchy.yaml",
        novel_root / "data" / "foreshadowing" / "dag.yaml",
        novel_root / "data" / "style" / "fingerprint.yaml",
    ]


def _rollback_initialization(
    project_root: Path, novel_id: str, snapshot: dict[str, object]
) -> None:
    files = snapshot["files"]
    assert isinstance(files, dict)
    for path, content in files.items():
        assert isinstance(path, Path)
        if content is None:
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
            continue
        assert isinstance(content, bytes)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    novel_root = project_root / "data" / "novels" / novel_id
    existing_dirs = snapshot["existing_dirs"]
    assert isinstance(existing_dirs, set)
    if novel_root.is_dir():
        candidates = sorted(
            (path for path in novel_root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        candidates.append(novel_root)
        for path in candidates:
            if path in existing_dirs:
                continue
            try:
                path.rmdir()
            except OSError:
                pass

    metadata_dir = project_root / ".openwrite"
    if not snapshot["metadata_dir_existed"] and metadata_dir.is_dir():
        try:
            metadata_dir.rmdir()
        except OSError:
            pass

    container_dirs = snapshot["container_dirs"]
    assert isinstance(container_dirs, dict)
    for path in reversed(tuple(container_dirs)):
        if container_dirs[path] or not path.is_dir():
            continue
        try:
            path.rmdir()
        except OSError:
            pass


def _init_project_impl(
    project_root: Path,
    novel_id: str,
    title: str | None = None,
    *,
    template: str = "default",
):
    """初始化小说项目

    Args:
        project_root: 项目根目录
        novel_id: 小说ID
        title: 小说标题（可选）
        template: ``default`` 或 ``demo_short``。后者会写入示范资产，
                  便于新用户直接进入写章流程。
    """
    project_root = Path(project_root)
    novel_root = project_root / f"data/novels/{novel_id}"

    src_dirs = [
        novel_root / "src",
        novel_root / "src" / "story",
        novel_root / "src" / "characters",
        novel_root / "src" / "world",
        novel_root / "src" / "world" / "entities",
    ]

    data_dirs = [
        novel_root / "data" / "characters" / "cards",
        novel_root / "data" / "foreshadowing",
        novel_root / "data" / "workflows",
        novel_root / "data" / "world" / "entities",
        novel_root / "data" / "compressed",
        novel_root / "data" / "memory" / "chapters",
        novel_root / "data" / "reviews",
        novel_root / "data" / "snapshots",
        novel_root / "data" / "test_outputs" / "context_packets",
        novel_root / "data" / "test_outputs" / "multi_write",
    ]

    for dir_path in src_dirs + data_dirs:
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"✓ 创建目录: {dir_path.relative_to(project_root)}")

    config_path = project_root / "novel_config.yaml"
    if not config_path.exists():
        title_line = f"title: {title}\n" if title else ""
        config_content = f"""novel_id: {novel_id}
{title_line}style_id: {novel_id}
current_arc: arc_001
current_chapter: ch_001
writing_targets:
  book_words: 100000
  chapter_words: 3000
  outline_volume_words: 800
  outline_act_words: 500
  outline_section_words: 300
  outline_chapter_words: 180
"""
        config_path.write_text(config_content, encoding="utf-8")
        print("✓ 创建配置: novel_config.yaml")

    outline_src_path = novel_root / "src" / "outline.md"
    if not outline_src_path.exists():
        outline_content = """# 大纲

> 核心主题: 待填写
> 故事简介: 待填写，说明主角、核心冲突和整本书的大方向
> 目标字数: 100000

## 第一篇

用普通散文填写本篇主要事件、推进过程和结果。

> 起止章节: ch_001-ch_003

### 开头

用普通散文填写本节主要事件、推进过程和结果。

#### 第一章

> 预估字数: 3000
> 戏剧位置: 待填写
> 内容焦点: 待填写

"""
        outline_src_path.write_text(outline_content, encoding="utf-8")
        print(f"✓ 创建大纲源文件: data/novels/{novel_id}/src/outline.md")

    author_intent_path = novel_root / "src" / "story" / "author_intent.md"
    if not author_intent_path.exists():
        author_intent_path.write_text(
            """# 作者意图

<!-- 这份文件定义整本书长期不变的创作承诺。 -->

## 核心承诺

（待填写：读者为什么要持续追这本书？）

## 题材与目标读者

（待填写）

## 主角与核心矛盾

（待填写）

## 不可妥协

- （待填写：绝不牺牲的体验、主题或人物原则）
""",
            encoding="utf-8",
        )
        print(f"✓ 创建作者意图: data/novels/{novel_id}/src/story/author_intent.md")

    background_path = novel_root / "src" / "story" / "background.md"
    if not background_path.exists():
        background_path.write_text(
            """# 故事背景

## 一句话故事

（待填写：主角在什么处境下，为了什么目标，对抗什么阻力。）

## 核心冲突

（待填写）

## 故事基调

（待填写）
""",
            encoding="utf-8",
        )
        print(f"✓ 创建故事背景: data/novels/{novel_id}/src/story/background.md")

    foundation_path = novel_root / "src" / "story" / "foundation.md"
    if not foundation_path.exists():
        foundation_path.write_text(
            """# 基础设定

## 故事发生的世界

（待填写）

## 核心机制

（待填写）

## 叙事边界

- （待填写：本书不会使用或不能突破的规则）
""",
            encoding="utf-8",
        )
        print(f"✓ 创建基础设定: data/novels/{novel_id}/src/story/foundation.md")

    from tools.novel_workspace import CreativeFocus, current_focus_path, render_creative_focus

    focus_path = current_focus_path(project_root, novel_id)
    if not focus_path.exists():
        focus_path.write_text(render_creative_focus(CreativeFocus()), encoding="utf-8")
        print(f"✓ 创建创作罗盘: data/novels/{novel_id}/src/story/current_focus.md")

    from tools.outline_sync import sync_outline_to_hierarchy
    from tools.project_registry import write_content_project_metadata

    src_dir = novel_root / "src"
    data_dir = novel_root / "data"
    sync_outline_to_hierarchy(src_dir, data_dir)
    print(f"✓ 生成层级文件: data/novels/{novel_id}/data/hierarchy.yaml")
    write_content_project_metadata(project_root)

    rules_path = novel_root / "src" / "world" / "rules.md"
    if not rules_path.exists():
        rules_content = compose_toml_document(
            {
                "id": "world_rules",
                "type": "world_document",
                "summary": "作品的底层规则、限制与未知项。",
                "detail_refs": ["力量体系", "社会规则", "物理法则"],
            },
            """# 世界底层规则

## 力量体系
- （待填充）

## 社会规则
- （待填充）

## 物理法则
- （待填充）
""",
        )
        rules_path.write_text(rules_content, encoding="utf-8")
        print(f"✓ 创建规则: data/novels/{novel_id}/src/world/rules.md")

    timeline_path = novel_root / "src" / "world" / "timeline.md"
    if not timeline_path.exists():
        timeline_content = compose_toml_document(
            {
                "id": "world_timeline",
                "type": "world_document",
                "summary": "作品关键事件的时间顺序记录。",
                "detail_refs": ["时间线"],
            },
            """# 关键事件时间线

| 时间 | 事件 | 涉及章节 | 影响 |
|------|------|----------|------|
| （待填充） | | | |
""",
        )
        timeline_path.write_text(timeline_content, encoding="utf-8")
        print(f"✓ 创建时间线: data/novels/{novel_id}/src/world/timeline.md")

    terminology_path = novel_root / "src" / "world" / "terminology.md"
    if not terminology_path.exists():
        terminology_content = compose_toml_document(
            {
                "id": "world_terminology",
                "type": "world_document",
                "summary": "作品内高频术语与概念定义。",
                "detail_refs": ["术语表"],
            },
            """# 术语表

| 术语 | 定义 | 分类 |
|------|------|------|
| （待填充） | | |
""",
        )
        terminology_path.write_text(terminology_content, encoding="utf-8")
        print(f"✓ 创建术语表: data/novels/{novel_id}/src/world/terminology.md")

    dag_path = novel_root / "data" / "foreshadowing" / "dag.yaml"
    if not dag_path.exists():
        dag_content = """# 伏笔DAG
nodes: {}
edges: []
status: {}
"""
        dag_path.write_text(dag_content, encoding="utf-8")
        print(f"✓ 创建伏笔: data/novels/{novel_id}/data/foreshadowing/dag.yaml")

    style_path = novel_root / "data" / "style" / "fingerprint.yaml"
    style_dir = novel_root / "data" / "style"
    style_dir.mkdir(exist_ok=True)
    if not style_path.exists():
        style_content = """# 作品风格指纹
voice: "待定义"
language_style: "待定义"
rhythm: "待定义"
"""
        style_path.write_text(style_content, encoding="utf-8")
        print(f"✓ 创建风格: data/novels/{novel_id}/data/style/fingerprint.yaml")

    manuscript_dir = novel_root / "data" / "manuscript" / "arc_001"
    manuscript_dir.mkdir(parents=True, exist_ok=True)
    print(f"✓ 创建手稿目录: data/novels/{novel_id}/data/manuscript/arc_001")

    print(f"\n✅ 项目初始化完成: {novel_id}")
    if template == "demo_short":
        _seed_demo_assets(project_root, novel_id, title)
        print("\n下一步:")
        print("1. openwrite studio              # 打开 Studio 配置模型后写第一章")
        print("2. openwrite dante               # CLI 直接推进正文")
        return
    print("\n目录结构:")
    print("  src/           - 人类编辑的源文件 (source of truth)")
    print("    outline.md   - 大纲源文件")
    print("    characters/  - 角色源文件")
    print("    world/       - 世界源文件")
    print("      entities/  - 世界实体源文件")
    print("  data/          - 机器生成的运行时文件")
    print("    hierarchy.yaml - 从 src/outline.md 自动生成")
    print("    characters/cards/ - 生成的角色卡片")
    print("\n下一步:")
    print("1. openwrite goethe   # 先聊书名、冲突、人物与可写大纲")
    print("2. openwrite desk     # 查看资产就绪度与建议")
    print("3. openwrite dante    # 资产就绪后再持续写正文")
    print("4. openwrite studio   # 也可用网页端完成同样流程")


def _seed_demo_assets(project_root: Path, novel_id: str, title: str | None) -> None:
    """写入示范资产，使 demo 项目可立刻进入写章流程。"""
    novel_root = project_root / "data" / "novels" / novel_id
    demo_title = title or "雾城来信"
    story_dir = novel_root / "src" / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "author_intent.md").write_text(
        """# 作者意图

## 核心承诺

在代价面前展现普通人如何主动选择，而不是被命运推着走。

## 题材与目标读者

悬疑 / 都市，面向喜欢克制叙述与情感余味的读者。

## 主角与核心矛盾

林舟：一个在钟表行业摸爬滚打的修表师，必须选择是揭露钟楼秘密，还是继续安稳生活。

## 不可妥协

- 主角必须主动承担代价
- 避免靠新能力突然解围
""",
        encoding="utf-8",
    )
    (story_dir / "background.md").write_text(
        """# 故事背景

## 一句话故事

林舟在祖传钟楼发现少了一拍的钟声，被迫在揭露家族秘密与维持平静之间做选择。

## 核心冲突

钟楼每七十年少响一拍，背后藏着林家与城中另一家族的旧契约。

## 故事基调

克制、冷调，以动作和细节代替情绪直述。
""",
        encoding="utf-8",
    )
    (story_dir / "foundation.md").write_text(
        """# 基础设定

## 故事发生的世界

现代都市，旧城区保留着一座百年钟楼，是林舟家族的最后产业。

## 核心机制

钟声每七十年少响一拍，与林家签订的旧契约同步生效；
少掉的那一拍对应一次必须有人承担的选择。

## 叙事边界

- 不使用超自然能力
- 不出现全知视角
""",
        encoding="utf-8",
    )
    (novel_root / "src" / "characters" / "lin_zhou.md").write_text(
        """# 林舟

性别: 男
年龄: 32
职业: 修表师

## 性格

沉默、谨慎，习惯用行动而不是语言表达。
对外人保持距离，对信任的人会主动承担。

## 核心冲突

在家族秘密与个人安稳之间选择是否揭开真相。
""",
        encoding="utf-8",
    )
    outline_path = novel_root / "src" / "outline.md"
    outline_path.write_text(
        f"""# {demo_title}

> 核心主题: 主动选择与代价
> 故事简介: 修表师林舟在祖传钟楼发现异常，被迫在真相与安稳间抉择
> 目标字数: 9000

## 第一篇

林舟因钟楼异响追查祖父留下的秘密，在家族真相与原有安稳之间作出选择。

> 起止章节: ch_001-ch_003

### 开头

林舟在钟楼值夜时察觉钟声异常，并从祖父留下的日志中找到与异常有关的线索。

#### 第一章 钟声少了一拍

> 预估字数: 3000
> 戏剧位置: 开篇
> 内容焦点: 林舟夜修钟楼，第一次听见少掉的一拍，并发现祖父日志里的空白页

#### 第二章 日志里的空白

> 预估字数: 3000
> 戏剧位置: 发展
> 内容焦点: 林舟调查日志，接触到另一个家族的后人，开始怀疑祖辈契约

#### 第三章 选择之前

> 预估字数: 3000
> 戏剧位置: 收束
> 内容焦点: 林舟在真相与安稳之间做出第一次主动选择
""",
        encoding="utf-8",
    )

    from tools.outline_sync import sync_outline_to_hierarchy

    sync_outline_to_hierarchy(novel_root / "src", novel_root / "data")

    from tools.novel_workspace import CreativeFocus, current_focus_path, render_creative_focus

    focus = CreativeFocus(
        goal="完成第一篇：让林舟主动承担第一次代价",
        must_keep=["克制的叙述视角", "师徒关系的信任裂缝"],
        must_avoid=["靠新能力强行解围"],
    )
    current_focus_path(project_root, novel_id).write_text(
        render_creative_focus(focus), encoding="utf-8"
    )
    print(f"✓ 写入示范资产: {novel_id}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python init_project.py <novel_id> [title]")
        print("示例: python init_project.py my_novel '我的小说'")
        sys.exit(1)

    novel_id = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else None

    project_root = Path(__file__).parent.parent
    init_project(project_root, novel_id, title)
