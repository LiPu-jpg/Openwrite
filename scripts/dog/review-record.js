#!/usr/bin/env node
// Programmatic verifier for hierarchical review context/domain/gate/aggregate records.

import { readFile } from 'node:fs/promises'

const inputPath = process.argv[2]
if (!inputPath) {
  process.stdout.write(JSON.stringify({ verdict: 'inconclusive', evidence: { error: 'missing input path' } }))
  process.exit(0)
}

try {
  const value = JSON.parse(await readFile(inputPath, 'utf8'))
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('review record must be an object')
  }
  if (!String(value.recordType ?? '').startsWith('review')) {
    throw new Error('recordType is not a review artifact')
  }
  if (!['pass', 'fail', 'inconclusive'].includes(value.verdict)) {
    throw new Error('review record has an invalid verdict')
  }
  process.stdout.write(JSON.stringify({
    verdict: value.verdict,
    evidence: {
      recordType: value.recordType,
      chapterId: value.chapterId,
      id: value.id,
      status: value.status ?? value.deliveryStatus ?? value.executionStatus,
      qualityScore: value.qualityScore,
      coverage: value.coverage,
      gateStatus: value.gateStatus,
      deliveryStatus: value.deliveryStatus,
      issueCount: Array.isArray(value.issues) ? value.issues.length : value.issueCount,
    },
  }))
} catch (error) {
  process.stdout.write(JSON.stringify({
    verdict: 'inconclusive',
    evidence: { error: error instanceof Error ? error.message : String(error) },
  }))
}
