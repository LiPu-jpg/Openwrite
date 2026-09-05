# Style System Tools

风格系统现在默认走“项目内 source pack”模式。

## 设计原则

- 不内置参考作品风格库
- 不把版权作品片段随仓库分发
- 所有提取都来自用户自己提供的文本
- 提取结果写回当前小说项目，而不是全局共享目录

## 对应动作

| 动作 | 结果 |
|------|------|
| 风格初始化 | 写 `data/novels/{id}/data/style/fingerprint.yaml` |
| 风格提取 | 写 `data/novels/{id}/data/sources/{source_id}/...` |
| 风格合成 | 写 `data/novels/{id}/data/style/composed.md` |
| 风格分析 | 写 `data/novels/{id}/data/style/analysis_report.yaml` |

## 当前实现口径

- `tools/style_extraction_pipeline.py` 负责大文本提取的分块、进度和批次结果
- `tools/cli.py` 的 `style extract` / `setting extract` / `source review` / `source promote` / `style synthesize` 负责 CLI 入口
- `craft/` 提供通用技法，不提供作品样例库

## source pack 路径

```text
data/novels/{novel_id}/data/sources/{source_id}/
```

这是当前推荐的长期风格来源结构。
