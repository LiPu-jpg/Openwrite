#!/usr/bin/env node
// dsh-dog verifier for one imported manuscript chapter.

import { readFile } from 'node:fs/promises'

const inputPath = process.argv[2]
if (!inputPath) {
  process.stdout.write(JSON.stringify({ verdict: 'inconclusive', evidence: { error: 'missing input path' } }))
  process.exit(0)
}

try {
  const text = await readFile(inputPath, 'utf8')
  if (!text.trim()) throw new Error('chapter file is empty')
  const heading = text.match(/^#\s+(.+)$/m)?.[1]?.trim() ?? ''
  if (!heading) throw new Error('chapter file has no markdown title')
  process.stdout.write(JSON.stringify({ verdict: 'pass', evidence: { heading, bytes: Buffer.byteLength(text) } }))
} catch (error) {
  process.stdout.write(JSON.stringify({ verdict: 'fail', evidence: { error: error instanceof Error ? error.message : String(error) } }))
}
