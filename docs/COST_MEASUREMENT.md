# 小说工具成本比较方法

本文件只定义可复现的测量步骤。UTF-8 工具声明字节数 **不是** tokenizer token，也不是账单费用。没有作者在本会话明确提供的凭据时，真实服务商一行记为 `not-run`。

## 离线（默认，不调用模型）

在隔离环境执行：

```sh
npm --prefix packages/openwrite-bridge run build
node --test packages/openwrite-bridge/scripts/tool-policy.test.mjs
```

`real dsh tool registry isolates 90 tools` 会打印两行 JSON：

| 字段 | 含义 | 不是什么 |
|---|---|---|
| `measurement: native-tool-schema` 的 `utf8Bytes` | `JSON.stringify(tools)` 的 UTF-8 字节 | 不是 tokenizer token |
| `measurement: ptc-presentation` 的 `schemaBytes` | PTC 传输声明的 UTF-8 字节 | 不是缓存命中 |
| `sdkBytes` | 注入到 system prompt 的 SDK 文本字节 | 不是费用 |
| `tokenizer: not-measured` | 本仓库不内置某家 tokenizer | 不得改写成已测 token |

同一套检查还断言：普通预设 `novel_*` 为 0；创作预设为 90 且不随 PTC 另一 scope 改变。

要对比「请求大小」，把一次真实 `tools.schemas(agent)` 或 PTC `wireSchemas` 的 JSON 写入文件后对体积做 `wc -c` / SHA-256。这仍是请求体字节，不是 token。

## 真实服务商（需明确授权）

仅当作者在当前会话提供密钥，并且同意产生费用时执行。不要从聊天记录、临时文件或其他应用配置里找密钥。

1. 使用同一创作预设、同一章节、同一提示，分别跑 native 与 PTC（若宿主支持）。
2. 记录：HTTP 请求体字节、服务商返回的 `usage`（prompt/completion/cache 读写）、账单金额、缓存命中字段（若有）。
3. 取消一次生成：确认不再调度新请求，已完成候选与用量保留；若服务商请求仍在途，界面保持「取消中」，不得记为已撤回。
4. 报告分成两块：`offline` 与 `provider`。缺凭据时 `provider.status = not-run`。

## 本任务状态

- 离线 schema 字节：由 tool-policy 测试每次打印。
- 真实 tokenizer / 缓存命中 / 费用：`not-run`（无本会话授权的模型凭据）。
