---
name: character
description: 角色管理功能模块
triggers:
  - "创建角色"
  - "添加角色"
  - "新建人物"
  - "查询角色"
  - "获取角色信息"
  - "角色关系"
  - "人物关系"
  - "角色时间线"
  - "人物状态历史"
  - "更新角色状态"
---

# Character Skill

角色管理功能模块。

## 功能描述

管理小说中的角色信息，包括：
- 角色档案（静态信息、动态状态）
- 角色关系网络
- 角色时间线（状态变更历史）
- 角色摘要生成

## 触发器

- "创建角色"、"添加角色"、"新建人物"
- "查询角色"、"获取角色信息"
- "角色关系"、"人物关系"
- "角色时间线"、"人物状态历史"
- "更新角色状态"

## 指令

### 角色档案结构

```
data/novels/{novel_id}/characters/
├── cards/                    # 角色卡片（YAML）
│   └── {character_id}.yaml
├── profiles/                 # 详细档案（Markdown）
│   └── {character_id}.md
├── text_profiles/            # 文本优先档案（YAML）
│   └── {character_id}.yaml
└── snapshots/                # 状态快照
    └── {volume_id}/
        └── {character_id}.yaml
```

### 角色类型

- `主角` - 主要角色
- `重要配角` - 重要配角
- `普通配角` - 普通配角
- `龙套` - 临时角色（不记录详细档案）

### 查询工具

1. `get_character_state` - 获取角色当前状态
2. `get_character_timeline` - 获取角色时间线
3. `get_character_relationships` - 获取角色关系
4. `list_characters` - 列出所有角色

### 注意事项

- 炮灰角色不记录详细档案
- 主要角色使用多段文字描述
- 角色状态通过时间线重建
