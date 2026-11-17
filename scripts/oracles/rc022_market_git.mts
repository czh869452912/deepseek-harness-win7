import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { load } from './rc022_subagent_fixture.mts'
const { RepositoryCache } = await load('packages/boot/plugin-market/src/repository-cache.ts')
const fixture = JSON.parse(readFileSync(process.argv[3], 'utf8')), { data } = fixture
const signal = new AbortController().signal, dir = join(fixture.root, 'source-cache')
const options = { dir, maxRepositoryBytes: 10*1024*1024, maxCacheBytes: 100*1024*1024,
  timeoutMs: 10000, ttlMs: 60000, transports: ['file'], lifetime: signal, sizePollMs: 1 }
const cache = new RepositoryCache(options), rows = []
const operations = [['read', data.first, 'docs/a b#中.png', 100], ['read', data.first, 'missing', 100],
  ['read', data.first, 'docs', 100], ['read', data.first, 'big.bin', 100], ['readme', undefined, '', 100],
  ['readme', data.first, '', 100], ['readme', data.first, 'docs', 100], ['readme', data.first, 'missing', 100],
  ['read', data.second, 'Readme.md', 100], ['read', data.first, 'big.bin', 4096]]
for (const [action, commit, path, maximum] of operations) {
  try {
    let value = await cache[action](data.url, commit, path, maximum, signal)
    if (value instanceof Uint8Array) value = [...value]
    else if (value !== undefined) value = { ...value, bytes: [...value.bytes] }
    rows.push({ value: value ?? null })
  } catch (error: any) { rows.push({ error: { reason: error.reason ?? null, message: error.message } }) }
}
await cache.settled()
rows.push({ clones: readdirSync(dir).length, running: cache.running.size })
options.maxCacheBytes = 1
rows.push({ value: [...await cache.read(data.url, data.first, 'Readme.md', 100, signal)] })
await cache.settled()
rows.push({ clones: readdirSync(dir).length, running: cache.running.size })
console.log(JSON.stringify(rows))
