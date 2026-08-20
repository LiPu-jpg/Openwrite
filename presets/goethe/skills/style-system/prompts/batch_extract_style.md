# 大文本分批风格提取提示词

你正在处理一部用户提供的大文本。你的任务是逐批提取风格信号，并逐渐更新项目内的 source pack。

## 路径

```text
data/novels/{novel_id}/data/sources/{source_id}/
```

其中：

- `style/*.md`：累计更新的风格文档
- `setting_profile.md`：累计更新的设定提要
- `extraction/batch_results/*.yaml`：每批次原始发现

## 每批次要做的事

1. 阅读当前 chunk
2. 参考现有 `style/*.md`
3. 输出本批次发现
4. 区分 `reusable` 与 `source_bound`
5. 更新对应风格文档

## 关注重点

### 前几批

- 定主基调
- 定叙述距离
- 定句长和段落节奏
- 识别高频对话模式

### 中间批次

- 看这些特征是否稳定
- 修正之前的误判
- 补充例外情况

### 后几批

- 补边缘模式
- 查缺补漏
- 总结真正稳定的可复用信号

## 输出格式

```yaml
findings:
  reusable:
    - name: ""
      dimension: ""
      description: ""
      evidence: []
  source_bound:
    - name: ""
      type: ""
      description: ""
  summary: ""
```

## 禁止事项

- 不把专名当成风格
- 不把剧情设定误判成节奏特征
- 不长篇复制原文
