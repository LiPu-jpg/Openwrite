---
name: workflow-manager
description: Use when user wants to check writing progress, manage workflow stages, or resume interrupted tasks. Triggers include "工作流", "进度", "阶段", "写作流程".
---

# 工作流管理系统

管理章节写作流程，跟踪每个阶段的进度。

## 核心概念

**写作流程阶段**：
1. `context_assembly` - 组装上下文
2. `writing` - 生成草稿
3. `review` - 审查
4. `user_confirm` - 用户确认
5. `styling` - 风格润色
6. `compression` - 压缩归档

**阶段状态**：
- `pending` - 等待执行
- `running` - 执行中
- `completed` - 已完成
- `failed` - 失败
- `skipped` - 跳过

## 可用工具

| 工具 | 说明 |
|------|------|
| `get_workflow_status` | 获取工作流状态 |
| `start_workflow` | 启动工作流 |
| `advance_workflow` | 推进工作流 |

## 使用示例

### 查看所有工作流

```
用户: 目前有哪些章节在工作流中？

AI:
[COMMAND] get_workflow_status {}

结果:
- 进行中: ch_003, ch_005
- 已完成: ch_001, ch_002
- ch_003: 阶段=review (审查)
- ch_005: 阶段=writing (写作)
```

### 查看特定章节进度

```
用户: ch_003 现在到哪个阶段了？

AI:
[COMMAND] get_workflow_status {
  "chapter_id": "ch_003"
}

结果:
- 章节: ch_003
- 当前阶段: review
- 阶段详情:
  - context_assembly: ✅ completed
  - writing: ✅ completed
  - review: 🔄 running
  - user_confirm: ⏳ pending
  - styling: ⏳ pending
  - compression: ⏳ pending
```

### 启动新工作流

```
用户: 开始写第四章

AI:
[COMMAND] start_workflow {
  "chapter_id": "ch_004"
}

结果: ✅ 工作流已创建: ch_004
当前阶段: context_assembly
```

### 推进工作流

```
用户: ch_003 审查完成了，继续下一步

AI:
[COMMAND] advance_workflow {
  "chapter_id": "ch_003"
}

结果: ✅ 已推进到 user_confirm
```

### 跳到特定阶段

```
用户: ch_003 用户已确认，直接到润色

AI:
[COMMAND] advance_workflow {
  "chapter_id": "ch_003",
  "stage_name": "styling"
}

结果: ✅ 已推进到 styling
```

## 工作流生命周期

```
创建 → context_assembly → writing → review → user_confirm → styling → compression → 完成
```

**中断恢复**：如果会话中断，重新打开时用 `get_workflow_status` 查看进度，然后 `advance_workflow` 继续。

## 与其他系统的关系

- **上下文组装** → 调用 `get_context`
- **写作** → 调用 `write_chapter`
- **审查** → 调用 `review_chapter` + `validate_post_write`
- **确认** → 用户手动确认
- **润色** → 调用风格系统
- **归档** → 调用 `compress_section`
