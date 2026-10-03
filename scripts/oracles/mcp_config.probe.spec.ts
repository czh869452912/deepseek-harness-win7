import { writeFileSync } from 'node:fs'
import { expect, it } from 'vitest'
import { Config } from '../../reference/packages/mcp/mcp-client/src/index.ts'
import { resolveReconnectPolicy } from '../../reference/packages/mcp/mcp-client/src/connection.ts'

it('observes canonical configuration and direct reconnect resolution', () => {
  const observations = []
  for (const transport of ['stdio', 'streamable-http']) {
    const baseline = {transport, serverName: 'controlled', ...(transport === 'stdio' ? {command: 'server'} : {url: 'http://localhost'})}
    const inputs = [baseline, {...baseline, unknown: {retained: true}}, {...baseline, reconnect: {}},
      {...baseline, reconnect: {enabled: false, initialDelayMs: 10, maxDelayMs: 20, maxAttempts: 3}}]
    for (const field of ['transport', 'serverName', transport === 'stdio' ? 'command' : 'url',
      transport === 'stdio' ? 'args' : 'headers', 'toolCallTimeoutMs', 'failOnStartupError', 'reconnect']) {
      for (const value of [null, false, 1, 1.5, '', 'invalid?', [], {}, {maxAttempts: 1.5}, {maxAttempts: 9007199254740992}]) inputs.push({...baseline, [field]: value})
      const missing = {...baseline}
      delete missing[field]
      inputs.push(missing)
    }
    for (const input of inputs) {
      let result
      try {result = {data: Config(input as any)}}
      catch (error: any) {result = {name: error.name, message: error.message}}
      observations.push({kind: 'config', input, result})
    }
  }
  for (const input of [undefined, {}, null, {enabled: null}, {enabled: 'configured'}, {initialDelayMs: null},
    {maxDelayMs: null}, {maxAttempts: null}, {unknown: 1}, {initialDelayMs: true},
    {maxAttempts: 3}, {maxAttempts: 1.5}, {initialDelayMs: 0}, {initialDelayMs: 2, maxDelayMs: 1}]) {
    let result
    try {result = {data: resolveReconnectPolicy(input as any, 'controlled')}}
    catch (error: any) {result = {message: error.message}}
    observations.push({kind: 'policy', input, result})
  }
  expect(observations.length).toBeGreaterThan(160)
  writeFileSync(process.env.MCP_CONFIG_OUTPUT!, JSON.stringify(observations, null, 2) + '\n')
})
