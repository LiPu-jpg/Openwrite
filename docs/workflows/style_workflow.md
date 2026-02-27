# 风格系统工作流 (Style Workflow)

## 概述

OpenWrite 的风格系统采用**三层架构**，通过分层约束确保生成文本符合作品风格。本文档定义风格系统的标准工作流程，包括风格提取、合成、应用、迭代优化等环节。

---

## 三层风格架构

```
优先级：用户偏好覆盖 > 作品设定（硬性约束） > 作品风格（核心约束） > 通用技法（可选参考）
```

| 层级 | 目录 | 作用 | 约束力 | 示例 |
|------|------|------|--------|------|
| **通用技法** | `craft/` | 跨作品通用的写作技巧 | 可选参考 | 场景结构、信息揭示策略、POV 技巧 |
| **作品风格** | `styles/{作品}/` | 作者/作品特有的风格指纹 | 应当遵循 | 叙述声音、语言偏好、节奏、幽默体系 |
| **作品设定** | `novels/{作品}/` | 作品的硬性约束 | 不可违反 | 角色设定、世界观规则、术语表 |

**合成规则**：
- 同名文件：下层覆盖上层（`novels/` > `styles/` > `craft/`）
- 用户运行时覆盖：通过 API 参数传入的偏好优先级最高

---

## 工作流类型

### 1. 风格提取流程（从原著中学习）

**适用场景**：已有参考原著，希望提取其风格特征。

**流程步骤**：

```
准备原著文本 → Reader 批量阅读 → 三层抽取 → StyleDirector 分析 → 人工审核 → 保存风格档案
```

#### 1.1 准备原著文本

**要求**：
- 格式：纯文本（`.txt`）或 Markdown（`.md`）
- 长度：建议 10 万字以上（样本越大，提取越准确）
- 分块：可选，Reader 会自动分块处理

**操作**：
```bash
# 将原著文本放入 data/reference_books/
cp original_novel.txt data/reference_books/my_novel.txt
```

#### 1.2 Reader 批量阅读

**目标**：从原著中提取风格特征，分层存储到 `craft/`、`styles/`、`novels/`。

**操作**：
```bash
python3 -m tools.cli style read-batch \
  --file data/reference_books/my_novel.txt \
  --novel-id my_novel \
  --style-id my_novel
```

**Reader 输出**：
- `craft/*.md`：通用技法（如对话节奏、场景转换）
- `styles/my_novel/*.md`：风格指纹（叙述声音、语言偏好、节奏、幽默）
- `novels/my_novel/*.md`：作品设定（角色、世界观、术语）
- `styles/my_novel/reader_notes/`：完整笔记（供人工审核）

#### 1.3 StyleDirector 分析

**目标**：对比提取的风格与现有风格档案，识别偏差和收敛趋势。

**操作**：
```bash
python3 -m tools.cli style iterate \
  --draft path/to/draft.md \
  --novel-id my_novel \
  --style-id my_novel
```

**StyleDirector 输出**：
- 分层差异分析（craft/style/novel 各层的偏差）
- 偏差检测（哪些特征与原著不符）
- 收敛追踪（多次迭代后的改进趋势）
- 文档更新建议（哪些 `.md` 文件需要调整）

#### 1.4 人工审核

**检查项**：
- **通用技法**：是否真的通用？还是作品特有？
- **风格指纹**：是否准确捕捉了作者的声音和节奏？
- **作品设定**：是否有遗漏或错误？

**调整方式**：
- 直接编辑 `craft/*.md`、`styles/my_novel/*.md`、`novels/my_novel/*.md`
- 移动文件：将误分类的技法从 `craft/` 移到 `styles/`

#### 1.5 保存风格档案

**结构化档案**：
```bash
python3 -m tools.cli style profile --novel-id my_novel
```

**输出**：`data/novels/my_novel/style/style_profile.yaml`

**内容**：
- 禁用表达列表（banned_phrases）
- 节奏指标（rhythm_metrics）
- 声音特征（voice_features）
- 语言偏好（language_preferences）

---

### 2. 风格合成流程（生成最终指令）

**适用场景**：准备生成新章节，需要将三层风格合成为一个统一的生成指令。

**流程步骤**：

```
加载三层文档 → StyleComposer 合成 → 输出最终风格文档 → 传递给 Writer
```

#### 2.1 加载三层文档

**StyleComposer 自动加载**：
- `craft/*.md`：所有通用技法
- `styles/{style_id}/*.md`：指定作品的风格指纹
- `novels/{novel_id}/*.md`：指定作品的设定约束

#### 2.2 合成规则

**优先级**：
1. 用户运行时覆盖（API 参数）
2. `novels/` 中的同名文件覆盖 `styles/` 和 `craft/`
3. `styles/` 中的同名文件覆盖 `craft/`

**示例**：
- 如果 `craft/dialogue_craft.md` 和 `styles/my_novel/dialogue_craft.md` 都存在，使用后者
- 如果 `novels/my_novel/terminology.md` 存在，其中的术语定义优先级最高

#### 2.3 输出最终风格文档

**操作**：
```bash
python3 -m tools.cli style compose \
  --novel-id my_novel \
  --style-id my_novel
```

**输出**：`composed/my_novel_final.md`

**结构**：
```markdown
# 最终风格文档

## 硬性约束（不可违反）
- 角色设定
- 世界观规则
- 术语表

## 风格约束（应当遵循）
- 叙述声音
- 语言偏好
- 节奏特征
- 幽默体系

## 可选技法（参考）
- 场景结构
- 信息揭示策略
- POV 技巧
```

#### 2.4 传递给 Writer

**在 Pipeline V2 中**：
- `DirectorAgent` 调用 `StyleComposer.compose()` 生成最终风格文档
- 将风格文档作为 `GenerationContext` 的一部分传递给 `LibrarianAgent`
- `LibrarianAgent` 根据风格文档生成草稿

---

### 3. 风格应用流程（生成时）

**适用场景**：使用风格系统生成新章节。

**流程步骤**：

```
准备上下文 → 合成风格 → 生成草稿 → Stylist 验证 → 输出最终稿
```

#### 3.1 准备上下文

**GenerationContext 包含**：
- 大纲信息（章纲、节纲、篇纲、总纲）
- 人物档案（涉及人物的完整描述）
- 世界观设定（涉及地点/道具的规则）
- 前文摘要（最近 2000 字原文 + 更早的压缩摘要）
- 伏笔提示（活跃伏笔的埋设/回收要求）
- **风格文档**（合成后的最终风格指令）

#### 3.2 生成草稿

**LibrarianAgent 职责**：
- 按章纲的 `beats` 逐节拍生成
- 遵循风格文档中的约束
- 保持与前文的连贯性

**LLM 模式**：
- 使用 `Kimi K2.5` 或 `MiniMax M2.5`（长文本生成）
- Prompt 包含完整的 `GenerationContext`

**规则模式**：
- 使用模板 + 关键词替换
- 适用于测试或无 LLM 环境

#### 3.3 Stylist 验证

**目标**：检测 AI 痕迹、验证风格一致性。

**Stylist 检查项**：
- **禁用表达**：是否使用了 `banned_phrases` 中的词汇
- **节奏验证**：句长分布、段落长度是否符合 `rhythm_metrics`
- **声音一致性**：叙述视角、语气是否符合 `voice_features`
- **AI 痕迹**：是否有"然而"、"仿佛"、"不禁"等 AI 常用词

**Stylist 输出**：
- 分类评分（节奏/声音/语言/AI 痕迹，各 0-100 分）
- 具体问题列表（哪些句子/段落有问题）
- 修改建议（可选，LLM 模式下提供）

#### 3.4 输出最终稿

**流程**：
1. 如果 Stylist 评分 < 60 分 → 打回重写（最多 `max_rewrites` 次）
2. 如果评分 >= 60 分 → 交给用户审核
3. 用户通过 → 可选进入 Stylist 润色（LLM 模式）
4. 输出最终稿到 `data/novels/{novel_id}/manuscript/drafts/`

---

### 4. 风格迭代优化流程

**适用场景**：已生成多个章节，希望根据反馈优化风格档案。

**流程步骤**：

```
收集生成稿 → StyleDirector 分析偏差 → 识别问题模式 → 更新风格档案 → 重新生成验证
```

#### 4.1 收集生成稿

**要求**：
- 至少 3-5 个章节的生成稿
- 包含用户已审核通过的版本

#### 4.2 StyleDirector 分析偏差

**操作**：
```bash
python3 -m tools.cli style iterate \
  --draft data/novels/my_novel/manuscript/drafts/ch_001.md \
  --novel-id my_novel \
  --style-id my_novel
**StyleDirector 输出**：
- **分层差异**：哪些层级的偏差最大
- **偏差类型**：节奏/声音/语言/AI 痕迹
- **收敛趋势**：多次迭代后是否在改进

#### 4.3 识别问题模式

**常见问题**：
- **节奏单调**：句长分布过于集中
- **声音不稳定**：叙述视角在章节间切换
- **语言过于书面**：缺少口语化表达
- **AI 痕迹明显**：频繁使用"然而"、"不禁"等

**分析方法**：
- 对比原著和生成稿的统计指标
- 查看 `styles/my_novel/iteration_log.md` 中的历史记录

#### 4.4 更新风格档案

**调整方式**：
1. **禁用表达**：将频繁出现的 AI 痕迹词加入 `banned_phrases`
2. **节奏指标**：调整 `rhythm_metrics` 中的句长分布目标
3. **声音特征**：明确 `voice_features` 中的叙述视角规则
4. **语言偏好**：补充 `language_preferences` 中的口语化要求

**保存**：
```bash
# 手动编辑 styles/my_novel/*.md
# 或更新 style_profile.yaml
```

#### 4.5 重新生成验证

**操作**：
- 选择 1-2 个章节重新生成
- 对比新旧版本的 Stylist 评分
- 如果评分提升 → 确认更新有效
- 如果评分下降 → 回滚更新，重新分析

---

## 风格文件结构

### craft/ 目录（通用技法）

```
craft/
├── dialogue_craft.md        # 对话技巧
├── information_reveal.md    # 信息揭示策略
├── pov_techniques.md        # 视角技巧
├── scene_structures.md      # 场景结构
└── ...
```

**内容示例**（`dialogue_craft.md`）：
```markdown
# 对话技法

## 对话标签
- 优先使用"说"，避免过度修饰（"嘶吼"、"咆哮"）
- 动作描写代替对话标签：他转过身，"我不同意。"

## 对话节奏
- 短句推进紧张感
- 长句展开解释或回忆
```

### styles/{作品}/ 目录（风格指纹）

```
styles/my_novel/
├── fingerprint.md           # 风格 DNA（总览）
├── voice.md                 # 叙述者声音
├── language.md              # 语言风格
├── rhythm.md                # 节奏风格
├── humor.md                 # 幽默体系
├── dialogue_craft.md        # 对话风格（覆盖 craft/）
├── iteration_log.md         # 迭代记录
└── reader_notes/            # Reader 完整笔记
    ├── batch_001.md
    └── ...
```

**内容示例**（`voice.md`）：
```markdown
# 叙述者声音

## 视角
- 第三人称限知（主角视角）
- 偶尔插入全知视角的旁白（用于世界观说明）

## 语气
- 冷静、客观，带有讽刺意味
- 避免煽情和过度抒情
```

### novels/{作品}/ 目录（作品设定）

```
novels/my_novel/
├── characters.md            # 角色设定
├── worldbuilding_rules.md   # 世界观规则
├── terminology.md           # 术语表
├── scene_instances.md       # 名场面实例
└── notes.md              n```

**内容示例**（`terminology.md`）：
```markdown
# 术语表

## 魔法体系
- **术灵**：虚境中的能量实体，可被术师召唤
- **虚翼**：成功召唤术灵的术师称号
- **架势**：修炼法 + 召唤法 + 战斗法的组合

## 禁用词
- 避免使用"魔法"、"法术"（使用"术法"、"奇迹"）
```

---

## 与其他系统的协作

### 1. 与大纲系统协作

**关联点**：
- 大纲中的 `ChapterOutline.goals` 影响生成内容
- 风格系统确保生成内容符合作品风格

**操作建议**：
- 在章纲中明确写作目标
- 在风格文档中补充针对特定场景的技法（如战斗场景、对话场景）

### 2. 与人物系统协作

**关联点**：
- `novels/{作品}/characters.md` 定义角色设定
- 风格系统中的 `voice.md` 定义叙述视角

**操作建议**：
- 在角色设定中明确说话风格
- 在风格文档中补充角色对话的差异化技巧

### 3. 与 Pipeline V2 协作

**流程**：
1. **Director** 调用 `StyleComposer.compose()` 生成最终风格文档
2. **Writer** 根据风格文档生成草稿
3. **R* 检查逻辑一致性（不检查风格）
4. **User** 人工审核
5. **Stylist** 验证风格一致性并可选润色

---

## 常见问题

### Q1: 如何选择参考原著？

**建议**：
- 选择与目标作品风格相近的原著
- 长度至少 10 万字（样本越大越好）
- 避免选择风格混杂的作品（如多作者合著）

### Q2: Reader 提取的风格不准确怎么办？

**排查方法**：
1. 检查原著文本质量（是否有乱码、格式问题）
2. 增加样本量（提供更多章节）
3. 人工审核 `reader_notes/` 中的完整笔记
4. 手动调整 `styles/` 和 `novels/` 中的文件

### Q3: 如何处理多作者风格？

**方案 1**：为每个作者创建独立的 `styles/{作者}/`
**方案 2**：提取共同特征到 `styles/`，差异部分放入 `novels/`

### Q4: 风格迭代多少次合适？

**建议**：
- 初次提取后，生成 3-5 个章节
- 运行 StyleDirector 分析偏差
- 调整风格档案，重新生成 1-2 个章节验证
- 重复 2-3 轮，直到 Stylist 评分稳定在 70 分以上

### Q5: 如何平衡风格约束和创作自由？

**原则**：约束**（`novels/`）不可违反
- **风格约束**（`styles/`）应当遵循，但允许适度偏离
- **通用技法**（`craft/`）仅供参考，可灵活运用

**实践**：
- 在 Stylist 评分中，硬性约束违反扣分最重
- 风格约束偏离适度扣分
- 通用技法不影响评分

---

## 附录：CLI 命令速查

```bash
# 批量阅读原著并提取风格
python3 -m tools.cli style read-batch \
  --file data/reference_books/my_novel.txt \
  --novel-id my_novel \
  --style-id my_novel

# 合成三层风格文档
python3 -m tools.cli style compose \
  --novel-id my_novel \
  --style-id my_novel

# 风格迭代分析
python3 -m tools.cli style iterate \
  --draft path/to/draft.md \
  --novel-id my_novel \
  --style-id my_novel

# 查看结构化风格档案
python3 -m ols.cli style profile --novel-id my_novel

# 列出可用风格模板
python3 -m tools.cli style list
```

---

## 相关文档

- [大纲编排工作流](./outline_workflow.md)
- [Stylist Agent 使用指南](../../README.md#stylist-agent)
- [StyleDirector Agent 使用指南](../../README.md#styledirector-agent)
- [三层风格架构说明](../../README.md#三层风格架构)
