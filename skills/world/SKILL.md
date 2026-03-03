---
name: world
description: 世界观管理功能模块
trigger: /world
triggers:
  - "世界观"
  - "世界设定"
  - "添加地点"
  - "创建组织"
  - "实体关系"
  - "世界图谱"
  - "世界规则"
  - "设定约束"
  - "冲突检查"
  - "查看世界观"
  - "世界观管理"
  - "世界"
---

# World Skill

世界观管理功能模块。

## 功能描述

管理小说的世界观设定，包括：
- 世界实体（地点、组织、物品、概念）
- 实体关系（从属、对立、合作等）
- 世界规则（硬性约束）
- 冲突检测

## 触发器

- "世界观"、"世界设定"
- "添加地点"、"创建组织"
- "实体关系"、"世界图谱"
- "世界规则"、"设定约束"
- "冲突检查"

## 指令

### 世界观结构

```
data/novels/{novel_id}/world/
├── graph.yaml                # 实体关系图谱
├── entities/                 # 实体详情
│   ├── locations/
│   ├── organizations/
│   ├── items/
│   └── concepts/
└── rules.yaml                # 世界规则
```

### 实体类型

- `location` - 地点
- `organization` - 组织/势力
- `item` - 重要物品
- `concept` - 概念/术语
- `event` - 历史事件

### 关系类型

- `contains` - 包含（地点层级）
- `belongs_to` - 属于（组织成员）
- `opposes` - 对立
- `allies_with` - 结盟
- `created` - 创造
- `owns` - 拥有

### 查询工具

1. `get_entity` - 获取实体信息
2. `list_entities` - 列出实体
3. `get_relationships` - 获取关系
4. `check_conflicts` - 检查冲突

### 注意事项

- 世界观规则是不可违反的硬性约束
- 实体变更需要记录原因
- 冲突检测应定期运行
