# 归档文件说明

本目录存放 OpenWrite 项目的历史文件，保留作为参考。

## 目录结构

```
_archive/
├── old_reports/          # 历史报告（第一~三期）
│   ├── 第一期报告.md
│   ├── 第二期报告.md
│   └── 第三期报告.md
│
├── old_skills/           # 旧版 Skill 目录（已被 skills/ 替代）
│   └── .agents/skills/
│       ├── openwrite-overview/
│       └── style-system/
│
├── old_workflows/        # 旧版工作流配置（已迁移到 skills/ 模块内）
│   └── workflows/
│       ├── chapter_writing.yaml
│       ├── outline_creation.yaml
│       ├── outline_modification.yaml
│       └── style_selection.yaml
│
├── old_data/             # 旧数据/临时文件
│   ├── my_novel/         # 测试项目数据
│   ├── composed/         # 风格合成输出（已迁移到 data/）
│   └── templates/        # 空目录
│
└── old_logs/             # 运行日志
    └── logs/
        ├── simulations/  # 模拟运行记录
        └── *.log         # 其他日志
```

## 说明

- **当前有效报告**: `第四期报告.md`（项目根目录）
- **当前 Skill 系统**: `skills/`（项目根目录）
- **当前工作流**: 已集成到各 Skill 模块的 `workflows/` 子目录
- **当前数据目录**: `data/`（项目根目录）

---

*归档时间: 2026-03-02*
