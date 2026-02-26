# OpenWrite 当前架构与功能清单

> 更新时间：2026-02-27
> 目的：让你快速判断“现在做到了什么、怎么做的、下一步该提什么需求”

---

## 1. 当前总体架构

OpenWrite 现在是一个 **CLI 驱动的本地多 Agent 模拟系统**，核心链路是：

`CLI -> 数据/查询层 -> Agent 调度层 -> 草稿与报告落盘`

### 分层说明

1. 入口层（CLI）
- 文件：`tools/cli.py`
- 作用：提供所有命令入口（初始化、人物、伏笔、模拟）

2. 领域模型层（Models）
- 目录：`tools/models/`
- 作用：定义大纲、伏笔、人物、文风等结构化数据模型（Pydantic）

3. 解析与查询层（Parsers / Queries）
- 目录：`tools/parsers/`、`tools/queries/`
- 作用：
  - 解析 markdown 标注（`fs/fs-recover/char/scene`）
  - 查询大纲与人物状态

4. 业务状态层（Character / Foreshadowing）
- 文件：
  - `tools/character_state_manager.py`
  - `tools/graph/foreshadowing_dag.py`
- 作用：
  - 人物时间线（文本优先，结构化 mutation 可选）
  - 人物双层档案（简卡 `cards/*.yaml` + 动态主档 `profiles/*.md`）
  - 伏笔 DAG 管理与待回收查询

5. Agent 层（Simulation）
- 目录：`tools/agents/`
- 核心文件：`tools/agents/simulator.py`
- 作用：调度 `Director -> Librarian -> LoreChecker`（Stylist 默认跳过）

---

## 2. 当前主流程（simulate chapter）

命令：

```bash
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel
# 严格检查模式（需要时再开）
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --strict-lore
```

执行流程：

1. CLI 解析参数并创建 `AgentSimulator`
2. Simulator 读取上下文：
- 章节大纲（`outline/chapters/ch_003.md`）
- 待回收伏笔（优先 DAG，其次大纲标注扫描）
- 人物当前状态摘要
- 人物动态主档摘要（`characters/profiles/*.md`）
- 世界观图谱摘要（`world/world_graph.yaml`）
- 场景标注摘要（tension/emotion）
3. Director 生成本轮执行决策
4. Librarian 生成章节节拍 + 模拟草稿
5. LoreChecker 执行规则检查
6. 结果落盘：
- 草稿：`data/novels/<novel_id>/manuscript/drafts/<chapter_id>_draft.md`
- 报告：`logs/simulations/<timestamp>_<chapter_id>.yaml`

---

## 3. 已实现功能（可用）

### A. 人物系统（Phase 3 核心）

- 创建人物卡
- 动态主档自动创建（Markdown，可自由写作）
- 记录自由文本时间线（`--note`）
- 可选记录结构化变更（`acquire/use/move/health/realm/flag`）
- 时间线重建（按章节回放简卡摘要）
- 生成人物卷快照

相关命令：
- `character create`
- `character mutate`
- `character query`
- `character profile`
- `character snapshot`

### B. 世界观图谱（Phase 4 基础版）

- 世界实体管理（Entity）
- 世界关系管理（Relation）
- 图谱摘要生成（供 Agent 上下文注入）
- 图谱冲突检查（引用缺失/重复关系/境界层级循环）

相关命令：
- `world entity-add`
- `world relation-add`
- `world list`
- `world check`

### C. 伏笔系统（Phase 2 核心）

- 伏笔节点管理（含权重、层级、目标章节）
- 状态统计与待回收查询
- DAG 结构验证（基础版）

相关命令：
- `foreshadowing-add`
- `foreshadowing-list`
- `foreshadowing-check`
- `foreshadowing-statistics`

### D. Markdown 标注解析

已解析：
- `fs` / `伏笔`
- `fs-recover` / `recover` / `回收`
- `char`
- `scene`

### E. Agent 模拟（原型）

- Director：流程路由与说明
- Librarian：章节节拍 + 草稿生成
- LoreChecker：逻辑检查
- Stylist：已接入接口，默认不启用

---

## 4. LoreChecker 当前规则（已启用）

1. 基础关键词规则
- forbidden 词命中报错
- required 词缺失警告

2. 结构化规则（第一版）
- scene `tension` 必须为 1-10
- scene 张力全低或全高时给节奏预警
- scene emotion 过度单一时预警
- char mutation 格式校验
- `use:<item>` 时检查人物库存
- 默认宽松模式：结构化问题记为 warning，不阻断创作
- 严格模式：`--strict-lore` 时，结构化问题升级为 error

---

## 5. 还没完成（你可直接提需求）

1. 世界观图谱（Phase 4）
- 已完成：实体/关系基础管理、冲突检查、模拟上下文注入
- 待完成：复杂规则推理（克制链、条件触发）、跨章节一致性检查、可视化

2. 大纲深度能力
- `outline init/create` 仍偏轻量
- 大纲版本历史与写入权限控制未完成

3. Agent 深化
- Director 还未做真正上下文压缩策略
- Librarian 还未连接真实 LLM
- LoreChecker 还没做跨章节硬一致性（例如“已死亡角色复活”）

4. Web 应用
- API 与前端尚未开始

---

## 6. 你提需求时建议给的信息

为了让我更快改到位，建议每次需求都带这 5 项：

1. 目标功能一句话  
2. 输入示例（命令或文件片段）  
3. 期望输出示例  
4. 失败时要报错还是警告  
5. 是否要写入版本控制（commit + push）  

---

## 7. 常用命令速查

```bash
# 初始化项目
python3 -m tools.cli init my_novel

# 创建人物
python3 -m tools.cli character create 李逍遥 --tier 主角 --novel-id my_novel

# 记录文本时间线（推荐）
python3 -m tools.cli character mutate 李逍遥 --chapter ch_001 --note "这一章形成对黑旗盟的误判" --novel-id my_novel

# 可选：记录结构化变更
python3 -m tools.cli character mutate 李逍遥 --chapter ch_001 --change acquire:神秘玉佩 --note "关键道具入手" --novel-id my_novel

# 添加伏笔
python3 -m tools.cli foreshadowing-add f001 --content 玉佩线索 --weight 9 --layer 主线 --target-chapter ch_010 --novel-id my_novel

# 世界观图谱
python3 -m tools.cli world-entity-add faction_shushan 蜀山派 --type faction --novel-id my_novel
python3 -m tools.cli world-entity-add loc_qingyun 青云镇 --type location --novel-id my_novel
python3 -m tools.cli world-relation-add --source faction_shushan --target loc_qingyun --relation protects --novel-id my_novel
python3 -m tools.cli world-check --novel-id my_novel

# 模拟一章（默认跳过文风模块）
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel

# 需要硬校验时
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --strict-lore
```
