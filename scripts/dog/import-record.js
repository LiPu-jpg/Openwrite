#!/usr/bin/env node
// dsh-dog verifier for a smart-import manifest.

import { readFile } from 'node:fs/promises'

const inputPath = process.argv[2]
if (!inputPath) {
  process.stdout.write(JSON.stringify({ verdict: 'inconclusive', evidence: { error: 'missing input path' } }))
  process.exit(0)
}

try {
  const value = JSON.parse(await readFile(inputPath, 'utf8'))
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('manifest must be an object')
  if (value.recordType !== 'smart-import' || !['completed', 'partial', 'failed'].includes(value.status)) throw new Error('manifest has an invalid status')
  if (!Number.isInteger(value.chapterCount) || !Array.isArray(value.chapters) || value.chapterCount !== value.chapters.length) {
    throw new Error('chapterCount does not match chapters')
  }
  const invalid = value.chapters.some(item => item === null || typeof item !== 'object' || typeof item.target !== 'string' || !item.target.endsWith('.md'))
  if (invalid) throw new Error('manifest contains an invalid chapter target')
  process.stdout.write(JSON.stringify({
    verdict: value.status === 'completed' ? 'pass' : 'fail',
    evidence: {
      importId: value.importId,
      status: value.status,
      error: value.error,
      source: value.source,
      chapterCount: value.chapterCount,
      aiCheck: value.aiCheck,
      construction: value.construction,
    },
  }))
} catch (error) {
  process.stdout.write(JSON.stringify({ verdict: 'fail', evidence: { error: error instanceof Error ? error.message : String(error) } }))
}
