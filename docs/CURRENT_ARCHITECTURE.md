# OpenWrite 当前架构与功能清单

> 更新时间：2026-02-27（Phase 6B 完成）
> 目的：让你快速判断“现在做到了什么、怎么做的、下一步该提什么需求”

---

## 1. 当前总体架构

OpenWrite 是一个 **CLI 驱动的本地多 Agent 模拟系统**，支持 opt-in LLM 模式，核心链路：

`CLI → 数据/查询层 → Agent 调度层 → 草稿与报告落盘`

### 分层说明

1. 入口层（CLI）
   - 文件：`tools/cli.py`（~745 行）
   - 命令组：character、outline、world、simulate、style、foreshadowing

2. 领域模型层（Models）
   - 目录：`tools/models/`
   - 包含：大纲、伏笔、人物、风格等 Pydantic 模型
   - `tools/models/style.py`（353 行）：StyleProfile、StyleCategory、QualityMetric 等，支持 `from_composed_doc()` 和 `to_summary()`

3. 解析与查询层（Parsers / Queries）
   - 目录：`tools/parsers/`、`tools/queries/`
   - 解析 markdown 标注（`fs/fs-recover/char/scene`）
   - 查询大纲与人物状态

4. 业务状态层（Character / Foreshadowing / World）
   - `tools/character_state_manager.py`（495 行）：人物 CRUD、变更、时间线重建、快照
   - `tools/graph/foreshadowing_dag.py`（281 行）：伏笔 DAG 管理、DFS 环检测
   - `tools/world_graph_manager.py`：实体/关系 CRUD、摘要生成、冲突检查

  5. 工具层（Utils）
   - `tools/utils/style_composer.py`（288 行）：三层风格文档加载、冲突解决、合成输出
   - `tools/utils/context_compressor.py`（228 行）：优先级加权预算分配、句边界截断、跨段去重

6. Agent 层（Simulation）
   - 目录：`tools/agents/`（7 个 Agent）
   - 核心编排：`tools/agents/simulator.py`（403 行）
   - 流程：`Director → Librarian → LoreChecker → Stylist(可选) → Reader+StyleDirector(可选)`

---

## 2. 当前主流程（simulate chapter）
### 基础命令
```bash
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel
# 严格检查模式
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --strict-lore
# Lore失败后自动重写
python3 -m tools.cli simulate chapter --id ch_003 --forbidden 冲突 --max-rewrites 1 --novel-id my_novel
# 带风格系统 + 后分析
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --style-id 术师手册 --style-analysis
```
### 执行流程
1. CLI 解析参数并创建 `AgentSimulator`
2. **跨章节预检**（新）：`LoreChecker.check_cross_chapter()` 检查角色位置连续性、物品库存、逾期伏笔，警告注入上下文
3. Simulator 读取上下文：章节大纲、待回收伏笔、人物状态、动态主档、世界观图谱、场景标注
4. **Director** 生成执行决策（使用 ContextCompressor 压缩上下文；有 LLM 时调用 LLM 决策，否则规则引擎）
5. **Librarian** 生成章节节拍（规则）+ 结构化草稿（有 LLM 时 LLM 扩写，否则规则模拟）
6. **LoreChecker** 执行规则检查 + 可选 LLM 语义审查（advisory）
7. 若未通过且设置 `--max-rewrites`，Librarian 按规则反馈自动重写并复检
8. 可选 **Stylist** 文风润色（有 LLM 时 LLM 润色，否则规则引擎）
9. 可选 **Reader + StyleDirector** 风格后分析（`--style-analysis`）
10. 结果落盘：草稿 + YAML 报告
---

## 3. 已实现功能（可用）
### A. 人物系统（Phase 3）
- 创建人物卡 + 动态主档自动创建（Markdown）
- 自由文本时间线（`--note`）+ 可选结构化变更（`acquire/use/move/health/realm/flag`）
- 时间线重建、卷快照
- 命令：`character create/mutate/query/profile/snapshot`
### B. 世界观图谱（Phase 4 基础版）
- 实体/关系管理、图谱摘要生成、冲突检查（引用缺失/重复关系/境界循环）
- 命令：`world entity-add/relation-add/list/check`
### C. 伏笔系统（Phase 2）
- 伏笔节点管理（含权重、层级、目标章节）
- 状态统计与待回收查询
- DAG 结构验证 + DFS 环检测
- 命令：`foreshadowing-add/list/check/statistics`
### D. Markdown 标注解析
- 已解析：`fs`/`fs-recover`/`char`/`scene`
### E. Agent 系统（Phase 5 完成）
| Agent | 职责 | 代码量 |
|-------|------|--------|
| Director | 上下文压缩 + 路由（opt-in LLM 决策） | 365 行 |
| Librarian | 节拍生成 + 草稿（opt-in LLM 扩写） | 722 行 |
| LoreChecker | 规则审查 + LLM 语义审查（advisory） | 420+ 行 |
| Stylist | AI 痕迹检测 + 评分（opt-in LLM 润色） | 500+ 行 |
| Reader | 批量阅读 + 三层抽取 | 668 行 |
| StyleDirector | 差异分析 + 收敛追踪 | 705 行 |
| Simulator | 全流程编排（传递 llm_client/router） | 420+ 行 |
### F. 风格系统（完整）
- 三层架构：`craft/`（通用技法）→ `styles/{work}/`（作者风格）→ `novels/{work}/`（作品设定）
- 优先级：用户偏好覆盖 > 作品设定（硬性约束）> 作品风格（核心约束）> 通用技法（可选参考）
- StyleComposer：三层文档自动合成为最终生成指令
- StyleProfile：Pydantic 结构化档案，支持 `from_composed_doc()` 和 `to_summary()`
- Reader → StyleDirector 迭代循环：批量阅读 → 差异分析 → 文档更新 → 重复直到收敛
- 命令：`style compose/list/read-batch/iterate/profile`
---

## 4. LoreChecker 当前规则
### 单章检查
1. 基础关键词规则：forbidden 词命中报错，required 词缺失警告
2. 场景规则：tension 1-10 校验、张力节奏预警、emotion 单一预警
3. 人物规则：mutation 格式校验、`use:<item>` 库存检查
4. 模式：默认宽松（warning），`--strict-lore` 升级为 error
### 跨章节检查（新）
1. 角色位置连续性：检测无 move 变更的瞬移（上一章在 A，本章在 B）
2. 物品库存一致性：检测负数库存（use 超过 acquire 数量）
3. 逾期伏笔检测：按权重分级严重度（≥8 严格、≥5 警告、<5 信息）
4. 集成：在 Simulator 生成草稿前自动运行，警告注入上下文
---

## 5. LLM 集成层（Phase 6B）
### 架构
- LiteLLM 封装：`tools/llm/client.py`（重试 + fallback 链）
- 模型路由：`tools/llm/router.py`（按任务类型选择模型）
- 配置：`tools/llm/config.py` + `llm_config.yaml`
- Prompt 模板：`tools/llm/prompts.py`（Director/Librarian/LoreChecker/Stylist）
### 模型路由表
| 任务类型 | 首选 | 备选 | 兜底 |
|----------|------|------|------|
| reasoning | Claude Opus 4.6 | GLM-4.7 | DeepSeek |
| generation | Kimi K2.5 | MiniMax M2.5 | DeepSeek |
| review | Claude Opus 4.6 | GLM-4.7 | DeepSeek |
| style | Kimi K2.5 | MiniMax M2.5 | DeepSeek |
### 设计原则
- Strangler Fig 模式：所有 Agent 保留规则引擎 fallback
- LLM 调用失败时自动回退，保证管线不中断
- LoreChecker LLM 发现默认为 advisory（警告）
- API key 通过环境变量注入，不存储在配置文件中
- CLI: `--use-llm` 启用，`--llm-config` 指定配置路径
### 尚未完成
1. 世界观图谱高级功能（复杂规则推理、可视化）
2. 大纲深度能力（版本历史与写入权限控制）
3. Web 应用（API 与前端）

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

# 人物管理
python3 -m tools.cli character create 李逍遥 --tier 主角 --novel-id my_novel
python3 -m tools.cli character mutate 李逍遥 --chapter ch_001 --note "这一章形成对黑旗盟的误判" --novel-id my_novel
python3 -m tools.cli character mutate 李逍遥 --chapter ch_001 --change acquire:神秘玉佩 --note "关键道具入手" --novel-id my_novel

# 伏笔
python3 -m tools.cli foreshadowing-add f001 --content 玉佩线索 --weight 9 --layer 主线 --target-chapter ch_010 --novel-id my_novel

# 世界观图谱
python3 -m tools.cli world-entity-add faction_shushan 蜀山派 --type faction --novel-id my_novel
python3 -m tools.cli world-relation-add --source faction_shushan --target loc_qingyun --relation protects --novel-id my_novel
python3 -m tools.cli world-check --novel-id my_novel

# 模拟章节
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --strict-lore
python3 -m tools.cli simulate chapter --id ch_003 --forbidden 冲突 --max-rewrites 1 --novel-id my_novel
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --style-id 术师手册 --style-analysis
# LLM 模式模拟章节
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --use-llm


# 风格系统
python3 -m tools.cli style compose --novel-id 术师手册
python3 -m tools.cli style list
python3 -m tools.cli style read-batch --novel-id 术师手册 --batch-size 3
python3 -m tools.cli style iterate --novel-id 术师手册 --draft-path path/to/draft.md
python3 -m tools.cli style profile --novel-id 术师手册

# 测试
python3 -m pytest -q  # 84 passed
```
