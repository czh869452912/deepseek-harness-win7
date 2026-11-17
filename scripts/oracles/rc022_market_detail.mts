import { load } from './rc022_subagent_fixture.mts'
const { DetailReader } = await load('packages/boot/plugin-market/src/detail.ts')
const { DetailFailure, readmeName } = await load('packages/util/plugin-detail/src/index.ts')
const rows: any[] = []; let now = 1000
class Memory {
  reads: string[] = []
  constructor(readonly key: string, readonly values: any) {}
  async read(path: string, maximum: number, signal: AbortSignal) {
    this.reads.push(path); signal.throwIfAborted(); const value = this.values[path]
    if (value instanceof Error) throw value
    if (value === undefined) return undefined
    const data = new TextEncoder().encode(value)
    if (data.length > maximum) throw new DetailFailure('too-large', path)
    return data
  }
  async readme(directory: string, maximum: number, signal: AbortSignal) {
    const prefix = directory ? directory+'/' : '', name = readmeName(Object.keys(this.values).filter(path => path.startsWith(prefix) && !path.slice(prefix.length).includes('/')).map(path => path.slice(prefix.length)))
    if (name === undefined) return undefined
    const path = prefix+name; return { path, bytes: await this.read(path, maximum, signal) }
  }
}
const reader = new DetailReader({ maxDocumentBytes: 100, maxImageBytes: 10, ttlMs: 1000 }, { lifetime: new AbortController().signal } as any)
const saved = Date.now; Date.now = () => now
const step = async (name: string, work: () => any) => {
  try { let value = await work(); if (value?.bytes instanceof Uint8Array) value = { ...value, bytes: [...value.bytes] }; rows.push({ step: name, value: value ?? null }); return value }
  catch (error: any) { rows.push({ step: name, error: { reason: error.reason ?? null, message: error.message } }) }
}
try {
  const files = new Memory('npm:a@1', { 'locale/en.json': JSON.stringify({ meta: { detail: 'guide/DETAIL.md' } }),
    'guide/DETAIL.md': '# Detail', 'guide/img/a.png': 'png', 'logo.SVG': '<svg/>', 'guide/a b.webp': 'webp', 'guide/big.gif': 'x'.repeat(20) })
  const location = { files, dir: '', repository: undefined }, [a, b] = await Promise.all([reader.read(location, ['zh', 'en']), reader.read(location, ['zh', 'en'])])
  rows.push({ step: 'shared', same: a === b, value: a, reads: [...files.reads] }); await step('cached', () => reader.read(location, ['zh', 'en']))
  for (const authored of ['img/a.png?raw=1#x', '/logo.SVG', './a%20b.webp', '../../escape.png', 'notes.txt', 'img/missing.png', 'big.gif']) await step('image:'+authored, () => reader.image(a.document, authored))
  await step('unknown-id', () => reader.image('unknown', 'a.png'))
  const idle = new Memory('npm:idle@1', { 'README.md': '# Idle', 'a.png': 'png' }), value = await step('idle', () => reader.read({ files: idle, dir: '', repository: undefined }, ['en']))
  now += 600; await step('keep-image', () => reader.image(a.document, 'img/a.png'))
  now += 600; await step('kept-image', () => reader.image(a.document, 'img/a.png'))
  await step('expired-id', () => reader.image(value.document, 'a.png'))
  await step('same-id-restored', () => reader.read({ files: idle, dir: '', repository: undefined }, ['en']))
  now += 1000; await step('exact-ttl-image', () => reader.image(value.document, 'a.png'))
  await step('refresh', () => reader.read(location, ['zh', 'en'], true))
  for (const reason of ['too-large', 'denied', 'invalid', 'network', 'git-unavailable']) {
    const broken = new Memory(reason, { 'locale/en.json': new DetailFailure(reason, 'failure '+reason) })
    for (let i = 0; i < 2; i++) await step('failure:'+reason, () => reader.read({ files: broken, dir: '', repository: undefined }, ['en']))
    rows.push({ step: 'failure-reads:'+reason, reads: broken.reads.length })
  }
  const missing = new Memory('missing', { 'locale/en.json': JSON.stringify({ meta: { detail: 'GONE.md' } }) })
  await step('missing-declared', () => reader.read({ files: missing, dir: '', repository: undefined }, ['en']))
  const empty = new Memory('empty', {})
  await step('none', () => reader.read({ files: empty, dir: '', repository: undefined }, ['en']))
  await step('none-cached', () => reader.read({ files: empty, dir: '', repository: undefined }, ['en']))
  rows.push({ step: 'settled', pending: (reader as any).pending.size })
} finally { Date.now = saved }
console.log(JSON.stringify(rows))
