# OpenWrite - AI辅助小说创作系统架构设计

> **版本**: v1.0  
> **创建日期**: 2025-02-26  
> **目标**: 基于VSCode+OpenCode环境的Agent模拟，最终演进为完整Web应用

---

## 一、系统愿景

OpenWrite是一个AI辅助小说创作平台，通过多Agent协作架构，帮助作者维护复杂的长篇小说世界观、人物关系、剧情大纲，并保持文风一致性。

**核心设计原则**:
- **分层管理**: 总纲→卷纲→章纲→节纲，权限逐级开放
- **知识图谱**: 用Graph结构替代纯文本RAG，支持逻辑推理
- **事件溯源**: 人物状态变更可追溯，确保时间线一致性
- **权重系统**: 伏笔、人物、设定均有权重分级（主线/支线/彩蛋）

---

## 二、核心数据模型

### 2.1 大纲系统 (Outline System)

#### 层级结构
```yaml
总纲 (Archetype): 只读层
├── 核心主题、结局走向、关键转折点
├── 权重: 主线(9-10) | 支线(5-8) | 彩蛋(1-4)
└── 版本控制: Git管理，需审核修改

卷纲 (Volume): 只读层
├── 本卷起止、主要冲突、人物登场/退场
├── 张力曲线 (tension_score): 1-10
└── 版本控制: Git管理，需审核修改

章纲 (Chapter): 可写层
├── 章节目标、关键场景、伏笔标记
├── 情感曲线 (emotion_tag): 紧张/温馨/悲伤/...
└── 版本控制: 自动记录变更历史

节纲 (Scene): 可写层
├── 具体场景、对话要点、动作细节
├── 状态标记: TODO | WRITING | REVIEW | DONE
└── 版本控制: 自动记录变更历史
```


#### 卷末快照机制 (Volume Snapshot)

每卷结束时自动生成快照，作为后续卷创作的基准状态：


**快照触发条件:**
- 卷内最后一章标记为 DONE
- 作者手动触发: `openwrite snapshot create vol_003`
- Director在生成下一卷前自动检查


**快照内容** (`snapshots/vol_003_snapshot.md`):
```markdown
# 第三卷《风云再起》卷末快照

## 基本信息
- **卷标题**: 风云再起
- **章节范围**: ch_021 - ch_030
- **快照时间**: 2025-02-26
- **字数统计**: 12.5万字

## 人物状态汇总

### 主角团当前状态
| 人物 | 境界 | 位置 | 关键状态 | 待办标记 |
|------|------|------|----------|----------|
| 李逍遥 | 金丹初期 | 青云镇 | 轻伤、焦虑 | 寻找师父、清除毒素 |
| 赵灵儿 | 金丹中期 | 青云镇 | 恋爱中 | 觉醒女娲之力 |
| 林月如 | 筑基后期 | 青云镇 | 挚友状态 | 突破金丹 |

### 人物关系变化 (本卷)
- 李逍遥 ↔ 赵灵儿: 陌生 → 恋人 (+85)
- 李逍遥 ↔ 酒剑仙: 师徒 → 失散 (师父失踪)
- 李逍遥 → 拜月教主: 仇恨加深 (-95, 杀父之仇)

### 新登场人物
- [ ] 青云镇镇长 (普通配角)
- [ ] 神秘黑衣人 (伏笔人物)

### 退场人物
- [x] 酒剑仙 (失踪，下卷回归)

## 剧情进展

### 主线推进
- [x] 揭露主角身世之谜
- [x] 主角突破金丹期
- [ ] 寻找五灵珠 (3/5)
- [ ] 阻止拜月教主阴谋

### 关键事件
1. ch_020: 主角得知杀父真相
2. ch_028: 主角与赵灵儿确定关系
3. ch_030: 酒剑仙失踪，主角继承掌门信物

### 本卷伏笔状态
| 伏笔ID | 内容 | 权重 | 状态 | 计划回收 |
|--------|------|------|------|----------|
| f001 | 神秘玉佩的真相 | 10 | 埋伏 | vol_005 |
| f003 | 师父失踪的幕后黑手 | 9 | 埋伏 | vol_004 |
| f007 | 左臂毒素来源 | 7 | 埋伏 | vol_004 |
| f002 | 小镇乞丐的身份 | 4 | 已收 | ch_025 |

## 世界观变更

### 势力变动
- 蜀山派: 掌门失踪，暂由大长老代理
- 拜月教: 活动加剧，袭击3个正派据点
- 青云镇: 成为新的剧情据点

### 设定启用
- [ ] 女娲族觉醒仪式
- [ ] 五灵珠共鸣机制

## 张力曲线分析

```
tension_score: [3, 4, 5, 7, 6, 8, 7, 9, 8, 10]
              ch21                              ch30
```

- **平均张力**: 6.7
- **高潮分布**: ch_030 (卷末高潮 ✓)
- **问题**: ch_021-023 连续3章张力 < 5 (平淡预警)

## 下卷预设

### 第四卷目标
- **标题**: 《寻师之旅》
- **核心冲突**: 寻找师父 + 追查毒素来源
- **预计章节**: 8-10章
- **必达目标**: 
  - 回收伏笔 f003 (师父失踪)
  - 回收伏笔 f007 (毒素清除)
  - 主角达到金丹中期

### 风险预警
- 主角左臂毒素倒计时: 30天 (现实时间约2章)
- 玉佩异动周期: 月圆之夜 (每15天)

## 存档信息

- **上一卷快照**: [vol_002_snapshot.md](./vol_002_snapshot.md)
- **人物完整状态**: [../../characters/protagonist/char_001/vol_003_snapshot.md]()
- **完整章节草稿**: [../../outline/scenes/]()
```

**快照文件结构:**
```
/novels/my_novel/
├── outline/
│   └── snapshots/
│       ├── vol_001_snapshot.md
│       ├── vol_002_snapshot.md
│       └── vol_003_snapshot.md  # 当前
```

**快照使用场景:**
1. **跨卷创作**: Director自动读取上一卷快照作为上下文
2. **长暂停恢复**: 作者休息一段时间后快速回顾
3. **Agent协作**: Librarian基于快照状态生成新卷剧情
4. **一致性检查**: LoreChecker对比快照与新草稿



#### 伏笔追踪 (Foreshadowing DAG)
```yaml
伏笔节点:
  id: unique_id
  content: "伏笔内容描述"
  weight: 1-10  # 权重
  layer: "主线" | "支线" | "彩蛋"
  status: "埋伏" | "待收" | "已收" | "废弃"
  created_at: "chapter_id"
  target_chapter: "预期回收章节"  # 可选
  tags: ["人物相关", "世界观相关", "道具相关"]

DAG边:
  from: "伏笔A"
  to: "伏笔B" | "回收点"
  type: "依赖" | "强化" | "反转"
```

**Markdown标记语法**:
```markdown
# 章节标题

## 场景一

<!--伏笔 weight=9 layer=主线 id=f001 target=第15章-->
主角发现父亲留下的神秘玉佩...
<!--/伏笔-->

<!--回收 ref=f001 -->
玉佩突然发光，原来它是开启...
<!--/回收-->

<!--人物 ref=character_001 state_change="获得道具:玉佩" -->
主角将玉佩收入怀中...
<!--/人物-->
```

### 2.2 人物系统 (Character System)

#### 人物卡结构
```yaml
Character:
  # 静态属性 (Static)
  id: unique_id
  name: "姓名"
  aliases: ["别名", "称号"]
  gender: "男"
  age: 18
  appearance: "外貌描述文本"
  personality: ["性格标签1", "性格标签2"]
  background: "背景故事"
  faction: "所属势力"
  tier: "主角" | "重要配角" | "普通配角" | "炮灰"  # 权重
  
  # 动态状态追踪 (Timeline目录)
  timeline_dir: "./timeline/"  # 按章节存储的状态变更记录
  # 动态状态 - 以Markdown形式存储在timeline目录
  timeline_dir: "./timeline/"
  current_snapshot: "vol_001_snapshot.md"  # 当前卷快照文件
  
#### 人物状态文件结构
  
**主人物卡** (`char_001.yaml`):
```yaml
Character:
  # 静态属性 (Static)
  id: char_001
  name: "李逍遥"
  aliases: ["小李子", "逍遥哥"]
  gender: "男"
  age: 18
  appearance: "外貌描述文本..."
  personality: ["乐观", "机灵", "重情义"]
  background: "背景故事..."
  faction: "蜀山派"
  tier: "主角"
  
  # 动态状态 - 指向Markdown快照
  snapshot_dir: "./timeline/"
  current_snapshot: "vol_003_snapshot.md"
```
  
**卷快照文件** (`timeline/vol_003_snapshot.md`):
```markdown
# 李逍遥 - 第三卷状态快照
  
## 基本信息
- **卷数**: 第三卷《风云再起》
- **章节范围**: ch_021 - ch_030
- **快照时间**: 第三卷结束时
  
## 当前状态
  
### 身体状态
- **健康**: 轻伤（左臂中毒，已压制）
- **境界**: 金丹初期
- **体力**: 70%
- **精神状态**: 焦虑（师父失踪）
  
### 位置信息
- **当前地点**: [青云镇](../../world/locations/qingyun_town.md)
- **上一地点**: [蜀山](../../world/locations/shushan.md)
  
### 持有物品
| 物品 | 数量 | 来源 | 备注 |
|------|------|------|------|
| 青锋剑 | 1 | ch_001获得 | 主武器，已损坏 |
| 回气丹 | 3 | ch_025获得 | 可恢复真气 |
| 神秘玉佩 | 1 | ch_003获得 | [伏笔f001](../../foreshadowing/f001.md)待回收 |
  
### 技能与能力
- **剑法**: 《蜀山剑诀》第三层 (熟练度: 85%)
- **身法**: 《逍遥游》第二层 (熟练度: 60%)
- **特殊**: 可感知妖气（玉佩赋予）
  
### 人际关系
| 人物 | 关系 | 好感度 | 最新事件 |
|------|------|--------|----------|
| 赵灵儿 | 恋人 | +85 | ch_028 表白成功 |
| 林月如 | 挚友 | +70 | ch_025 共同御敌 |
| 酒剑仙 | 师徒 | +90 | ch_030 师父失踪 |
| 拜月教主 | 仇敌 | -95 | ch_020 杀父之仇 |
  
### 关键事件标记
- [x] ch_001 获得青锋剑
- [x] ch_003 获得神秘玉佩
- [x] ch_015 突破筑基期
- [x] ch_020 得知杀父真相
- [x] ch_028 与赵灵儿确定关系
- [ ] 待触发: 玉佩觉醒
- [ ] 待触发: 师徒决裂
  
## 本卷重要变更
  
### ch_021 - 青云镇初遇
- **获得**: 回气丹×5（林月如赠送）
- **关系变更**: 林月如 +10（从+60到+70）
- **状态变更**: 疲劳（连续赶路3天）
  
### ch_025 - 妖兽夜袭
- **消耗**: 回气丹×2
- **武器损坏**: 青锋剑（需修复）
- **关系变更**: 林月如 +10（并肩作战）
  
### ch_028 - 月下表白
- **关系变更**: 赵灵儿 +20（从+65到+85）
- **状态变更**: 获得buff「爱情的力量」（修炼速度+10%）
  
### ch_030 - 师父失踪
- **状态变更**: 焦虑（修炼速度-20%，持续到找到师父）
- **获得任务**: 寻找酒剑仙
  
## 卷末总结
  
**本卷成长**:
- 境界: 筑基后期 → 金丹初期
- 主线推进: 得知身世真相，情感线突破
- 战力评估: 可击败普通金丹中期
  
**下卷伏笔**:
1. 玉佩在月圆之夜的异动（f001待收）
2. 师父失踪背后的阴谋
3. 左臂毒素需在30天内清除
```
  
**单章变更日志** (`timeline/logs/ch_025.md`):
```markdown
# ch_025 变更日志
  
## 人物: 李逍遥
  
### 状态变更
- **health**: 健康 → 轻伤（左臂被妖兽抓伤）
- **weapon**: 青锋剑（损坏）
- **inventory**: +0（消耗回气丹×2，剩余3）
  
### 关系变更
- **林月如**: 60 → 70 (+10，共同御敌)
  
### 新增标记
- `wounded_left_arm`: 左臂受伤，需治疗
- `broken_qingfeng_sword`: 青锋剑损坏，需修复
  
## 人物: 林月如
  
### 状态变更
- **health**: 健康 → 健康
- **真气**: 90% → 60%（战斗中消耗）
  
### 关系变更
- **李逍遥**: 60 → 70 (+10)
```

### 2.3 世界观系统 (Worldbuilding System)

#### 知识图谱结构
```yaml
# 实体类型
Entity:
  - type: Location
    properties: [name, description, parent_location, climate, resources]
  
  - type: Faction
    properties: [name, description, leader, members, ideology, territories]
  
  - type: Ability
    properties: [name, description, type, level, requirements, effects]
  
  - type: Realm  # 境界/等级
    properties: [name, level, description, requirements, breakthrough_method]
  
  - type: Artifact
    properties: [name, description, type, origin, abilities, owner]
  
  - type: Event
    properties: [name, date, description, participants, impact]

# 关系类型
Relation:
  - type: "belongs_to"      # Character -> Faction
  - type: "located_in"      # Character/Artifact -> Location
  - type: "counters"        # Ability -> Ability
  - type: "requires"        # Realm -> Realm | Ability -> Realm
  - type: "owns"            # Character -> Artifact
  - type: "participated"    # Character -> Event
  - type: "above"           # Realm -> Realm (等级关系)
```

#### 查询接口设计
```python
# 示例查询
world.query("主角当前境界的下一个境界是什么？")
# -> 通过 Realm.above 关系查找

world.query("哪些势力与主角所在势力敌对？")
# -> 通过 Faction 关系 + 人物归属查询

world.check_conflict("让筑基期主角击败元婴期敌人")
# -> 检查 Ability/Realm 关系，提示战力不合理
```

### 2.4 文风系统 (Style System)

#### 文风档案结构

##### 核心设计理念

文风系统不仅定义"要写什么"，更重要的是定义"**不要写什么**"。借鉴`humanizer-zh`的研究成果，我们建立**负面清单驱动**的文风维护机制：先去除AI痕迹，再注入作者个性。

##### 文风档案 (`style_profile.yaml`)

```yaml
StyleProfile:
  # === 基础风格参数 (必须定义) ===
  base:
    tense: "过去时"           # 过去时 | 现在时
    perspective: "第三人称限知"  # 第一人称 | 第三人称限知 | 第三人称全知
    tone: "严肃偏热血"         # 严肃 | 轻松 | 黑暗 | 理想主义 | 自定义描述
    pacing: "张弛有度"         # 紧凑 | 舒缓 | 张弛有度
  
  # === 正向特征库 (应该模仿的) ===
  positive_features:
    # 句式特征
    sentence_patterns:
      - "短句开场建立节奏"
      - "对话打断叙述"
      - "长句用于描写，短句用于动作"
    
    # 词汇偏好
    vocabulary:
      preferred: ["高频词1", "高频词2"]     # 鼓励使用的词
      frequency_ratio: 0.15                   # 特征词密度
    
    # 节奏参数
    rhythm:
      avg_sentence_length: 25               # 平均句长（字）
      dialogue_ratio: 0.35                  # 对话占比
      paragraph_max_lines: 8                # 段落最大行数
  
    # 名场面向量库 (Dynamic Few-Shot来源)
    iconic_scenes:
      - type: "战斗"
        examples: ["战斗片段1.md", "战斗片段2.md"]
        tags: ["快节奏", "动作感", "紧张"]
      - type: "煽情"
        examples: ["煽情片段1.md", "煽情片段2.md"]
        tags: ["内心独白", "情感细腻", "留白"]
      - type: "日常"
        examples: ["日常片段1.md", "日常片段2.md"]
        tags: ["轻松", "对话为主", "细节描写"]
  
  # === 负面清单 (必须避免的AI痕迹) ===
  negative_patterns:
    # 1. 过度强调意义
    banned_phrases_significance:
      - "标志着"          # 改为: "发生在"
      - "极其重要的"       # 改为: "关键的"
      - "反映了更广泛的"   # 改为: 具体说明
      - "象征着"          # 改为: "代表"
    
    # 2. 宣传和广告式语言
    banned_phrases_hype:
      - "充满活力的"
      - "丰富的文化遗产"
      - "迷人的自然美景"
      - "必游之地"
      - "令人叹为观止的"
    
    # 3. AI高频词汇
    banned_ai_words:
      - "此外"            # 改为: 直接连接或删除
      - " crucial"        # 改为: "重要的"
      - "复杂"            # 改为: 具体描述
      - "培养"            # 改为: "养成"
      - "增强"            # 改为: "加强"
    
    # 4. 填充短语
    banned_fillers:
      - "为了实现这一目标"
      - "由于...的事实"
      - "在这个时间点"
      - "值得注意的是"
      - "不可否认的是"
    
    # 5. 结构性套路
    banned_structures:
      - "不仅...而且..."    # 改为: 简单并列
      - "三段式列举"       # 改为: 2项或4项
      - "过度换词"         # 同一段落保持用词一致
      - "破折号过度使用"    # 每章不超过3个
      - "段落以单行金句结尾"  # 多样化结尾
    
    # 6. 模糊归因
    banned_attributions:
      - "专家认为"
      - "行业报告显示"
      - "一些批评者认为"
      - "观察者指出"
  
  # === 质量评分标准 (Stylist评估用) ===
  quality_metrics:
    directness:      # 直接性
      weight: 20
      criteria: "直接陈述事实，不绕圈宣告"
    
    rhythm:          # 节奏变化
      weight: 20
      criteria: "句子长度变化，避免机械重复"
    
    trust_reader:    # 信任读者
      weight: 20
      criteria: "简洁明了，不过度解释隐喻"
    
    authenticity:    # 真实性
      weight: 20
      criteria: "听起来像真人说话，有观点和个性"
    
    conciseness:     # 精炼度
      weight: 20
      criteria: "无可删减内容，无冗余"
    
    pass_threshold: 40  # /50分合格线
  
  # === 个性化特征 (可选) ===
  personality:
    quirks: ["特定口癖", "惯用比喻"]           # 角色或作者的个人特色
    humor_style: "冷幽默"                      # 幽默风格
    preferred_metaphors: ["自然类", "武侠类"]  # 偏好的隐喻类型
```

##### Stylist工作流程 (基于负面清单)

```
输入: Librarian生成的章节草稿
  │
  ▼
[Step 1] AI痕迹扫描
  ├── 检测: 负面清单中的短语和结构
  ├── 检测: 高频AI词汇
  ├── 检测: 机械节奏（连续同长句子）
  └── 输出: 问题清单
  │
  ▼
[Step 2] 场景类型识别
  ├── 分析: 战斗/对话/描写/煽情
  ├── 检索: 名场面库匹配3-5个相似片段
  └── 输出: Few-Shot示例集
  │
  ▼
[Step 3] 第一轮修正 (去AI化)
  ├── 替换: 负面清单短语 → 自然表达
  ├── 删除: 填充词和过度强调
  ├── 打断: 机械节奏（变化句长）
  └── 输出: 去AI化文本
  │
  ▼
[Step 4] 第二轮修正 (注入个性)
  ├── 应用: 正向特征库的句式
  ├── 插入: 个性化口癖和隐喻
  ├── 匹配: 名场面风格
  └── 输出: 个性化文本
  │
  ▼
[Step 5] 质量评分
  ├── 评估: 5个维度各0-10分
  ├── 总分 ≥ 40? 
  │   ├── 是 → 输出最终文本
  │   └── 否 → 回到Step 3 (最多3次)
  └── 输出: 评分报告 + 最终文本
```

##### 文风样本收集指南

**步骤1: 提供参考小说**
- 用户提供1-2部目标风格的小说（5-10万字足够）
- 或用户提供自己已写的章节（至少3章）

**步骤2: Stylist自动分析**
```
Stylist.analyze_style(samples):
  # 提取正向特征
  - 统计平均句长、对话占比
  - 提取高频词汇和句式模板
  - 识别场景类型分布
  
  # 识别AI痕迹（反向指标）
  - 检测负面清单中的模式
  - 标记需要避免的表达方式
  
  # 生成文风档案
  - 创建 style_profile.yaml
  - 保存名场面片段到 samples/
```

**步骤3: 人工校准**
- 作者审阅文风档案
- 调整负面清单（有些AI模式可能是作者习惯）
- 确认个性化特征

**步骤4: 持续迭代**
- 每5章重新分析一次
- 根据作者反馈调整权重
- 补充新的名场面示例

---

## 三、Agent协作架构

### 3.1 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        用户 (Author)                        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                     🎬 Director (导演)                       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ • 全局读写权限控制器                                    │  │
│  │ • 上下文压缩与分发                                      │  │
│  │ • 大纲层级权限管理（总纲/卷纲只读，章纲/节纲可写）        │  │
│  │ • 任务路由与调度                                        │  │
│  │ • 版本控制与变更记录                                    │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────┬──────────────────────────────┬───────────────────┘
           │                              │
     ┌─────┴─────┐                 ┌──────┴──────┐
     ▼           ▼                 ▼             ▼
┌─────────┐ ┌──────────┐    ┌──────────┐ ┌──────────┐
│Librarian│ │LoreCheck │    │ Stylist  │ │ NewAgent │
│(图书馆长)│ │(逻辑审查)  │    │(文书长)  │ │  (扩展)  │
└────┬────┘ └────┬─────┘    └────┬─────┘ └────┬─────┘
     │           │               │            │
     ▼           ▼               ▼            ▼
┌─────────────────────────────────────────────────────────────┐
│                      知识存储层                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ Outline  │ │Character │ │World     │ │ Style    │       │
│  │  (大纲)   │ │(人物状态) │ │(世界观)   │ │ (文风)   │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Agent职责与权限

#### 🎬 Director (主控导演)
```yaml
权限:
  - 全局读写权限（总纲/卷纲修改需确认）
  - 所有Agent的调度与路由
  - 上下文压缩策略制定

d职责:
  - 接收用户高层指令
  - 根据大纲层级准备上下文:
      总纲: 主题、结局、关键转折
      卷纲: 本卷起止、主要冲突
      章纲: 前3章 + 本章 + 后1章
      节纲: 本章内前文 + 当前节
  - 查询知识图谱获取相关设定
  - 分发任务给下游Agent
  - 监控Agent工作状态
  - 合并多个Agent的输出

工作流:
  1. 用户: "写第三章"
  2. Director:
     - 读取总纲、卷纲、章纲
     - 查询: 第三章涉及的人物、地点、伏笔
     - 压缩上下文至目标token数
     - 生成任务包: {context, constraints, output_format}
     - 路由给 Librarian
```

#### 📖 Librarian (图书馆长/剧情生成)
```yaml
权限:
  - 读: 总纲、卷纲、章纲、人物状态、世界观
  - 写: 节纲草稿、新伏笔标记（不可修改旧伏笔权重）
  - 不可: 修改已确定的总纲/卷纲

职责:
  - 基于Director提供的上下文生成章节草稿
  - 标记新伏笔（需注明权重、预期回收章节）
  - 推进剧情发展
  - 保持人物行为一致性

输入:
  - 大纲上下文
  - 人物当前状态
  - 世界观设定
  - 文风指导（可选）

输出:
  - 章节草稿（Markdown）
  - 新伏笔列表
  - 人物状态变更建议
  - 待检查项列表
```

#### 🕵️‍♂️ LoreChecker (时空维护者/逻辑审查)
```yaml
权限:
  - 读: 所有存储层数据
  - 写: 错误日志、修改建议
  - 不可: 直接修改正文

职责:
  - 并行审查Librarian生成的草稿
  - 检查项:
    ✓ 时间线错误（死人复活、未出场就提及）
    ✓ 设定冲突（战力崩坏、属性矛盾）
    ✓ 状态非法变更（人物瞬移、物品凭空出现）
    ✓ 伏笔未授权闭合（权重10的伏笔被轻易收掉）
    ✓ 信息泄露（读者知道 > 角色知道）
    ✓ 张力曲线（连续平淡/连续高潮）
  - 输出Error Log给Director

Error Log格式:
  - severity: "致命" | "严重" | "警告" | "提示"
  - location: "章节X，段落Y"
  - issue: "问题描述"
  - suggestion: "修改建议"
  - reference: "相关设定/人物卡链接"
```

#### ✍️ Stylist (文书长/文风润色)
```yaml
权限:
  - 读: 文风档案、章节草稿
  - 写: 润色后的章节文本
  - 不可: 修改剧情逻辑

职责:
  - 在LoreChecker通过后接手
  - 根据文风档案进行润色
  - Dynamic Few-Shot匹配:
    - 识别当前场景类型（战斗/对话/描写）
    - 从名场面库检索3-5个相似片段
    - 作为示例进行风格模仿
  - 语言一致性检查
  - 段落节奏调整

Reflexion流程:
  while 风格差异 > threshold:
    1. 提取当前文本风格特征
    2. 与目标文风对比
    3. 生成修正建议
    4. 重写目标段落
    5. 评估改进程度
```

### 3.3 Agent协作工作流

```
┌─────────────────────────────────────────────────────────────┐
│                     标准章节生成流程                          │
└─────────────────────────────────────────────────────────────┘

[开始]
   │
   ▼
[Director] 接收用户指令 "写第三章"
   │
   ├── 读取大纲系统
   │   ├── 总纲: 核心主题、关键转折
   │   ├── 卷纲: 第三章属于第一卷冲突高潮
   │   └── 章纲: 第三章目标、场景规划
   │
   ├── 查询知识图谱
   │   ├── 人物: 第三章涉及的角色及当前状态
   │   ├── 地点: 场景发生地及环境设定
   │   └── 伏笔: 待埋伏笔、待回收伏笔
   │
   └── 上下文压缩
       ├── 总纲摘要 (500 tokens)
       ├── 卷纲摘要 (300 tokens)
       ├── 章纲详情 (500 tokens)
       ├── 人物状态 (400 tokens)
       └── 相关设定 (300 tokens)
           总计: ~2000 tokens
   │
   ▼
[Director] 生成任务包
   │
   ├── Task A -> Librarian: "生成第三章草稿"
   └── Task B -> LoreChecker: "预检查设定冲突" (可选)
   │
   ▼
[Librarian] 生成章节草稿
   │
   ├── 分析场景类型分布
   ├── 按场景生成内容
   ├── 标记新伏笔
   ├── 提出人物状态变更
   └── 输出: 草稿 + 元数据
   │
   ▼
[LoreChecker] 逻辑审查 (并行)
   │
   ├── 读取最新人物状态
   ├── 逐段检查逻辑错误
   ├── 验证伏笔回收合理性
   ├── 检查张力曲线
   └── 输出: Error Log
   │
   ▼
[Director] 审查Error Log
   │
   ├── 有严重错误?
   │   ├── 是 -> 退回 Librarian 重写
   │   └── 否 -> 继续
   │
   ▼
[Stylist] 文风润色
   │
   ├── 识别场景类型
   ├── Dynamic Few-Shot检索
   ├── 风格一致性修正
   ├── Reflexion迭代
   └── 输出: 最终文本
   │
   ▼
[Director] 合并输出
   │
   ├── 更新人物状态 (应用Mutation)
   ├── 更新大纲状态 (第三章标记为DONE)
   ├── 记录伏笔变更
   ├── 保存版本历史
   └── 输出给用户
   │
   ▼
[结束]
```

---

## 四、技术栈与目录结构

### 4.1 推荐技术栈

#### 阶段一: VSCode + OpenCode 模拟 (当前)
```yaml
环境:
  - VSCode + OpenCode Agent
  - Python 3.10+ (工具脚本)
  - Markdown (内容存储)
  - Git (版本控制)

Python依赖:
  - typer: CLI工具
  - pydantic: 数据验证
  - networkx: 图结构（伏笔DAG、知识图谱）
  - numpy: 向量计算
  - sentence-transformers: 文本嵌入
  - markdown-it-py: Markdown解析
  - yaml: 配置管理
  - watchfiles: 文件监控
```

#### 阶段二: Web应用
```yaml
后端:
  - FastAPI / Node.js + Express
  - Neo4j: 知识图谱存储
  - PostgreSQL: 结构化数据（大纲、人物卡）
  - Redis: 缓存、会话
  - Celery: 异步任务队列

前端:
  - React + TypeScript
  - React Flow: 大纲可视化、知识图谱可视化
  - TipTap / Slate.js: 富文本编辑器

AI:
  - OpenAI API / Claude API
  - LangChain / LlamaIndex: Agent框架
  - Vector DB: Pinecone / Weaviate / Chroma
```

### 4.2 目录结构 (阶段一)

```
openwrite/
├── README.md
├── PLAN.md                          # 本文件
├── config.yaml                      # 全局配置
├── requirements.txt
│
├── /data                            # 数据存储
│   ├── /novels                      # 小说项目
│   │   └── /{novel_id}
│   │       ├── metadata.yaml        # 小说元数据
│   │       │
│   │       ├── /outline             # 大纲系统
│   │       │   ├── archetype.md     # 总纲
│   │       │   ├── /volumes         # 卷纲
│   │       │   │   ├── vol_001.md
│   │       │   │   └── vol_002.md
│   │       │   ├── /chapters        # 章纲
│   │       │   │   ├── ch_001.md
│   │       │   │   └── ch_002.md
│   │       │   ├── /scenes          # 节纲（生成的草稿）
│   │       │   │   ├── ch_001/
│   │       │   │   │   ├── s_001.md
│   │       │   │   │   └── s_002.md
│   │       │   │   └── ch_002/
│   │       │   └── /snapshots       # 卷末快照
│   │       │       ├── vol_001_snapshot.md
│   │       │       └── vol_002_snapshot.md
│   │       ├── /characters          # 人物系统
│   │       │   ├── index.yaml
│   │       │   ├── /protagonist     # 主角
│   │       │   │   └── char_001/
│   │       │   │       ├── char_001.yaml      # 静态属性
│   │       │   │       ├── vol_001_snapshot.md  # 卷快照
│   │       │   │       ├── vol_002_snapshot.md
│   │       │   │       └── /logs              # 单章变更日志
│   │       │   │           ├── ch_001.md
│   │       │   │           └── ch_002.md
│   │       │   ├── /major           # 重要配角
│   │       │   │   └── char_002/
│   │       │   ├── /minor           # 普通配角
│   │       │   │   └── char_003/
│   │       │   └── /extras          # 炮灰
│   │       │       └── char_004/
│   │       │
│   │       ├── /world               # 世界观系统
│   │       │   ├── world_graph.yaml # 知识图谱定义
│   │       │   ├── /locations       # 地点
│   │       │   ├── /factions        # 势力
│   │       │   ├── /abilities       # 能力/功法
│   │       │   ├── /realms          # 境界/等级
│   │       │   ├── /artifacts       # 道具
│   │       │   └── /events          # 历史事件
│   │       │
│   │       ├── /foreshadowing       # 伏笔系统
│   │       │   ├── dag.yaml         # DAG结构
│   │       │   └── /logs            # 变更日志
│   │       │
│   │       ├── /style               # 文风系统
│   │       │   ├── style_profile.yaml
│   │       │   ├── /samples         # 样本文本
│   │       │   └── /embeddings      # 向量缓存
│   │       │
│   │       └── /manuscript          # 最终成稿
│   │           └── draft.md
│   └── /templates                   # 项目模板
│       └── default/
│
├── /tools                           # Python工具脚本
│   ├── __init__.py
│   ├── cli.py                       # 主CLI入口
│   │
│   ├── /parsers                     # 解析器
│   │   ├── markdown_parser.py       # Markdown解析
│   │   └── annotation_parser.py     # 标记语法解析
│   │
│   ├── /models                      # 数据模型
│   │   ├── outline.py
│   │   ├── character.py
│   │   ├── world.py
│   │   ├── foreshadowing.py
│   │   └── style.py
│   │
│   ├── /agents                      # Agent模拟
│   │   ├── director.py
│   │   ├── librarian.py
│   │   ├── lore_checker.py
│   │   └── stylist.py
│   │
│   ├── /graph                       # 图结构
│   │   ├── foreshadowing_dag.py
│   │   └── knowledge_graph.py
│   │
│   ├── /queries                     # 查询接口
│   │   ├── character_query.py
│   │   ├── world_query.py
│   │   └── outline_query.py
│   │
│   ├── /checks                      # 逻辑检查
│   │   ├── timeline_checker.py
│   │   ├── consistency_checker.py
│   │   └── foreshadowing_checker.py
│   │
│   └── /utils                       # 工具函数
│       ├── context_compressor.py
│       ├── version_control.py
│       └── embedding_utils.py
│
├── /tests                           # 测试
│   └── ...
│
└── /docs                            # 文档
    ├── architecture.md
    ├── agent_protocol.md
    └── markdown_syntax.md
```

---

## 五、MVP阶段与迭代路线图

### 5.1 阶段划分

#### Phase 1: 基础工具 (Week 1-2)
**目标**: 搭建基础数据结构和CLI工具

```yaml
任务:
  - [ ] 创建项目目录结构
  - [ ] 定义Pydantic数据模型
  - [ ] 实现Markdown解析器（伏笔标记、人物标记）
  - [ ] 实现基础CLI命令
      - openwrite init <novel_name>
      - openwrite character create <name>
      - openwrite outline create <chapter>
  - [ ] 实现简单查询工具
      - openwrite query character <name>
      - openwrite query world <keyword>
```

#### Phase 2: 大纲与伏笔 (Week 3-4)
**目标**: 完整的大纲系统和伏笔追踪

```yaml
任务:
  - [ ] 实现大纲层级结构
  - [ ] 实现伏笔DAG图
  - [ ] 实现伏笔标记语法解析
  - [ ] 实现伏笔状态检查
      - 检查未回收伏笔
      - 检查非法回收
  - [ ] 实现大纲版本历史
  - [ ] 大纲可视化（文本树形图）
```

#### Phase 3: 人物与状态 (Week 5-6)
**目标**: 人物系统和事件溯源

```yaml
任务:
  - [ ] 完善人物卡模型
  - [ ] 实现Mutation记录
  - [ ] 实现时间线重建
  - [ ] 实现人物状态查询
  - [ ] 实现一致性检查
      - 检查状态突变
      - 检查物品来源
```

#### Phase 4: 世界观图谱 (Week 7-8)
**目标**: 知识图谱和复杂查询

```yaml
任务:
  - [ ] 实现知识图谱模型
  - [ ] 实现图查询接口
  - [ ] 实现设定冲突检查
  - [ ] 导入示例数据
```

#### Phase 5: Agent模拟 (Week 9-12)
**目标**: 在OpenCode环境中模拟Agent协作

```yaml
任务:
  - [ ] 设计Agent提示词模板
  - [ ] 实现Director的上下文压缩
  - [ ] 实现各Agent的输入输出格式
  - [ ] 手动模拟完整工作流
  - [ ] 优化提示词和流程
```

#### Phase 6: Web应用 (Week 13+)
**目标**: 完整Web应用

```yaml
任务:
  - [ ] 后端API开发
  - [ ] 前端界面开发
  - [ ] 可视化编辑器
  - [ ] 知识图谱可视化
  - [ ] 实时协作
```

### 5.2 快速启动命令

```bash
# 初始化新项目
openwrite init my_novel --template xianxia

# 创建人物
openwrite character create "李逍遥" --tier protagonist

# 创建章节大纲
openwrite outline chapter create 3 --title "初入江湖"

# 查询人物当前状态
openwrite query character "李逍遥" --state

# 检查伏笔
openwrite check foreshadowing --status pending

# 生成章节（调用AI）
openwrite generate chapter 3 --agent librarian

# 检查逻辑
openwrite check logic --chapter 3

# 应用人物状态变更
openwrite character mutate "李逍遥" \
  --chapter 3 \
  --change "acquire:神秘玉佩" \
  --reason "山洞探险所得"
```

---

## 六、关键设计决策

### 6.1 为什么用Markdown而不是数据库？

**优势**:
- 作者可以直接阅读和编辑
- Git版本控制友好
- 与现有写作工具兼容（Obsidian, Typora）
- 渐进式增强，不锁定格式

**策略**:
- 阶段一: 纯Markdown + YAML Frontmatter
- 阶段二: Markdown存储 + 索引数据库
- 阶段三: 可选同步到数据库存储

### 6.2 上下文压缩策略

**200万字小说 = 约50万tokens**
一次性塞不进上下文，需要分级压缩：

```yaml
压缩策略:
  总纲: 全文摘要 + 主题关键词 (500 tokens)
  卷纲: 本卷摘要 + 关键事件 (300 tokens/卷)
  章纲: 前3章详情 + 本章 + 后1章 (2000 tokens)
  人物: 只取本章涉及人物 (500 tokens)
  设定: 动态检索相关设定 (500 tokens)

动态检索:
  - 从当前章节提取关键词
  - 查询知识图谱获取相关实体
  - 按相关度排序取Top-K
```

### 6.3 伏笔权重与回收策略

```yaml
权重定义:
  主线 (9-10): 影响最终结局，必须在特定章节回收
  支线 (5-8): 影响人物命运，建议在3-5章内回收
  彩蛋 (1-4): 增强趣味性，回收时间灵活

回收策略:
  主线伏笔:
    - Librarian生成时检查目标章节
    - 若非目标章节，禁止回收
    - 需回收时提前预警Director
  
  支线伏笔:
    - LoreChecker检查回收时机
    - 若过早回收给出警告
  
  彩蛋:
    - 自由回收
    - 但需记录回收位置
```

### 6.4 张力曲线系统

```yaml
张力评分 (tension_score):
  1-3: 日常/过渡/铺垫
  4-6: 小冲突/小高潮
  7-8: 中高潮/重要转折
  9-10: 大高潮/关键战役

检查规则:
  - 禁止: 连续3章张力 < 3（过于平淡）
  - 警告: 连续3章张力 > 8（疲劳轰炸）
  - 建议: 每5章至少1个张力 > 7的高潮
  - 强制: 卷末必须有张力 = 10的高潮

情感曲线 (emotion_curve):
  - 避免连续同类型情感（如连续5章悲伤）
  - 建议交替: 紧张 -> 温馨 -> 紧张 -> 悲伤
```

---

## 七、待决策问题

### 需要用户确认

1. **大纲修改权限**
   - 总纲/卷纲修改是否需要人工确认？
   - Agent提出的修改如何呈现给作者？

2. **人物状态变更**
   - Agent提议的状态变更自动应用还是人工审核？
   - 哪些变更需要确认（死亡、关系剧变）？

3. **文风样本**
   - 用户提供参考小说还是逐章训练？
   - 文风档案由AI生成还是人工编写？

4. **知识图谱构建**
   - 从文本自动提取还是人工录入？
   - 提取错误如何修正？

5. **多Agent并行度**
   - Librarian和LoreChecker完全并行还是串行？
   - Stylist是否必须在LoreChecker之后？

---

## 八、参考资源

### 技术参考
- LangChain Agent框架
- GraphRAG论文与实现
- Event Sourcing模式
- Reflexion论文

### 写作理论
- 《故事》罗伯特·麦基
- 《救猫咪》布莱克·斯奈德
- 三幕式结构、英雄之旅

### 相关项目
- NovelAI
- Sudowrite
- AI Dungeon
- 各种开源小说生成器

---

## 附录: 标记语法完整规范

### 伏笔标记
```markdown
<!--fs id=f001 weight=9 layer=主线 target=ch_015-->
这里埋下了伏笔内容...
<!--/fs-->

<!--fs-recover ref=f001 -->
这里回收了伏笔...
<!--/fs-recover-->
```

### 人物标记
```markdown
<!--char id=char_001 action=enter-->
人物登场
<!--/char-->

<!--char id=char_001 mutation="acquire:玉佩"-->
人物获得物品
<!--/char-->

<!--char id=char_001 mutation="relationship:char_002=敌对"-->
人物关系变化
<!--/char-->
```

### 场景标记
```markdown
<!--scene id=s_003 location=location_001 tension=8 emotion=紧张-->
场景内容...
<!--/scene-->
```

---

**文档结束**

> 下一步: 根据本计划开始Phase 1实现
