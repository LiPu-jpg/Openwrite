#!/usr/bin/env node
// dsh-dog programmatic verifier for one materialized OpenWrite dimension.

import { readFile } from 'node:fs/promises'

const inputPath = process.argv[2]
if (!inputPath) {
  process.stdout.write(JSON.stringify({ verdict: 'inconclusive', evidence: { error: 'missing input path' } }))
  process.exit(0)
}

try {
  const value = JSON.parse(await readFile(inputPath, 'utf8'))
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('dimension record must be an object')
  }
  const verdict = value.verdict
  if (verdict !== 'pass' && verdict !== 'fail' && verdict !== 'inconclusive') {
    throw new Error('dimension record has an invalid verdict')
  }
  process.stdout.write(JSON.stringify({
    verdict,
    evidence: {
      chapterId: value.chapterId,
      dimension: value.dimension,
      name: value.name,
      issueCount: value.issueCount,
      issues: Array.isArray(value.issues) ? value.issues : [],
    },
  }))
} catch (error) {
  process.stdout.write(JSON.stringify({
    verdict: 'inconclusive',
    evidence: { error: error instanceof Error ? error.message : String(error) },
  }))
}
