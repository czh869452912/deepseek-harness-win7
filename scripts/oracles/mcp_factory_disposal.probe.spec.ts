import { writeFileSync } from 'node:fs'
import { it } from 'vitest'
import { startConnection } from '../../reference/packages/mcp/mcp-client/src/connection.ts'

it('observes actual source SDK factory failure while disposal owns its unclosed client', async () => {
  const logs: any[] = []
  const ctx = {get: () => undefined, tools: {register: () => {throw new Error('unexpected registration')}},
    logger: Object.fromEntries(['warn', 'error', 'info'].map(level => [level, (message: string) => logs.push([level, message])]))}
  const handle = startConnection(ctx as any, {transport: 'streamable-http', serverName: 'controlled', url: 'invalid',
    headers: {}, toolCallTimeoutMs: 60000, failOnStartupError: true} as any,
    {enabled: true, initialDelayMs: 1, maxDelayMs: 1000, maxAttempts: 1})
  const disposing = handle.dispose()
  await disposing
  const outcome = await handle.ready
  const error: any = outcome.error
  writeFileSync(process.env.MCP_FACTORY_DISPOSAL_OUTPUT!, JSON.stringify({outcome: {
    name: error.name, message: error.message, code: error.code}, logs}, null, 2) + '\n')
}, 15000)
