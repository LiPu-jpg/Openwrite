# OpenWrite - AI 辅助小说创作系统

基于 VSCode + OpenCode 环境的多 Agent 协作系统，帮助作者创作长篇小说。

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
python3 -m tools.cli foreshadowing-statistics
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
- **事件溯源**: 所有状态变更可追溯
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
- [~] Phase 3: 人物与状态（进行中）
- [ ] Phase 4: 世界观图谱
- [ ] Phase 5: Agent 模拟
- [ ] Phase 6: Web 应用

## 贡献指南

1. 遵循 PLAN.md 中的设计原则
2. 使用 TDD 开发流程
3. 保持代码风格一致
4. 提交前运行测试

## 许可证

MIT License
