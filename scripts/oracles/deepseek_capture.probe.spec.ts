import { it, expect } from 'vitest'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { serializeRequest } from '../../reference/packages/llm/llm-deepseek/src/serialize.ts'
import { parseSse } from '../../reference/packages/llm/llm-deepseek/src/sse.ts'
import { translate, mapUsage } from '../../reference/packages/llm/llm-deepseek/src/translate.ts'
import { DeepSeekAdapter, resolveAdapterOptions } from '../../reference/packages/llm/llm-deepseek/src/index.ts'
import { observeHttp } from './deepseek_capture_http.ts'
import { observeFiles } from './deepseek_capture_files.ts'
import { observeSettings } from './deepseek_capture_settings.ts'

it('records actual pinned DeepSeek boundary observations', async () => {
  expect(process.version).toBe('v22.22.2')
  expect(execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim()).toBe('cd5ef8148158c3a752a658978873241fdf8e2bbc')
  expect(execFileSync('git',['-C','reference','status','--porcelain'],{encoding:'utf8'}).trim()).toBe('')
  const paths = [
  "migration/modules.json",
  "scripts/import_paths.py",
  "reference/packages/llm/llm-deepseek/src/adapter.ts",
  "reference/packages/llm/llm-deepseek/src/files-api.ts",
  "reference/packages/llm/llm-deepseek/src/index.ts",
  "reference/packages/llm/llm-deepseek/src/serialize.ts",
  "reference/packages/llm/llm-deepseek/src/sse.ts",
  "reference/packages/llm/llm-deepseek/src/translate.ts",
  "reference/packages/llm/llm-retry/src/index.ts",
  "reference/packages/llm/llm/src/retry-policy.ts",
  "scripts/oracles/deepseek-fixtures.json",
  "scripts/oracles/deepseek_capture.probe.spec.ts",
  "scripts/oracles/deepseek_capture_files.ts",
  "scripts/oracles/deepseek_capture_http.ts",
  "scripts/oracles/deepseek_capture_settings.ts",
  "scripts/oracles/vitest.deepseek-capture-probe.config.mts",
  "scripts/oracles/vitest.deepseek-probe.config.mts"
]
  const inputs = Object.fromEntries(paths.map(path => [path,createHash('sha256').update(readFileSync(path)).digest('hex')]))
  const fixtures = JSON.parse(readFileSync('scripts/oracles/deepseek-fixtures.json', 'utf8'))
  expect(fixtures).toHaveLength(76)
  expect(new Set(fixtures.map((fixture: any) => fixture.id)).size).toBe(76)
  const rows: any[] = []
  for (const fixture of fixtures) {
    const row: any = { id: fixture.id }
    if (fixture.kind === 'config') {
      try {
        const value = resolveAdapterOptions(fixture.config, new Map(Object.entries(fixture.environment ?? {}).map(([key, value]) => [key, {value}])) as any)
        const {defaults, filePolicy, ...rest} = value
        row.value = {...rest, ...defaults, fileExpiresAfterSeconds: filePolicy.expiresAfterSeconds,
          fileRefreshMarginSeconds: filePolicy.refreshMarginSeconds, fileQuotaCleanupBatch: filePolicy.quotaCleanupBatch}
      } catch (error: any) { row.error = {code: 'CONFIG_REJECTED', name: error.name, message: error.message} }
      rows.push(row)
      continue
    }
    try {
      if (fixture.kind === 'http') row.value = await observeHttp(fixture)
      if (fixture.kind === 'settings') row.value = await observeSettings(fixture)
      if (fixture.kind === 'files') row.value = await observeFiles(fixture)
      if (fixture.kind === 'serialize') row.value = serializeRequest(fixture.options, fixture.defaults)
      if (fixture.kind === 'usage') row.value = mapUsage(fixture.usage)
      if (fixture.kind === 'stream') {
        row.value = []
        const bytes = new TextEncoder().encode(fixture.sse)
        const stream = new ReadableStream({start(controller) {
          for (let index = 0; index < bytes.length; index += fixture.stride) controller.enqueue(bytes.slice(index, index + fixture.stride))
          controller.close()
        }})
        for await (const chunk of translate(parseSse(stream))) row.value.push(chunk)
      }
      if (fixture.kind === 'model') {
        const adapter = new DeepSeekAdapter({options: () => resolveAdapterOptions(fixture.config),
          resolveApiKey: async () => 'fixture', resolveUserId: () => 'fixture' as any,
          prepareExtensions: async () => ({fields: {}, accept: async () => {}})})
        row.value = await adapter.resolveModel('deepseek-official', fixture.model)
      }
    } catch (error: any) {
      row.error = {code: error.code ?? error.name, name: error.name, message: error.message, ...(error.failure ? {failure: error.failure} : {})}
    }
    rows.push(row)
  }
  expect(rows.length).toBe(fixtures.length)
  expect(Object.fromEntries(paths.map(path => [path,createHash('sha256').update(readFileSync(path)).digest('hex')]))).toEqual(inputs)
  writeFileSync(process.env.DSH_DEEPSEEK_CAPTURE_OUTPUT!, JSON.stringify({sourceCommit:'cd5ef8148158c3a752a658978873241fdf8e2bbc',node:process.version,inputs,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
