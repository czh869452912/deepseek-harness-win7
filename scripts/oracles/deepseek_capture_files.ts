import { createServer } from 'node:http'
import { DeepSeekFilesClient, isFilesQuotaError } from '../../reference/packages/llm/llm-deepseek/src/files-api.ts'

export async function observeFiles(fixture: any) {
  const requests: any[] = []
  const server = createServer(async (req, res) => {
    const chunks = []
    for await (const chunk of req) chunks.push(chunk)
    const request: any = {method: req.method, path: req.url, authorization: req.headers.authorization}
    if (req.method === 'POST') {
      const form = await new Response(Buffer.concat(chunks), {headers: {'content-type': req.headers['content-type']!}}).formData()
      request.form = {}
      for (const [name, value] of form.entries()) request.form[name] = typeof value === 'string' ? value
        : {filename: value.name, mediaType: value.type, bytes: Array.from(new Uint8Array(await value.arrayBuffer()))}
    }
    requests.push(request)
    res.writeHead(fixture.status ?? 200, {'Content-Type': 'application/json'})
    res.end(JSON.stringify(fixture.response))
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const client = new DeepSeekFilesClient({baseURL: `http://127.0.0.1:${(server.address() as any).port}`, apiKey: 'fixture-key'})
  const result: any = {originPort: (server.address() as any).port, origin: {host:(server.address() as any).address,port:(server.address() as any).port,baseURL:`http://127.0.0.1:${(server.address() as any).port}`}, requests}
  try {
    if (fixture.operation === 'upload') result.value = await client.upload({data: Uint8Array.of(1, 2, 3), mediaType: 'image/png', filename: 'fixture.png', expiresAfterSeconds: fixture.expiry ?? 3600})
    if (fixture.operation === 'retrieve') result.value = await client.retrieve(fixture.fileId)
    if (fixture.operation === 'list') result.value = await client.list(fixture.options)
    if (fixture.operation === 'delete') { await client.delete(fixture.fileId); result.value = null }
  } catch (error: any) {
    result.error = {code: error.code ?? error.name, name: error.name, message: error.message, quota: isFilesQuotaError(error), ...(error.failure ? {failure: error.failure} : {})}
    if (error.failure?.status !== undefined) result.error.status = error.failure.status
  } finally {
    server.closeAllConnections()
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
  return result
}
