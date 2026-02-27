---
name: openwrite-style-system
description: >
  OpenWrite 三层风格生成系统。当涉及风格合成（compose）、草稿分析（analyze）、
  Reader 批量抽取、StyleDirector 迭代收敛、Stylist 评分、StyleProfile 管理，
  或修改 craft/、styles/、novels/ 目录下的文件时，加载此 skill。
  触发词：style, 风格, compose, reader, iterate, 三层, banned phrases,
  fingerprint, voice, rhythm, 禁用表达, 偏差检测, 收敛
globs:
  - "craft/**"
  - "styles/**"
  - "novels/**"
  - "composed/**"
  - "tools/agents/stylist.py"
  - "tools/agents/reader.py"
  - "tools/agents/style_director.py"
  - "tools/utils/style_composer.py"
  - "tools/models/style.py"
---

# OpenWrite 风格生成系统 (Style System)

## 1. 架构概览

三层优先级架构，从低到高：

```
通用技法 (craft/)        → 可选参考，跨作品通用的写作技巧
作品风格 (styles/{id}/)  → 应当遵循，作者/作品的风格 DNA
作品设定 (novels/{id}/)  → 不可违反，角色、世界观、术语等硬性约束
```

优先级规则：`用户偏好覆盖 > 作品设定（硬性约束）> 作品风格（核心约束）> 通用技法（可选参考）`

## 2. 核心文件清单

### 代码文件

| 文件 | 类 | 职责 |
|------|-----|------|
| `tools/utils/style_composer.py` | `StyleComposer` | 三层文档合成器，输出 `composed/{id}_final.md` |
| `tools/models/style.py` | `StyleProfile` | Pydantic 模型，结构化风格档案（质量指标、禁用短语） |
| `tools/agents/stylist.py` | `StylistAgent` | AI 痕迹检测、节奏验证、声音一致性、分类评分（opt-in LLM 润色） |
| `tools/agents/reader.py` | `ReaderAgent` | 批量阅读原著，三层抽取（craft/style/novel findings） |
| `tools/agents/style_director.py` | `StyleDirectorAgent` | 分层差异分析、偏差检测、收敛追踪、文档更新建议 |
| `tools/utils/context_compressor.py` | `ContextCompressor` | 优先级加权预算分配，压缩风格上下文 |

### 数据目录

```
craft/                          # 通用技法（7 个 .md 文件）
├── dialogue_craft.md           # 对话技巧
├── information_reveal.md       # 信息揭示策略
├── pov_techniques.md           # 视角技法
├── rhythm_craft.md             # 节奏技法
├── scene_structures.md         # 场景结构
├── tension_model.md            # 张力模型
└── show_dont_tell.md           # 展示而非叙述

styles/{作品名}/                # 作品风格指纹
├── fingerprint.md              # 风格 DNA（核心特征）
├── voice.md                    # 叙述者声音
├── language.md                 # 语言风格偏好
├── rhythm.md                   # 节奏风格
├── humor.md                    # 幽默体系
├── dialogue_craft.md           # 对话风格（作品特有）
├── iteration_log.md            # 迭代记录
└── reader_notes/               # Reader Agent 完整笔记
    ├── batch_001_craft.md
    ├── batch_001_style.md
    ├── batch_001_novel.md
    └── ...

novels/{作品名}/                # 作品设定（硬性约束）
├── characters.md               # 角色设定
├── worldbuilding_rules.md      # 世界观规则
├── terminology.md              # 术语表
├── scene_instances.md          # 名场面实例
├── initial.md                  # 大纲
└── notes.md                    # 大纲注意事项

composed/                       # 合成输出
└── {作品名}_final.md           # 最终合成文档（供 LLM 消费）
```

## 3. 数据流与管线

### 完整管线流程

```
Director.plan(style_id)
  → 加载 composed/{style_id}_final.md
  → 生成 style_instructions（风格感知指令）
  → Librarian.generate_chapter(style_instructions)
    → 节拍生成 + 结构化草稿
  → LoreChecker.check_draft()
    → 逻辑审查（宽松/严格双模式）
  → [可选] Stylist.polish(draft, style_profile)
    → AI 痕迹检测 + 节奏验证 + 评分
  → [可选] Reader.read_batch() + StyleDirector.analyze()
    → 风格迭代循环
```

### 风格合成流程 (StyleComposer.compose)

```python
# 入口
StyleComposer.compose(novel_id="术师手册", style_id="术师手册")

# 步骤
1. 加载 craft/*.md          → 通用技法文本
2. 加载 styles/{id}/*.md    → 作品风格文本
3. 加载 novels/{id}/*.md    → 作品设定文本
4. 按优先级合并，冲突时高层覆盖低层
5. 输出 → composed/{id}_final.md
```

### 风格迭代循环 (Reader → StyleDirector)

```python
# 入口
# CLI: python3 -m tools.cli style iterate --novel-id 术师手册 --draft-path draft.md

# 步骤
1. Reader.read_batch(texts, batch_size=3)
   → 逐批阅读原著/草稿
   → 三层抽取：craft_findings, style_findings, novel_findings
   → 输出到 styles/{id}/reader_notes/

2. StyleDirector.analyze(draft, composed_style)
   → 逐层对比：draft vs composed 文档
   → 计算 LayerScore（每层偏差分数）
   → 生成 DocumentUpdate 建议
   → 判定是否收敛（convergence check）

3. 如未收敛 → 更新源文档 → 重新 compose → 重复
```

## 4. CLI 命令速查

```bash
# 合成三层风格文档
python3 -m tools.cli style compose --novel-id 术师手册

# 列出可用风格模板
python3 -m tools.cli style list

# 批量阅读原著并提取风格
python3 -m tools.cli style read-batch --novel-id 术师手册 --batch-size 3

# 风格迭代分析
python3 -m tools.cli style iterate --novel-id 术师手册 --draft-path path/to/draft.md

# 查看结构化风格档案
python3 -m tools.cli style profile --novel-id 术师手册

# 带风格分析的章节模拟
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel \
  --style-id 术师手册 --style-analysis
```

## 5. 关键类 API

### StyleComposer

```python
from tools.utils.style_composer import StyleComposer

composer = StyleComposer()
# 合成三层文档
result = composer.compose(novel_id="术师手册", style_id="术师手册")
# result.output_path → "composed/术师手册_final.md"
# result.layers → {"craft": [...], "style": [...], "novel": [...]}
```

### StyleProfile

```python
from tools.models.style import StyleProfile

# 从项目加载
profile = StyleProfile.from_project(novel_id="术师手册")
# profile.banned_phrases → ["不禁", "缓缓说道", ...]
# profile.quality_metrics → QualityMetrics(...)
# profile.voice → VoiceProfile(...)
```

### StylistAgent

```python
from tools.agents.stylist import StylistAgent

stylist = StylistAgent()
# 检查草稿风格
result = stylist.check_style(draft_text, style_profile=profile)
# result.score → 0.0~1.0
# result.ai_artifacts → [ArtifactMatch(...), ...]
# result.rhythm_analysis → RhythmResult(...)
# result.suggestions → [...]

# 润色草稿
polished = stylist.polish(draft_text, style_profile=profile)
```

### ReaderAgent

```python
from tools.agents.reader import ReaderAgent

reader = ReaderAgent()
# 批量阅读
findings = reader.read_batch(
    texts=["chapter1.md", "chapter2.md", "chapter3.md"],
    batch_size=3,
    novel_id="术师手册"
)
# findings.craft → [CraftFinding(...), ...]
# findings.style → [StyleFinding(...), ...]
# findings.novel → [NovelFinding(...), ...]
```

### StyleDirectorAgent

```python
from tools.agents.style_director import StyleDirectorAgent

director = StyleDirectorAgent()
# 分析偏差
analysis = director.analyze(
    draft_path="path/to/draft.md",
    composed_path="composed/术师手册_final.md"
)
# analysis.layer_scores → {"craft": 0.85, "style": 0.72, "novel": 0.95}
# analysis.updates → [DocumentUpdate(...), ...]
# analysis.converged → bool
```

## 6. 常见任务指南

### 任务 A：为新作品创建风格模板

```bash
# 1. 创建目录结构
mkdir -p styles/新作品名/{reader_notes}
mkdir -p novels/新作品名

# 2. 创建必需文件（最少需要 fingerprint.md）
# styles/新作品名/fingerprint.md — 风格 DNA
# novels/新作品名/characters.md — 角色设定
# novels/新作品名/worldbuilding_rules.md — 世界观

# 3. 合成
python3 -m tools.cli style compose --novel-id 新作品名
```

### 任务 B：添加禁用表达（banned phrases）

禁用表达存储在两个位置：
1. `tools/agents/stylist.py` → `DEFAULT_AI_BANNED_PHRASES`（全局默认，~50 条）
2. `StyleProfile.banned_phrases`（作品级别，从 `styles/{id}/` 加载）

作品级别优先。添加新禁用表达：
- 编辑 `styles/{作品}/language.md`，在"禁用表达"部分添加
- 或直接修改 `StyleProfile` 的 `banned_phrases` 字段

### 任务 C：调整风格评分阈值

评分在 `StylistAgent` 中计算，包含：
- `ai_artifact_score`：AI 痕迹检测（regex 匹配 banned phrases）
- `rhythm_score`：段落长度变化率
- `voice_score`：叙述声音一致性
- `overall_score`：加权综合分

阈值在 `StylistAgent.__init__` 中设置，可通过 `StyleProfile` 覆盖。

### 任务 D：修改合成规则

合成规则在 `StyleComposer` 中：
- 层级加载顺序：craft → style → novel
- 冲突解决：高层覆盖低层
- 输出格式：Markdown，按 section 组织
- 参考 `docs/prompts/COMPOSE_RULES.md` 了解详细规则

## 7. 约束与规则

### 不可违反

- **三层优先级**：novels/ > styles/ > craft/，永远不要反转
- **不删除数据文件**：craft/、styles/、novels/ 下的 .md 文件不可删除，除非用户明确要求
- **Pydantic v2**：所有数据模型必须使用 `BaseModel`，不用 dataclass
- **类型注解**：所有函数签名必须有 type hints
- **测试通过**：修改后运行 `python3 -m pytest -q`，确认 66 tests 全部通过

### 应当遵循

- 新增风格文件放在对应层级目录
- Reader 笔记输出到 `styles/{id}/reader_notes/`
- 合成输出到 `composed/` 目录
- CLI 命令注册在 `tools/cli.py` 的 `style_app` sub-app 中
- 文档字符串用中文，Google style

### 当前限制

- 所有 Agent 为本地规则模拟，尚未接入 LLM API
- Stylist 使用 regex 匹配，非语义理解
- Reader 使用 pattern-based extraction，非 NLU
- StyleDirector 使用 heuristic diff，非向量相似度

## 8. 测试

```bash
# 风格系统测试
python3 -m pytest tests/test_style_system.py -v    # 11 tests
python3 -m pytest tests/test_phase4.py -v           # 24 tests（含 Reader/StyleDirector）
python3 -m pytest tests/test_phase5.py -v           # 19 tests（含迭代循环）

# 全部测试
python3 -m pytest -q                                # 66 tests expected
```
