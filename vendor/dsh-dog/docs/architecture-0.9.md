# DoG v0.9 架构定稿(经业主审核)

> 本文件是 v0.9 重构的唯一依据。所有条目均为 owner 已拍板立场;改动需先改本文。

## 0. 总则
- 判据只有两个寄主:**代码(脚本)** 或 **自然语言(instruction)**;没有第三种(无"契约/验证器类型/参数白名单/证据格式/工具面"等中间层)。
- 引擎只做传话:**递对象 → 收 {结论, 证据} → 汇总**;不解释判据、不规定证据格式、不限制 agentic 工具。
- 一切"验证能力"的扩展 = 写脚本 或 写一句话;**引擎零改动**。

## 1. 图(节点)
### 1.1 节点类型
- `composite`:子节点布尔组合(completion AST:`ref/all/any/not/atLeast`)+ 失败传播(contains:`required` + `failure: fatal|tolerable|degrade` + `degradeTo`)+ 依赖门禁(dependsOn,仅调度顺序)。
- **composite 可选"整体断言"**:verifier 二选一形态(见 1.2),**在子树全部结算后执行**,对象=子树聚合(见 2.3);与子节点逻辑独立(只影响复合节点最终状态)。必带字段:`kind/title/constraint`。
### 1.2 叶子(只有两种形态)
```jsonc
// 程序化:判据=脚本;ENGINE 唯一必需参数=捕获副本路径(文件或 tar)
{ "kind":"leaf", "title":"…", "constraint":"hard",
  "target":"harness-article.md",          // 或目录(见 2.3)
  "script":"text-phrase-absent" }          // 宿主注册的脚本名(见 3.1)

// agentic:判据=一句自然语言;无参数、无白名单、无骨架
{ "kind":"leaf", "title":"…", "constraint":"hard",
  "target":"harness-article.md",
  "instruction":"检查…是否有模板腔/空口号/信息密度低;自己决定怎么查,给结论与证据。" }
```
- **没有** verifier.id/verifierParams/evidenceSchemaId/allowedTools/grounding 字段。

## 2. 对象与捕获
### 2.1 target 二义性
- 单文件:原样捕获。
- 目录/显式集合:**引擎递归打成 `<name>.tar**(保留相对路径结构)再捕获。
### 2.2 捕获(dog_create 时刻)
- resolve(workspaceRoot 内,防逃逸:相对路径/符号链接检查)→ 读字节 → SHA-256 → 内容寻址存储 `artifacts/<hash>.bin` + 元数据 `{path/digest/exists/byteLength/sha256, tar?: bool}`。
- **捕获=固定版本**:验证用捕获字节,指针不变。
### 2.3 执行时对象的交接
| 形态 | 引擎交 | 说明 |
|---|---|---|
| 程序化 | **捕获副本路径(文件或 .tar)**作为唯一必需参数 | 脚本自己决定是否解 tar;其余自理 |
| agentic | 解包后的完整产物(单文件或解 tar 后的目录树)放进该叶私有工作区;instruction 随 prompt | 子代理读工作区;免解包 |
| composite 整体断言 | 子树聚合(tar):程序化=tar 路径;agentic=解包目录树 | 时机=子树结算后 |
## 3. 执行内核(仅两个)
### 3.1 程序化(脚本)
- 脚本来自**宿主注册的脚本库**(仓库 `scripts/` 或宿主扩展目录);图只能引用**已注册脚本名**,不能给任意路径/内联代码(安全)。
- 引擎→脚本:仅"捕获副本路径"一个必需参数(可加可选 stdin 约束?——**no:单参数即定案**)。
- 脚本→引擎:**极小 JSON** `{"verdict":"pass"|"fail", "evidence": <任意 JSON 值>}`(stdout;非零退出=inconclusive)。
### 3.2 agentic(子代理)
- 引擎→子代理:instruction(一句话)+ 工作区内产物;不限制工具、不规定证据格式。
- 子代理→引擎:`settlement.json` = `{"verdict":..., "evidence": ...}`(同极小 JSON);文件为唯一交付通道。
- 子代理完不成写文件:引擎按"已完成但未交付"结算 `inconclusive → needs_human`(不过度等待)。
## 4. 判据流转
- 程序化:判据=脚本代码(词表/阈值/逻辑全内置);更新判据=改脚本,不改图。
- agentic:判据=instruction 文本;更新=改一句话。
- 引擎:不校验参数形状、不拼接骨架、不声明证据类型。
## 5. 结算与失败语义(保留)
- 叶子 state:pass→success / fail→failure / inconclusive→needs_human。
- composite:completion AST + contains(fatal/tolerable/degrade)结算;**整体断言的结果并入该节点最终状态**(断言被跳过/无法判 = 按 inconclusive 处理)。
- 根(hard):success/failure/partial_success(仅 allowPartialRoot)/needs_replan/infeasible/cancelled。
## 6. 增量与继承
- 判定锚点 = **对象捕获 hash + 判据身份(脚本名+脚本文件自身 hash / instruction 全文 hash)**。
- 双匹配且 prior 同契约 → `inherited`;否则重验。
## 7. 与旧版(v0.2)兼容
- **正向兼容不承诺**:v0.2 图/runs 记录=历史档案,不再被 v0.9 工具读取(保留磁盘原样)。
- skill/README/SPEC 同步至 0.9;`schemaVersion: "0.9"`。
## 8. 待办内选项(非阻塞,采用最保守默认)
- 脚本库=仓库 `scripts/`(宿主/owner 可加);注册表=目录枚举(文件名即脚本名,含 `skel/*.sh`+`skel/*.py` 等)。
- agentic 子代理执行可用工具集:全部宿主可用工具(不裁剪)。
