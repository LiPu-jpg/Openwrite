# OpenWrite - AI 辅助小说创作系统

基于 VSCode + OpenCode 环境的多 Agent 协作系统，帮助作者创作长篇小说。

## 项目进度看板（截至 2026-02-27）

- 当前阶段：`Phase 3（人物与状态）后期 + Phase 5（Agent模拟）原型`
- 已可用主流程：`Director -> Librarian -> LoreChecker` 本地模拟跑通
- 文风模块：按你的要求，当前流程默认跳过 Stylist，可后续单独接入
- 现有测试：`python3 -m pytest -q`，当前 `12 passed`
- 架构说明文档：`docs/CURRENT_ARCHITECTURE.md`

### 已完成能力

- 人物双层档案：`cards/*.yaml` 简卡 + `profiles/*.md` 动态主档（自由格式）
- 人物时间线（文本优先）：自由备注时间线、可选结构化变更、摘要重建、卷快照
- 世界观图谱（基础版）：实体/关系管理、图谱摘要、冲突检查
- 伏笔 DAG 基础：节点管理、状态统计、待回收伏笔读取
- Markdown 标记解析：`fs`、`fs-recover`、`char`、`scene`
- Agent 模拟命令：
  - `python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel`
  - 自动注入人物动态主档摘要（来自 `characters/profiles/*.md`）
  - 输出草稿到 `data/novels/<novel_id>/manuscript/drafts/`
  - 输出报告到 `logs/simulations/`
- LoreChecker 结构化检查（第一版）：
  - 场景 `tension` 范围检查（1-10）
  - 场景 `emotion` 单一度预警
  - 人物 `mutation` 合法性检查（含 `use` 物品库存预检）
  - 默认宽松模式（以警告为主），可用 `--strict-lore` 切换严格模式

### 正在进行

- LoreChecker 规则扩展为跨章节时间线与关系一致性检查
- 将章节结构化标记接入更细粒度的重写反馈闭环

### 尚未开始或未完成

- 世界观图谱（`Phase 4`）：复杂规则推理、跨章节冲突检查、可视化
- 文风迭代闭环（你单独维护的模块）
- Web 应用（`Phase 6`）：后端 API、前端编辑器、可视化界面

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 初始化项目

```bash
# 在工作目录创建新小说项目
python3 -m tools.cli init my_novel
```

### 3. 创建人物

```bash
python3 -m tools.cli character create 李逍遥 --tier 主角
python3 -m tools.cli character create 林月如 --tier 重要配角
```

### 4. 查询人物

```bash
python3 -m tools.cli character query 李逍遥
python3 -m tools.cli character profile 李逍遥
python3 -m tools.cli character mutate 李逍遥 --chapter ch_001 --note "这一章立下一个性格转折点"
python3 -m tools.cli character mutate 李逍遥 --chapter ch_002 --change acquire:神秘玉佩 --note "关键道具入手"
python3 -m tools.cli world-entity-add faction_shushan 蜀山派 --type faction --novel-id my_novel
python3 -m tools.cli world-relation-add --source faction_shushan --target loc_qingyun --relation protects --novel-id my_novel
python3 -m tools.cli world-check --novel-id my_novel
python3 -m tools.cli foreshadowing-statistics
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --strict-lore
```

## 项目结构

```
openwrite/
├── data/                    # 数据存储
│   └── novels/{novel_id}/
│       ├── outline/           # 大纲系统
│       ├── characters/         # 人物系统
│       ├── world/            # 世界观
│       ├── foreshadowing/    # 伏笔追踪
│       ├── style/            # 文风系统
│       └── manuscript/       # 最终成稿
├── tools/                    # Python 工具
│   ├── cli.py              # CLI 入口
│   ├── models/             # 数据模型
│   ├── parsers/            # Markdown 解析
│   ├── agents/             # Agent 模拟
│   └── utils/             # 工具函数
└── PLAN.md                  # 完整架构设计
```

## Agent 架构

| Agent | 职责 | 模型 |
|--------|------|--------|
| Director | 主控导演、上下文压缩 | GLM-4.7 |
| Librarian | 剧情生成 | GLM-4.7 |
| LoreChecker | 逻辑审查 | GLM-4.7 |
| Stylist | 文风润色（去AI痕迹） | GLM-4.7 |

## 核心特性

### 1. 大纲系统
- **分层管理**: 总纲→卷纲→章纲→节纲
- **权限控制**: 总纲/卷纲只读，章纲/节纲可写
- **伏笔追踪**: DAG 结构，权重分级

### 2. 人物系统
- **双层结构**: 简卡摘要（数组/短字段） + 动态主档（Markdown 长文）
- **文本优先**: 以自由文本时间线为主，结构化变更为可选
- **事件溯源**: 结构化变更可回放重建摘要
- **快照机制**: 每卷结束自动生成快照
- **Markdown 存储**: 纯文本格式，易于阅读

### 3. 文风系统
- **负面清单**: 21 类 AI 痕迹检测
- **质量评分**: 5 维度 × 10 分制
- **Reflexion**: 自动迭代优化

### 4. 知识图谱
- **Graph 结构**: 支持逻辑推理
- **关系类型**: 人物、势力、地点、能力、境界
- **复杂查询**: 属性克制、传承关系等

## 开发状态

- [x] Phase 0: 架构设计
- [x] Phase 1: 基础工具
- [x] Phase 2: 大纲与伏笔
- [~] Phase 3: 人物与状态（后期）
- [~] Phase 4: 世界观图谱（基础版）
- [~] Phase 5: Agent 模拟（原型已跑通）
- [ ] Phase 6: Web 应用

## 贡献指南

1. 遵循 PLAN.md 中的设计原则
2. 使用 TDD 开发流程
3. 保持代码风格一致
4. 提交前运行测试

## 许可证

MIT License
