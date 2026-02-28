---
name: foreshadowing
description: 伏笔管理功能模块
triggers:
  - "伏笔"
  - "埋伏笔"
  - "回收伏笔"
  - "伏笔回收"
  - "伏笔状态"
  - "伏笔列表"
  - "待回收伏笔"
  - "伏笔依赖"
---

# Foreshadowing Skill

伏笔管理功能模块。

## 功能描述

管理小说中的伏笔系统，包括：
- 伏笔节点（埋设、待收、已回收）
- 伏笔依赖关系（DAG 结构）
- 伏笔状态追踪
- 环检测（防止循环依赖）

## 触发器

- "伏笔"、"埋伏笔"
- "回收伏笔"、"伏笔回收"
- "伏笔状态"、"伏笔列表"
- "待回收伏笔"
- "伏笔依赖"

## 指令

### 伏笔结构

```
data/novels/{novel_id}/foreshadowing/
├── dag.yaml                  # 伏笔 DAG 定义
└── logs/                     # 操作日志
    └── YYYYMMDD.log
```

### 伏笔状态

- `埋伏` - 已埋设，未到回收时机
- `待收` - 到了目标章节，等待回收
- `已收` - 已完成回收
- `逾期` - 超过目标章节未回收

### 伏笔层级

- `主线` - 主线剧情伏笔（权重 7-10）
- `支线` - 支线剧情伏笔（权重 4-6）
- `细节` - 细节伏笔（权重 1-3）

### 查询工具

1. `get_pending_foreshadowing` - 获取待回收伏笔
2. `get_foreshadowing_stats` - 获取伏笔统计
3. `validate_dag` - 验证 DAG 有效性
4. `create_foreshadowing` - 创建伏笔节点
5. `update_foreshadowing_status` - 更新伏笔状态

### 注意事项

- 主线伏笔必须指定目标章节
- DAG 不能有循环依赖
- 逾期伏笔需要特别关注
- 伏笔权重影响优先级
