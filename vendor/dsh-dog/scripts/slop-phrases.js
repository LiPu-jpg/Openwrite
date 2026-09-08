#!/usr/bin/env node
// DoG v0.9 programmatic kernel: AI-slop phrase gate.
// Usage: slop-phrases.js <inputPath>
// Verdict: fail if the object contains any built-in AI-slop phrase; otherwise pass.
// Evidence: list of matched phrases with counts (free-form, decided by this script).

const { readFileSync } = require('node:fs')

const SLOP_PHRASES = [
  '值得一提的是', '不仅如此', '总而言之', '综上所述', '横空出世',
  '在...的今天', '全新的工作方式', '前所未有的', '承上启下',
  '不难看出', '与此同时', '毫无疑问', '赋能', '护城河',
  '落地生根', '生机勃勃', '我们坚信', '未来已来', '值得信赖',
  '谱写', '携手并肩', '抢占先机', '多赢', '生态闭环',
]

function main() {
  const inputPath = process.argv[2]
  if (!inputPath) throw new Error('missing input path argument')
  const text = readFileSync(inputPath, 'utf8')
  const matches = {}
  for (const phrase of SLOP_PHRASES) {
    let count = 0
    let from = 0
    const needle = phrase.replace('...', '')
    let idx = needle.length === 0 ? -1 : text.indexOf(needle)
    while (idx !== -1) {
      count += 1
      from = idx + needle.length
      idx = text.indexOf(needle, from)
    }
    if (count > 0) matches[phrase] = count
  }
  const verdict = Object.keys(matches).length === 0 ? 'pass' : 'fail'
  process.stdout.write(JSON.stringify({
    verdict,
    evidence: Object.keys(matches).length === 0
      ? { outcome: 'no AI-slop phrases found', matched: 0 }
      : { matched: matches },
  }))
}

main()
