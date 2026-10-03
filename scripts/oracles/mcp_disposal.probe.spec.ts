import { writeFileSync } from 'node:fs'
import { it, vi } from 'vitest'

const fixture = vi.hoisted(() => ({name: '', trace: [] as any[], clients: [] as any[],
  fetches: 0, entered: undefined as any, connectGate: undefined as any, listGate: undefined as any}))

vi.mock('@modelcontextprotocol/sdk/client/index.js', () => ({Client: class {
  onclose: any
  notify: any
  constructor() {fixture.clients.push(this); fixture.trace.push(['create', fixture.clients.length])}
  setNotificationHandler(_schema: any, callback: any) {this.notify = callback}
  async connect() {
    fixture.trace.push(['connect'])
    if (fixture.name.startsWith('connect-')) {fixture.entered.resolve(); await fixture.connectGate.promise}
  }
  async close() {fixture.trace.push(['close']); this.onclose?.()}
  async request(packet: any) {
    fixture.trace.push(['fetch', packet.method]); fixture.fetches++
    if (fixture.name === 'initial-list' || fixture.fetches > 1) {
      fixture.entered.resolve()
      return await fixture.listGate.promise
    }
    return {tools: [{name: 'old', inputSchema: {type: 'object'}}]}
  }
}}))
vi.mock('@modelcontextprotocol/sdk/client/stdio.js', () => ({StdioClientTransport: class {}}))

import { startConnection } from '../../reference/packages/mcp/mcp-client/src/connection.ts'

it('observes source disposal ownership of connecting and queued tool generations', async () => {
  const rows: any[] = []
  for (const name of ['connect-resolve', 'connect-reject', 'initial-list', 'resync-list', 'resync-reject', 'queued-resync']) {
    Object.assign(fixture, {name, trace: [], clients: [], fetches: 0,
      entered: Promise.withResolvers(), connectGate: Promise.withResolvers(), listGate: Promise.withResolvers()})
    const logs: any[] = []
    const registered = new Set<string>()
    const tools = {register: (definition: any) => {
      fixture.trace.push(['register', definition.name]); registered.add(definition.name)
      return () => {fixture.trace.push(['unregister', definition.name]); registered.delete(definition.name)}
    }}
    const ctx = {tools, get: (key: string) => key === 'tools' ? tools : undefined,
      logger: Object.fromEntries(['warn', 'error', 'info'].map(level => [level, (message: string) => logs.push([level, message])]))}
    const handle = startConnection(ctx as any, {transport: 'stdio', serverName: 'controlled', command: 'unused',
      args: [], env: {}, toolCallTimeoutMs: 60000} as any,
      {enabled: false, initialDelayMs: 1, maxDelayMs: 1000, maxAttempts: 1})
    const notifications: Promise<void>[] = []
    if (name.startsWith('resync-') || name === 'queued-resync') {
      await handle.ready
      notifications.push(fixture.clients[0].notify({method: 'notifications/tools/list_changed'}))
      if (name === 'queued-resync') notifications.push(fixture.clients[0].notify({method: 'notifications/tools/list_changed'}))
    }
    await fixture.entered.promise
    const before = [...registered]
    const disposing = handle.dispose()
    if (name === 'connect-reject') fixture.connectGate.reject(new Error('controlled disposed connect'))
    else fixture.connectGate.resolve()
    if (name === 'resync-reject') fixture.listGate.reject(new Error('controlled disposed fetch'))
    else fixture.listGate.resolve({tools: [{name: 'late', inputSchema: {type: 'object'}}]})
    await disposing
    await Promise.all(notifications)
    const outcome = await handle.ready
    rows.push({name, before, after: [...registered], outcome: outcome.error === undefined ? {} :
      {error: {name: (outcome.error as any).name, message: (outcome.error as any).message}}, trace: fixture.trace, logs})
  }
  writeFileSync(process.env.MCP_DISPOSAL_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
}, 15000)
