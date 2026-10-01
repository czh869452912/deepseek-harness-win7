/** Run pinned validators over real Object.freeze, not a JS emulator. */
import { it, expect } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { isJsonValue } from '../../reference/packages/core/session/src/json.ts'
import { isRemoteJsonValue } from '../../reference/packages/api/gateway/src/stream-protocol.ts'

it('observes frozen JSON through both source event and Gateway validators', async () => {
  const target = JSON.parse(await readFile('migration/baseline.json', 'utf8')).target_upstream
  expect(execFileSync('git', ['-C', 'reference', 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()).toBe(target)
  expect(execFileSync('git', ['-C', 'reference', 'status', '--short', '--untracked-files=no'], { encoding: 'utf8' }).trim()).toBe('')
  const sourcePaths = ['scripts/oracles/remote-frozen.spec.ts', 'scripts/oracles/vitest.remote-frozen.config.mts',
    'scripts/oracles/vitest.agent-lifecycle.config.mts', 'scripts/oracles/vitest.consumers.config.mts',
    'scripts/oracles/vitest.core.config.mts', 'reference/packages/core/session/src/json.ts',
    'reference/packages/api/gateway/src/stream-protocol.ts']
  const source_sha256: Record<string, string> = {}
  for (const path of sourcePaths) source_sha256[path] = createHash('sha256').update((await readFile(path, 'utf8')).replaceAll('\r\n', '\n')).digest('hex')
  const observations = []
  for (const container of ['object', 'array']) {
    for (const recipe of ['valid-shared', 'negative-zero', 'infinity', 'nan', 'undefined', 'exotic-object', 'exotic-array', 'cycle']) {
      let leaf: any
      switch (recipe) {
        case 'valid-shared': leaf = Object.freeze({ nested: Object.freeze([null, false, '中文', 42]) }); break
        case 'negative-zero': leaf = -0; break
        case 'infinity': leaf = Infinity; break
        case 'nan': leaf = NaN; break
        case 'undefined': leaf = undefined; break
        case 'exotic-object': leaf = new (class Exotic {})(); break
        case 'exotic-array': leaf = new (class Exotic extends Array {})(); break
        case 'cycle': leaf = {}; break
      }
      const value = Object.freeze(container === 'object' ? { first: leaf, second: leaf } : [leaf, leaf])
      if (recipe === 'cycle') leaf.cycle = value
      const row = { container, recipe, session: isJsonValue(value), gateway: isRemoteJsonValue(value) }
      expect(row.session).toBe(recipe === 'valid-shared')
      expect(row.gateway).toBe(row.session)
      observations.push(row)
    }
  }
  if (!process.env.FROZEN_OUTPUT) throw new Error('FROZEN_OUTPUT is required')
  await writeFile(process.env.FROZEN_OUTPUT, JSON.stringify({ target_upstream: target, node: process.version, source_sha256, observations }, null, 2) + '\n')
})
