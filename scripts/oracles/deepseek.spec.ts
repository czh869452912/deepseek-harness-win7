import { it, expect } from 'vitest'
import { readFileSync, writeFileSync } from 'node:fs'
import { serializeRequest } from '../../reference/packages/llm/llm-deepseek/src/serialize.ts'
import { parseSse } from '../../reference/packages/llm/llm-deepseek/src/sse.ts'
import { translate, mapUsage } from '../../reference/packages/llm/llm-deepseek/src/translate.ts'
import { DeepSeekAdapter, resolveAdapterOptions } from '../../reference/packages/llm/llm-deepseek/src/index.ts'
import { observeHttp } from './deepseek-http.ts'
import { observeFiles } from './deepseek-files.ts'
import { observeSettings } from './deepseek-settings.ts'

it('records actual pinned DeepSeek boundary observations', async () => {
  const fixtures = JSON.parse(readFileSync('scripts/oracles/deepseek-fixtures.json', 'utf8'))
  const rows: any[] = []
  for (const fixture of fixtures) {
    const row: any = { id: fixture.id }
    if (fixture.kind === 'config') {
      try {
        const value = resolveAdapterOptions(fixture.config, new Map(Object.entries(fixture.environment ?? {}).map(([key, value]) => [key, {value}])) as any)
        const {defaults, filePolicy, ...rest} = value
        row.value = {...rest, ...defaults, fileExpiresAfterSeconds: filePolicy.expiresAfterSeconds,
          fileRefreshMarginSeconds: filePolicy.refreshMarginSeconds, fileQuotaCleanupBatch: filePolicy.quotaCleanupBatch}
      } catch { row.error = {code: 'CONFIG_REJECTED'} }
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
          for (let i = 0; i < bytes.length; i += fixture.stride) controller.enqueue(bytes.slice(i, i + fixture.stride))
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
      row.error = { code: error.code ?? error.name }
    }
    rows.push(row)
  }
  expect(rows.length).toBe(fixtures.length)
  writeFileSync(process.env.DEEPSEEK_OUTPUT!, JSON.stringify(rows, null, 2))
})
