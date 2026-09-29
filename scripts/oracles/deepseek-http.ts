import { createServer } from 'node:http'
import { DeepSeekAdapter, resolveAdapterOptions } from '../../reference/packages/llm/llm-deepseek/src/index.ts'
import { Context } from '@deepseek-ai/cordis'
import Sessions from '@deepseek-ai/dsh-session'
import * as Retry from '../../reference/packages/llm/llm-retry/src/index.ts'

export async function observeHttp(fixture: any) {
  const requests: any[] = [], accepted: string[] = []
  const reads: any[] = [], uploads: string[] = []
  const controller = new AbortController()
  const mode = fixture.behavior ?? 'success'
  const server = createServer(async (req, res) => {
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    const headers: any = {}
    for (const name of ['authorization', 'x-deepseek-harness-user-id', 'x-deepseek-harness-session-id', 'x-deepseek-harness-compact']) {
      if (req.headers[name] !== undefined) headers[name] = req.headers[name]
    }
    requests.push({body, headers})
    if (mode === 'cancel' || mode === 'idle') {
      if (mode === 'cancel') controller.abort('fixture cancellation')
      return
    }
    const status = fixture.statuses?.[Math.min(requests.length - 1, fixture.statuses.length - 1)] ?? fixture.status ?? 200
    const payload = status === 200
      ? fixture.sse ?? 'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
      : JSON.stringify({error: fixture.error ?? {message: 'failed'}})
    res.writeHead(status, {'Content-Type': status === 200 ? 'text/event-stream' : 'application/json', ...fixture.headers})
    res.end(payload)
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as any).port
  const adapter = new DeepSeekAdapter({options: () => resolveAdapterOptions({...fixture.config, baseURL: `http://127.0.0.1:${port}`, streamIdleTimeoutMs: mode === 'idle' ? 150 : 3000}),
    resolveApiKey: async () => 'fixture-key', resolveUserId: () => 'fixture-user' as any,
    resolveAttachments: () => fixture.images ? {readImageRequest: async (ref: any, policy: any) => {
      reads.push({id: ref.attachmentId, policy})
      return {attachment: ref, variantId: ref.attachmentId, data: new Uint8Array(ref.bytes),
        mediaType: ref.mediaType, bytes: ref.bytes, width: ref.width, height: ref.height,
        depth: 'uchar', space: 'srgb', hasAlpha: true}
    }, imageHostPath: () => undefined} as any : undefined,
    resolveFiles: () => ({ensureUploaded: async (version: any) => {
      uploads.push(version.attachment.attachmentId)
      if (fixture.filesFail && uploads.length >= fixture.filesFail) throw new Error('fixture files unavailable')
      return {record: {fileId: `fixture-file-${uploads.length}`}, uploaded: true}
    }}) as any,
    prepareExtensions: async () => ({fields: fixture.extension ? {[fixture.extension === 'collision' ? 'model' : 'fixture_extension']: {version: 1}} : {},
      accept: async () => { if (fixture.extension) accepted.push('accepted'); if (fixture.extension === 'accept-failed') throw new Error('fixture acceptance failed') }}),
  })
  const result: any = {chunks: [], requests, accepted}
  const ctx = new Context()
  let session: any
  if (fixture.retry) {
    await ctx.plugin(Sessions)
    session = ctx.sessions.create('retry-session' as any)
    Retry.apply(ctx)
    result.decisions = []
  }
  if (fixture.images) Object.assign(result, {reads, uploads})
  try {
    for (let attempt = 0; attempt < 8; attempt++) {
      try {
        for await (const chunk of adapter.stream({provider: 'deepseek-official', model: fixture.model ?? 'model',
          messages: fixture.messages ?? [{role: 'user', content: [{type: 'text', text: 'hello'}]}],
          sessionId: 'fixture-session' as any, purpose: 'compaction', signal: controller.signal})) result.chunks.push(chunk)
        break
      } catch (error: any) {
        if (!fixture.retry) throw error
        const decision = await ctx.waterfall('agent/request-error', {agent: {session}, turn: 1, step: 1,
          provider: 'deepseek-official', failure: error.failure, signal: controller.signal,
          retryPolicy: adapter.providerRetryPolicy('deepseek-official')}, async () => undefined)
        result.decisions.push(decision ?? null)
        if (decision?.kind !== 'retry') throw error
      }
    }
  } catch (error: any) {
    result.error = {}
    for (const name of ['code', 'status', 'providerRetryAfterMs', 'requestId']) {
      const value = name === 'code' ? error.code : error.failure?.[name]
      if (value !== undefined) result.error[name] = value
    }
  } finally {
    if (fixture.retry) result.retryEvents = session.events.map((event: any) => {
      const {retryId, failure, ...data} = event.data
      if (failure) { const {message, ...rest} = failure; data.failure = rest }
      return {type: event.type, data}
    })
    await ctx.fiber.dispose()
    server.closeAllConnections()
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
  return result
}
