"""Shared, parser-aligned instructions for agents that write project Markdown."""


INLINE_ANNOTATION_CONTRACT = """## OpenWrite 内联批注契约

用独立一行、且仅在代码围栏之外写入以下机器可读批注：

```text
//**人物[维度]：旧状态 -> 新状态**
//**关系源~>关系目标:具体关系**
```

规则：
- 状态批注记录一次状态迁移；维度必须具体，例如位置、伤势、立场或“与某人关系”。
- `A~>B` 是从 A 指向 B 的有向关系注册，用于当前关系图，不表示关系随时间的变化，
  也不会自动创建 `B~>A`。
- 关系发生演变时使用状态迁移，例如 `//**A[与B关系]：互相戒备 -> 暂时结盟**`。
- 使用 `src/characters/` 与 `src/world/` 中的规范名称或 ID，不使用含糊代称。
- 大纲中的批注必须放在对应章节标题下；无法放入章纲时显式添加 `@ch_070` 章节范围。
- Goethe 在大纲中只登记计划变化；Dante 与 Writer 在正文中只登记本章实际写出的变化，
  不能把未落地计划写成事实。
- 同章同人物同维度同时存在大纲与正文批注时，正文事实优先用于当前状态和连续性判断；
  大纲计划仍保留为历史来源。
- 旧式 `//**A~B:具体关系**` 仅为已有项目读取兼容；不得继续生成，必须写成 `~>`。
- 只有格式完整的有效批注会从字数统计与成书导出中隐藏；无效批注会保留在原文中并报告错误。
"""

OUTLINE_MARKDOWN_CONTRACT = """## OpenWrite 大纲写入契约

凡是生成、补全或修改 `src/outline.md`，必须写成解析器可消费的四级 Markdown，不能只写自然语言梗概：

```markdown
# 作品名

全书梗概，说明主角、核心冲突、主要推进和故事结果。

## 第1篇：篇标题

本篇梗概，说明这一阶段的主要事件、推进过程和结果。

### 第1节：节标题

本节梗概，说明主要事件、推进过程和结果。

#### 第1章：章标题

本章梗概，说明本章实际发生的核心行动、冲突和结果。

> 戏剧位置: 起
> 内容焦点: 本章实际发生的核心行动、冲突和结果
> 本章目标: 建立当前矛盾, 推进人物选择
> 预估字数: 3000
> 出场角色: 角色规范名A, 角色规范名B
> 涉及设定: 已存在设定名A, 已存在设定名B
> 情感弧线: 戒备 -> 动摇 -> 决意
> 节拍: 场景切入, 冲突升级, 关键选择, 后果与章末钩子
> 悬念: 下一章需要承接的问题

```

规则：
- 总纲、篇纲、节纲和章纲统一在标题后直接写普通散文梗概，不使用弧线、情感或张力元数据代替梗概。
- 章级元数据必须使用 `> 键: 值`；不要改写成项目符号、表格、粗体标签或含糊散文。
- `出场角色`只列本章实际进入场景或直接参与行动的人物，使用 `src/characters/`
  中的规范名或 ID；“团队”“众人”等群体词不能代替具体人物，不得把仅被提及者
  自动算作出场。
- `涉及设定`使用 `src/world/` 中可解析的规范名称；不要为填字段而虚构人物或设定。
  缺少必要资产时先读取、创建草案或向用户确认。
- 完善已有章纲前，先读取目标章、所属节、相邻章、最近正文、相关人物与设定；
  依据事实补字段，不凭空扩写。
- 四级梗概粒度逐级收窄：总纲概括全书，篇纲概括阶段事件，节纲概括一组章节，章纲概括本章；章另写戏剧位置与章内节拍。
- 修改后自检标题层级和上述字段；精确保留用户未要求修改的内容，并继续遵守预览 diff 与确认边界。
""" + "\n\n" + INLINE_ANNOTATION_CONTRACT


OUTLINE_JSON_FIELDS = """每个章节 JSON 对象必须包含：
- number、title、summary
- dramatic_position（起/承/转/合/过渡）
- content_focus、goals、estimated_words
- involved_characters、involved_settings
- emotional_arc、beats、hooks

人物与设定名称必须来自已提供的规范资料；不要用“团队”“众人”等群体词代替具体人物。"""


def validate_outline_markdown(content: str, novel_id: str) -> list[str]:
    """Return parser-aligned completeness errors for a writable outline."""
    from .outline_parser import OutlineMdParser

    hierarchy = OutlineMdParser().parse(str(content or ""), novel_id)
    errors: list[str] = []
    if hierarchy.master is None:
        errors.append("缺少一级作品标题")
    if not hierarchy.arcs:
        errors.append("缺少篇纲")
    if not hierarchy.sections:
        errors.append("缺少节纲")
    if not hierarchy.chapters:
        errors.append("缺少章纲")
    required = {
        "summary": lambda node: bool(node.summary.strip()),
        "dramatic_position": lambda node: bool(node.dramatic_position.strip()),
        "content_focus": lambda node: bool(node.content_focus.strip()),
        "goals": lambda node: bool(node.goals),
        "estimated_words": lambda node: node.estimated_words > 0,
        "involved_characters": lambda node: bool(node.involved_characters),
        "involved_settings": lambda node: bool(node.involved_settings),
        "emotional_arc": lambda node: bool(node.emotional_arc.strip()),
        "beats": lambda node: bool(node.beats),
        "hooks": lambda node: bool(node.hooks),
    }
    for chapter in hierarchy.chapters:
        missing = [name for name, check in required.items() if not check(chapter)]
        if missing:
            errors.append(f"{chapter.node_id} 缺少: {', '.join(missing)}")
    return errors
