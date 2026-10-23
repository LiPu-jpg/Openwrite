# Gitee AI Embedding dimensions 兼容性修复（开发分支）

## 根因

用户在 OpenWrite「模型 → Embedding」中把 Qwen3-Embedding-8B 配置为 4096 维，但原
`tools/embedding_runtime.py` 调用 `client.embeddings.create()` 时只发送
`model`、`input` 和 `encoding_format`。界面中的 Dimension 原本只用于本地输出校验，
**没有传给提供商**。

2026-10-23 使用单独的临时开发凭据验证 Gitee AI `https://ai.gitee.com/v1/embeddings`：

| 请求 | HTTP | 返回向量 | 每条实际维度 |
| --- | --- | --- | --- |
| 不传 dimensions | 200 | 2 | 1024 |
| `dimensions: 4096` | 200 | 2 | 4096 |
| `dimension: 4096`（单数，非有效参数） | 200 | 2 | 1024 |

因此旧 OpenWrite 将正确的 1024 维响应判定为配置 4096 维不匹配，错误码为
`MODEL_TEST_INVALID_RESPONSE`，前端只能展示抽象提示。**并不是 Gitee AI 不支持 4096 维**。

## 修复

- OpenWrite Core 5.8.13（基于上游 5.8.12）：发送 `dimensions=settings.dimension`，同时保留
  `encoding_format=float`；只有 400/422 响应明确指出不支持 `dimensions`
  参数时，才回退到旧格式，回退结果仍必须通过严格的维度校验。
- Core 连接测试：维度不匹配时，保留 `MODEL_TEST_INVALID_RESPONSE` 的兼容错误码，
  但向界面返回安全的实际维度与配置维度，以及下一步处理建议。不会向客户端回显 API Key 或上游响应正文。
- Studio 模型管理：向量参数本地化，说明配置维度如何用于云端请求及改变索引维度的影响；
  Embedding 测试成功后直接展示维度、返回向量数量和延迟；错误码对应排查提示。
- Core 源码追踪：`kelriclink/Openwrite` 的 `fix/gitee-embedding-dimensions-core`，新 wheel 和
  `release/runtime-manifest.json` 的来源提交/SHA-256 保持一致。

## 验证与使用边界

- 真实 Gitee AI OpenAI SDK 调用：`run_embedding_probe()` 返回 2 条 × 4096 维（1153 ms），成功。
- Core 定向自动化测试：35 项通过，包括维度参数、旧服务商回退、不支持的维度与错误信息。
- 前端模型及 DTO 测试包括两种 Embedding 适配器下拉选择、本地字段切换及凭据不泄露；请以当前分支的 `npm run check` 结果为准。
- 临时凭据只用于进程内诊断，未写入源码、文档、测试断言或构建制品。
- 本分支仅是**开发修复**，不是 npm/Release 正式版；用户现有插件不会自动更新。
  修改了实际向量维度时，需要根据当前索引的维度/模型重建向量索引，不能混用旧向量。
