---
name: openwrite-novel
description: 'Use when user wants to write novels, manage outlines, characters, world-building, style, workflows, or chapter review. Triggers: 写章节, 生成大纲, 创建角色, 世界观, 风格, 伏笔, 小说'
---

# OpenWrite 小说创作系统

OpenWrite 是一个面向长篇小说创作的技能集合。当前口径已经统一到：

- 日常主入口只有两个：`openwrite goethe` 与 `openwrite dante`
- `src/` 是人和 AI 共读的确认版真源
- `data/` 是运行态、缓存、workflow、手稿与草案
- `src/story/author_intent.md` 是长期作者意图，`src/story/current_focus.md` 是近期创作罗盘
- `openwrite dante` 是主编排入口
- `openwrite goethe` 是长期会话 planning 入口
- `write` / `multi-write` / `review` 也会推进同一套 runtime state
- 每章摘要、观察与三阶段 token 用量保存在 `data/memory/chapters/`
- `write` 使用跨进程作品锁，并对正文、truth、memory 做失败回滚

## 子技能导航

根据用户意图，读取对应子技能的 `SKILL.md`：

| 用户意图 | 子技能文件 | 说明 |
|----------|-----------|------|
| 写章节 / 续写 / 生成草稿 | [skills/novel-creator/SKILL.md](./skills/novel-creator/SKILL.md) | 章节创作 Pipeline |
| 角色 / 大纲 / 世界观 / 伏笔管理 | [skills/novel-manager/SKILL.md](./skills/novel-manager/SKILL.md) | 项目资产维护 |
| 审查 / 润色 / 连续性检查 | [skills/novel-reviewer/SKILL.md](./skills/novel-reviewer/SKILL.md) | 审查与修订 |
| 风格初始化 / 合成 / 提取 | [skills/style-system/SKILL.md](./skills/style-system/SKILL.md) | 风格系统 |
| 世界观实体 / 关系图谱 | [skills/world-query/SKILL.md](./skills/world-query/SKILL.md) | 世界查询 |
| 对话风格 / 口头禅分析 | [skills/dialoguequality/SKILL.md](./skills/dialoguequality/SKILL.md) | 对话质量检测 |
| 真相文件一致性 | [skills/truth-validation/SKILL.md](./skills/truth-validation/SKILL.md) | 运行态验证 |
| 后置规则检查 | [skills/post-validation/SKILL.md](./skills/post-validation/SKILL.md) | AI 痕迹与规则检测 |
| 伏笔 DAG 管理 | [skills/foreshadowing-system/SKILL.md](./skills/foreshadowing-system/SKILL.md) | 伏笔跟踪 |
| 工作流 / 阶段进度 / 恢复 | [skills/workflow-manager/SKILL.md](./skills/workflow-manager/SKILL.md) | 流程调度 |
| 切割 / 压缩 / 长文本处理 | [skills/text-processing/SKILL.md](./skills/text-processing/SKILL.md) | 文本处理 |
| 长期规划 / 建书 / 灵感收敛 | [skills/goethe-agent/SKILL.md](./skills/goethe-agent/SKILL.md) | Goethe planning 会话与 handoff |

## 当前架构

### Goethe / Dante 分工

- Goethe 负责长会话规划：汇总灵感、提建议、修背景、修人物、修设定、修大纲，并在资产成熟时显式 handoff 给 Dante
- Dante 负责把可写资产持续写成正文：预检、写章、审查、状态结算；必要时为正文推进回修人物、设定和大纲

### 1. 单源文档

核心文档优先使用 `TOML front matter + Markdown 正文`：

- `src/story/*.md`
- `src/characters/*.md`
- `src/world/entities/*.md`
- `data/world/*.md`

front matter 负责索引字段：

- `id`
- `summary`
- `tags`
- `detail_refs`
- `related`

正文负责详细设定、人类可读说明和长期维护内容。

### 2. 大纲层级

```text
总纲 (Master)
  └─ 篇纲 (Arc)       — 长线篇章，通常 150-300 章量级
      └─ 节纲 (Section) — 中层段落，通常 15-40 章量级
          └─ 章纲 (Chapter) — 最小写作单元，通常 3000-5000 字
```

`src/outline.md` 是唯一语义真源。`data/hierarchy.yaml` 只是派生缓存，不应手工维护。

### 3. 风格层次

```text
craft/                                      -> 通用写作技法
data/novels/{id}/data/sources/{source_id}/  -> 用户提供文本提取出的 source pack
data/novels/{id}/src/**                     -> 本书设定约束
data/novels/{id}/data/style/composed.md     -> 合成后的作品风格文档
```

### 4. 运行态

`data/novels/{id}/data/` 下的重点目录：

- `planning/`：草案、灵感、未确认大纲
- `manuscript/arc_*/ch_*.md`：章节正文
- `world/`：`current_state.md` / `ledger.md` / `relationships.md`
- `workflows/`：`book_state.yaml` 与 `wf_ch_*.yaml`
- `memory/chapters/`：有界章节摘要、客观观察与 token 用量
- `reviews/`：结构化章节审稿结果
- `foreshadowing/dag.yaml`：伏笔图
- `style/`：`fingerprint.yaml` 与 `composed.md`

## 上下文组装

当前默认使用 canonical packet，而不是分散读取多套来源。

```python
from pathlib import Path
from tools.chapter_assembler import ChapterAssemblerV2

assembler = ChapterAssemblerV2(
    project_root=Path.cwd(),
    novel_id="my_novel",
    style_id="my_novel",
)
packet = assembler.assemble("ch_005")
prompt_text = packet.to_markdown()
```

packet 典型包含：

- 系统职责提示词
- 故事背景
- 历史篇梗概
- 当前篇各节梗概
- 上一章正文
- 主角状态 / current_state / ledger / relationships
- 相关人物文档
- 风格文档
- 概念文档

## CLI 入口

### 主入口

- `openwrite dante`：长期会话主编排入口
- `openwrite goethe`：长期会话 planning 入口
- `openwrite agent`：已退役，提示用户改用 `openwrite dante`

如果不是在做调试、脚本化或精确控制，优先只通过 `goethe` / `dante` 两个 agent 使用系统。

### 直接命令

- `openwrite write ch_005`
- `openwrite multi-write ch_005`
- `openwrite review ch_005`
- `openwrite context ch_005`
- `openwrite assemble ch_005`
- `openwrite style synthesize`
- `openwrite setting extract <source_id> --source <file>`
- `openwrite source review <source_id>`
- `openwrite source promote <source_id> --target all`

`source promote --target all` 会把 source pack 同时晋升到 style、foundation 和 world 文档。
- `openwrite sync --check`
- `openwrite status`
- `openwrite desk`
- `openwrite studio`
- `openwrite focus set "本阶段目标"`
- `openwrite import existing-novel.txt`
- `openwrite export --format md`

### 当前约束

- `write` / `multi-write` / `review` 现在都会复用 canonical packet 语义
- direct CLI 也会推进 `book_state.yaml` 与 `wf_ch_*.yaml`
- CLI 与 Studio 共用同一套写章锁、事务提交、审稿存储和生命周期
- Studio 前端覆盖模型会话配置、Goethe/Dante 对话、导入、同步、上下文预览、资产新建、连续性、伏笔和 source pack 全流程
- 空目录运行 `openwrite studio` 会进入前端建书页，不再要求先执行 `openwrite init`
- `current_state / ledger / relationships` 是公开 canonical 命名

## 关键 Python 工具

| 工具 | 文件 | 用途 |
|------|------|------|
| 大纲解析 | `tools/outline_parser.py` | `outline.md` → `OutlineHierarchy` |
| 大纲缓存 | `tools/outline_cache.py` | outline 派生缓存 |
| 上下文构建 | `tools/context_builder.py` | 章节级生成上下文 |
| 章节组装 | `tools/chapter_assembler.py` | canonical packet |
| 主编排 | `tools/agent/orchestrator.py` | 书级流程推进 |
| 多代理编排 | `tools/agent/director.py` | `multi-write` 子流程 |
| 工作流调度 | `tools/workflow_scheduler.py` | `wf_ch_*.yaml` |
| 书级状态 | `tools/agent/book_state.py` | `book_state.yaml` |
| 真相文件 | `tools/truth_manager.py` | runtime truth files |
| 世界查询 | `tools/world_query.py` | 世界观实体与关系 |
| 共享文档规范化 | `tools/shared_documents.py` | 单源文档规范化 |

## 目录约定

```text
data/novels/{novel_id}/
├── src/
│   ├── outline.md
│   ├── story/*.md
│   ├── characters/*.md
│   └── world/
│       ├── rules.md
│       ├── terminology.md
│       ├── timeline.md
│       └── entities/*.md
└── data/
    ├── hierarchy.yaml
    ├── planning/*.md
    ├── characters/cards/*.yaml
    ├── manuscript/arc_*/ch_*.md
    ├── memory/chapters/ch_*.yaml
    ├── reviews/ch_*.json
    ├── foreshadowing/dag.yaml
    ├── world/*.md
    ├── style/composed.md
    ├── style/fingerprint.yaml
    ├── workflows/book_state.yaml
    ├── workflows/wf_ch_*.yaml
    └── test_outputs/
```

## 参考入口

- [README.md](./README.md) — 项目概览与命令入口
- `tests/test_novel_workspace.py` — 小说工作台、创作罗盘与导入导出验收

*版本: 5.8.0 | 最后更新: 2026-07-14*
