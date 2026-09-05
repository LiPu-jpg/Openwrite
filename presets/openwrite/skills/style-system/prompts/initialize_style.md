# 风格初始化提示词

你要通过问答帮用户生成这本书的初始风格指纹。

## 目标文件

```text
data/novels/{novel_id}/data/style/fingerprint.yaml
```

## 询问重点

1. 基调
2. 节奏
3. 对话/描写比例
4. 是否有用户提供的参考文本
5. 禁止事项或特别要求

## 输出要求

- 只记录可执行的风格偏好
- 不凭空创造“参考作品特征”
- 如果用户有自己的样文，记成 `source_id`
- 不写具体版权作品名作为默认建议

## 示例思路

输入：

- 基调：轻压抑但偶尔冷幽默
- 节奏：中快
- 对话：占比高
- 来源：用户提供一篇职场悬疑样文
- 禁止事项：不要堆网络流行语

输出：

```yaml
core:
  tone: "轻压抑 + 冷幽默"
  pacing: "中快"
  dialogue_ratio: 0.55

source:
  source_id: "office_excerpt"
  source_type: "user_supplied_text"

constraints:
  banned_phrases: []
  custom_rules:
    - "避免网络流行语"
```
