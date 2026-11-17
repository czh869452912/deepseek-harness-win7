import { readFileSync } from 'node:fs'
import { load } from './rc022_subagent_fixture.mts'
const { repositoryFiles } = await load('packages/boot/plugin-market/src/detail-files.ts')
const { DetailFailure } = await load('packages/util/plugin-detail/src/index.ts')
const saved = globalThis.fetch, rows = []
try {
  for (const fixture of JSON.parse(readFileSync(process.argv[3], 'utf8'))) {
    const calls: any[] = [], signal = new AbortController().signal
    const cache = {
      async isPublic(url: string) { calls.push({ kind: 'public', url }); if (fixture.public === 'offline') throw new DetailFailure('network', 'offline'); return fixture.public },
      async read(url: string, ref: any, path: string, maximum: number) { calls.push({ kind: 'read', url, ref: ref ?? null, path, maximum }); return new TextEncoder().encode('clone') },
      async readme(url: string, ref: any, path: string, maximum: number) { calls.push({ kind: 'readme', url, ref: ref ?? null, path, maximum }); return { path: path+'/README.md', bytes: new TextEncoder().encode('# Clone') } },
    }
    globalThis.fetch = (async (url: string) => {
      calls.push({ kind: 'fetch', url, maximum: 100 })
      const status = fixture.status === 404 && fixture.action === 'readme' && url.includes('/Readme.md') ? 200 : fixture.status
      return new Response(status === 200 ? '# API' : 'missing', { status })
    }) as any
    const files = repositoryFiles(fixture.repository, fixture.commit ?? undefined, { timeoutMs: 1000, lifetime: signal, gitlabHosts: ['gitlab.example'], cache })
    try {
      let value = await files[fixture.action](fixture.path, 100, signal)
      if (value instanceof Uint8Array) value = [...value]
      else if (value !== undefined) value = { ...value, bytes: [...value.bytes] }
      rows.push({ key: files.key, calls, value: value ?? null })
    } catch (error: any) { rows.push({ key: files.key, calls, error: { reason: error.reason ?? null, message: error.message } }) }
  }
} finally { globalThis.fetch = saved }
console.log(JSON.stringify(rows))
