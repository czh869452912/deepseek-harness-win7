import { createServer } from 'node:http'
import { DeepSeekAdapter, resolveAdapterOptions } from '../../reference/packages/llm/llm-deepseek/src/index.ts'

export async function observeHttp(fixture: any) {
  const requests: any[] = [], accepted: string[] = []
  const controller = new AbortController()
  const mode = fixture.behavior ?? 'success'
  const server = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    const headers: any = {}
    for (const name of ['authorization', 'x-deepseek-harness-user-id', 'x-deepseek-harness-session-id', 'x-deepseek-harness-compact']) {
      if (request.headers[name] !== undefined) headers[name] = request.headers[name]
    }
    requests.push({body, headers})
    if (mode === 'cancel' || mode === 'idle') {
      if (mode === 'cancel') controller.abort('fixture cancellation')
      return
    }
    const status = fixture.status ?? 200
    const payload = status === 200
      ? fixture.sse ?? 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
      : JSON.stringify({error: fixture.error ?? {message: 'failed'}})
    response.writeHead(status, {'Content-Type': status === 200 ? 'text/event-stream' : 'application/json', ...fixture.headers})
    response.end(payload)
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as any).port
  const adapter = new DeepSeekAdapter({
    options: () => resolveAdapterOptions({baseURL: `http://127.0.0.1:${port}`, streamIdleTimeoutMs: mode === 'idle' ? (fixture.idleTimeoutMs ?? 150) : 3000}),
    resolveApiKey: async () => 'fixture-key', resolveUserId: () => 'fixture-user' as any,
    prepareExtensions: async () => ({fields: fixture.extension ? {fixture_extension: {version: 1}} : {},
      accept: async () => { if (fixture.extension) {accepted.push('accepted'); throw new Error('fixture acceptance failed')} }}),
  })
  const result: any = {name: fixture.id, chunks: [], requests, accepted}
  try {
    for await (const chunk of adapter.stream({model: 'model', messages: [{role: 'user', content: [{type: 'text', text: 'hello'}]}],
      sessionId: 'fixture-session' as any, purpose: 'compaction', signal: controller.signal})) {
      result.chunks.push(chunk)
    }
  } catch (error: any) {
    if (!error.failure || typeof error.name !== 'string' || typeof error.message !== 'string' || typeof error.code !== 'string') throw error
    result.error = {name: error.name, message: error.message, failure: error.failure, code: error.code}
    for (const name of ['status', 'providerRetryAfterMs', 'requestId']) if (error.failure[name] !== undefined) result.error[name] = error.failure[name]
  } finally {
    server.closeAllConnections()
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
  return result
}
