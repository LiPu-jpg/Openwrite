# Changelog

## 0.2.39：宿主兼容扩到 dsh 0.2.2-rc.2 与 0.2.2-rc.3，并新增隐私安全的诊断反馈与引导

修 [#170](https://github.com/LiPu-jpg/Openwrite/issues/170)（`dsh-openwrite@0.2.38` 在 `dsh 0.2.2-rc.3` 上被安装前闸门直接拒绝），并改进「设置 → OpenWrite」诊断反馈与 Agent 初始引导：

- 根包与两个内嵌子包（`@dsh-novel/openwrite-bridge`、`@dsh-novel/studio-panel`）以及三个 lock 文件的 `@deepseek-ai/dsh-*` peer 范围、`dsh.compatibility.dsh`、`dshReleases` 同步加入精确宿主 `0.2.2-rc.2` 与 `0.2.2-rc.3`。
- 两个新宿主仍使用 `@deepseek-ai/cordis ~4.1.0`，既有 peer 匹配集合只增不改（`0.1.2-rc.1`、`0.1.5-alpha.1`、`0.1.7-rc.2`、`0.2.0-rc.2`、`0.2.1-rc.2`–`0.2.1-rc.5`、`0.2.2-rc.1` 不受影响）。
- 发布矩阵与最终验收门禁新增 `0.2.2-rc.2` 与 `0.2.2-rc.3` 的客户端验收任务，各自带 `--before` 截止时间。
- **「设置 → OpenWrite → 环境」新增隐私安全的诊断复制与开源支持卡片**：提供一键「复制脱敏诊断信息」与「去 GitHub 反馈问题（自动带入环境信息）」，以及 GitHub Star 支持入口；诊断信息自动脱敏本地用户目录（`<HOME>`）与令牌，绝不包含任何小说正文、大纲、角色设定、本地作品路径或 API 密钥。
- **Agent 初始引导与隐私安全排障引导**：`openwrite` 预设与 `/progress` 技能新增空项目/首次上手 3 步引导（配模型 → 聊设定与大纲预览 diff → 斜杠命令推进连载）及隐私安全的故障反馈指引。
- **修复「设置 → OpenWrite → 搜索」全局默认无法持久化与显示截断（Core 5.8.32 + Studio Panel）**：Core `StudioResearchSettingsStore` 在 DSH 托管模式下现在会读取带 `explicit: true` 的全局 `research-settings.json`，不再把用户保存的 Bing/博查/Jina/不联网覆盖回 `dsh`；同时放大搜索源卡片布局避免 `DSH web_search / web_fetch` 文本截断，右上角标签明确显示 `当前默认：<Provider>`，并在服务端回读未保留选择时提示报错而非误报已保存。

## 0.2.38：预设挂载失败不再被一句「Unknown agent preset」盖住

修 [#166](https://github.com/LiPu-jpg/Openwrite/issues/166)（0.2.37 升级后仍进不去工作台）。

- **报错不再说谎。** 客户端先选稳定 id `openwrite`，失败后再回退去选带版本号的 id
  `openwrite-0-2-37`；而带版本号的 id 在 0.2 系宿主上**从不注册**（它被显式排除在别名集合之外），
  所以这句「Unknown agent preset: openwrite-0-2-37」永远出现、却只描述了回退本身，
  真正的失败原因（宿主拒绝挂载、会话已开始等）被整段丢弃。
  现在客户端保留**每一次**尝试的原始报错并一起抛出，第一条就是真实原因；
  回退也改为「按宿主名册里真实注册过的 id 再找一次」，而不是猜一个必然不存在的 id。
- **宿主找不到时不再硬挂那一行。** 可选行（`dsh-tool-subagent-control/list-agents`）此前只有在
  能定位到宿主包树时才会被丢弃；定位不到时反而保留——而桌面版（Electron）把宿主放在应用包内、
  profile 里只有插件，定位必然落空，于是保留了一行 0.2.2 线宿主已经删掉导出的行，
  宿主因此拒绝整个预设。现在改为**除非能确认宿主提供，否则一律不挂**：
  少一个工具是可承受的，工作台整个起不来不可承受。
- **桌面版也能定位宿主。** 宿主包的查找多了一条路径：进程入口向上的 `node_modules/@deepseek-ai/dsh`。
  桌面应用从「不属于任何包」的入口启动，宿主只存在于应用包内，这正是此前定位落空的原因。
- **宿主日志会写明原因。** 插件注册完预设后会回读宿主名册；预设挂载失败时，宿主日志里会出现
  `OpenWrite preset openwrite did not mount: <原因>`，不再需要靠那句回退报错猜。
- 回归用例补齐：宿主无法定位时可选行必须被丢弃（`scripts/preset-lifecycle.test.mjs`）。

> 0.2.36 与 0.2.37 在桌面版 profile 上都可能因同一原因进不去工作台；
> 若 0.2.38 仍失败，请把宿主日志里 `OpenWrite preset` 那一行发到 issue 里。

## 0.2.37：把 cordis 的 peer 范围补到宿主实际使用的 4.1.x

功能与 0.2.36 一致；本次只修一处声明错误。

- 0.2.36 声明支持 dsh 0.2.2-rc.1，但插件自己的 `@deepseek-ai/cordis` peer 范围仍写着 `4.0.2 || ~4.0.4`。
  dsh 0.2.2 线的宿主带的是 cordis 4.1.0（0.1.2-rc.1 是 4.0.2，0.1.7-rc.2 与 0.2.1-rc.5 是 4.0.5），
  4.1.0 不在范围内：npm 会直接以 `ERESOLVE` 拒绝安装，pnpm 只警告一句 `unmet peer`。
  声明与事实不符，装得上装不上取决于包管理器——这正是本次要修的。
- 根包与两个内嵌子包的 cordis peer 范围改为 `4.0.2 || ~4.0.4 || ~4.1.0`，三个 lock 文件同步。
  插件在 cordis 4.1.0 上确实可用：0.2.2-rc.1 宿主的跨宿主验收腿全绿，工作台在该宿主上挂载通过。
- 发布矩阵新增一步：把插件按该宿主解析一遍（`npm install --dry-run` 装进已装好宿主的 profile），
  peer 范围与宿主实际依赖冲突时矩阵腿当场失败，而不是等用户安装时才报。

> 0.2.36 已发布，但它的 cordis peer 范围不含 4.1.0；在 dsh 0.2.2-rc.1 上请用 0.2.37。

## 0.2.36 / Core 5.8.31：宿主兼容扩到 dsh 0.2.2-rc.1 与 0.1.7-rc.2，并修掉大纲插入与 Windows 启动器

### 宿主兼容矩阵扩展

- 宿主在安装前读取包里的 `@deepseek-ai/dsh-*` **peer 范围**做版本闸门，`dsh.compatibility` 只是展示元数据，
  因此根包、两个内嵌子包（`@dsh-novel/openwrite-bridge`、`@dsh-novel/studio-panel`）和四个 lock 文件
  的 peer 范围、`dsh.compatibility.dsh`、`dshReleases` 同步加入精确宿主 `0.1.7-rc.2` 与 `0.2.2-rc.1`。
- 这修复了 [#160](https://github.com/LiPu-jpg/Openwrite/issues/160)、
  [#163](https://github.com/LiPu-jpg/Openwrite/issues/163)（dsh 0.2.2-rc.1）与
  [#161](https://github.com/LiPu-jpg/Openwrite/issues/161)（dsh 0.1.7-rc.2）的
  `plugin does not support the DSH version in use` 拒装——失败发生在安装之前，与 Node、pnpm、操作系统无关。
- 旧宿主的 peer 匹配集合逐项对比只增不改（`0.1.2-rc.1`、`0.1.5-alpha.1`、`0.2.0-rc.2`、
  `0.2.1-rc.2`–`0.2.1-rc.5` 不受影响）。
- 发布矩阵新增这两个宿主的客户端验收任务，并各自保留 `--before` 截止时间，
  避免上游部分发布时把更新的依赖批次带进旧宿主验收。

### 预设行的宿主判定改到宿主自己的包树

- dsh 0.2.2 把 `list_agents` 并入 `@deepseek-ai/dsh-tool-subagent-control` 主入口并删掉了
  `./list-agents` 子路径导出。宿主解析不到这一行就会**拒绝整个预设**，工作台因此挂不起来。
- 先前这行的去留是在**插件自己的 node_modules** 里探测的，而宿主是在**自己的包树**里解析预设行的
  （cordis loader 直接 `import(name)`）。两个树不是一回事：真实 profile 里插件根本没装宿主的包，
  而仓库里又常驻着旧宿主，探测永远给出错误答案。
- 现在改为在宿主的包根上解析该 specifier：能解析就保留，不能解析才丢弃。
  判定跟着宿主真实导出的走，不再跟某个写死的版本号走。
- 同一份代码在 `0.2.2-rc.1` 上丢弃该行、在 `0.2.1-rc.5` 与 `0.1.7-rc.2` 上保留该行；
  `scripts/preset-smoke.mjs` 按被测宿主判定，工作台挂载在两个宿主上都已实测通过。

### Core 5.8.31

- **[#162](https://github.com/LiPu-jpg/Openwrite/issues/162)：`novel_outline_edit(add_after)` 在卷/幕/节上永久 400。**
  该操作此前只接受与目标同级的层级，而容器节点没有同级的下级，于是「在某个卷之后新增一幕」
  对任何 `kind` 都撞上「新增层级与当前节点不匹配」。
  新节点现在可以落在两处：目标的**下一个兄弟**（同层级，行为不变），或目标的**最后一个下级**
  （即目标容器接受的层级：卷→幕、幕→节、节→章）。拒绝时的提示改为列出此处可新增的层级，调用方不必再猜。
- **[#164](https://github.com/LiPu-jpg/Openwrite/issues/164)：Windows 启动脚本命令偏移。**
  `启动 OpenWrite.bat` 以 LF 行尾随 wheel 一起发布，而 cmd.exe 按字节偏移续读批处理文件：
  LF 行尾叠加文件里的多字节 UTF-8，cmd 会从词中间接着读，把 `set` 的尾巴 `t`、`nul` 的尾巴 `ul`
  当成命令执行。文件现在以 CRLF 提交（`.gitattributes` 固定），macOS 的 `.command` 保持 LF。
- **[#164](https://github.com/LiPu-jpg/Openwrite/issues/164)：装依赖时找不到 setuptools。**
  启动器先把 setuptools 装进运行环境，随后那次带隔离的 editable 安装又会**再下载一份**构建后端；
  镜像取不到时就报「No matching distribution found for setuptools>=77」——这条报错与 OpenWrite
  自己的依赖无关。editable 安装改为复用环境里已装好的构建后端。
- `requirements.txt` 原先比 `pyproject.toml` 少了六个运行时依赖，其中四个正是启动器自检时要 import 的
  （openai / anthropic / markdown_it / prompt_toolkit），按该文件装出来的环境会被判为不可用；
  两份清单现已对齐，并有回归用例防止再次漂移。
- Core 全量 1777 passed / 33 skipped；捆绑 wheel 与来源提交 `89dd74c` 逐字节校验通过（506 个源文件）。


## 0.2.35：联动区的模型选择不再被默认模型覆盖

功能与 0.2.34 一致；本次只带一个修复。

- 设置 → 联动插件里接入 `dsh-our-free-model` 时，网关数据是异步到的，于是「取列表第一个模型当默认值」
  这个 effect 可能落在作者已经选好模型之后，把选择重置回第一个，写进模型配置的就是错的模型。
  现在只在作者还没选过时才采用默认值；已经选过、且网关仍然提供的模型予以保留；
  选中的模型不再提供时才退回第一个。
- 修掉把上述竞态暴露出来的 CI 失败：测试原先等的是「写入按钮存在」，而按钮在默认模型落地前是禁用的，
  于是等待可能早于 effect，写入的模型偶发变成列表第一个。测试改为等按钮可用，并断言选中的模型，
  迟到的重置会在这里直接失败，而不是悄悄写错模型。

## 0.2.34：Core 指针前移，让发布校验跑到修好的 Core 回归

功能与 0.2.33 一致；本次只把捆绑 Core 的来源提交从 `b9fcacfa` 前移到 `82bae73`。

- Core 5.8.30 的那条「研究质量在启动子进程前被拒绝」用例原先依赖运行机器的 `pnpm` 是否在 PATH 上：
  Linux 与 Windows 的 CI runner 没有 `pnpm`，于是服务先报 `RESEARCH_RUNTIME_UNAVAILABLE`，
  用例永远走不到它要验的质量校验。Core 现在按同文件既有写法桩掉工具链查找——
  若真走到启动子进程那一步，用例仍会失败（`test-pnpm` 不可执行）。
- Core 5.8.30 的运行时内容未变，捆绑 wheel 与来源提交的逐字节校验不受影响；
  `docs/CONTEXT_SLOTS.md` 按新提交重新生成。

## 0.2.33 / Core 5.8.30：深度研究搜索默认走 DSH web_search / web_fetch

- **默认搜索提供方 `dsh`**：托管运行时由宿主把 `ctx.web` 的搜索/抓取能力经环回中继交给 Core；没有 Key、
  不走第三方搜索 API。外部 Studio 仍默认 `bocha`，可在设置里切换。
- **工作台「研究」页新增搜索设置**：选择提供方、填写/清除 API Key、记住 Key；`dsh` 显示无需 Key 的说明。
  保存走 `POST /api/research/settings`，与工具 `novel_research_settings_save` 同一路由。
- **宿主中继**：新增 `host-web.ts`（`/search`、`/fetch`、Bocha 兼容 `/bocha`，仅 127.0.0.1 + 机器 token），
  通过 managed runtime 的私有 handshake 传给 Core；Core 用 Bocha 兼容端点接入现有 DeepResearch
  搜索管线，并用 `FETCH_PROVIDER=dsh` 的新 Relay fetch provider 走 `web_fetch`。
- 契约：`research-surface-v1` 的 provider enum 增加 `dsh`；Core 设置默认在托管环境为 `dsh`。
- 测试：宿主中继 4 项、Core 搜索设置/环境 2 项、研究页设置保存 1 项；组件 400 passed。
- DeepResearch 仍是可选依赖；首次使用需在其 integration 目录执行 `pnpm install --frozen-lockfile`。
- `research.quality` 在启动子进程前校验为 `advisory` / `balanced` / `strict`，不再把 `fast` 之类的值交给 pnpm 后才报 `Unsupported --quality`。

## 0.2.30：三条联动插件的可执行接入

- **dsh-our-free-model**：联动区的接入按钮不再只写一条 model profile，还会读取全局路由并在确认后把
  `chapter_write` / `review` 切到 `our-free-model`；规划、检索、研究等其余路由不动。已存在 profile 或路由将变化时
  二次确认，路由失败会明确报告“profile 已写入、路由失败”，不谎称整体成功。网关地址自带 `/v1` 时不再拼成 `/v1/v1`；
  面板注明写的是全局路由，作品内 `model_routes` 优先。
- **dsh-ops**：`/studio-panel/companions` 用与预设行相同的选项调用上游 `resolveIntegrationConfig`，返回并展示实际解析出的
  文件工具/渐进发现/呈现方式/是否替换官方工具/shell 与常驻工具数；上游没有该导出时退回概述。
- **dsh-dog**：保留“不内置 DoG”的边界，新增非斜杠技能 `dog-delivery-verification`：把章节/整书正文、最新评审与交付
  preflight 证据写成工作区内的不可变 handoff 包和 DoG 0.9 图，由 Agent 经 `dog_validate`/`dog_create`/`dog_run` 做独立判断；
  未安装时回到 OpenWrite 门禁，不假装跑过。
- 面板对 dsh-dog 的状态文案改为“已安装且宿主放行”，不再暗示 OpenWrite 自动委托。
- 测试：companions 组件 10 项（含路由切换确认、部分成功、关闭路由、ops 计划、`/v1` 规范化），companion 检测 21 项。

## 模型打通宿主：直接用 dsh 本体的模型和其它插件提供的模型

需求：OpenWrite 要能**直接使用 dsh 本体能用的模型**，也能用**别的插件提供给本体的模型**
（Our Free Model 那批白嫖模型），并且路由表**不再区分 Goethe / Dante 两个 agent**。
Core 授权可改。

### 做法：宿主开一个 OpenAI 兼容的环回中继

Core 用 LiteLLM 走 OpenAI chat-completions 协议，所以只要给它一个普通 HTTP 端点，
它就能调用宿主目录里的任何模型——**凭据不出宿主**，中继只翻译请求形状。

- **新增** `packages/openwrite-bridge/src/host-llm.ts`：`HostLlmRelay`
  - 绑 `127.0.0.1` 的**临时端口**（不占用宿主 web 端口，也不暴露给局域网），
    只认一台**机器令牌**（`Authorization: Bearer`）。
  - `GET /v1/models` → 宿主模型目录（`ctx.llm.listProviders()` + `listModels()`，
    附带 `resolveModelInfo()` 给出的上下文窗口）；`POST /v1/chat/completions` →
    OpenAI 形状的请求/响应，**支持 SSE 流式**。
  - 消息按宿主词表转换：system → system-prompt、user → user、assistant → model、
    tool → tool 结果；工具调用走 `tool-call` block。
  - 伪模型 `host/current` = 「宿主当前会用的那个模型」，每次调用时解析。
  - **装配按宿主的语义**：`block-end` 携带的整块内容才是权威，delta 只是增量视图；
    两种都给时不会重复计数。
  - **失败如实上报**：宿主的终止 finish（`{kind:'error'|'aborted', failure}`）会被
    转成带**服务商原始状态码**的错误，而不是一个空 200。
- **握手**（`packages/openwrite-bridge/src/managed-runtime.ts`）：Core 启动时
  通过私有的 stdio 握手收到 `host_llm: {url, token}`。
  端口是临时的，所以**每次启动都重新解析**，绝不缓存；中继起不来时**不影响 Core 启动**。
- **Core 侧**（`.wt-native-core`）：
  - 新增 `tools/host_llm.py`：只在内存里保存中继坐标与令牌，并负责读模型目录。
  - `tools/managed_runtime.py`：读握手里的 `host_llm`。
  - `tools/model_profiles.py`：新增档案认证方式 **`auth_source="host_relay"`**——
    档案**不存地址也不存密钥**（地址是临时的、令牌是机器秘密），`resolve()` 时
    按实时中继坐标注入；`configured` 取决于中继在不在；连接探测走中继。
  - `tools/llm/client.py`：放行 `host_relay`；**没配任何模型时回落宿主当前模型**
    （legacy 环境变量优先于回落）。
  - `tools/studio_application.py` + `tools/studio_http.py`：新增
    `GET /api/model/host-models`（宿主模型目录）与
    `POST /api/model/host-profiles`（一键建档；建档前先核对模型确实在目录里）。
  - 契约 `model-profile-surface-v1` 的 `auth_source` 枚举加 `host_relay`，
    `tools/schema_codegen.py` 重新生成了 Python 与 TypeScript 两份契约。
- **面板**（`packages/studio-panel`）：
  - 模型分组顶部新增「**宿主模型**」区：列出宿主目录里的模型，每条一个「使用」按钮，
    一点就建好档案。列表可滚动（宿主目录实测 **656 个模型 / 14 个提供方**）。
  - 宿主模型档案**只读**：地址与凭据由宿主在调用时解析，面板不让手改，
    因此也没有「保存」按钮。
  - 宿主分组新增同一份目录的只读清单。

### 路由表不再区分 Goethe / Dante

宿主早已把两个 agent 合成一个 `openwrite` 预设，路由表再分两行只是历史包袱。
面板把 `goethe` / `dante` 合并成一行「**对话**」，保存时**同时写回两个路由键**。

- Core 的 `ROUTE_KEYS` **一个没删**：旧存档 `novel_config.yaml` 的 `model_routes`、
  `tools/model_benchmark.py:465` 的 `operation="goethe"` 都还按这两个键解析。
- 两个键原本指向不同档案时，面板会明说「Goethe 与 Dante 原本指向不同档案，
  保存后统一为所选档案」。

### 顺带修掉的一个回归（上一轮留下的）

上一轮把模型路径加进 `GLOBAL_PATHS` 之后，**全局路径的失效通知落到了全局桶**：
工作区里的面板收不到「模型库变了」，而 `npm --prefix packages/openwrite-bridge run smoke`
因此变红。

现在：**上游调用照样不带工作区**（模型库是全局的），但**失效通知跟随请求方的工作区**——
问的人总得知道模型库动了。上下文无关的请求（宿主设置对话框）仍然落全局桶。
bridge smoke 恢复为绿，并补了一条断言：全局路径在**没有工作区头**时也必须答 200。

### 验证

- 面板 **46 files / 394 tests passed**（新增 `host-models.test.tsx` 5 条：
  列目录、一键建档、宿主档案只读、路由表合一、两键不同时的提示）
- bridge：`host-llm.test.mjs` **10 条**（鉴权、目录、provider/model 拆分、
  `host/current`、拒绝无路由的模型、SSE、只给 `block-end`、不重复计数、
  失败如实上报、令牌不可猜）+ `managed-runtime.test.mjs` 新增 2 条（握手带中继 /
  中继起不来不影响启动）+ `proxy-allowlist.test.mjs` 3 条 + **bridge smoke 绿**
- Core：**1688 passed / 32 skipped / 2 xfailed**（新增 `tests/test_host_llm.py` 13 条，
  含一条「被路由的操作真的跑在宿主模型上」）
- 插件 `test:maintenance` 94 passed；`docs:check` 绿（56 registered）；
  `test:profiles` / `test:preset` / `test:epochs` / 面板 smoke 均绿
- **真机核对（3081 测试实例）**：
  - `GET /studio-panel/api/model/host-models` → **656 个模型 / 14 个提供方**，
    含 `deepseek-official/*`（宿主本体）、`our-free-model/*`（插件提供的 22 个）、
    `codearts/*`、`buddy/*` 等，以及伪模型 `host/current`
  - `POST /studio-panel/api/model/host-profiles` → 建出
    `auth_source=host_relay`、`base_url=""` 的档案
  - `POST /studio-panel/api/model/test`（真实调用）：
    - `deepseek-official/deepseek-flash` → **ok，1889 ms，回复 OK**
    - `deepseek-official/deepseek-v4-pro` → **ok，1196 ms**
    - `host/current` → **ok，684 ms**
  - 路由表改成 7 行：对话 / 章节写作 / 章节评审 / 素材抽取 / 修订改写 / 项目搜索 / 研究；
    面板上**不再出现 Goethe / Dante 两行**
  - 宿主档案面板只读（无「保存」按钮），显示「这个档案由宿主模型目录提供」
  - 设置对话框的宿主分组列出同一份目录；**零 pageerror**
- 部署一致性：`client.js` / `client.js.map` / `domain.js` / `host-llm.js` /
  `index.js` / `managed-runtime.js` / `plugin.mjs` / `runtime-manifest.json` /
  Core wheel 与仓库**逐字节一致**

### 已知情况

- **Our Free Model 的通道当下被限流**（`MODEL_TEST_RATE_LIMITED`）。这是服务商侧
  的状态，不是接线问题：中继把服务商的原始状态码与文案如实带回来了。
  该插件自己的本地转发仍是关的（`forward.enabled=false`、`egress.enabled=false`），
  需要时在「设置 → Our Free Model」里打开。
- **Core 版本号没有跟着升**（仍是 5.8.22），wheel 与清单哈希已更新；
  正式发版前需要按发版流程升版本号。
- `npm run test:release` 有一条**既有失败**（与本轮无关）：仓库 HEAD 的
  `presets/openwrite/agent.cordis.yml` 本来就没有 `preset: openwrite` 那一行，
  而 `scripts/release-smoke.mjs:127` 要求它必须在。

---

## 设置类功能搬进宿主设置对话框（学 our-free-model 的 tab 式分组）

左下角的「OpenWrite」弹窗和任务页的「模型」页签，都是**设置**混在做事的地方。
这一轮把它们搬进宿主自己的设置对话框，做法照抄 `dsh-our-free-model`：
**一个 section + 内部 tab 分组 + localStorage 记住选中的分组**。

### 搬了什么

| 原来在哪 | 现在在哪 |
|---|---|
| 任务页 →「模型」（ModelView，1074 行） | 设置 → OpenWrite → **模型** |
| 左下角弹窗 → 联动插件清单 | 设置 → OpenWrite → **宿主** |
| 左下角弹窗 →「诊断与帮助」 | 设置 → OpenWrite → **环境** |
| 顶栏 ⋯ 菜单 →「环境与诊断」（重复入口） | 删除 |
| 任务页 →「模型」导航项 | 删除 |

留下的是**做事**：任务 / 模型测试 / 研究 / 导入与导出 / 连载体检 / 资产 / 大纲 /
图谱 / 搜索 / 创作页。左下角弹窗瘦身成「开始创作」——状态一行 + 作品目录 + 进入作品，
外加一句指向设置对话框的说明。

设置页三个分组：**环境**（写作环境 / Studio 后端 / 诊断）、**模型**（模型档案库）、
**宿主**（宿主当前模型 / 联动插件）。

### 为什么能搬：模型档案库本来就是全局的

Studio 把模型档案放在用户偏好目录（`~/Library/Application Support/OpenWrite/`），
**在所有作品之外**；Core 的每条模型路由都标 `requires_project=False`
（`tools/studio_http.py:65-92`）。所以模型档案库**根本不需要项目上下文**——
搬进设置对话框是顺着架构走，**Core 一行没改**。

代价是浏览器侧要能「不带工作区身份」地访问模型域：

- `packages/openwrite-bridge/src/domain.ts`：新增 `GLOBAL_PATHS`（10 条模型路径）。
  这些路径的请求**不要求** `X-Dsh-Workspace-Id`，代理转发时也不发工作区根/ID 头。
  其余路径照旧 fail-closed。
- `packages/studio-panel/src/client/api.ts`：新增 `fetchGlobalStudioApi` /
  `postGlobalStudioApi`——不发任何工作区头；`assertGlobalPath` 保证只有全局路径
  能走这条道，项目路径误用会直接抛 `WORKSPACE_CONTEXT_MISSING`，而不是悄悄降级。
- `packages/studio-panel/src/client/ModelView.tsx`：改成可复用面板。没注入 API 时
  走全局通道；草稿记忆从「按工作区」改成**一个全局槽**（模型库是全局的，
  草稿也该是），并导出 `resetModelViewMemory()` 供测试隔离。

### 顺带的收获

- **free-model 网关接入不再要求先进入一个作品。** 联动插件那节原本检查
  `getStudioContext() === null` 就拒绝写入；模型库既然全局，改走全局 API 后，
  在设置对话框里就能直接把网关写进档案。
- **修了一个真 bug**：`CompanionSection` 在 `useEffect` 之前提前 `return null`，
  hook 数量会随数据到达而变化 → 「Rendered more hooks than during the previous
  render」。设置页先挂载、后拿数据，正好把它踩出来了。
- **设置页不再一读不到就摆烂**：状态读不到会重读（最多 4 次、间隔 2s）。
  宿主刚起来、写作环境还在起的时候，第一屏不再是一片「暂时读不到这项状态」。
- **旧宿主不再把模型页打不开（降级兜底）。** 宿主的代理那半是**启动时加载**的：
  插件更新会立刻到达浏览器，宿主却要到下次重启才换规则。于是更新后不重启宿主，
  设置页的模型组会直接报 `WORKSPACE_CONTEXT_MISSING`。
  现在全局调用被代理拒绝时，若**有绑定的工作区**，会自动改走工作区通道
  （模型库是全局的，两条路读到的是同一个库），并在模型组顶部明说
  「宿主还在运行上一版 OpenWrite……重启宿主后就会走全局通道」。
  守卫「非全局路径」用的错误码与代理的拒绝码**故意分开**（`PATH_NOT_GLOBAL`
  vs `WORKSPACE_CONTEXT_MISSING`），否则调用方的笔误会误触发降级。

### 验证

- 面板 **45 files / 388 tests passed**（新增 `settings-model-panel.test.tsx`、
  `launch-openwrite.test.tsx`；改写 `operations-navigation.test.tsx`；
  `model-view.test.tsx` 补 5 条全局草稿槽的用例）
- bridge `proxy-allowlist.test.mjs` 3 条；插件 `test:maintenance` 94 passed；
  `docs:check` 绿（56 registered）
- **变异 11/11 CAUGHT**（bridge 全局放行 2 条、面板免工作区 2 条、tab 记忆 1 条、
  模型面板回落 1 条、free-model 接入 1 条、状态重读 1 条、弹窗瘦身 1 条、
  旧宿主降级 1 条、守卫码撞车 1 条）
- 真机核对（3081 测试实例）：设置对话框三个分组齐全且可切换；模型分组完整加载
  模型库；宿主分组显示 `deepseek-flash · deepseek-official · max` 与联动插件；
  关闭重开仍停在上次分组；左下角弹窗只剩「开始创作」+ 设置指引；
  任务页导航为 任务/模型测试/研究/导入与导出/连载体检（无「模型」）；
  顶栏 ⋯ 菜单只剩「同步」；**零 pageerror**
- **A/B（同一台 3081，换 bridge 版本）**：
  - 装**旧** bridge → 模型组仍能加载模型库，并显示「宿主还在运行上一版 OpenWrite」提示
  - 装**新** bridge → 直接走全局通道，提示消失
- API 层：无工作区头 `GET /studio-panel/api/model/profiles` → **HTTP 200**；
  项目域 `GET /studio-panel/api/assets` → **HTTP 400 WORKSPACE_CONTEXT_MISSING**（仍 fail-closed）

> Core 一行没改，所以**不需要重启写作环境**。面板改动刷新即可；
> bridge 改动需要重启宿主（代理路由在宿主进程里）——但**在重启之前**，
> 面板会自动降级，模型页不会打不开。

---

## 初始化后的项目不再显示成「结构问题」

新建的项目只有规划骨架（`src/outline.md` 模板、世界观、风格指纹、伏笔 DAG、层级），
**一个章节正文都没有**。于是「原生场景结构」不存在，迁移预览也没有可迁移的章节——
这都是正常状态，但页面把它渲染成了红色「结构问题（1）[SCENE_STRUCTURE_ABSENT] 需要处理」，
看上去像初始化失败。

三处叠加造成的：

1. 面板 `parseIssues` 只取 code 和 message，**把 Core 的 `severity` 字段丢了**，
   于是 `severity: "info"` 的「还没生成」和真错误长得一模一样。
2. Core 的 issue 载荷**根本没有 `message` 字段**，面板只能兜底成「需要处理」。
3. `SCENE_STRUCTURE_ABSENT` 已经是 info 级，`MIGRATION_PLAN_EMPTY` 却用了
   `_issue()` 的默认 `severity="error"`。

- `packages/studio-panel/src/client/SceneWorkbench.tsx`：`parseIssues` 解析 `severity`，
  **info 级不进「结构问题」列表**（没标 severity 的按 error 处理，兼容旧 Core）；
  `absent` 状态文案改成「还没有原生场景结构：初始化只建了规划骨架，写出章节稿件后才会生成。」
- Core `tools/scene_structure.py`：`_issue()` 支持 `message` 并写进载荷；
  `SCENE_STRUCTURE_ABSENT` 与 `MIGRATION_PLAN_EMPTY` 各带一句自己的解释。
- `packages/studio-panel/scripts/components/scene-workbench.test.tsx`：新增 2 条
  （info 级不算问题、真问题仍然显示）。
- Core `tests/test_scene_structure.py`：新增 1 条（两条「还没生成」的 issue 必须自带文案）。

验证：面板 43 files / 376 tests passed、Core **1675 passed / 32 skipped / 2 xfailed**、
`test:maintenance` 94 passed、变异 4/4 CAUGHT。
真机核对：大纲页再无「结构问题」红框，页面上没有任何红色边框块；
`[MIGRATION_PLAN_EMPTY]` 那行从「需要处理」变成「规划章节还没有稿件正文，暂时无法迁移。
先写出章节稿件，再回到此处刷新。」；零 pageerror。

> Core 改动要等**写作环境重启**才生效（宿主会重新拉起 Core 进程）：
> 重启 dsh 宿主最稳。面板改动浏览器刷新即可。

---

## 工作台铺到窗口最底部：我们这三页不再显示 composer

创作/资料/任务三页的底部一直有一条**死白**：宿主把 composer 放在一个「座位」元素里
（`[data-composer-seat]`，128px），并从内容区里扣掉座位的高度；座位自带的渐变遮罩只盖到
面板最后 4px，其余盖在纯白页面底色上，于是底下就是一条没有过渡的白带。
用户的原话是「这个对话框下面为啥是白的一部分，不是悬浮效果」。

改成：只要我们自己的视图挂在页面上，就把宿主的座位收起来，工作台铺满内容区直到窗口底边。

宿主给了正规开关 `data-conversation-composer-overlay`（宿主自己的轨迹页就是这么用的），
它把座位切成绝对定位、内容区撑满；但 composer 卡片是**居中**的（1920 宽下左缘 x=621），
而工作台是整宽的——悬浮的 composer 一定会压住我们的卡片（大纲页的「原生场景结构」
卡片被切掉一半）。所以最终落在用户点头的退路上：**我们这三页不要对话框**。

- `packages/studio-panel/src/client/workspace-chrome.ts`：新增，注入全局规则
  `[data-conversation-scroll]:has([data-openwrite-workspace]) > [data-composer-seat] { display: none; }`，
  按文档 id 幂等。宿主没有「隐藏 composer」的插槽：`conversation.composer` 虽然是 chain，
  但它的 `select` 只看得到 session 状态、看不到当前视图，且在视图挂载之前就跑；
  `:has()` 是唯一能对已挂载视图起反应的钩子，而且用的是宿主稳定的 `data-*` 属性，
  不依赖 CSS module 的哈希类名。
- `packages/studio-panel/src/client/index.ts`：`install()` 里装一次样式。
- `packages/studio-panel/src/client/LibraryView.tsx` / `OperationsView.tsx` / `CreationView.tsx`：
  根节点挂 `data-openwrite-workspace=""` + `data-conversation-composer-overlay=""`。
- `packages/studio-panel/src/client/Workbench.module.css`：`.workspaceRoot` 与 `.creationRoot`
  的高度改为 `100%`（创作页原来是 `calc(100dvh - 200px)`）。
  ⚠️ `height: 100%` 只在 overlay 属性生效时才解析得出来——宿主此时把内容区设成
  `flex: 1 1 0; min-height: 0`，高度才确定。两个属性要一起留着。
- `packages/studio-panel/src/client/views.module.css` / `AssetsView.tsx`：
  去掉只为悬浮 composer 预留的底部内边距（`.body` 180→24、`.mainPane` 120→24、
  删掉 `.assetsSidebar`）——没有东西浮在列表上面了，这些留白只是空白。
- `packages/studio-panel/scripts/components/workspace-chrome.test.tsx`：新增 6 条
  （替换 `composer-overlay.test.tsx`），含幂等安装、`:has()` 作用域、三视图标记、
  高度跟随宿主内容区、清空预留带。

验证：面板 43 files / 374 tests passed、`test:maintenance` 94 passed、两端 `tsc --noEmit`
EXIT=0、`docs:check` 绿；变异 13/13 CAUGHT。
真机核对（1920×1080，无头 Playwright）：三页的座位 `display:none`、
`--dsh-composer-height: 0px`、我们的根 `y=76 bottom=1080`；
**最底一行像素归属检查**在 x=300/500/900/1500/1900 命中的全是我们自己的元素（无白带）；
宿主自己的「对话」「轨迹」两页 composer 完好（128px、sticky/absolute）；零 pageerror。

代价：这三页没有 composer 输入框了，跟 agent 说话要切回「对话」页。

---

## 资产视图空状态：不再是一行灰字

`资料 → 资产` 在「没有选中任何条目」时，主面板只渲染一行 13px 的 `.notice` 灰字，
挂在约 700px 高的白色面板顶部。用户看到的就是一片白，判断成"什么都没加载"。
实际行为是正确的（项目 0 资产、无选中项），问题在空状态本身没有可读性。

改为居中的空状态：标题说明这一区是空的、正文说明从这里能看到什么、并按分类给出
唯一有意义的动作——可创建分类（角色/世界/进阶）放「新建」按钮，只读分类
（参考作品/作品核心）说明可以让 agent 用 `novel_asset_*` 写入后刷新。
同时去掉 `.mainPane` 在该状态下的 120px 滚动预留，不再放大空白。

- `packages/studio-panel/src/client/AssetsView.tsx`：`selected === null` 分支
  改用 `.mainEmpty` 结构。
- `packages/studio-panel/src/client/views.module.css`：新增 `.mainEmpty` /
  `.mainEmptyTitle` / `.mainEmptyHint`。
- `packages/studio-panel/src/client/locales.ts`：新增 `assets.emptyTitle` /
  `assets.emptyHint` / `assets.emptyAgent`（中英）。
- `packages/studio-panel/scripts/components/assets-view.test.tsx`：新增 4 个测试，
  含一条源码级断言——vitest 把 CSS module 打桩成空对象，DOM 上断言不到类名，
  所以在源码里钉住「空状态不得复用通用 `.notice`」，否则样式会静默回退。

变异验证：把类名改回 `css.notice`、删掉标题、让只读分类也显示「新建」，
三个全部 CAUGHT。

真机核对（宿主 0.2.1-rc.5，`~/.dsh/profiles/web` 安装版，会话 agentPreset=openwrite）：
空状态居中渲染；`Story Core` 有 4 篇文档，点开 `作者意图` 正常显示正文，
`mainEmpty` 消失；无 pageerror。

---

## 场景迁移：空计划不再可应用（资料页白块定位）

`~/novel` 这类「规划了章节、还没有写正文」的项目，`迁移预览` 返回 `plan: []`，而 Core 的
`can_apply` 只检查阅读顺序与 issue 列表，不看计划是否为空。于是「应用迁移」可点，且真的会成功：
它写出一个 `chapters: []` / `scenes: []` 的 sidecar，把 `surface()` 从 `absent` 翻成 `current`，
迁移入口随之消失，用户得到一个什么都没有的结构。面板上只留下一段没有解释的空白。

- Core `tools/scene_structure.py`：`migration_preview()` 在计划为空时追加 `MIGRATION_PLAN_EMPTY`
  issue，`can_apply` 显式要求 `bool(plan)`；`apply_migration()` 的拒绝分支按真实原因分流，
  空计划报 `SCENE_MIGRATION_PLAN_EMPTY` 与「没有可迁移的章节正文，请先为规划章节创建稿件」，
  不再一律说成「正文顺序存在歧义」。
- 面板 `packages/studio-panel/src/client/SceneWorkbench.tsx`：空预览的提示说明缺的是稿件正文，
  以及要做什么才能继续。
- 测试：Core `test_plan_without_manuscript_is_not_migratable`（断言拒绝、无 sidecar、状态仍为
  `absent`）；面板 `refuses to apply a preview whose plan is empty and says why`
  （断言勾选确认后按钮仍禁用、不发出请求、`MIGRATION_PLAN_EMPTY` 可见而 `MISSING_CHAPTER_FILE`
  仍被过滤）。

变异验证：删掉空计划 issue（CAUGHT）、让 apply 忽略空计划（CAUGHT）；`bool(plan)` 那层是冗余
兜底，单独删除测不到，属预期。

`MISSING_CHAPTER_FILE` 被 `parseIssues` 过滤**不是**缺陷——已有测试钉住该行为，且
「N 个规划章节尚无稿件」提示已承载同一信息，127 个章节会刷满预览。

---

## 第十二轮：派生缓存 / 生成层 / conductor / 测试质量

---

## 第七轮：agent 层 / 验收状态机 / 导出链路 / 预设层

第七轮把审查延伸到 Core 的 agent 层、验收状态机、导出链路，以及插件的预设/技能层。共 **31 个缺陷**，其中 1 个 CRITICAL、7 个 HIGH。Core 测试 **1598 passed / 0 failed**（含本轮新增 8 个回归）。

### CRITICAL

- **`abandon()` 把 facts 未同步的 head 提升为 `current`**：`accept_without_model` 刻意把 `accepted_revision` 设为新字节、`facts_revision` 留在旧 revision；`abandon` 看到 `accepted_revision` 非空就置 `current`。head 于是声称新正文已验收且事实最新，而 facts、章节记忆、runtime state 都还描述旧文本。**之后任何章节的验收都硬失败 `ACCEPTED_SOURCE_CHANGED`，而其处方「新建 operation」并不能修复——只能手工 `accept_external`。** 改为 `facts_revision != accepted_revision` 时置 `stale` 并清空 `operation_id`。

### HIGH

- **被确认门禁拦住的变更被报告成「已成功并保留」**：软门禁返回空 failure_reason（本意是不中断 ReAct 轮次），payload 于是落入成功分支；另一个工具连续失败两次后，`_partial_success_response` 输出「主操作 edit_project_document 已成功并保留」，而同一段 JSON 里写着 `ok:false, applied:false`。改为把 gated 结果单列，并在文案里明确「尚未应用（等待你明确确认）」。
- **一轮里剩余的 tool call 被静默丢弃，然后报告成功**：assistant 消息声明了本轮全部调用，但中途 `return`（terminal next_action / 失败上限）把后面的调用丢掉了，用户看到干净的「完成」。改为先跑完剩余调用，并在返回文案里列出「未执行：<names>（未产生任何变更）」。
- **`needs_review` 守卫只从 `latest_operation_id` 推导**：新 operation 移动该指针后，旧 operation 未确认的评审项就此不可见，`inspect` 从 `needs_review` 翻成 `current`，下一章照着作者被要求复审的旧大纲生成。改为聚合所有仍持有 head 的 operation。
- **三个技能教模型调用不存在的工具**：`world-query` 教 `edit_world_relation` 并发明了 `confirm`/`base_revision` 两阶段协议与 `relation_revision_conflict` 错误码；`dialoguequality` 教 `extract_dialogue_fingerprint`（无后继）和 `review_chapter`（合并前旧名）。
- **`[COMMAND] <tool> {…}` 伪调用语法**：3 个技能用它举例，而全仓没有任何解析方——模型会把它当助手文本打印，**操作静默不发生**。全部改写为真实工具调用，并在 `check-tool-references.mjs` 加门禁（负验证通过）。
- **`truth-validation` 用项目级零参工具做章节级校验**；**`style-system` 教一个本插件不发行的 `openwrite` CLI**（`bin` 只有两个维护脚本）。两者都改为真实工具。

### MEDIUM

- **`review_chapter` 在 `store.save` 之前释放了全部锁**，而 `save` 会按当前正文重算 `source_revision`——窗口内落地的写入让评审盖上新 revision 的戳却描述旧正文，新鲜度门认为它 current。改为在 `ProjectWriteLock` 内保存，并在保存后复检正文是否变动。
- **`establish_baseline` 把全部章节（而非仅 untracked）传给 `_start`**：已验收且事实最新的章节被重置为 pending、事实失效、分析器重跑（付费调用），并抢走进行中 operation 的 head，使 `abandon` 变成静默 no-op。改为只传 untracked。
- **`manuscript_acceptance` 的 operations/snapshots 从不清理**：实测 12 章书 30 次自动保存 → 31 个目录 1.9 MB。按「最新 N 个 + 仍被 head 引用」保留，`forget` 也清理该章快照。
- **15 个验收错误码一个都不在 HTTP 状态表里**，全部落到 502 `BAD_GATEWAY`——陈旧 revision 被报成上游故障而非可恢复冲突。补全映射，并让 `write_chapter` 转译子层的 `ManuscriptAcceptanceError`。
- **`_start` 的 `state.json` 读-改-写无锁**：两个并发基线都读旧状态，输家 head 消失后 `_set_heads_status` 跳过它们，章节永久 pending。在两个未加锁的调用方（HTTP baseline、`import_book`）补 `ProjectWriteLock`。
- **`max_model_repairs` 是每轮预算而非 run 上限**：每次成功响应重置，`max_turns=20` 时最多 20 次额外付费调用，且 `_exhausted_model_error` 永不触发。加 run 级计数；`stage_outline_edits` 的各批次改为独立重试预算（与系统提示词「分批调用」的契约一致）。
- **`book_state.yaml` 静默重置/降级**：解析失败时覆盖文件（无 transcript 可恢复），未知 stage 映射为 DISCOVERY 却不重存，下次 save 静默降级。改为隔离损坏文件、保留原 stage 值并置 `stage_unrecognized`。
- **`truth_manager` 三文件保存无快照回滚**、**`character_state_index` 一个文件失败清空全部正文贡献**、**`asset_package` 跳过包内依赖不报悬空引用**、**`stage_outline_edits` 批次共用重试预算**。

### 本轮被否决的两项（误报，已撤销）

- **「head 状态 `missing` 不阻断，导出会静默漏掉整章」**：实测 delivery 导出**已经被 `CHAPTER_SEQUENCE_GAP` 拦住**（同一 missing 列表，`export_preflight.py:112-120`），`REVIEW_MISSING` 也会触发；`personal_archive` 正确地只给警告。审查者只看了第 139 行的验收门。已撤销该改动。
- **「`epochs.models` 是死通道」**：发布方在宿主侧（`domain.ts` 把 `/api/model*` 映射为 `models`，`WorkbenchStore` 从 SSE 发布），审查脚本只走了客户端所以漏报。

### 过程中我自己制造又修好的三个回归

修 `save()` 信任调用方 `source_revision` 时无条件重算，把 `mark_stale` 依赖的「被评审时 revision」覆盖掉了——收窄成「非 stale 才重算」后两个性质同时成立；批量加锁时把 `with` 插进函数签名中间导致语法坏掉；`_from_dict` 改完后忘了 `return state`，84 个测试红。

---


第八轮把审查延伸到此前完全没碰过的区域：Core 的上下文构建/大纲/滚动计划/arc 审计/agent 人格，以及插件的预设与发布门禁。共 **约 45 个发现**，其中 6 个 HIGH。Core 测试 **1608 passed / 0 failed**（含本轮新增 10 个回归）。

### HIGH

- **`settle_backfill` 全程无锁读-改-写**：`load_truth_files` → `create_snapshot` → `apply_runtime_delta_with_fallback` 序列不持 `ProjectWriteLock`（该模块是少数从不 import 它的写入器）。两个重叠 `run()` 都报 `applied`，但只有一个章节的 delta 落盘——另一个章节的 memory record 已写入，默认 `only_missing=True` 从此跳过它，**真相对账永久丢失**。
- **已解决的伏笔被复活**：`_get_foreshadowing_state` 只在 `pending or planted` 非空时信任 DAG；DAG 里只剩已收/废弃节点时，代码回退用 legacy `hierarchy.yaml` 的 `key_foreshadowing` **整个替换**状态——实测 `status: 已收` 的节点被渲染成【待回收伏笔】+【已埋下伏笔】，写手被要求再收一次。
- **`_force_fit` 静默丢掉全部伏笔义务**：预算收紧时它把 `foreshadowing` 置空、`outline_window` 与 `active_characters` 清空，而 `foreshadowing` 不在 `generation_protected_items` 里，`assert_protected_unchanged` 照样通过并报 `protected_unchanged: True`，`compression.actions` 里只有一句通用的「L4: 最终适配循环 N 次」。模型于是在完全不知道未回收伏笔的情况下写作。把未决伏笔加入受保护集。
- **`rolling_planning` 空 revision 绕过 CAS 写进正典**：`delete` 与 `apply_proposal` 用 `if revision and revision != …`，空串让 `and` 短路、守卫整个被跳过；同文件的 `stage_proposal` 却是严格的。实测 `apply_proposal(revision="")` 把 `ch_009` 追加进 `outline.md` 且无任何修订检查。
- **`arc_audit` 基线快照无界增长**：每次 drift entry 和每次 reconcile 都把整份大纲 + 该组每一章正文完整复制进 `baselines/baseline_<uuid>/`，全模块没有任何 `unlink`。实测 200 章组 3 次 drift → 606 文件 1.59 MB；真实书籍到 GB 级。改为保留最新 N 个 + 仍被 open entry 引用的，被裁掉的 open entry 打 `baseline_evicted` 标记让 `recover` 明确拒绝。
- **`release-smoke` 用陈旧产物通关**：未传 `.tgz` 参数时它直接装仓库根下那个文件，既不打包当前源码也不校验一致性。实测该 tgz 是陈旧的（还带着 `openwrite-dog` 行和 `vendor/dsh-dog`），而门禁端到端通过、24 项检查全绿——`npm run test:release` 能在并非将发布内容的代码上放行。改为无参数时 `npm pack` 到临时目录。
- **`gen-tools-md` 白名单可把破坏性工具标成只读**：用一个封闭的方法名名单决定「影响」标签，而 `--check` 只重新生成并逐字节比对，看不出错分。实测把 `novel_chapter_delete` 的 `client.postJson` 改成 `client.post`，生成器就标它「只读查询」而 `--check` 退出 0。改为「除非可证明只读否则视为写入」。
- **`_tools_for_instruction` 可收窄到空集**：指令点名了当前人格之外的工具时得到 `[]`，下游 `_completion_params` 的 `if tools:` 直接把 `tools` 键整个省略——模型在系统提示仍宣传全部工具的情况下无工具可用，轮次以纯文本「成功」结束，用户请求静默不发生。改为空则回退全量，并做大小写不敏感比较。
- **解析门禁走的不是插件注册的那条路**：`preset-smoke.mjs` 用一个未安装的包推导 `modern`，于是恒为 false，校验的是插件从不注册的定义；而 `plugin.mjs` 恒传 `true`。改为与插件一致，并对现代化后的行跑 `require.resolve` 清扫（`dsh-workflow-ptc` 在这棵宿主树里预期缺失，显式列出而非静默跳过）。

### MEDIUM

- **三个技能教模型调用不存在的工具**：`world-query` 教 `edit_world_relation` 并发明了 `confirm`/`base_revision` 协议与一个不存在的错误码；`dialoguequality` 教 `extract_dialogue_fingerprint`（无后继）和 `review_chapter`（合并前旧名）。
- **`[COMMAND] <tool> {…}` 伪调用语法**：3 个技能用它举例，全仓没有任何解析方——模型会把它当助手文本打印，**操作静默不发生**。全部改写，并在 `check-tool-references.mjs` 加门禁。
- **`truth-validation` 用项目级零参工具做章节级校验**；**`style-system` 教一个本插件不发行的 `openwrite` CLI**。
- **`review_chapter` 在 `store.save` 之前释放了全部锁**，而 `save` 会按当前正文重算 `source_revision`——窗口内落地的写入让评审盖上新 revision 的戳却描述旧正文，新鲜度门认为它 current。
- **`establish_baseline` 把全部章节（而非仅 untracked）传给 `_start`**：已验收且事实最新的章节被重置、事实失效、分析器重跑（付费调用），并抢走进行中 operation 的 head。
- **15 个验收错误码一个都不在 HTTP 状态表里**，全部落到 502 `BAD_GATEWAY`。
- **`max_model_repairs` 是每轮预算而非 run 上限**：`max_turns=20` 时最多 20 次额外付费调用，且 `_exhausted_model_error` 永不触发。
- **`TaskStore.list` 先按 created_at 降序截断再让调用方按章节过滤**，小说超过 500 个任务时该章任务整个消失。
- **`context_builder` 的禁用短语列表每次运行随机不同**（`list(set(...))`），同一份配置跑 6 次 6 种输出。
- **大纲重复节点 id 静默指向错误节点**；`promote` 从不重编号留下永久空洞；**dante 系统提示点名 `create_outline` 而 Dante 没有这个工具**。
- **`check-editor-coordinates` 只比对 wheel 与 transpile(TS)**，从未读原生面板的构建产物——TS 源若变得不可达，模块死了而 wheel 副本仍同步，面板跑的却是另一份代码。
- **`narrative_forecast`/`rolling_planning` 每次 create 新目录从不清理**；`settle_backfill` 降级章节被排到正常章节之前，顺序错乱。

### 本轮被否决的一项（误报，已撤销）

- **「preset 现代化改名指向不存在的包」**：我先按建议删掉了改名，一个既有测试立刻红——它明确断言 ptc 行存在。查明改名是**有意为之**，针对的是更新版本的宿主，而这棵仓库的 node_modules 是旧宿主。真正的问题是门禁走了另一条路，已按那个方向修（并在 `expectedAbsent` 里显式列出 ptc，而非静默跳过）。

### 过程中我自己制造又修好的三个回归

`_from_dict` 改完忘 `return state`（84 个测试红）；把 `with ProjectWriteLock` 塞进 `_start` 触发同进程嵌套锁失败（`ProjectWriteLock` 是 O_EXCL 文件锁，不可重入）；`_requested_tool_name` 初版把工具名和限制短语的位置绑太死，导致「只能用 X」匹配不到。

---

## 第九轮：章节记忆 / 写作资产 / 风格合成 / install.sh / lifecycle 门禁 / 面板竞态

第九轮把审查推到此前完全没碰过的区域：章节记忆、写作资产、风格合成、安装脚本、lifecycle 门禁，以及一批面板竞态。共 **约 50 个发现**，其中 5 个 HIGH。Core 测试 **1608 passed / 0 failed**，插件侧全绿。

### HIGH

- **一个命名不规范的记忆文件让整本书的上下文构建永久崩溃**：`chapter_memory.list_before` / `usage_totals` glob `ch_*.yaml` 后把 `path.stem` 直接喂给 `load()`，而后者对不匹配 `ch_\d+` 的名字抛 `ValueError`。任意一个 `ch_old.yaml`（手改、`cp` 改名）就让 `render_context`（每次 `build_generation_context` 都调）和 `usage_totals`（`build_workspace_snapshot` 调用）对整个小说抛错，且无恢复路径。
- **`anchors()` 静默截断到 100 条，查重门禁放过第 101 条以后的全文抄袭**：同一行注释声称「every reference remains available to overlap checks」，实际 `sorted(glob)[:100]`。实测 101 个锚点里第 101 条是章节正文的逐字副本 → `flagged sources: []`，100% 抄袭报成干净。
- **`install.sh` 把作者对「包内文件」的修改静默覆盖且无备份**：move-aside 过滤器只保护包里**没有**的文件，而 rsync 无条件覆盖包内文件。作者编辑 `agent.cordis.yml` 或某个 skill 后重跑安装，改动被静默还原——而同一段注释称该目录是「author-owned territory」。同时 `.openwrite-managed.json` 从未被写入，导致包自己的预设被 `maintenance.mjs` 判成 author-owned。
- **`safe-upgrade` 的 `--profile` 无值时静默改错 profile**：`value('--profile')` 在参数位于末尾时返回 `undefined`，`|| 'web'` 后直接操作 web 并退出 0——与 `maintenance.mjs` 已修的是同一个 bug，这边漏了。
- **style 合成丢掉 15/23 条创作规则**：`_build_fallback_style_document` 对每个节硬性截断，`craft_rules[:8]` 只留下 dialogue_craft 的 7 条加 scene_craft 的第一条，rhythm_craft 整份（章末钩子/视角切换/信息密度/加速减速）和全部英文写作禁令消失。这是未配置 LLM key 时的**默认路径**。
- **lifecycle 门禁无法在预设内容上失败**：夹具把 `agent.cordis.yml` 写成字面 `'preset: openwrite\n'`，从不写 `preset.yml`/`skills/`，且全文没有任何断言读取 `.agent-presets/openwrite` 下的内容——install.sh 的 move-aside 分支从未被执行，上面那条数据丢失对它完全不可见。

### MEDIUM

- **章节记忆读放大是 O(n²)**：`load()` 每条记录都构造 `ManuscriptAcceptanceService` 并跑一次全量 `inspect()`（对每章做 SHA-256），外加一次全稿扫描；`list_before`/`usage_totals` 再每章调一次。实测 120 章 0.595s、150 章 0.99s，500 章约 25 万次文件读取——每次生成和每次 desk 加载都付。
- **损坏的记忆记录被静默吞成「还没有记忆」**：`yaml.YAMLError` → `None`，与空目录无法区分，该章摘要从此从每个提示里消失且无任何信号。
- **`writing_assets.load()` 的 YAML 无防护**：一个坏字节就让 `load`/`surface`/`context`/`inspect_chapter`/`mark_usage` 全抛裸 `ParserError`。
- **`join_segment` 的 12 字符下限复制作者的文本**：「天亮了。」这类短重复尾不被去掉，续写时变成两份。
- **`doctor` 在 bundle 树不存在时报健康**：`installed` 只看 manifest 的 bundle 列表，`node_modules/dsh-openwrite` 缺失也输出「正常」指令。
- **面板三处竞态/输入丢失**：`CreationView` 的 `manuscriptEpochRef` 在 `documentState !== 'ready'` 时也被无条件记录，加载期间到达的第二个 epoch 永久丢失（注释声称会恢复，实际不会）；`OutlineView.load()` 的 `setDrafts({})` 把作者正在输入的标题/摘要静默还原；`AssetsView.saveField` 在另一字段保存进行中时把第二次 blur 保存**静默丢弃**（无请求、无错误、无提示）。

### 过程中我自己制造又修好的两个回归

给 `load()` 加记忆化时用了 store 生命周期缓存，而重写会改变验收状态——一个既有测试立刻抓住（缓存的 head 过期）。改为只在单次批量调用内共享，单条 `load()` 仍然每次新算。

---

## 第十轮：craft 规则 / style_synthesizer / 面板 409 与双语

第十轮处理的是前几轮点名但未修的项：craft 规则消费方、style_synthesizer 的裸写、面板 409 缺口、以及一批破坏双语的硬编码中文。共 **约 20 个缺陷**。Core **1608 passed / 0 failed**，插件侧全绿。

### craft 规则：三条独立的失效

- **两条正则规则永不触发**：`craft/ai_patterns.yaml` 的「仿佛.*一样」「如同.*一般」是正则，但消费方做字面子串测试（`if pattern in content`）——两条比喻套话门禁从来没生效过。
- **`severity` 是死数据**：12 处声明 `high/medium/low`，消费方硬编码 `"warning"`，高严重度禁用词与低严重度套话产生同级 issue，作者无法按严重度分诊。改为映射到 `critical/warning/info`。
- **三组规则全无人读取**：`info_dump_patterns`（信息倾倒）、`structure_patterns`（「首先/其次/最后」「总而言之」「值得注意的是」——AI 结构门禁）和 `detection_config`（每千字阈值、评分权重）在 rubric 里声明了却没有任何读取方。写手最需要的「设定堆砌 / 信息倾倒 / AI 结构」三类门禁实际不生效。已接入检测。

### style_synthesizer：一次崩溃静默丢掉整份风格清单

`manifest.toml` 用裸 `write_text` 写，崩溃留下截断文件；随后 `render_style_manifest_summary` 吞掉解析错误返回 `""`，`docs["work.manifest"]` 变成空串——writer 和 reviewer 在没有任何风格指导的情况下运行，且无任何诊断。改用项目统一的 `atomic_write`，解析失败记 warning。

另外 `_remove_source_bound_signals` 用 `text.replace(signal, "")` 盲子串删除，会把合法规则从中间剪断：「保持冷峻的叙述声音，避免解释性连接词。」在信号是「叙述声音」时变成「保持冷峻的，避免解释性连接词。」。改为删整条列表项。

### 面板 409 缺口

`SerialWritingView` 的五条写路径（保存资产/对账/章纲元数据/锚点/漂移记录）都没有 409 分支：原样显示服务端中文消息并保留陈旧 `expected_revision`，作者点重试必然再 409，没有「重载并重试」指引。所有写路径都走同一个 `run` helper，所以在**一处**加分支即全覆盖。`OutlineView` 的四个滚动计划动作（stage/delete/apply/create）同样只在校验成功时刷新，冲突后列表里的 `plan.revision` 仍是旧值，后续每个动作都 409 直到手工刷新——已统一走 409 感知的 `planFailure`。

### 面板健壮性

- **`ContinuousReader` 中途失败丢弃全部已取到的章节**：20 章里第 7 章坏掉就一章都看不到。改为保留已取到的，错误单独显示。
- **`showToast` 的 6 秒定时器不清场**：第二个 toast 会被第一个的定时器提前擦掉。改用 ref 存 handle 先 `clearTimeout`。
- **`AssetsView.saveField` 遗留陈旧恢复草稿**：单字段保存成功后更新了 `revisionsRef` 却没有重新标记恢复草稿，重挂载后恢复旧 `baseRevision`，立即对作者自己的保存报「此资产在他处被修改」冲突横幅，且下一次自动保存会拿旧 revision 再吃一个 409。（`saveAsset` 原本就正确处理了，只有单字段路径漏了。）

### 双语面板

`OutlineView` 18 处硬编码中文（草案工具栏、两个 `window.confirm` 正文、接预演选择器及其选项）——英文语者看到半中文面板；`ModelView` 新 Embedding 档案的 label 硬编码中文并会作为 profile label **写进服务端**（即使用户切换语言也改不回来），另有 confirm 与 tab 硬编码英文；`CreationView` 的「综合状态」初始值；`GraphView` 重复一份已本地化的统计行。全部接入 `locales.ts`（zh + en 双语）。

另外 `SerialWritingView` 的指标 effect 依赖数组缺 `refreshEpoch`（同级 effect 都有），别处保存/评审后指标面板显示旧计数直到重新选章。

---

## 第十一轮：orchestrator 阶段机 / handoff 清单 / 持久化

第十一轮审查 Core 的 agent 层（orchestrator / handoff / 持久化 / 检查器），共 **14 个缺陷**，其中 5 个 HIGH。Core **1609 passed / 0 failed**。

### HIGH

- **三个 stage 是永久死胡同**：`DRAFTING` / `SETTLEMENT` / `MILESTONE_REVIEW` 在 enum 里定义、全仓没有任何地方赋值，而 `BookStateStore` 会从磁盘接受它们。一旦进入（手改 yaml 或旧版本写入），章节编写、大纲确认、推进确认三条路全被拦，且提示自相矛盾——「请先确认大纲范围」对「当前没有可确认的大纲范围」，而 `outline.md` 实际存在且有效。两个允许集都已补入这三个 stage。
- **`confirm_outline_scope` 可跳过基础设定直接晋升**：`_confirm_existing_outline_scope` 直接从裸大纲晋升到 `CHAPTER_PREFLIGHT`，绕过 `_handle_outline_confirmation` 的三道闸。实测新建项目 + `outline.md` 存在 + `foundation.md`/`background.md` 被删除 → 晋升成功、`blocked=False`、基础设定仍不存在——作者会在没有任何正典基础的情况下开始写作。已补 `foundation` 非空与 `outline_edit_batches_complete()` 两个前置条件。
- **`generate_character_draft` 静默覆盖待确认的大纲**：完整链路实测——暂存有效大纲草案 + `pending_confirmation="outline_scope"` → 生成角色把 `pending_confirmation` 覆盖成 `character:*`，暂存草案仍在盘上 → 下一次 `confirm_outline_scope()` 因 `pending != "outline_scope"` 落入「既有大纲」分支，晋升的是**旧** `src/outline.md`。作者以为新大纲已确认，Dante 按被取代的大纲规划。已在该场景下拒绝生成角色并给出下一步动作。
- **handoff 清单不带签名，陈旧大纲被当新鲜消费**：manifest 里没有 `outline_revision` / 资产签名 / `generated_at`。实测 `prepare_dante_handoff()` 返回 `ready=True` 后改写 `src/outline.md`，`get_goethe_handoff` 仍返回 `ready=True`、零陈旧信号。已在 manifest 记录 `asset_revisions`（含 `outline`、`ideation_summary`、`background`、`foundation`、各 persona）并在读取时校验。同时修掉 `revision` 的哈希缺陷：它只哈希渲染后的 Markdown，而模板丢弃 `current_arc`/`current_section`/`current_chapter` 和所有路径——实测 `current_chapter` 从 `ch_001` 变 `ch_009` 的两个 handoff 产出**完全相同**的 revision；改为哈希完整 manifest JSON。端到端验证：新 handoff 不报陈旧，大纲被改写后精确报 `stale: True, stale_assets: ['outline']`。
- **context_inspector 宣称只读却写派生缓存**：模块 docstring 写 "Read-only inspection"，工具对模型宣传为「只读检查…」，但 `assemble_packet` → `ensure_runtime_fresh` → `run_sync` 会写角色卡，上下文构建会刷新角色状态索引。第二个更严重：它让 `source_sync` 的新鲜度检查以为缓存是当前的，从而**对后续写手掩盖真实的陈旧**。已改为快照-还原：已存在文件按字节还原，检查期间新建的文件删除。既有测试只断言 session 文件未创建，所以这个洞一直是绿的；新增的回归用前后字节 diff 验证。

### MEDIUM

- **`book_state.save()` 整对象写丢并发字段**：两个 writer 各自 load 后保存，A 设的 `current_chapter` 被 B 的保存抹成空。Studio HTTP 服务与 CLI 同时操作同一文件时完全可达。改为读-合并，只覆盖本次写者真正设置的字段；`pending_confirmation`/`blocking_reason`/`last_agent_action` 属于「当前意图」，空值意味着清除而非继承。
- **Dante 的 book_state 快照永不刷新**：`startup()` 加载一次，之后每次工具动作推进盘上状态，`_build_context_messages()` 仍输出旧 stage/chapter——LLM 被告知一个书已经不在的状态。改为每次构建前重读，读失败时保留上次已知状态。
- **session 转录无上限**：YAML 有严格的 `_compress_for_size`/`_hard_truncate_state` 收敛，JSONL 却完全无帽——实测 500 轮 × 4KB → YAML 18KB 而 JSONL 2MB。改为超 8 MiB 轮转到 `.1` 并留轮转标记。
- **大纲草案在非规划阶段生成后永远无法晋升**、**`delegate_writing` 会把 `current_chapter` 回退到更早的章**（另两个写路径都有 `>=` 守卫，只有 orchestrator 漏了）。

### 过程中修掉的三个自己的回归

1. 把 craft 的 `high` 映射成 `critical`——而 `critical` 是**硬门禁严重度**，会让整章评审直接 `blocked`。原文硬编码 `warning` 虽丢信息但不会误杀；契约也明确写着 `critical 仅用于明确事实矛盾、连续性破坏或使章节不可用的问题`。已改回 `warning`。
2. `book_state` 的合并把 `pending_confirmation` 也从磁盘继承，破坏了两个既有测试——该字段描述写者当前意图，不是持久身份。
3. K6 的快照只还原已存在文件，而 `run_sync` 会**新建**角色卡；测试抓到这个边界后改为收尾时重新 glob 并删除新建文件。

### 最终状态

| | |
|---|---|
| Core | **1609 passed / 0 failed** |
| 插件 docs:check / doctor / preset | 全绿 |

改动：Core **47 项**（1982 insertions）+ 插件侧不变，未提交。

未覆盖：三系统 CI、Windows/Ubuntu/Android 实机、真实付费模型。

十一轮下来我的判断仍然没变：每轮都能找到从上线就存在、前几轮和全部门禁都没发现的缺陷。这一轮 5 个 HIGH 全是——包括「三个 stage 是永久死胡同」和「handoff 不带签名导致陈旧大纲被静默消费」这种会直接卡死或误导创作流程的。已审查区域我都执行过验证，但没法证明没有下一个。
---

## 第十二轮：派生缓存 / 生成层 / conductor / 测试质量

第十二轮审查 Core 的剩余未碰面：派生缓存同步、生成层、conductor/CLI、以及**测试自身的质量**。共 **3 个真实缺陷 + 1 个重大测试缺口**。Core **1616 passed / 0 failed**。

### 修掉的缺陷

**L1 — 派生缓存裸写 + mtime 判新鲜度，崩溃后截断缓存被当成新的**

`outline_sync.sync_outline_to_hierarchy` 和 `character_sync.sync_all_profiles_to_cards` 都用裸 `open(path, "w")` 截断写入。而 `collect_sync_status` 的新鲜度判定**只比 mtime**。实测：把 `hierarchy.yaml` 写一半、再把 mtime 推回旧值 → `outline_pending = False`，**截断的缓存被判定为新鲜**。此后 workspace 快照、上下文构建、阅读顺序全部从半份大纲工作。

更糟的是这与 K6 相关：inspector 的快照-还原会把这些缓存恢复原样，于是**还原动作本身就会掩盖一次真实的同步失败**。

两处都改为 temp + `fsync` + `os.replace`。新增原子性回归（断言无残留临时文件、卡片可完整解析）。

### 排除的风险（实测干净）

- **L2 生成层**：`validate_outline_markdown` 对空/纯空白/纯代码围栏输入都返回 4 条错误——LLM 空输出或截断不会落盘。`save_outline_draft` 已用 `_atomic_write_text`。`_chat_text` 的重试是**有界的一次**，且只对 `MODEL_EMPTY_RESPONSE`/`MODEL_OUTPUT_TRUNCATED`/`MODEL_REASONING_ONLY` 三类可恢复错误触发——不会重复扣费。
- **L3 conductor / CLI**：`conductor/` 无任何生产代码引用（纯开发工具）；CLI 的 `sync --check` 只读、写入需显式执行；`shutil.rmtree` 的三处（项目删除、导入暂存、归档恢复）全部有 `confirm == novel_id` 或事务路径守卫。
- **32 个 skip 全部是「标准样例已从公开仓库移除」**——数据缺失，不是掩盖失败。**零恒真断言。**

### 本轮最实的成果：四个修复原本没有测试覆盖

L4 做变异验证时发现：**上一轮 K1/K2/K3/K4 四个修复，把代码改回缺陷形态后测试全绿**。也就是说我修了缺陷却没写回归——下一次有人重构就会静默破坏它们。

已补 4 个测试（含 3 参数化的 stage 死胡同用例），并逐个变异验证：

| 变异 | 测试结果 |
|---|---|
| 去掉 `MILESTONE_REVIEW` 允许 | 1 failed ✓ |
| 去掉 `_foundation_is_promoted()` 前置 | 1 failed ✓ |
| 去掉 K3 角色生成守卫 | 1 failed ✓ |
| 去掉 K4 manifest 签名 | 1 failed ✓ |

### 最终状态

| | |
|---|---|
| Core | **1616 passed / 0 failed**（新增 6 个回归） |
| 插件 docs:check / doctor | 全绿 |

改动：Core **51 项**（2187 insertions）+ 插件 207 项，未提交。

未覆盖：三系统 CI、Windows/Ubuntu/Android 实机、真实付费模型。

**这一轮改变了我的判断**：前十一轮我一直在找新缺陷，这一轮证明的是**已修的缺陷也可能没有防线**。四个上一轮刚修的 HIGH 全是裸的——这比新缺陷更危险，因为它看起来已经完成了。变异验证（把修复 revert 掉、看测试是否红）应该成为每一轮的标准动作，我之前的轮次没做。
---

## Unreleased

同一轮审查延伸到 Core 的 Python 侧（`.wt-native-core`）。全部修复均以执行验证，Core 测试套件 **1588 passed / 0 failed**（含本轮新增 8 个回归测试）。

- **修掉两个高危缺陷**：
  1. `manuscript_import.py` 的 `confirm_structure` / `revise_preview` 没有 `discarded` 终态守卫（`_resume` 有），作者显式「丢弃」的导入可被后续预览+确认复活并重新发布，章节落入正式稿而 `discarded_at` 仍在。补终态守卫，discard 时清空确认令牌。
  2. `_observe_reconciliation` 只在验收状态为 `completed` 时推进，而 `manuscript_acceptance.abandon`（官方推荐的 `STALE_ACCEPTED_REVISION` 补救手段）会把验收置为 `abandoned`——一个永远不可能变成 `completed` 的状态。导入于是永久卡在 `awaiting_reconciliation`，`discard` 报 `IMPORT_DISCARD_FORBIDDEN`、`revise_preview` 报 `IMPORT_ALREADY_PUBLISHING`，**只能手改 journal.json**。改为把这几种状态当硬失败，落到带可操作错误的 `failed` 态。
- **修掉一个高危模型路由缺陷**：`model_profiles.resolve()` 在路由指向不存在的档案 id 时静默回落到默认档案——换成另一个模型**和另一把 API key**，且 `surface()` 仍显示该路由已配置、`used_by_routes` 谎报归属。项目级路由直接读 `novel_config.yaml`，`save_routes` 从未校验它，所以恢复归档或手改配置即可触发。改为拒绝并抛 `MODEL_PROFILE_NOT_FOUND`，`surface()` 新增 `unresolved_routes` 使其可观测。
- **修掉一个高危评审新鲜度缺陷**：v1 评审记录完全没有新鲜度门——`review_is_deliverable` 绕过它，`canonical_review_decision` 的 v1 适配器把 `freshness_status` 硬编码成 `unknown`。被显式标记为 stale（正文在评审后发生变化）的旧版评审仍判为可交付，导出预检/验收因此可以放过陈旧章节。补 stale 判断，并把新鲜度计算提成两个分支共用的函数使其无法再分叉。
- **修掉三个崩溃窗口导致的数据不可恢复**：场景迁移此前先换 sidecar 再写迁移记录，崩溃后新 sidecar 无记录、旧字节只在孤立 tmp 里，作者指派的场景元数据不可恢复（改为先写记录）；回滚崩溃后记录永久停在 `applied`，重试永远 `SCENE_MIGRATION_DIVERGED`（改为识别「已恢复即已完成」并补盖）；阅读顺序移动此前先复制章节文件再提交 outline 与身份注册表，崩溃后章节在两个 arc 各一份、注册表仍映射旧路径导致新文件拿到派生的 `document_id`、批注/验收锚点静默脱落（改为先提交元数据再移动文件）。
- **修掉四个并发丢失更新**：`model_profiles` 六个写入器只有三个持 `_mutation_lock`，并发保存时另一次写入静默丢失（实测嵌入档案从磁盘消失而调用返回成功）；`credential_ref` 取自载荷原文，档案可指向别人的密钥槽并用自身密钥覆盖它（改为按档案 id 派生）；`reference_library.apply_adoption` 的 validate-then-write 既不持 `ProjectWriteLock` 也不逐文件复验，两个并发 adopt 有一个确认结果落盘却不在 `recipe.yaml` 里，其风格规则静默丢失；`review_store.save()` 的 load→write 无锁，并发 `mark_stale` 丢一条历史记录（`novel_service` 恰好在 `store.save` 之前就释放了项目写锁）。
- **修掉 `novel_id` 项目根逃逸**：`_activate_project` 只检查 `novel_id` 非空，而 `initialize_project` 校验格式。`novel_config.yaml` 里写 `novel_id: ../../..` 可让 `novel_root` 逃出 `project_root`，`_resolve_document` 的 containment 锚点随之逃逸——实测能读到并覆写项目外文件。补同样的格式校验，打开即拒绝。
- **修掉「写成功却报 500」**：`write_document` 先提交 rename，再用 `relative_to(self.project_root)` 算 checkpoint 路径；路径在项目外时 `ValueError` 在提交之后抛出，客户端收到 500 而文档已经改了。checkpoint 改为尽力而为，绝不能让已提交的写入失败。
- **修掉 workspace 卡在 428**：`app_for` 按 root 缓存且 `initialized` 只在构造时算一次。未初始化 root 上的 GET（浏览器在 `openwrite init` 期间轮询，本就允许）会缓存一个 `initialized=False` 的应用；项目随后出现在磁盘上也一直返回 428，`POST /api/project/init` 反而报 409。缓存命中时若 `novel_config.yaml` 已存在就重新激活。
- **其它**：`TaskStore.transition` 加 `expected_status` CAS（此前可把终态覆盖回 `interrupted`）；`update_writing_targets` 补乐观并发并暴露 `config_revision`；`task_store` 的索引在每次 transition 时全量重写，而它**没有任何读取方**（`list()` 直接 glob 快照）——改为只在索引列真正变化时重写，实测 stage/progress 更新从 ~80 ms 降到 ~1 ms；评审历史与 `revision_closures` 加上限（实测 30 个循环曾产生无界增长）；`compare()` 读字节后重新校验摘要；`base_url` 带 `?api_key=` 或 `user:pass@` 不再被接受（会原样返回给浏览器）；`_write_json_atomic` 改用 temp+replace（原名不副实，崩溃会留下截断缓存）；auto-select 同分时按 `(score, model_id)` 决胜（此前取决于目录顺序）；`chapter_run_v2` 的畸形 run id 与非整数 limit 改抛带 code 的错误（此前是裸 `ValueError` → 500）。
- **审查中被否决的两项**：(a) 「切到 console 认证时应清除已持久化的手动密钥」——仓库刻意保留它以便切回时恢复，`test_switching_auth_source_keeps_inactive_manual_key_and_clears_old_probe` 明确编码了该契约，且 console 档案经 API 解析出来本就是空串，已撤销该改动。(b) 「`epochs.models` 是死通道」——发布方在宿主侧（`domain.ts` 把 `/api/model*` 映射为 `models`，`WorkbenchStore` 从 SSE 发布），审查脚本只走了客户端所以漏报，已做正向验证后判定为误报。
- **测试夹具修复**：`test_http_persistence_hardening.py` 的 HTTP 助手用 `urllib` 且未绕过代理，本机设有 HTTP/SOCKS 代理时环回请求被代理拦截并返回 502 空 body，8 个测试假失败。改为显式 `ProxyHandler({})`。

---

- **修掉两个此前无解的阻断级缺陷**：(1) 文档变更计划的「应用 / 撤销」从不带 `confirm: true`，而 Core 对这两步强制要求它——面板上的这两个按钮**一直返回 `CONFIRMATION_REQUIRED`**，Search 的行内替换和变更计划卡片的接受/撤销 100% 不可用（拒绝/重试能走，所以界面看起来是活的）；改为按 Core 与 agent 工具的既有约定，仅对 document 计划下发 `confirm`。(2) `tool-policy.ts` 把 `novel_model_profiles` / `novel_embedding_profiles` 两个 action 式工具整体归为 `read`，于是删除 profile、改配置、覆写路由表这些持久化写在只读沙箱和计划模式下都能执行——`readActions` 里正确的拆分因为 `reads` 提前返回而成了死代码。
- **修掉一个高危可用性缺陷**：`api.ts` 的写路径一直没有超时（读路径有 60 秒），而 `ModelView.load()` 又会无上限等待一个进行中的保存。写入不返回时作者切换 workspace 导致卸载，下次挂载就永远停在 loading 分支——模型页彻底卡死且没有重试入口。写路径补 120 秒期限，等待补 10 秒兜底。
- **修掉一个高危运行时缺陷**：`probeHealth` 把探针超时也当成「后端已死」，`verifyConnection` 随即 SIGTERM 并重启。后端忙于写章/评审时 `/api/health` 答得慢，与真死无法区分——实测后端 health 停顿 3 秒，子进程 1518 毫秒就收到 SIGTERM，正在跑的工作被销毁。探针改为三态：只有子进程退出、连接被拒、health 非 ok 才算「死」，超时算「未知」并加长预算重试一次，绝不杀。
- **工具面补强**：`novel_doc(action="write")` 省略 `version` 就是无锁 last-write-wins 覆写（与工具描述承诺相反），改为要求 `version` 或显式 `force: true`；`novel_assets_package(action="export")` 被标为并发安全却写本地文件（三个并发导出返回同一路径并互相截断），改为非并发安全；`restore_draft` 与 `annotate` 此前会发送空 `revision`/`confirm: false`/空 `quote`，服务端的修订守卫被静默满足或落库垃圾批注，全部补本地必填校验；`novel_review_chapter(action="compare")` 缺 `revision` 时发空串，得到的是误导性的「没有这次评审」404；`novel_writing_assets(action="save_anchor")` 空 name/content 会让 CAS 冲突和畸形载荷都返回同一个 400；`novel_task(action="get")` 硬编码 DoG 阈值 70；`dog-review.ts` 的 10+ 个产物改用 `atomicWrite`（中途崩溃不再留下被读成 corrupt 的截断 JSON）；导出文件名加长度上限（此前是裸 `ENAMETOOLONG` 且带本地路径）。
- **StudioClient 归一化**：超时与「后端不可达」此前同码，导致可能已落盘的写被盲目重试，改为独立的 `REQUEST_TIMEOUT`；主体读取中止不再是「成功状态 + 错误码」；workspace 根目录消失不再被误报成网络故障并写一份冤枉传输层的诊断；下载加 256 MiB 硬上限；调用方中止不再逃逸成裸 `DOMException`；`connect()` 的启动引导不再计入请求期限（冷启动首调用此前必然假失败）。
- **代理层加固**：SSE 现在遵守背压并按流限制缓冲（此前停滞客户端无界堆积，实测 2 万事件 18.6 MB）；每 root 限制并发流数并回收半开连接（此前 500 个连接全收且永不释放）；请求主体与下载都加了上限（此前 64 MiB 主体可被完整缓冲进宿主进程）；代理 catch 不再把 409 `REVISION_CONFLICT` 之类的错误压成通用 502——那会让面板的冲突本地化失效；插件重载时 `invalidation.json` 不再返回空 200（面板会因此抛错转 offline），改为显式 503 并保证不重复写。
- **启动期校验**：`timeoutMs <= 0`、非 http(s) 的 `baseUrl`、`managed` 模式带 `authToken`（静默忽略）、`artifacts` 缺 `runtime-manifest.json`、非绝对路径——此前都要到第一个请求才炸，且原因被改写得很误导。`mode` 补显式 `default('external')`；`config.json` 现在声明 `managed` 并在托管模式下上报实时后端地址（此前下发的是从未绑定的默认 4567）。
- **面板缺陷**：修订「应用」和版本「恢复」此前直接以 `allowDiscard` 覆盖编辑器，未保存文本静默消失（同文件其他处理器都会先保存再检查）；变更计划操作没有 busy 守卫，双击会双发同一个 `preview_token`，409 时显示服务端中文原文且按钮保持可用；`ResearchView.load()` 没有请求序号守卫，慢请求后到会擦掉成功的刷新；manuscript epoch 在文档 loading 期间到达会被吞掉；`epochs.dag` 此前无人消费（章写/评审/修订终态不刷新任何视图），现在由连续写作页消费；模型页导航在保存中时静默失效；GraphView 手动刷新无序号守卫；workspace chip 浮层补 Escape；`LibraryView` 的 `pendingMode` 跨上下文残留；`BenchmarkView` 六处硬编码中文改为走 locales。
- **发布与文档**：`prepare.mjs` 此前只在「本次恰好构建了」时才刷新 provenance，改源码不重建就带着旧 `source.json` 发布；`release-provenance.mjs` 的源码哈希排除所有 `lib/`，而 `lib/index.js`/`lib/client.js` 正是随包执行的代码（已用篡改实验验证）；`release-report.mjs` 中缺 `host` 的报告能满足任意平台腿；`plugin-check.yml` 的 `paths-ignore` 含 `docs/**/*.md`，使 `docs:check` 永远跑不到它要防的那类改动；`repair-regressions.yml` 此前整体重试 pytest，会把 flaky 测试记成通过，且 Core 固定 commit 可被 PR 自带 manifest 改动。文档侧修掉 11 处仍在描述已删除的 DoG / 旧工具名 / 95 工具面的内容，并把工具名检查扩展到全部用户文档；`THIRD_PARTY_NOTICES.md` 承诺的 OpenSSL 许可证（静态链接进 cryptography wheel）此前并未随包，已补并可校验。


- **修掉一个此前无解的阻断级缺陷**：浏览器代理的白名单漏了 `model/profiles/delete-preview`，而面板的删除是两步走（先 preview 拿 `deletable`，再删）。预览永远 405，于是**任何一个对话模型 profile 都无法从面板删除**，只剩一句「…is not allowlisted」。新增 `proxy-allowlist.test.mjs` 把面板发出的每个写路径都钉在白名单上（并带 stale-build 检查）。
- **修掉 13 处会误导模型的旧工具名**：工具描述与参数文档里仍写着 `novel_task_get` / `novel_task_cancel` / `novel_doc_read` / `novel_assets_list` / `novel_export_preflight` / `novel_structured_change_plan` 等——模型照着调用就会得到「工具不存在」。这些字符串还被 `gen-tools-md.mjs` 原样搬进 `docs/TOOLS.md`。值得注意的是 `tool-policy.test.mjs` 此前**正因为这些错名而通过**（断言 SDK 段落里出现 `novel_doc_read`）。新增 `scripts/check-tool-references.mjs`：把工具源、全部 24 个技能与 `docs/TOOLS.md` 里出现的每个工具名对照注册表校验，并拦截已退役的命令式旧名；已挂进 `docs:check`。该门禁随即抓到三个此前**结构上无法被检查**的技能（`foreshadowing-system`、`truth-validation`、`world-query` 仍在教 `create_foreshadowing` / `validate_truth` / `query_world`），已改写为现行工具面；`preset-smoke.mjs` 也对全部技能而非 11 个跑旧命令检查。
- **修掉三个中危问题**：`OperationsView` 的「在新标签页打开」硬编码 `127.0.0.1:4567`，而 managed 模式端口由系统分配，点了必然连接失败（且没有 workspace 上下文会显示错项目）——已删除；`safe-upgrade.mjs` 的 staging 过滤器用 `/` 比较路径，Windows 上 `path.join` 产出 `\`，`.plugin-manager` 排除完全失效——改为按相对路径判断并补回归；导入 tab 把终态 `published` 当成活跃状态，每个已完成的导入都会留下一个永久 2.5 秒轮询——只保留真正会自行推进的 `running`。
- **修掉两个低危数据问题**：`dog-review.ts` 的 10+ 个产物用裸 `writeFile`，中途崩溃会留下截断 JSON，之后被读成「DoG artifact corrupt JSON」——改用 `dog-delivery.ts` 的 `atomicWrite`；`openwrite-maintenance migrate --profile`（无值）会以裸 `TypeError` 崩溃，因为 `PROFILE.test(undefined)` 会把 `undefined` 转成字符串并通过校验——改为用法错误。
- **其它**：`scripts/plugin-doctor.mjs` 此前不在 `files` 里，而两份随包发布的文档都让用户 `npm run doctor`——已补；`SerialWritingView` 此前不响应任何变更周期，`novel_writing_assets` / 章纲审计等结果要切 tab 才刷新——接入 epoch，同时让此前无人消费的 `epochs.dag` 有了消费方（章写/评审/修订终态），并补「每个 epoch 键都必须有消费方」与「刷新求和必须严格单调」两条回归；`dog-*.ts` 里指向已删除脚本的 `verifier` 元数据补了说明（它是服务端声明的契约字段，本插件只透传，不能删）。
- 本轮审查同时纠正了上一轮我自己引入的一个回归：`install.sh` 的备份目录从 `mktemp -d` 改成秒级时间戳，同一秒内两次安装会共用目录、第二次覆盖第一次的内容——已改回 `mktemp -d`，并用 `/tmp` 下的真实目录复验了作者文件保留行为。


- **修掉两个数据丢失级缺陷**：`scripts/install.sh` 不再用 `rsync --delete` 同步预设（作者在 `~/.dsh/.agent-presets/openwrite/` 下的自建文件改为移到 `.agent-presets-legacy/` 并报告，不再被静默删除）；`openwrite-maintenance migrate` 中途失败时把已 remove 的依赖按原 spec 装回，不再留下「manifest 列了依赖而 node_modules 没有」的半迁移 profile。
- **plugin.mjs**：托管预设目录里的编辑器/系统杂文件（`.DS_Store`、`*.bak`、悬空符号链接）不再让 `apply()` 抛错以至于整个插件不激活，真正的作者修改仍被拒绝；`/studio-panel/companions` 补上与其它 `/studio-panel/*` 路由一致的浏览器鉴权。
- **免费模型接入**：检测到本地转发已开启时可一键写入 `our-free-model` 模型 profile（保留作者调过的参数、覆盖前需确认、不默认持久化密钥）；网关读取失败按 404/5xx/非 JSON/形状不符分别说明，不再一律说成「本地转发没有开启」。
- **门禁补强**：浏览器验收现在把任何 >=400 的响应判为失败（此前只打印）；新增对 `/studio-panel/companions` 路由与响应形状的断言；#149 的别名断言改为先证明选择器真的打开。
- **合并 thin 工具面（95 → 56）**：把 13 族「一个动作一个工具」的 thin 工具合并为 action 式工具——模型/嵌入配置（`novel_model_profiles`、`novel_embedding_profiles`）、后台任务（`novel_task`）、修订（`novel_revision`）、项目（`novel_project`）、资料（`novel_assets`、`novel_assets_package`）、场景（`novel_scene`、`novel_scene_migration`）、文档（`novel_doc`）、导入（`novel_import`）、阅读顺序（`novel_reading_order`）、导出（`novel_export`）、变更计划（`novel_change_plan`）。HTTP 端点、参数名与产物格式不变，合并只发生在工具面； 回归中发现并修掉两个阻断级缺陷：`novel_task` 的 `type`/`input` 误留 required 导致 6 个 action 里 5 个不可达；`novel_revision` 的两个 `case 'create'` 让 selection 路径变成死代码、from-review 路径反而多要求 `selection`。同时按 `tool-policy.ts` 的名字分类补齐合并后的只读/生成动作（否则只读动作会在只读/计划模式会话里被拒），恢复三类下载动作的严格输出 schema，并把此前不在任何测试集里的 `tool-policy.test.mjs` / `followup-tools.test.mjs` 纳入 `test:managed`。每个 action 沿用原工具的必填校验与并发安全标注。技能、面板工具族、`docs/TOOLS.md`（已重新生成）与全部测试同步更新。

- **移除内置 DoG 引擎**：删除 `vendor/dsh-dog`（v1.2.0 + 适配补丁）、`dog_*` 模型侧工具、「DoG 验收」调试器入口与 `scripts/dog/` verifier 脚本；安装脚本不再自动克隆上游。三个查询技能改名为 `review-artifact-query` / `delivery-artifact-query` / `import-artifact-query`，内容改为直接读 OpenWrite 自己的评审/交付/导入产物（`dog_review`、`dog_delivery`、`data/novels/{id}/data/dog/**`），不再调用任何 DoG 工具。OpenWrite 自己的六域评审/交付闭环不受影响；需要图形化 DoG 验证可自行安装 `@dsh-external/dsh-dog`。发布门禁同步去掉 `dog-overlay` / `dog-snapshot` 客户端检查项。

- 新增可选联动插件支持（[联动插件说明](docs/COMPANION_PLUGINS.md)）：检测到已安装且宿主放行的 `@dsh-external/dsh-dog` 时，DoG 引擎/调试器交给对方最新版，内置副本不注册任何服务与工具，预设改挂只含执行策略的 `dog-policy`；检测到 `dsh-ops` 时通过其官方 `integration({ preset: 'openwrite' })` 挂载有界文件工具与渐进发现（不替换官方工具、不发布 shell）；检测到 `@ebony-vinyl/dsh-our-free-model` 时在工作台「联动插件」区显示状态与接入提示。三者均为可选项，判定集中在 `companions.mjs`（含所需 semver 子集，无新增依赖），任何失败都 fail-closed 回退到 OpenWrite 自己的实现；`npm run doctor` 新增联动检查。
- 修复 [#150](https://github.com/LiPu-jpg/Openwrite/issues/150)/[#151](https://github.com/LiPu-jpg/Openwrite/issues/151)/[#142](https://github.com/LiPu-jpg/Openwrite/issues/142)：根包与全部内嵌子包的 `peerDependencies`、`dsh.compatibility.dsh`、`dshReleases` 与 lock 同步加入精确宿主 `0.2.1-rc.4`、`0.2.1-rc.5`，安装与激活不再被宿主版本闸门拒绝；旧宿主匹配集合逐项对比无变化。发布矩阵新增这两个宿主的客户端验收。
- 修复 [#149](https://github.com/LiPu-jpg/Openwrite/issues/149)：预设别名不再无条件注册全部已发布版本，改为按会话存储里真实引用过的 `agentPreset` 注册（只解每个会话日志的第一帧，带指纹缓存），新建会话选择器不再出现 27 条「（历史会话 openwrite-0-2-N）」；别名显示名改为「（旧版 0.2.24 · 仅用于恢复历史会话）」，工作台入口改用稳定预设 id `openwrite`（发布 id 仅作回退）。会话存储不可读时仍回退全量别名，#105 的历史会话恢复不回归。

## 0.2.27

- Bundle Core 5.8.16: reviewer safety/domain/legacy calls honor the profile output allowance from the first request, without a hidden 4096-token cap (#69); retain context limits and bounded truncation recovery.
- Include the workbench OpenCode Go Console integration from Core 5.8.15 (#114), with CLI credential refresh and automatic workspace headers.
- Preserve 0.2.26/27 session identities as durable aliases; require each new release alias and run lifecycle/upgrade/runtime regressions on the native platform matrix (#105).
- Fix manual backend retry racing the tail of a failed recovery: wait for the old startup to settle, return a fresh connection, and let a later cancellation take precedence.
- Add inline quote-anchor HTTP preview/apply/undo regressions for LF/CRLF and tool argument serialization (#109 B-13). Keep original reproduction, real-device acceptance and upstream release work open in #123; see `docs/CLOSED_ISSUE_FOLLOWUPS.md`.

## Unreleased

- Bundle Core 5.8.15: workbench OpenCode Go Console authentication, per-request CLI credential refresh and automatic workspace headers (#114).
- Add explicit Console/API Key authentication and optional Go workspace pinning; keep Console tokens out of profiles and browser DTOs.

## 0.2.26（2026-10-26）

- Support configured embedding dimensions and cloud/local embedding configuration (#103, #104).
- Bundle Core 5.8.14: serial-writing continuation/retry reliability, style and world context, incomplete-review scoring, relation preservation and document-edit lifecycle (#109).
- Expose full writer input previews and explicit relation replacement through the bridge.
- Adapt OpenCode Go client/session headers and document current DeepSeek V4.1 Flash configuration (#114).
- Restore historical session presets, exact DSH 0.2.1-rc.3 compatibility and actionable external-runtime diagnostics (#105–#113; PR #115).

## 0.2.25（2026-10-23）

- 捆绑 Core 5.8.12，处理 #98–#100：无模型验收、实例根目录校验、任务心跳与有限超时、历史隔离横评、作者自留存档及逐章体检。
- 新增长章分段续写、范本池、共享术语表、角色属性轮换和重合检测；新增「连载体检」工作台及 5 个领域工具。
- 章纲支持承诺、回收伏笔、字数预算、章节功能；章组审计输出计数事实，漂移裁决保留不可变基线和中断恢复日志。
- 新增 `openwrite-safe-upgrade` 停机旁路安装、完整日志与失败恢复；原生 `dsh plugin add/update` 和宿主 bundle 启动降级仍需宿主侧处理。详见 [实现与限制](docs/ISSUES_98_100.md)。

## 0.2.23

- 修复 [#83](https://github.com/LiPu-jpg/Openwrite/issues/83)/[#84](https://github.com/LiPu-jpg/Openwrite/issues/84)/[#85](https://github.com/LiPu-jpg/Openwrite/issues/85)：声明并验证精确宿主 dsh `0.2.1-rc.2`。根包与内嵌子包（`@dsh-novel/openwrite-bridge`、`@dsh-novel/studio-panel`、`@dsh-external/dsh-dog`）的 `peerDependencies`、`dsh.compatibility.dsh` 与 `dshReleases` 同步加入 `0.2.1-rc.2`；宿主安装和激活不再以“plugin does not support the DSH version in use”拒绝，也不需要版本豁免或手工编辑 `compatibility.json`。宿主闸门读取的是 `@deepseek-ai/dsh-*` peer 范围（`dsh.compatibility` 只是展示元数据），因此只改后者无效；实测 0.2.1-rc.2 的宿主 API 未发现破坏性变更，失败原因是版本门槛。
- 客户端验收脚本适配 0.2.1 的首次启动界面（可关闭的凭据提示、侧栏 `OpenWrite` 入口），并在 `0.2.1-rc.2` 上完成 Web 启动、预设选择、工作台三页签、DoG 面板与其他插件共存的实机验证；`0.1.2-rc.1`、`0.2.0-rc.2` 回归通过。发布工作流新增精确 `0.2.1-rc.2` 的客户端验收矩阵。
- Core 保持 5.8.10，模型、作品数据和依赖清单没有变更。

## 0.2.22

- 修复与 dsh-vision-router 等同台 bundle 共存时整机无法启动的问题（[#81](https://github.com/LiPu-jpg/Openwrite/issues/81)）：bundle patch 不再覆写核心 `connection` 行的 `inject`——include patch 逐顶层键赋值，覆写会丢掉其他 bundle 追加的服务（如 `visionRouterWebConnectionReady`），导致必需的 `connection` 插件激活失败。DoG 调试 RPC 通道改为插件自己在 Web 载体上注册 `/dog-rpc` 路由（0.2 宿主的 Connection 通用通道注册需要 connection 自身上下文持有 `webServer`，而共享 `/api` 通道已被宿主 Typert 网关占用）：准入沿用 Connection 的 trusted-host 围栏与浏览器鉴权，线信封与 Connection 保持一致，浏览器侧传输不变。
- 修复受限网络下「准备写作环境」必然失败或极慢的问题（[#82](https://github.com/LiPu-jpg/Openwrite/issues/82)）：
  - 运行时下载从「10 分钟总时长上限」改为「慢源看门狗 + 30 秒无数据空闲超时」：宽限期内达不到阈值字节即切换候选源（默认回退 `gh-proxy.com` 镜像前缀，`OPENWRITE_DOWNLOAD_MIRRORS` 可覆盖、置空可禁用），下载内容仍按 manifest 校验 sha256，慢和断流都能被区分并给出逐源诊断；启动前清理上次强杀残留的 `.partial` 碎片。
  - 依赖安装放开索引源自救通道：子进程环境白名单新增 `UV_DEFAULT_INDEX`/`UV_INDEX_URL`/`UV_INDEX`/`UV_HTTP_TIMEOUT` 与 `PIP_*` 索引变量（`UV_NO_CONFIG=1` 保留以锁死依赖集，环境变量仍然生效），受限网络用户现在可以自行指向镜像源。
- Core 保持 5.8.10，模型、作品数据和依赖清单没有变更。

## 0.2.21

- 修复 Windows Desktop 的宿主目录选择器仅提供 browse 能力时，OpenWrite 无法弹出系统文件夹对话框的问题（[#79](https://github.com/LiPu-jpg/Openwrite/issues/79)）。宿主接口失败后使用桌面公开的系统目录选择通道；侧栏进入、作品绑定、新建与恢复共用该入口。取消保持无副作用，手填路径继续直接进入。
- Core 保持 5.8.10，模型、作品数据和依赖清单没有变更。

## 0.2.20

- 修复 #76 的草稿丢失、断点恢复、任务状态、编辑与审稿契约；捆绑 Core 5.8.10。
- 补充 #65 的作者语言指令、英文运行状态及错误信息、语言切换说明。
- 新增审稿历史、批量章级元数据、操作恢复说明与职责范围文档，详见 [修复说明](docs/ISSUE_76_REPAIRS.md)。

## 0.2.19

- 修复部分安装（pnpm 隔离布局）下「OpenWrite 创作」预设从 agent 预设列表消失、DoG 工具不可用：vendor/dsh-dog 运行时不再裸导入 `@deepseek-ai/dsh-home-paths` 与 `@deepseek-ai/dsh-tools` 两个 peer 宿主包（在该布局下从 vendor 目录不可解析，导致 openwrite-dog 条目导入失败、`openwriteDog` 服务未注册、预设不注册），`dshHomePath` 与 `defineTool` 改为插件内自包含实现，升级/重装后无需再手动补 junction（[#74](https://github.com/LiPu-jpg/Openwrite/issues/74)）。
- 修复 `novel_*` 工具的对象/数组类参数：模型把 `edits`/`change`/`data` 等 `type: 'json'` 参数输出为 JSON 字符串时，插件在校验前先做 `JSON.parse` 归一化，change-plan 预览/确认门控与 asset `data` 字段恢复可用；参数无法解析或类型不符时报错文案带参数名与实际类型（[#75](https://github.com/LiPu-jpg/Openwrite/issues/75)）。

## 0.2.18

- 修正 0.2.17 的 `auto:cheapest`：零价模型（不限于 `:free` 后缀，如 OpenRouter 上定价 0/0 的模型）不再参与比价，自动落到付费低价模型上——免费模型可用性不稳定，低价策略不应选中它们（Core 5.8.9）。

## 0.2.17

- 模型档案新增自动选模：把档案的模型名写成 `auto:cheapest` 或 `auto:popular` 即可。`auto:cheapest` 在每次解析档案时实时拉取服务商的 `/models` 价格目录（缓存一小时），按"文本对话、上下文 ≥32K、最大输出 ≥4K"过滤并排除 `:free`/`:batch`/动态定价条目，自动选用 prompt+completion 总价最低的模型，价格变动会自动跟随；`auto:popular`（OpenRouter）直接路由到官方 `openrouter/auto`，由社区实际用量自动挑选模型。解析结果记录在 `auto_select` 字段里便于溯源，目录拉取失败自动回退到缓存，静态模型档案不受影响（Core 5.8.8）。

## 0.2.16

- 补漏 #64/#67：字数精简重试耗尽后保留下来的草稿，其 `length_out_of_range`/`length_warning` 标记与后置校验问题（`validation_issues`）现在会持久化进草稿产物（Core 5.8.7）。此前 0.2.15 只覆盖了运行内存态：产物文件里这两个标记为空，导出/审阅侧无法追溯该章曾发生字数越界。

## 0.2.15

- 修复 #63/#66：Windows 上残留 `project.lock` 不再永久阻断写章/审稿。Core 5.8.6 用 Windows 正确的进程存活探测（`OpenProcess`/`GetExitCodeProcess`）替换 POSIX 语义的 `os.kill(pid, 0)`（在 Windows 上它会抛 `OSError [WinError 87]` 且未被捕获），死进程持有的残留锁自动判陈旧并清理；无法验证存活时按"初始化宽限后视为陈旧"兜底。锁被占用时的报错现在带上占用者 operation、pid、起始时间与锁文件路径，不再显示误导性的 `[WinError 87] 参数错误`；写章/审稿的阶段标签改由流水线在真正进入生成时上报，文件锁失败不再被误报为"模型生成失败"。
- 修复 #64/#67：`continuous_write` 单章失败不再整队终止。`max_failures` 连续失败上限按字面语义生效——未达上限时记录该章失败并继续下一章，达到上限才优雅返回 `max_failures_reached`；任务取消仍会立即中止。字数精简重试耗尽后不再丢弃已完成初稿：最后一版正文标记 `length_out_of_range` 保留为草稿（附字数告警），导出前可人工去水或分章。
- 修复 #68：「模型横评」运行期间详情接口不再恒 400。产物契约 `model_benchmark_v1` 的 `status` 枚举补齐实时态 `running`/`cancelling` 与终态 `cancelled`，进行中的记录与已取消的记录都可以正常读取。
- 修复 #69：推理模型评审不再因输出预算地板锁死 4096 而全域 `MODEL_OUTPUT_TRUNCATED`。Core 5.8.6 在 usage 中观察到思维链（reasoning tokens）后把评审输出预算地板抬到 16384，安全门同享；截断后先按翻倍预算原批重试一次，仍失败才二分，且二分不再沿用旧地板。
- #65 部分落地：README 说明界面语言切换（Settings → General → Language，面板已内置英文词典）；Agent persona 增加语言跟随约定（始终用用户对话语言回复）。英文版 persona/skills 与后端信息英文化留待后续版本。

## 0.2.14

- 修复 #60：桥接层转发前消毒 `NO_PROXY`/`no_proxy`（剥掉会令 httpx 构造即失败的 `[::1]` 类带括号 IPv6 字面量），系统代理场景下模型连接测试不再误报"服务商拒绝了请求"；Core 5.8.5 把 httpx 构造期异常归类为本地配置错误（HTTP 412）。`Studio request failed` 附带底层 `error.cause` 便于诊断。
- 修复 #61：Core 5.8.5 启动时预热 numpy/fastembed 重依赖（请求线程里首次 import 会在 Windows 模块加载器里永久卡死），`run_embedding_probe()` 增加硬超时，收尾阶段限时 10 秒、超时强制退出，杜绝"活着但不服务"的僵尸后端；桥接层复用就绪连接前做带超时的健康探活，子进程 stderr 落盘 `state/logs/backend.log`（末尾 64 KiB）可事后取证。

## 0.2.13

- 修复 #57：浏览器代理和 Agent 客户端只在实际写操作成功后通知数据变更，批注与版本读取不再触发自维持刷新循环。
- Core 升至 5.8.4：HTTP action 契约声明查询/预览语义，通过 `X-OpenWrite-Mutated` 告知桥接层；只读请求不再递增工作区 `context_epoch`。旧 Core 的批注/版本查询保留兼容分类。
- 批注 effect 使用正文与修订事件刷新，不再响应无关的 workspace 失效；等待真实修改的读取结果时保留批注，切换作品或章节时清空旧批注并忽略迟到响应。
- 正文编辑动作按 manuscript 通知，确保保存、批注、版本恢复仍会触发界面刷新。

## 0.2.12

- 修复 #50–#52：DSH 0.2 按版本 ID 注册 OpenWrite 预设，技能使用包内绝对路径；0.1 保留目录发现和工作流实现。
- 会话导航适配 `uiWorkspace.openSession`，工作台按主视图持有的会话挂载，进入作品后等待投影就绪再激活创作视图。客户端基础修法来自 PR #53。
- DoG 适配条目配置与主视图导航，不再调用已移除的 settings/catalog 接口或等待不存在的 `current` 字段；补齐 Connection 声明上下文的 Web 依赖，让调试面板真正读取数据。
- 修复 #54：连续审读按章节内容签名刷新，保留正文与滚动 DOM；真实修订变化或手动刷新仍重新取正文。
- Core 升至 5.8.3 / contract 1：模型连接测试使用配置的输出预算，避免 32-token 上限耗尽推理额度；补充托管配置目录说明。
- 客户端验收覆盖预设选择、会话导航及三个工作台页签实际出现、点击创作后工作台可操作及 DoG 真实数据响应；修正 Windows smoke 的 ESM 文件 URL。Windows Electron 原生恢复仍须实机复测。

## 0.2.11

- 修复 #45：根包及内嵌子包的兼容声明覆盖精确宿主 `0.2.0-rc.2`，保留 `0.1.2-rc.1` / `0.1.5-alpha.1`。
- 工作台适配 turn-tail list 槽位，DoG 适配 `sessionStatus`；客户端初始化失败会回滚部分注册并输出可读错误。
- 补充旧包子包授权与 profile 备份恢复说明。Windows Electron 桌面端恢复链路尚未实机复测。
- 包含 #44 的 minimap CSS 修复。Core 仍为 5.8.2 / contract 1。

## 0.2.7

- 未解决批注显示在正文上方的「作者选区批注」条，点击即可定位。
- 正文里的批注颜色和下划线加重，避免几乎看不见。
- 「修订」页签在有未解决批注时显示数量。

## 0.2.6

- 批注输入框可以点击和输入；不再被选区保护的 `preventDefault` 挡住焦点。

## 0.2.5

- 覆盖层按整段 IR 文本定位，粗体/拆节点的引文和 `//**…**` 标记也能画中。
- 正文滚动或窗口缩放后重新对齐覆盖层，不再停在第一次绘制的位置。
- 「定位」会选中并滚到原文，而不只改侧栏状态。

## 0.2.4

- 创作工作台支持选区批注：保存后绑定范围，重复引文不取第一处；未保存先保存再核对。
- 批注使用固定颜色，旧记录缺颜色时显示琥珀；覆盖层不写入 Markdown。
- 可插入人物状态变化和指向关系两种内部标记；同名人物需明确选择。有效标记不计入字数和默认导出。
- Core 5.8.1：批注记录增加可选 `color`。不回退 0.2.3 的迁移、环境允许列表和自动恢复。

## 0.2.3

- 受管理后端自动恢复失败不再把未处理 Promise 抛给宿主；dsh 保持运行。
- 恢复过程中的启动失败按同一上限继续退避重试，而不是只试一次。
- 恢复等待期间取消或卸载不产生未处理错误，也不会再拉起后端。

## 0.2.2

- 旧安装迁移同时处理 bundle 登记和 `dependencies`，通过宿主 `dsh plugin remove` 删除 `@dsh-novel/openwrite-bridge`、`@dsh-novel/studio-panel`、`@dsh-external/dsh-dog`；备份失败可恢复，不改用户 `node_modules` 源码，不删除作者预设。
- 受管理后端异常退出后有限次退避自动恢复；取消、卸载和宿主退出不复活。恢复不重放付费请求。
- Python / uv 子进程改为允许列表环境，不再整包继承 `process.env`。
- 补齐 leftover-deps、自动恢复、环境允许列表、Workspace/revision/未认证策略的回归测试。真实模型费用测量未执行。

## 2026-08-23 - dsh 原生创作工作台

- OpenWrite 改为无界面领域后端；`NovelDomainService` 统一工具、同源 API 代理和轻量 revision 失效流。
- 顶层插件视图收敛为「创作 / 资料 / 任务」，默认工作流彻底移除 iframe 与重复导航。
- 新增原生 Vditor 正文编辑器：1.2 秒自动保存、version 乐观锁、409 草稿保护、显式覆盖。
- 新增共享 `NovelWorkbenchStore`、会话头作品状态、输入章节上下文、Turn 写操作汇总。
- 44 个常用工具归入八类原生卡片；大纲默认只展开当前章节路径。
- Vditor 主运行时随插件打包，辅助资源由 dsh 同源提供；增加原生路由、无 iframe 与多工作台 smoke 门禁。

## 未发布

- 安装器默认从 `Fun10165/dsh-dog` 获取固定的 `v1.2.0`，原子安装到
  `$DSH_HOME/extensions/dsh-dog`，构建后只挂载 web profile；已有安装可复用，也可用
  `DSH_DOG_DIR` 指向开发工作树或用 `DSH_DOG_AUTO_INSTALL=0` 跳过。获取失败会在清理
  临时目录后尝试禁用 Git HTTP(S) 代理直连；DoG 以当前会话 Workspace 为图根，静态
  `dog.workspaceRoot` 只作兜底，切换作品不再需要改配置或重启。
- 评审体系升级为 review v2：原 37 项恰好映射到六个计分域和一个硬门禁，使用有正文
  证据才得分的累加机制；`quality_score`、`coverage`、`gate_status`、
  `delivery_status` 分离，issue 不再直接扣分，severity 与 `revision_priority` 独立。
- 评审 DoG 改为 47 节点分层图（上下文、六域、门禁、确定性聚合、37 个 legacy leaf），
  全部使用程序 verifier；交付图扩为
  `writing → review → revision → application → rereview → closure` 六阶段。
- 「图谱」新增 React Flow + ELK 的评审/交付 DAG，可选章节、筛选异常/blocker、折叠六域、
  展开 37 项并查看 score/coverage/evidence/issue/provenance；Studio 新增只读
  `GET /api/dog/graphs`，不会运行 verifier 或模型。
- 新增框架内模型测试台与第 63 个工具 `novel_model_benchmark`：通过 OpenWrite profile
  和 LiteLLM-compatible gateway 固定上下文 hash，隔离运行多写作模型 × 独立评审模型，
  artifact 写入 `data/novels/{id}/data/benchmarks/`，不修改全局路由或正式正文。
- 模型测试默认进入 OpenWrite 公共生产写章与评审管线；每个候选/重复轮次使用完整作品
  沙箱并保留 Chapter Run V2、记忆、工作流与提交证据。裸 `_creative_write` 路径仅作为
  显式 `creative` 诊断模式。
- 框架内候选失败现在也保留公共入口、Run V2 ID、阶段状态、失败阶段与安全错误码；未完成
  `commit` 的可靠性失败不会进入评审或获得质量分，旧 artifact 在 UI 中仍按执行模式显示
  正确入口。
- 模型测试统一归一 OpenRouter/OpenAI-compatible/LiteLLM 的 token 与实际费用，汇总输入、
  输出、推理用量和费用覆盖率；明确免费的 `$0` 与未知费用分开显示，并提供本次调用的综合
  有效价 `/ 1M tokens`，不冒充模型目录单价。
- 审稿卡和任务列表优先显示 v2 质量分、覆盖率、门禁/交付状态，并分别展示
  `critical/warning/info` 评审严重度与 `blocker/high/medium/low` 修订优先级。
- 新增 DAG/benchmark HTTP 生命周期测试、bridge tool/proxy smoke、Python/TypeScript
  parity/无环/stale 测试，以及优质/当前/故障三类合成 golden fixtures 与 v1/v2 双轨校准。

- dsh-dog 进一步融合：同步评审、conductor 与后台 `chapter_review` 任务统一物化
  分层评审查询图（保留 `1..37` legacy leaf）；修正维度参数为 OpenWrite 要求的
  `1..37` 整数数组并加入阈值校验。
- 新增章节交付总图：以正文 SHA、评审 `source_revision`、修订提案状态和复评结果
  串联 `writing → review → revision → application → rereview → closure`；应用修订后强制进入待复评，
  只有当前正文复评通过才标记 `readyForDelivery`。同步工具、后台任务和 conductor
  均会刷新交付快照，并新增 `dog-delivery-query` 技能。
- 修复智能导入的 DOCX/EPUB 二进制文件被提前文本解码、空任务项目无法解析
  `novel_id` 的问题；补齐导入格式依赖和 DoG 契约测试（含真实 dsh-dog 图校验）。

- 「审稿」tab 并入「写作」（原总览）三分段：总览 ⇄ 正文 ⇄ 审稿，Studio iframe
  三合一；tab 总数 10 → 9，标签更名「写作」
- 搜索 tab 点击即读：结果行可点击，内联预览经 GET /api/document 取全文，
  命中行 ±2 行带行号高亮，返回钮回列表——查到的资料不再需要跳去别处看
- 任务 tab 补管理闭环：行悬停 取消（pending/running/awaiting_confirmation，
  confirm 门）与 重试（failed 且 recoverable）按钮，走 host 代理新增的模式
  白名单 `tasks/{id}/cancel|retry`
- 任务 tab 评审结果可见化：完成的 chapter_review 行内嵌分数徽章（分档着色），
  点击展开问题清单（severity 着色 + 维度 + 摘要，≤10 条）——conductor 经 HTTP
  跑的评审与 agent 工具跑的同样可见
- 设计令牌归一：本轮新增样式全部映射回平台既有词汇，清除自造令牌
- conductor 新增 dsh 原生深度研究路线（`research.py`）：headless 会话用平台
  自带 web_search 联网调研并综合成报告，落库 OpenWrite 报告目录（研究 tab
  直接可见）——绕开博查 Key 依赖，零额外凭据；实测两份真实报告入库
- 研究 tab 补「发起研究」：问题输入 → type=research 托管任务（进度在任务 tab，
  可恢复错误如搜索凭据缺失原样透传）；host 白名单增补 `tasks` 写路径
  （修复研究提交被代理 405 拦截的遗漏）
- 「总览」「正文」两个 tab 合并为一个「总览」：原生工具箱条 + 分段切换
  （总览 ⇄ 正文），单一 Studio iframe 经 hash 片段导航切换（不整页重载，
  编辑器状态保留）；tab 总数 11 → 10
- 总览 tab 原生工具箱条：导出 md/txt/epub（经代理二进制安全下载）、同步项目、
  导入章节（文件选择 → 预览切章计划/冲突 → 确认/强制覆盖）——补齐 Studio
  「工具与设置」抽屉在 dsh 侧最后一个无 UI 缺口；代理改二进制安全透传并放宽超时至 60s，
  写白名单增补 sync / import/preview / import
- conductor 落地（`conductor/`）：无人值守写章流水线——写章/评审/修订回炉全部
  走 OpenWrite 后台任务系统（phase 轮询、预算超时显式取消、recoverable 原生
  retry），回炉经 revision_from_review → regenerate → apply 修订闭环（含客户端
  锚点预过滤）；可选 --agent-guidance 用 dsh SDK bundled 会话综合改写指导。
  同步端点 /api/write、/api/review 因孤儿化服务端任务被弃用于编排路径
- 新增 --review-only（对成稿章节只跑评审门）；实测 ch_001~004 全流程，
  ch_003 修订回炉 0 → 35 分
- 根目录 `skills/` 移除：技能唯一来源是 `presets/*/skills/`（内容相同，根副本无任何引用）
- `scripts/verify.sh` / `dev.sh` 导出 `NO_PROXY`：系统代理指向本机时
  （HTTP_PROXY=127.0.0.1:*），探活与验证请求不再被代理劫持而全部误报失败
- DESIGN.md / README 与实现对齐：补 studio-panel 组件章节；「组合与启动」改为
  profile bundle 安装路径（`overlays/` patch 层方案已废弃）；技能章节改为预设自带 skills/
- studio-panel：新增「研究」tab（深度研究报告库，主从布局 + 全文渲染 + 运行环境就绪态）
  与「搜索」tab（项目资料检索：350ms 防抖、canonical scope 下拉、命中词高亮、
  加载/空态/服务端 warning 提示）；「图谱」tab 补齐连续性面——伏笔校验错误块与 ⚠ 角标、
  事实账本（truth 三文档渲染）、章节工作流列表；新增 search-harness 逻辑级测试
  （真实 bundle 组件 + DOM shim 驱动防抖→fetch→渲染流）
- openwrite-bridge 从 14 扩到 **62 个 `novel_*` 工具**，OpenWrite Studio 动作面全覆盖
  （修订闭环、任务中心、后台连写、章节运行、滚动大纲、叙事预测、风格/参考库/规则、
  深度研究、模型配置、项目生命周期等）；刻意不桥接 `/api/chat` 与 `/api/agent/*`，
  agent 会话层唯一归属 dsh
- 移除 `novel_chat_goethe`：不再回调 OpenWrite 内部 agent，草案生成由 dsh agent 自身完成
- goethe/dante 预设 persona 更新完整工具面；删章改走 `novel_chapter_delete` 服务端三重确认
- `subagent_goethe` 只读面补 `novel_asset_read`、`novel_continuity`
- studio-panel：新增「大纲」「资产」「任务」「图谱」原生视图 tab 与 `novel_review_chapter`
  评审报告卡；host 侧 `GET /studio-panel/api/*` 只读代理（透传状态码/错误体，
  写操作仍只走 agent 工具）。「资产」tab 含资料库（参考作品）分组；「图谱」tab 为
  伏笔分层看板 + 人物关系环形图（类型过滤、密度自适应）
- 配套 OpenWrite 侧改动（在 OpenWrite 仓库，未提交）：嵌入检测改为
  参数/被嵌/sessionStorage 三重判定；修复 start() 覆盖 shell 主题的问题；
  `applyShellTheme` 实时联动 Vditor 编辑器主题；嵌入时隐藏 Studio 主题切换按钮；
  **修复嵌入模式从未生效的根因——Studio CSP `script-src 'self'` 拦截内联脚本，
  启动逻辑移到外部 `embed-boot.js`**；嵌入时不再自动弹新手引导
- studio-panel：iframe 带 `?embed=dsh&theme=` 参数，跟随 shell 深浅色主题实时联动
- 配套 OpenWrite 侧改动（在 OpenWrite 仓库，未提交）：`OPENWRITE_FRAME_ANCESTORS`
  可配置嵌入白名单、`embed-dsh.css` 皮肤（嵌入时隐藏 Studio 内置 agent 入口）、
  index.html 启动脚本
- 新增 `scripts/verify.sh` 一键集成验证

## 0.1.0

- 首个版本：`@dsh-novel/openwrite-bridge`（14 个 `novel_*` 工具）、
  `@dsh-novel/studio-panel`（「稿件」tab 内嵌完整 Studio）、
  goethe/dante 双 agent 预设（persona 移植自 OpenWrite）、13 个移植技能、
  `install.sh` / `dev.sh` 脚本
