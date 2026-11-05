# 第十六轮：系统性扫描未触碰模块

## 方法

写了一个 AST 扫描器，对 `tools/` 下 86 个从未被任何轮次触碰的模块，按四类缺陷模式找候选：

| 模式 | 命中 |
|---|---|
| (a) 非原子写（裸 `open(...,"w")` / `write_text`） | 62 |
| (b) except 后只 log 且返回默认值 | 50 |
| (c) 宽 `except Exception` 导致状态降级 | 24 |
| (d) 读-改-写无 `ProjectWriteLock` | 23 |

命中数大是因为其中大量是误报（`init_project.py` 是新建项目、`file_ops.py` 是原子写实现本身、`_to_int` 之类的纯函数容错）。**扫描只负责给候选，缺陷必须用可执行探针证明。**

## 修掉的缺陷：工作流状态的三重失效

`workflow_scheduler.py` 是扫描结果里最严重的一个，三个缺陷构成完整破坏链：

1. `_save_state` 裸 `open(..., "w")` — 崩溃留下截断的状态文件
2. `load_workflow` / `_load_from_path` 解析失败返回 `None` — 与"文件不存在"无法区分
3. `load_or_create` 见 `None` 就**创建全新的空工作流** — 随后保存会覆写原文件

后果：`current_stage` 回到 `context_assembly`、`user_approved` 变回 `None`、所有 `stages` 记录消失。探针证实：

```
STAGE context_assembly        # 原本是 polish
APPROVED None                 # 原本是 True
PROGRESS_LOST True
```

比第十五轮的伏笔 DAG 更糟：那个返回空图但保留文件，这个直接覆写。

### 连带修的三处调用点

- `tool_runtime.py` 的 `advance_workflow` / `get`：抛错会变成未处理的 500。改为区分"状态损坏"与"工作流不存在"。
- `tool_runtime.py` 的 list 分支：用一个推导式读所有状态文件，**任何一个损坏都会让整个列表失败**。
- `orchestrator.py:398`：`scheduler.load_workflow(...).current_stage` 直接取属性，损坏时连阶段信息一起丢。

`list_active_workflows` 本身也读文件且会抛——改为跳过损坏文件并通过 `last_listing_damaged` 上报。

## 被证伪的两个高危候选

**`chapter_assembler._load_hierarchy`**：静态看是"解析失败返回空大纲"，会静默丢掉整个章节上下文。但探针显示损坏后仍有 2 章——因为它**优先从 `src/outline.md` 重建**，只在没有源文件时才读缓存。降级顺序正确，不是缺陷。

**`shared_documents.shared_document_lookup_keys`**：读失败返回空列表。但两个调用点都传 `content=text`，`content is None` 分支实际不可达。

这两个证伪很重要：静态扫描会把有回退的代码和真的会降级的代码标成同一类。不跑探针就会把 `chapter_assembler` 也"修"一遍，而那个改动会破坏它正确的降级顺序。

## 验证

| 变异 | 结果 |
|---|---|
| P-1a 读失败静默重启 | 2 failing ✓ |
| P-1b 裸写 | 1 failing ✓ |
| P-1c 列表不跳过损坏文件 | 1 failing ✓ |
| P-1d 不区分损坏与不存在 | 1 failing ✓ |

新增 3 个测试（`test_workflow_scheduler.py`）。

| | |
|---|---|
| Core | **1640 passed / 32 skipped / 2 xfailed / 0 failed** |
| 插件 test:maintenance | **80 passed / 0 failed** |
| docs:check / doctor | 全绿 |

改动：Core 55 文件 / 2781 insertions，未提交。

## 十六轮的总账

| 轮次 | 发现 |
|---|---|
| 12 | 派生缓存裸写（hierarchy/卡片） |
| 13 | 15 个修复无防线 + acceptance 过滤失败丢弃全部批注 |
| 14 | 3 个修复无防线（含 OutlineView 零测试） |
| 15 | 横评调度器丢任务 + 伏笔 DAG 三重失效 + 修正自己的误判 |
| 16 | 工作流状态三重失效 |

同一个缺陷类（**裸写 + 读失败降级 + 调用方覆写**）在五个不同模块里各出现一次：`outline_sync`、`character_sync`、`foreshadowing_manager`、`workflow_scheduler`，以及第十三轮的 `character_state_index`。每一处都是单独发现的，没有一处是被另一处的修复顺带覆盖的。

这说明它是**代码库的系统性模式**，不是个别疏忽。剩下的未触碰模块里很可能还有，建议后续按这个模式继续扫（`write_guard.py`、`source_pack.py`、`runtime_diagnostics.py`、`goethe.py` 都在扫描命中列表里）。
