# openwrite-novel-swarm

把 OpenWrite 长篇小说引擎的单体创作编排，移植为 JiuwenSwarm 平台上的多智能体创作蜂群（Swarm Skill）。参赛作品对应 openJiuwen 智能体创新大赛「办公 / 内容创作」方向。

## 团队拓扑

混合模式（专精流水线 C + 并行分解 B + 写审对抗隔离 A），6 名成员：

```
作者意图
  └─ goethe-planner  规划师：人物卡 / 世界观 / 卷幕节章四级大纲（唯一规划真源）
       └─ author-gate  作者确认门（HITL）：大纲定稿批准
            └─ dante-writer  主笔：消费 canonical context packet 写章
                 ├─ reviewer-canon  正典审查：连贯与逻辑 + 正典与资料
                 ├─ reviewer-drama  叙事审查：情节与承诺 + 节奏与场景
                 └─ reviewer-prose  文辞审查：角色与关系 + 文风与表达
                      └─ (聚合不通过) revision-forge 修订匠 → author-gate → 定向复评
```

六域评审拓扑继承 OpenWrite `review-dag-framework.v1`（47 节点固定 DAG 的六域划分）。三评审互相隔离、看不到主笔过程稿——隔离是评审价值的一部分。

## 文件构成

| 文件 | 说明 |
|---|---|
| `SKILL.md` | 技能入口：frontmatter（kind: swarm-skill）、workflow、roles 表 |
| `roles/*.md` | 7 个角色的身份 / 成功标准 / 边界 / 输出 schema / Inline Persona |
| `workflow.md` | Mermaid 拓扑、逐步协议、确定性聚合规则、交付报告格式 |
| `bind.md` | 资源上限（token/墙钟/回炉轮数）、行为约束、失败处理与降级模式 |
| `dependencies.yaml` | OpenWrite 本地技能集 + python/git 依赖（启动 pre-flight 核对） |
| `scripts/workflow.py` | 可执行 SwarmFlow 编排（JiuwenSwarm 集群模式直接运行） |
| `tests/test_workflow_stub.py` | 桩件端到端测试（18 项断言，无需模型 key） |

## 安装

```bash
# 1. 安装 JiuwenSwarm（Python 3.12+）
pip install jiuwenswarm
jiuwenswarm-init

# 2. 安装本技能
cp -r openwrite-novel-swarm ~/.jiuwenswarm/agent/workspace/skills/

# 3. 配置模型（config.yaml 的 models.defaults，或环境变量 API_BASE/API_KEY/MODEL_NAME）
# 4. 启动
jiuwenswarm-start    # 打开 http://localhost:5173，集群模式使用
```

## 运行

**对话模式**：在 JiuwenSwarm（集群模式）中说"用 openwrite-novel-swarm 帮我规划并写第一章：……"。Leader 按 SKILL.md 协议派发 teammate。

**SwarmFlow 模式**：`scripts/workflow.py` 为可执行编排真源，支持两种入口：

- 全链路：args 传 `author_intent` / `genre_constraints`，自动走 规划 → 写章 → 评审 → 修订闭环 → 交付。
- 仅评审：args 传 `chapter_text`（已有章节），跳过规划与写作直接六域评审。

HITL 门以 approval args 表达（`outline_approved` / `revision_approved`）；缺批准时 run 返回 `awaiting_gate` payload 交由人类决定，批准后带参重入。

## 验证

```bash
# 结构校验（官方 swarmskill-creator 校验器，0 error）
python3 ~/.jiuwenswarm/agent/workspace/skills/swarmskill-creator/scripts/validate_swarmskill.py openwrite-novel-swarm/

# 端到端桩件测试（18 项断言：全通过/回炉/HITL/仅评审/回炉耗尽/重试）
python3 tests/test_workflow_stub.py
```

## 与 OpenWrite 本体的关系

- 角色与门禁语义移植自 OpenWrite `native-core` 的 SKILL.md、六域评审 DAG（`tools/review_dag_framework.py`）与 Goethe/Dante 分工。
- OpenWrite 技能集（novel-creator / novel-manager / novel-reviewer / foreshadowing-system / style-system 等）作为 `dependencies.yaml` 中的本地依赖接入；缺失时降级为 inline-persona-only 模式。
- 后续深化方向：角色与 OpenWrite 引擎工具（canonical packet 组装、truth/ledger、伏笔 DAG 读写）对接，让 teammate 直接读写作品目录资产。
