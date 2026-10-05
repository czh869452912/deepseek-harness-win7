import { expect, it } from 'vitest'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { observeHttp } from './deepseek_error_http.ts'

it('captures complete actual DeepSeek local HTTP failure graphs', async () => {
  const sourceCommit = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
  expect(process.version).toBe('v22.22.2')
  expect(execFileSync('git', ['-C', 'reference', 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim()).toBe(sourceCommit)
  expect(execFileSync('git', ['-C', 'reference', 'status', '--porcelain'], {encoding: 'utf8'}).trim()).toBe('')
  const paths = [
    'reference/packages/llm/llm-deepseek/src/index.ts', 'reference/packages/llm/llm-deepseek/src/adapter.ts',
    'reference/packages/llm/llm-deepseek/src/translate.ts', 'reference/packages/llm/llm-deepseek/src/sse.ts',
    'scripts/oracles/deepseek_error_http.ts',
    'scripts/oracles/deepseek_error.probe.spec.ts',
    'scripts/oracles/vitest.deepseek-error-probe.config.mts',
    'scripts/oracles/deepseek-error-fixtures.json',
    'scripts/oracles/vitest.deepseek-probe.config.mts', 'migration/modules.json',
  ]
  const inputs = Object.fromEntries(paths.map(path => [path, createHash('sha256').update(readFileSync(path)).digest('hex')]))
  const fixtures = JSON.parse(readFileSync('scripts/oracles/deepseek-error-fixtures.json', 'utf8'))
  expect(fixtures).toHaveLength(24)
  expect(new Set(fixtures.map((fixture: any) => fixture.id)).size).toBe(24)
  const rows = []
  for (const fixture of fixtures) rows.push(await observeHttp(fixture))
  expect(Object.fromEntries(paths.map(path => [path, createHash('sha256').update(readFileSync(path)).digest('hex')]))).toEqual(inputs)
  writeFileSync(process.env.DSH_DEEPSEEK_ERROR_OUTPUT!, JSON.stringify({sourceCommit, node: process.version, inputs, rows}, null, 2) + '\n', {encoding: 'utf8', flag: 'wx'})
}, 30000)
