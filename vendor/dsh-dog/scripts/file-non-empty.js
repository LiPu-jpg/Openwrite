#!/usr/bin/env node
// DoG v0.9 programmatic kernel: object non-empty check.
// Usage: file-non-empty.js <inputPath>
const { statSync } = require('node:fs')
const inputPath = process.argv[2]
if (!inputPath) throw new Error('missing input path argument')
const s = statSync(inputPath)
process.stdout.write(JSON.stringify(
  s.size > 0
    ? { verdict: 'pass', evidence: { outcome: 'object is non-empty', bytes: s.size } }
    : { verdict: 'fail', evidence: { outcome: 'object is empty', bytes: 0 } },
))
