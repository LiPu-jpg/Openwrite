#!/usr/bin/env node
// dsh-dog verifier for one materialized chapter-delivery stage.

import { readFile } from 'node:fs/promises'

const inputPath = process.argv[2]
if (!inputPath) {
  process.stdout.write(JSON.stringify({ verdict: 'inconclusive', evidence: { error: 'missing input path' } }))
  process.exit(0)
}

try {
  const value = JSON.parse(await readFile(inputPath, 'utf8'))
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('delivery stage must be an object')
  if (!['delivery-stage', 'chapter-delivery'].includes(value.recordType)) throw new Error('record is not a delivery artifact')
  if (!['pass', 'fail', 'inconclusive'].includes(value.verdict)) throw new Error('delivery stage has an invalid verdict')
  process.stdout.write(JSON.stringify({
    verdict: value.verdict,
    evidence: {
      chapterId: value.chapterId,
      stage: value.stage,
      status: value.status ?? (value.readyForDelivery ? 'ready' : 'not_ready'),
      readyForDelivery: value.readyForDelivery,
      ...(value.evidence !== null && typeof value.evidence === 'object' ? value.evidence : {}),
    },
  }))
} catch (error) {
  process.stdout.write(JSON.stringify({
    verdict: 'inconclusive',
    evidence: { error: error instanceof Error ? error.message : String(error) },
  }))
}
