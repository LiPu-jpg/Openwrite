# OpenCode Go：DeepSeek V4.1 Flash

#114 的配置应使用 OpenAI 兼容 **Chat Completions** 协议。
按 [OpenCode Go 官方文档](https://opencode.ai/v2/docs/console/go/)（2026-10-26 核对）：

| OpenWrite 模型档案字段 | 值 |
| --- | --- |
| Provider / 协议适配器 | `openai` |
| API format | `chat` |
| Base URL | `https://opencode.ai/inference/go/openai/v1` |
| Model ID | `deepseek-v4.1-flash` |
| API Key | 当前 OpenCode Go 工作区的 Key |

不要把 OpenCode 自己的 `opencode-go/` 模型选择前缀放入原始 API Model ID。
完整 `/chat/completions` 地址也会被 Core 规范化为 API 根路径；旧 `/zen/go/v1`
地址仅作为原有配置保留，不作为当前官方地址推荐。

Core 5.8.14 对 Go 请求自动发送真实 `OpenWrite/<版本>` User-Agent 与同一客户端内稳定的
`x-opencode-session`，符合官方客户端标识说明；不会冒充其他应用，也不发送作品路径。
这覆盖 OpenWrite Core 的模型调用，DSH 对话模型另由宿主自己的适配器处理。

官方说明 DeepSeek 模型可能需要工作区 Settings → Privacy → Regions 允许 Global。
Go 面向编码客户端，服务端的用途、地区、权限或额度策略仍可能拒绝请求；若订阅不适用写作，
应选用服务商允许的 API 产品。这里不会尝试绕过服务端限制。

先在「任务 → 模型」保存档案并运行连接测试，再将其选为写作/评审路由。
认证、授权、模型不存在及限流分别保留对应错误码。若仍失败，反馈脱敏错误码、HTTP 状态、
所用 API 路径和模型名即可，不需要提供 API Key。

自动化测试核对新旧 Go 根路径、Chat 协议、原始模型名和稳定请求头；未使用用户的 Go 凭据，
未执行收费请求，也不保证特定账户的授权状态。该修复是否已发布，以 npm/Release 为准。
