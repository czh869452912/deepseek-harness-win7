import { createServer } from 'node:http'
import { streamSimple } from './official/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js'
import { streamSimple as responsesSimple } from './official/node_modules/@earendil-works/pi-ai/dist/api/openai-responses.js'
import { toStreamChunks } from '../../reference/packages/llm/llm-pi-ai/src/stream.ts'

export async function observePiHttp(fixture: any) {
  const requests: any[] = []
  const server = createServer(async (req, res) => {
    const buffers: Buffer[] = []
    for await (const data of req) buffers.push(Buffer.from(data))
    requests.push({path: req.url, authorization: req.headers.authorization,
      body: JSON.parse(Buffer.concat(buffers).toString('utf8'))})
    res.writeHead(fixture.status ?? 200, {'content-type': fixture.status ? 'application/json' : 'text/event-stream'})
    if (fixture.status) res.end(JSON.stringify(fixture.errorBody ?? {error: {message: 'fixture error'}}))
    else {
      for (const frame of fixture.frames) res.write(`data: ${JSON.stringify(frame)}\n\n`)
      if (!fixture.omitDone) res.write('data: [DONE]\n\n')
      res.end()
    }
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  try {
    const address: any = server.address()
    const model = {...fixture.model, baseUrl: `http://127.0.0.1:${address.port}/v1`}
    const source = fixture.kind === 'responses-http' ? responsesSimple : streamSimple
    const events = source(model, fixture.context, {...fixture.options, apiKey: 'oracle', maxRetries: 0, env: {}})
    const chunks: any[] = []
    for await (const chunk of toStreamChunks(events, model.contextWindow)) {
      if (chunk.type === 'finish' && chunk.reason.failure) delete (chunk.reason.failure as any).message
      chunks.push(chunk)
    }
    return {requests, chunks}
  } finally {
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
  }
}
