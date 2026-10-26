# OpenCode Go：DeepSeek V4.1 Flash

#114 的底层请求和工作台认证接入分两步完成。0.2.26（Core 5.8.14）仅补充客户端/会话请求头；工作台的 Console 认证、工作区与续期接入从 Core 5.8.15 开始，正式插件版本以 npm/Release 为准。

## 工作台：使用已有 Console 登录

1. 在 **Studio 后端所在电脑**安装官方 OpenCode CLI 并登录 OpenCode Console。已验证 CLI 1.18.15 的 `opencode console login`；官方 V2 对应 `opencode auth login opencode`，以当前 CLI 提示为准。浏览器授权由用户按页面范围确认。
2. 打开「任务 → 模型」，在认证方式选择 **本机 OpenCode Console（Go）**。界面填入官方 Go Chat 地址与 `deepseek-v4.1-flash`，无需复制 API Key。
3. 工作区 ID 留空会跟随 CLI 当前工作区；可填写 ID 固定到指定工作区。若 CLI 切换到其他工作区，固定档案会拒绝请求，而非悄悄换账户/工作区。
4. 保存并运行连接测试，成功后再把档案选为写作/评审/研究等任务路由。

远程/外部 Studio 使用的是远程后端的 CLI 登录，不是浏览器所在电脑的登录。CLI 不存在、未登录、配置读取失败或工作区不匹配时，工作台提供对应登录/工作区提示。

每次模型请求通过 `opencode debug config --pure` 读取 Go 凭据与 `x-opencode-org-id`，官方 CLI 负责令牌续期；OpenWrite 不把 Console 令牌复制到模型档案、浏览器 DTO 或日志。普通、流式、连接测试及图检索调用均携带真实 `OpenWrite/<版本>` 和客户端内稳定的 `x-opencode-session`。Console 认证只允许官方 Go HTTPS Chat 接口，不能通过编辑 Base URL 把令牌发送给其他站点。

## 手工 API Key

| 字段 | 值 |
| --- | --- |
| Provider / 协议适配器 | `openai` |
| API format | `chat` |
| Base URL | `https://opencode.ai/inference/go/openai/v1` |
| Model ID | `deepseek-v4.1-flash` |
| 认证方式 | API Key |
| Go 工作区 ID | 账户级凭据需要填写对应工作区 ID |

不要把 OpenCode 的 `opencode-go/` 模型选择前缀放入原始 API Model ID。完整 `/chat/completions` 地址会被 Core 规范化为 API 根路径；旧 `/zen/go/v1` 地址继续兼容。

`401 api_key_expired` 表示旧 Key 过期，普通网页登录不能续期该 Key。对于 Console 登录，请使用上述工作台认证方式；`403 Workspace selection is required` 表示账户级凭据缺少 `x-opencode-org-id`，仅填写 URL/模型/Key 不够。

## 实测与边界

2026-10-26 使用用户授权的 Go 订阅验证：0.2.26 底层手工补齐 Console 工作区请求头后，普通与流式小说生成均 HTTP 200；去掉工作区头时为 HTTP 403。补齐后的工作台 API 保存 Console 档案、测试连接返回 `OK`，经保存档案的实际流式写作也成功；没有手工传入 Key 或请求头，作者正文与作品配置哈希未变，Console 令牌未写入模型凭据文件。

自动回归覆盖每次请求读取更新凭据、64 KiB 以上 CLI 配置、超时/缺失/工作区错误的脱敏、错误目标站点拦截、普通 Key 工作区、图检索、连接测试、档案迁移及前端保存/测试。

[官方 Go 文档](https://opencode.ai/v2/docs/console/go/)要求 DeepSeek 所用工作区 Privacy → Regions 允许 Global。Go 面向编码客户端，本次短文实测通过不保证服务商未来接受所有小说任务；仍需遵守账号用途、地区与额度规则。此接入覆盖 OpenWrite Core 模型调用，DSH 聊天适配器属于宿主，未在此修改。
