/** Export the registered tool schema without running tools or connecting to Studio. */
import { readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(resolve(root, 'packages/openwrite-bridge/package.json'))
const ts = require('typescript')
const source = ts.createSourceFile('tools.ts', readFileSync(resolve(root, 'packages/openwrite-bridge/src/tools.ts'), 'utf8'), ts.ScriptTarget.Latest, true)
function literal(node) {
  if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node)) return node.text
  if (node.kind === ts.SyntaxKind.TrueKeyword) return true
  if (node.kind === ts.SyntaxKind.FalseKeyword) return false
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) return literal(node.left) + literal(node.right)
  if (ts.isArrayLiteralExpression(node)) return node.elements.map(literal)
  if (ts.isObjectLiteralExpression(node)) return Object.fromEntries(node.properties.map(property => {
    if (!ts.isPropertyAssignment(property)) throw Error(`Unsupported schema: ${property.getText(source)}`)
    return [property.name.text, literal(property.initializer)]
  }))
  throw Error(`Nonliteral schema must be documented explicitly: ${node.getText(source)}`)
}
function walk(node, visit) { visit(node); ts.forEachChild(node, child => { walk(child, visit) }) }
const tools = []
walk(source, node => {
  if (!ts.isCallExpression(node) || node.expression.getText(source) !== 'ctx.tools.register') return
  const definition = node.arguments[0]
  if (!ts.isCallExpression(definition) || definition.expression.getText(source) !== 'defineTool') throw Error('Unknown registration')
  const properties = new Map(definition.arguments[0].properties.map(p => [p.name?.text, p]))
  const calls = new Set()
  walk(properties.get('execute'), child => {
    if (ts.isCallExpression(child)) {
      const expression = child.expression
      calls.add(ts.isPropertyAccessExpression(expression) ? expression.name.text : expression.getText(source))
    }
  })
  const writes = [...calls].filter(name => ['postJson', 'putJson', 'patchJson', 'deleteJson', 'writeFile', 'mkdir'].includes(name))
  // Export and review helpers can also materialize files after a GET.
  const materializes = [...calls].some(name => /^materialize/.test(name) || name === 'deliveryForResponse')
  const effect = writes.length || materializes ? '会提交操作或保存文件；具体取决于 action/参数' : '只读查询（可更新检索缓存）'
  tools.push({ name: literal(properties.get('name').initializer), description: literal(properties.get('description').initializer), parameters: literal(properties.get('parameters').initializer), effect })
})
tools.sort((a, b) => a.name.localeCompare(b.name, 'en'))
if (!tools.length || new Set(tools.map(t => t.name)).size !== tools.length) throw Error('Empty or duplicate tool catalogue')
const cell = value => String(value ?? '').replaceAll('|', '\\|').replaceAll('\n', '<br>')
const lines = [
  '# 小说工具参考', '',
  `本候选共 ${tools.length} 个 novel_* 工具。由 tools.ts 的注册定义生成；说明与参数保留实际 schema 原文，避免手册与接口漂移。用浏览器或编辑器搜索工具名即可定位。`, '',
  '## 先选入口', '',
  '- 看当前作品：`novel_status`；查文件：`novel_doc_read`；看本章输入：`novel_context_preview`。上下文来源与预算见 [上下文槽位](CONTEXT_SLOTS.md)。',
  '- 修改大纲/设定/创作罗盘：先用 `novel_structured_change_plan` 预览并核对；只有作者已明确授权的精确变更才使用兼容的直接写入工具，如 `novel_focus`。',
  '- 正文确认：`novel_manuscript_acceptance {}` 只读查 operation_id，核对影响后用 `novel_manuscript_acceptance_reconcile {"action":"acknowledge","operation_id":"实际返回值","confirm":true}` 确认；这不会补跑结算或审稿。',
  '- 结算缺失：核对目标章节后使用 `novel_settle_backfill {"chapter_ids":["ch_001"],"only_missing":true}`，再查返回任务；会调用模型并写入记忆/运行态资料，不重写正文。不要把 canon 未定论一律解释为缺结算。',
  '- 模型与嵌入：Chat 与 Embedding 档案独立；配置不等于连接成功。`novel_model_test` / `novel_model_embedding_test` 会实际请求提供方，可能计费。',
  '- 写章返回 task_id 后用 `novel_task_get` 查询；取消用 `novel_task_cancel`。超时/网络错误后先查任务与运行，避免重复提交。', '',
  '## 参数和错误', '',
  '必填项是 schema 的静态必填；action 描述里的条件必填也要满足。JSON 参数传对象或数组，不要传 Markdown 代码块。章节 ID 使用 ch_数字。文档写入先读当前 version，大纲变更使用当前 revision；冲突时重读并重新预览。', '',
  '参数错误会在请求前或服务端拒绝并说明原因；服务端错误提供 code/message/status/details/request_id。这里只读/会操作按执行路径保守分类：POST 也可能是预览或查询，GET 后的导出/审稿辅助操作也可能落盘；请同时看 action 和下面的完整说明。', '',
  '## 工具索引', '', '| 工具 | 影响 | 必填参数 |', '| --- | --- | --- |',
  ...tools.map(t => `| [${t.name}](#${t.name}) | ${t.effect} | ${Object.entries(t.parameters).filter(([, p]) => p.required).map(([name]) => '`' + name + '`').join(', ') || '无'} |`), '',
]
for (const tool of tools) {
  lines.push(`## ${tool.name}`, '', tool.description, '', `影响：${tool.effect}。`, '', '| 参数 | 类型 | 必填 | 允许值 / 说明 |', '| --- | --- | --- | --- |')
  for (const [name, spec] of Object.entries(tool.parameters)) lines.push(`| ${name} | ${cell(spec.type)}${spec.items ? '[' + cell(spec.items.type) + ']' : ''} | ${spec.required ? '是' : '否'} | ${cell([spec.enum ? JSON.stringify(spec.enum) : '', spec.description].filter(Boolean).join('；'))} |`)
  if (!Object.keys(tool.parameters).length) lines.push('| 无 | — | — | — |')
  lines.push('')
}
const content = lines.join('\n')
const output = resolve(root, 'docs/TOOLS.md')
if (process.argv.includes('--check')) {
  if (readFileSync(output, 'utf8') !== content) throw Error('docs/TOOLS.md is stale; run node scripts/gen-tools-md.mjs')
  console.log(`Tool reference matches all ${tools.length} registered schemas`)
} else { writeFileSync(output, content); console.log(`Generated ${output} (${tools.length} tools)`) }
