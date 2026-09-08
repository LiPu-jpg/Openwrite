---
name: dog-v02-agentic-ci
description: 当一个目标是非形式化的、没有唯一判准的"大目标"时使用(例:"做一份高质量 PPT""写一篇真正的好文章""写一份可读性强的复盘报告")——这种目标不能直接判断"做到了没",需要:①把它拆成多个可以单独评看子目标(子目标本身也大多是非形式化的语义目标——好坏仍要靠判断力,所以由子代理 agentic 判定;只有少数能精确成规则的才用脚本 programmatic);②系统逐项验证;③汇总。效果:得到质量门禁报告——每个子目标通过/不通过/需要人看 + 证据,以及总体结论与失败原因。
license: MIT
metadata:
  author: dsh-dog
  version: "1.2.0"
---

# DoG(DAG of Goals)使用说明

> DoG = **DAG of Goals**(目标的有向无环图):把一个大目标拆成一棵"目标树",每个小目标可以被单独判定,系统逐项判定后汇总。
> 本说明对应 **dsh-dog v1.2.0**(协议 schemaVersion `0.9`);协议字段如下文所述,产品版本演进不改协议号。
> **需要完整操作手册(全部工具字段、状态语义、错误诊断、最佳实践)请读 `docs/agent-guide.md`。**

## 0. 什么时候使用这个 skill(什么时候不用)

**用**:你的任务目标是一句"非形式化"的话——"做得高不高/好不好"没有唯一判准,不能一眼说"做到了":
- "做一份高质量的答辩 PPT"
- "写一篇真正有质量的文章"(不是字数够、没有错别字那种)
- "重写一段可读性强的说明"

**不用**:能一条规则直接判断的("运行测试""改这个文件名")。

**判断口诀**:如果"我不能直接判断它完成没完成,需要'看'才能说好坏"——就是它。

**这条 skil 的效果**:把"做得怎么样"变成"逐项验收":系统给出每个子目标的判定+证据,以及"全局过没过、哪项不过、为什么"。

## 1. 本质(别当它是"检查清单")

**一个非形式化的大目标,拆成多个同样可以是非形式化的子目标;其中绝大多数要靠判断力(审美、理解、语义)来评——子代理 agentic 判定;只有少数能精确成规则的(文件存在、词表命中、页数)才用程序化脚本;系统逐项验证后汇总成结论与证据。**
- **子目标不要求"形式化"**:好坏仍可能要靠"看"才能定(如"这一段有没有思想""第 3 页是否协调")——这正是为什么它们由 agentic 判定;无法自动判的进入"需要人看"。
- **分解不改变本质**:总目标非形式化,子目标也大多非形式化;所谓"可单独判定"指的是"可以分别去评看",而不是"每条都有精确公式"。
- **判定方式主次分明**:能用判断力/审美/理解力判的(内容质量、可读性、气质、一致性)→ **agentic**;能精确写成规则、用词表、数个数、跑工具判的 → **programmatic**(少数、辅助)。
- **铁律:任何一个节点下面,不可能全都是程序化节点。** 如果整棵子树都只靠精确规则,那它就是一个纯规则集,不需要 DoG——DoG 存在的意义就是把"不能精确判定"的目标拆成"靠判断力逐项评看";所以**每个分支/每棵子树都必须有 agentic(判断力)参与**。见到"想全部用脚本判"的部分,那部分不属于 DoG(或应改为 agentic 一句判据)。
- 没有第二种判定方式;不要给子目标设计"参数模板/校验器类型/证据格式"——那都不存在。

## 2. 图(完整定义)

图 = 一个 JSON 对象(你写,系统验)。顶层字段:

| 字段 | 类型 | 必须 | 含义 |
|---|---|---|---|
| `schemaVersion` | 字符串 | ✔ | 固定 `"0.9"` |
| `id` | 字符串 | ✔ | 图的名字(英文/数字/._-) |
| `root` | 字符串 | ✔ | 总目标节点名(必须是 `nodes` 里的一个;必须"hard") |
| `nodes` | 对象 | ✔ | 所有子目标(键=节点名;值=节点定义,见下) |
| `contains` | 数组 | ✔ | "归属与优先级"边,每一项见下 |
| `dependsOn` | 数组 | ✔ | "先后"边(可空 `[]`):**`source` 依赖 `target`**——source 等 target 完成才开始(注意方向:让哪项先跑,就把哪项放 target) |

### 节点(`nodes` 的每个值):两种类型

**`leaf` —— 子目标(一个可单独判定的检查)**:
| 字段 | 类型 | 必须 | 含义 |
|---|---|---|---|
| `kind` | 枚举 | ✔ | `"leaf"` |
| `title` | 字符串 | ✔ | 给人看的名字 |
| `constraint` | 枚举 | ✔ | `"hard"` 必须满足;`"soft"` 不满足也不妨碍 |
| `target` | 字符串 | ✔ | 判定对象:**工作区内的相对路径**(单文件或一个目录,目录会被系统自动打包) |
| `verifier` | 对象 | ✔ | 怎么判,二选一(见下节) |

**`composite` —— 汇总/分组目标(把若干子目标组合)**:
| 字段 | 类型 | 必须 | 含义 |
|---|---|---|---|
| `kind` | 枚举 | ✔ | `"composite"` |
| `title` / `constraint` / `target` | | ✔ | 同 leaf |
| `completion` | 对象 | ✔ | 子目标怎么组合:见下 |
| `verifier` | 对象 | ✘(可选) | **整体断言**:子目标全都判完后,对整组再判一次(比如"每页都过了,但整份 deck 风格不统一"——这种只能整体看)。写法与 leaf 的 verifier 完全相同 |

### `verifier`(怎么判)——只有两种

> **主体是 agentic**(子目标大多语义、靠判断力);programmatic 只是少数"能精确写成规则"的辅助。且**每个复合节点之下必须有 agentic 参与**(见 §1 铁律)。

```jsonc
// A 让脚本精确定规则(programmatic)
{ "mode": "programmatic", "script": "slop-phrases" }
// script = 宿主脚本库里的脚本名;判据全在脚本里,脚本收到对象路径,
// 输出 {"verdict": "pass|fail|inconclusive", "evidence": <任意>}

// B 让子代理用自己的判断力(agentic)★ 大部分子目标用这个
{ "mode": "agentic", "instruction": "检查……;你自己决定怎么查,给结论和证据。" }
// instruction 就是判定标准,一句话自然语言;子代理自主决定方法/证据,无模板
```

### `completion`(子目标怎么组合)

```jsonc
{ "op": "all",     "items": [{ "op": "ref", "id": "A" }, { "op": "ref", "id": "B" }] }   // 全部通过
{ "op": "any",     "items": [...] }     // 至少一个通过
{ "op": "atLeast", "count": 2, "items": [...] }   // 至少 2 个通过
{ "op": "not",     "item": { "op": "ref", "id": "A" } }   // A 不通过才算通过
{ "op": "ref",     "id": "A" }          // 等同于单引用 A
```

### `contains` 每一项

```jsonc
{ "parent": "root", "child": "A", "required": true, "failure": "fatal" }
// parent/child:节点名;required: 是否必要;
// failure: "fatal" 失败=全局失败;"tolerable" 失败只算部分问题;
//          "degrade" 失败时换成 degradeTo 指定的备选子目标继续
```

## 3. 完整示例一:写一篇"真正有质量"的文章

四维拆法(每个维度一个 agentic 子目标——因为都要判断力;**程序化只做辅助提示**):

```jsonc
{
  "schemaVersion": "0.9",
  "id": "article-quality",
  "root": "root",
  "nodes": {
    "root": {
      "kind": "composite", "title": "文章质量门禁", "constraint": "hard", "target": "article.md",
      "completion": { "op": "all", "items": [
        { "op": "ref", "id": "no-slop" }, { "op": "ref", "id": "dense-fun" },
        { "op": "ref", "id": "readable" }, { "op": "ref", "id": "human-qual" }
      ] },
      "verifier": { "mode": "agentic",
        "instruction": "把整篇作为整体读一遍:即使每个维度都单独通过,作为一篇完整文章它是否成立(从头到尾通顺、有立意、结尾收得住)?给结论与证据。" }
    },
    "no-slop": { "kind": "leaf", "title": "AI-slop 味", "constraint": "hard", "target": "article.md",
      "verifier": { "mode": "agentic",
        "instruction": "检查是否有 AI 味儿:模板腔('在…的今天''值得一提的是''总而言之'),'不是X,而是Y'式转折,空口号(全新工作方式/未来基石),模糊词(很多/显著),空洞句(删掉不改变意思的句子)。逐句判定,给证据。" } },
    "dense-fun": { "kind": "leaf", "title": "信息密度与趣味", "constraint": "hard", "target": "article.md",
      "verifier": { "mode": "agentic",
        "instruction": "检查信息密度与趣味:每一段是否有独立思想(一个主张+证据/实例),是否只是复述堆字;是否旁征博引(引用/数据/类比/反例,而非自说自话);有没有'删掉整段也不损失'的废话段。逐段判定,给证据。" } },
    "readable": { "kind": "leaf", "title": "易懂、符合认知规律", "constraint": "hard", "target": "article.md",
      "verifier": { "mode": "agentic",
        "instruction": "以只懂基础概念的读者视角检查:生僻概念/缩写是否先定义后使用;段与段之间是否有'桥'(承接/转折),有无硬跳;是否先提到已有成果/常识、再自然引申到新东西;有没有跳跃或含糊的地方。给证据。" } },
    "human-qual": { "kind": "leaf", "title": "人类质感", "constraint": "hard", "target": "article.md",
      "verifier": { "mode": "agentic",
        "instruction": "检查是否像人类作者的高质量文本:句式长短交替、每段开头不同构(不是千篇一律的'主题句+例子')、有立场有判断、具体细节而非抽象套话。给证据。" } },
    "phrase-hint": { "kind": "leaf", "title": "模板词提示(辅助)", "constraint": "soft", "target": "article.md",
      "verifier": { "mode": "programmatic", "script": "slop-phrases" } }
  },
  "contains": [
    { "parent": "root", "child": "no-slop",     "required": true, "failure": "fatal" },
    { "parent": "root", "child": "dense-fun",   "required": true, "failure": "fatal" },
    { "parent": "root", "child": "readable",    "required": true, "failure": "fatal" },
    { "parent": "root", "child": "human-qual",  "required": true, "failure": "fatal" },
    { "parent": "root", "child": "phrase-hint", "required": false, "failure": "tolerable" }
  ],
  "dependsOn": []
}
```

## 4. 完整示例二:做一份"高质量答辩 PPT"

页级拆法(文件先存在(程序化)→ 每一页一个 agentic 子目标(渲染后看图判)→ 根做整体一致性断言):

```jsonc
{
  "schemaVersion": "0.9",
  "id": "deck-quality",
  "root": "root",
  "nodes": {
    "root": {
      "kind": "composite", "title": "PPT 质量门禁", "constraint": "hard", "target": "deck.pptx",
      "completion": { "op": "all", "items": [
        { "op": "ref", "id": "deck-exists" },
        { "op": "ref", "id": "slide-1" }, { "op": "ref", "id": "slide-2" },
        { "op": "ref", "id": "slide-3" }, { "op": "ref", "id": "slide-4" },
        { "op": "ref", "id": "slide-5" }, { "op": "ref", "id": "slide-6" }
      ] },
      "verifier": { "mode": "agentic",
        "instruction": "整份 deck 作为整体检查一遍:各页之间风格(字体/配色/版式)是否统一,内容是否连贯成篇,有无某页孤零零/与整体割裂。给结论与证据。" }
    },
    "deck-exists": { "kind": "leaf", "title": "文件存在且非空", "constraint": "hard", "target": "deck.pptx",
      "verifier": { "mode": "programmatic", "script": "file-non-empty" } },
    "slide-1": { "kind": "leaf", "title": "第 1 页可读无遮挡", "constraint": "hard", "target": "deck.pptx",
      "verifier": { "mode": "agentic",
        "instruction": "看第 1 页:标题/正文/图表是否互相遮挡或截断、是否溢出页面边缘、信息是否完整可读。把它渲染成图来看,给证据。" } },
    "slide-2": { "kind": "leaf", "title": "第 2 页可读无遮挡", "constraint": "hard", "target": "deck.pptx",
      "verifier": { "mode": "agentic",
        "instruction": "看第 2 页:标题/正文/图表是否互相遮挡或截断、是否溢出页面边缘、信息是否完整可读。把它渲染成图来看,给证据。" } },
    "slide-3": { "kind": "leaf", "title": "第 3 页可读无遮挡", "constraint": "hard", "target": "deck.pptx",
      "verifier": { "mode": "agentic",
        "instruction": "看第 3 页:标题/正文/图表是否互相遮挡或截断、是否溢出页面边缘、信息是否完整可读。把它渲染成图来看,给证据。" } },
    "slide-4": { "kind": "leaf", "title": "第 4 页可读无遮挡", "constraint": "hard", "target": "deck.pptx",
      "verifier": { "mode": "agentic",
        "instruction": "看第 4 页:标题/正文/图表是否互相遮挡或截断、是否溢出页面边缘、信息是否完整可读。把它渲染成图来看,给证据。" } },
    "slide-5": { "kind": "leaf", "title": "第 5 页可读无遮挡", "constraint": "hard", "target": "deck.pptx",
      "verifier": { "mode": "agentic",
        "instruction": "看第 5 页:标题/正文/图表是否互相遮挡或截断、是否溢出页面边缘、信息是否完整可读。把它渲染成图来看,给证据。" } },
    "slide-6": { "kind": "leaf", "title": "第 6 页可读无遮挡", "constraint": "hard", "target": "deck.pptx",
      "verifier": { "mode": "agentic",
        "instruction": "看第 6 页:标题/正文/图表是否互相遮挡或截断、是否溢出页面边缘、信息是否完整可读。把它渲染成图来看,给证据。" } }
  },
  "contains": [
    { "parent": "root", "child": "deck-exists", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "slide-1", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "slide-2", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "slide-3", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "slide-4", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "slide-5", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "slide-6", "required": true, "failure": "fatal" }
  ],
  "dependsOn": [ { "source": "slide-1", "target": "deck-exists" } ]
}
```

## 5. 怎么让它跑

1. `dog_validate`:`{ graph: <图> }`——只检查对错;
2. `dog_create`:`{ graph: <同样的图> }`——校验后定稿并**固定对象**(文件被记一份;目录被打包);返回 `graphId`;
3. `dog_run`:`{ graphId: "…" }`——开始,立即返回 running;
4. `dog_wait` / `dog_status` 反复调用,直到不再是 running,读报告。

## 6. 结果里每个状态是什么意思

| 状态 | 什么意思 |
|---|---|
| `success` | 该项通过 |
| `failure` | 该项不通过 |
| `needs_human` | 无法自动判定(证据不足/子代理没写出结论)——需要人看 |
| `inherited` | 对象和判定标准都没变,直接复用了上次的结果 |
| 根:`needs_replan` | 有子目标"需要人看",总判为"需要重新定判据/人工参与" |
| 根:`partial_success` | 部分通过(仅当配置允许) |

## 7. 常见错误

1. `target` 用了绝对路径 → 拒绝;必须是工作区(见 §8)内**相对路径**;
2. **把整棵子树写成全程序化 → 那不是 DoG。** 每个复合节点之下必须有 agentic(判断力)成分;全规则的部分直接交给普通 CI/脚本即可,不要放进图。
3. `verifier` 写了 `mode/script/instruction` 以外的字段(id/version/参数模板) → 不存在,会报错;
4. 给 leaf 忘写 `verifier`,或给节点忘写 `target`,或 root 不是 `constraint: "hard"` → `dog_validate` 拦;
5. 想让"程序化脚本直接判"——必须先有已有脚本(`slop-phrases` / `file-non-empty` 是带的;要新规则要么宿主加脚本,要么换 agentic 一句话);
6. 误以为"某个子目标 agentic 判不了"——不:判断力、审美、理解力都能交给 agentic 子代理,它自己想办法;无法自动判的会进入"需要人看",这是设计内的兜底。
7. 改变判定标准 = 改脚本 / 改那句话 + 重新 `dog_create`(会得到新图);不要原地改旧图复用。
8. 判据里出现"具体轮次/内部 id/特定模型名"这类**细枝末节** → verifier 无从判、也无从复用;判据只写本质维度(见 §9.2)。
9. 判据写得具体到"第 17 页要改什么" → 这既违背上下文隔离(引导 verifier),也违背"抽象规则"红线(见 §9.2)。

## 8. 宿主维护(模型不用动)

- 工作区根(对象来源):`~/.dsh/settings.yaml` 的 `dog.workspaceRoot`;
- 脚本库:`~/.dsh/dog/scripts/`(文件即脚本;脚本输出 `{"verdict":…}`);
- 图里只写相对路径与脚本名;配置由宿主改、改后重启。

## 9. 纪律与实战教训(务必遵守)

> 每条都来自真实协作中的"挨骂修正"——写图/执行/汇报前先过一遍。

### 9.1 范围与授权
- **只做明确指派的范围**。用户说"只做这些/立即停止"就执行;不扩展、不顺手加做、不恢复已叫停的事项。
- **未经用户批准,不写/不提交/不推送任何报告或产物**;用户要看方案/图 → 先把方案、图或清单给用户过目,**等批准**再 dog_create/dog_run。
- 用户给的精确指令(如"直接搜这个 skill 名")→ **照做,不要自作主张改写**;你觉得有更好的,先说明,由用户定。

### 9.2 判据的抽象层(上下文隔离红线)
- **只写抽象规则,不写与当前对象内容相关的具体指导/方向**。判据必须**可复用、不引导 verifier**——verifier 只有判据和对象,不能被主 agent 的倾向污染(否则等于替它做判断,违背上下文隔离)。
- 叶子粒度:**简单判据不要拆**(拆了审查者反而因信息不足无法判);**也不要细枝末节**(具体轮次、临时命名、特定模型名如 gpt-4 这类)——判据是**本质维度**,持续可复用。
- **判据覆盖要完整**:新版本不得比旧版少检查面(用户会问"为什么少了");减少只允许抽象化合并,不允许丢失。

### 9.3 判据措辞(歧义与"找全")
- 避免"存在任一……"这类措辞(会让执行者以为找一处就够)。**fail 逻辑 = 有一处不符合即 fail**;同时要求"为了迭代,尽量全部找到并列出"。
- 不要缩信息到 verifier 无法确认的程度:该引用完整规范(一整份文件/一个目录)就**直接作为对象**,不要自定义删减。
- 不确定/需要背景 → 从**源头文件**读(赛题、写作规范、答疑文档),不要"假装知道"或按猜测写判据。

### 9.4 表达与事实
- **事实性错误不可接受**(名称/数字/章节/模型名都要核对;出现"gpt-4 这种完全错误"即零容忍)。
- 讲给人听时**分层**:"最简单、最人话、大二 CS 能懂"作为理解门槛;该用图说明的地方用图。
- 汇报/产物**完整体现用户所做的工作**(负责人部分都要体现),不因"不重要"省略。
- 文件/产物**类型自称要准确**(是 Markdown 说 markdown,是 JSON 说 JSON)。
