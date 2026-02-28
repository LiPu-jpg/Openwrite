---
name: style
version: 1.0.0
description: |
  This skill should be used when the user wants to initialize, compose, or analyze
  the writing style. Triggers include "风格初始化", "合成风格", "风格分析",
  "去AI味".
trigger: /style
triggers:
  - "风格初始化"
  - "初始化风格"
  - "合成风格"
  - "风格分析"
  - "风格设置"
  - "去AI味"
  - "文风"
requires:
  - read_file
  - write_file
  - query_style
allowed-tools:
  - Bash(python:*)
  - Read
  - Write
---

# 风格系统功能

管理写作风格，包括初始化、合成和分析。

## 核心理念

**每个作品都有专属风格**，不是直接套用某个小说的风格。

风格初始化流程：
1. 通过问询了解作者偏好
2. 可选：从参考作品提取特征
3. 合并共享技法 + 专属设定
4. 生成作品专属 fingerprint.yaml

## 风格层次

```
┌─────────────────────────────────────────────┐
│  共享层（跨作品通用）                         │
│  ├── humanization.yaml    # 去 AI 味规则    │
│  ├── tropes/              # 叙事套路         │
│  └── dialogue_craft.md    # 对话技法         │
├─────────────────────────────────────────────┤
│  专属层（每部作品独立）                       │
│  ├── fingerprint.yaml     # 风格指纹         │
│  ├── voice.yaml           # 声音设定         │
│  └── constraints.yaml     # 硬性约束         │
└─────────────────────────────────────────────┘
```

## 共享技法库

### 文本人化（去 AI 味）
- 禁用词库
- 自然不完美规则
- 句式变化要求

### 叙事套路
- 冲突套路（"巨人逼近"、"先甜后打脸"）
- 揭示套路（"信息差"、"反转"）
- 转变套路（"成长弧"、"堕落弧"）

### 对话技法
- 格式规范
- 节奏光谱
- 乒乓球规则

## 使用方式

### 风格初始化
用户说"风格初始化"或创建新项目时：
1. 开始问询流程（5 个问题）
2. 记录偏好并生成 hints
3. 如有参考作品，提取风格特征
4. 合并共享层 + 专属层
5. 保存到 novels/{id}/style/fingerprint.yaml

### 风格合成
用户说"合成风格"：
- 重新合成所有风格层
- 输出到 composed/{novel_id}_composed.md

### 风格分析
用户说"风格分析"：
- 分析给定文本的风格特征
- 与当前作品风格对比
- 提供改进建议

## 工作流

- `workflows/initialize.yaml`: 风格初始化问询
- `workflows/iterate.yaml`: 风格迭代优化

## 提示词

- `prompts/initialize_style.md`: 风格初始化问询
- `prompts/extract_style.md`: 从参考作品提取风格
- `prompts/compose_style.md`: 合成风格文档
- `prompts/analyze_style.md`: 分析文本风格

## 工具

- `tools/style_initializer.py`: 风格初始化器
- `tools/style_extractor.py`: 风格提取器
- `tools/style_composer.py`: 风格合成器
