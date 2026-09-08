# DoG 演示模块

两个可直接投入使用的演示图,对象为 `harness-article.md`(任何你想质检的文本文件,把 `target` 改成你的相对路径即可)。

## 1. `article-quality.graph.json` — 非形式化目标的四维拆解

把"这是一篇真正有质量的好文章"(非形式化、无唯一判准)拆成四个可独立评看的子目标 + 一个根整体断言:

- `no-slop` — AI 味儿(模板腔/空口号/模糊词)
- `dense-fun` — 信息密度与趣味(每段有思想+证据)
- `readable` — 易懂、符合认知规律(定义先行/段间有桥)
- `human-qual` — 人类质感(句式节奏/有立场)
- `root` — 单维都过后,作为一篇**完整文章**是否成立(整体断言)
- `phrase-hint` — 程序化辅助(模板词表脚本,soft/tolerable)

**要演示**:四维全部由 agentic 子代理(独立判断力)判定;程序化只做辅助;根节点整体断言"只降不升"。

## 2. `dog-smoke-multi.graph.json` — 多级 + 混合判定(功能全景)

- **3 层结构**:`root` → `content-group` → 四个 agentic 叶;两个 composite 各带整体断言
- **程序化叶**:`phrase-hint`(slop-phrases)、`file-nonempty`(file-non-empty)——脚本名不带 `.js`
- **依赖边**:`content-group` 依赖 `file-nonempty`(文件检查先于内容组;`source` depends on `target`)
- **失败传播**:任一个 hard 子项失败 → 该组失败 → 根失败;**tolerable** 项不影响根

## 怎么跑(在 dsh web/tui 会话里,工具面:`dog_validate / dog_create / dog_run / dog_wait / dog_status`)

```
1. 把目标文件放在 dog 工作区(settings.yaml → dog.workspaceRoot)
2. dog_validate { graph: <图> }         # 只校验
3. dog_create   { graph: <图> }         # 固定对象副本 + 生成 graphId
4. dog_run      { graphId: "<…>" }      # 开始(后台)
5. dog_status / dog_wait                # 轮询到非 running
6. 面板(Debugger)看每个节点的状态/证据/事件流
```

## 预期行为(engine 语义,可当验收清单)

- agentic 叶:子代理独立判定,证据伴随(`{"verdict", "evidence"}`)
- 程序化叶:立即执行、不排队;输出也是 `{"verdict", "evidence"}`
- 复跑同图(对象+判据不变):已结算叶标记 `inherited`(复用,0 token)
- 子树失败:composite **跳过**自己的整体断言,原因定位到具体子项
- 宿主重启遗留 run:启动即标 `cancelled`(run+goal 级),已结算叶继续可继承
- 面板:节点状态与事件同帧;dependsOn 箭头 = 被依赖者 → 依赖者(执行先后)
