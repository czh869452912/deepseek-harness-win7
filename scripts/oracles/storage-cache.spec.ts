import { it } from 'vitest'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { setImmediate } from 'node:timers/promises'
import { Context } from '@deepseek-ai/cordis'
import { z } from 'zod'
import Storage, { storageBackendServiceKey } from '@deepseek-ai/dsh-storage'
import { JsonStorageBackend } from '@deepseek-ai/dsh-storage-json'
import * as JsonPlugin from '@deepseek-ai/dsh-storage-json'
import * as DomainPlugin from '@deepseek-ai/dsh-storage-domain'
import { defineDomain, domainTable } from '@deepseek-ai/dsh-storage-domain'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import Registry from '@deepseek-ai/dsh-session-projection'
import Cache from '@deepseek-ai/dsh-session-projection-cache'

async function until(test: () => boolean) {
  const deadline = Date.now() + 2000
  while (!test()) {
    if (Date.now() > deadline) throw new Error('observation did not settle')
    await setImmediate()
  }
}

const spec = (name: string) => defineDomain({name, version: 1, tables: {items: domainTable(z.any())}})
const append = (session: any, value: number) => session.append('cache-test/event', {value})
const recordPath = (root: string, id: string) => join(root, 'session_projcache', 'sessions', id + '.json')

async function namedBackend(ctx: Context, name: string, root: string) {
  return await ctx.plugin(Object.assign((inner: Context) => {
    const backend = new JsonStorageBackend(root)
    const unregister = inner.storage.backend.register(name, backend)
    inner.provide(storageBackendServiceKey(name), backend)
    inner.effect(() => async () => { unregister(); await backend.close() })
  }, {inject: ['storage']}))
}

async function cacheContext(root: string, count = 100) {
  const ctx = new Context()
  await ctx.plugin(Storage)
  await ctx.plugin(JsonPlugin, {root})
  await ctx.plugin(DomainPlugin, {backend: 'json'})
  await ctx.plugin(SessionStore)
  await ctx.plugin(Registry)
  ctx.sessionProjections.register({
    key: 'count', stateVersion: 1, stateSchema: z.number().int(),
    init: () => 0, apply: (state: number) => state + 1,
    wire: {viewSchema: z.number().int(), view: (state: number) => state},
  } as any)
  await ctx.plugin(Cache, {writeEveryEvents: count, writeIntervalMs: 60000})
  return ctx
}

it('observes routed provider lifecycles and detached durable cuts', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dsh-storage-cache-oracle-'))
  const rows: any[] = []
  const contexts: Context[] = []
  try {
    const routed = new Context()
    contexts.push(routed)
    await routed.plugin(Storage)
    await routed.plugin(DomainPlugin, {backend: 'main', routes: {routed: 'other'}})
    const gates = [routed.storageDomain !== undefined]
    await namedBackend(routed, 'main', join(root, 'main'))
    gates.push(routed.storageDomain !== undefined)
    const other = await namedBackend(routed, 'other', join(root, 'other'))
    await until(() => routed.storageDomain !== undefined)
    gates.push(routed.storageDomain !== undefined)
    const old = routed.storageDomain
    const normal = await old.open(spec('normal'))
    const remote = await old.open(spec('routed'))
    await normal.table('items').put('key', 'main')
    await remote.table('items').put('key', 'other')
    const persisted = [
      JSON.parse(await readFile(join(root, 'main', 'normal.json'), 'utf8')).tables.items.key,
      JSON.parse(await readFile(join(root, 'other', 'routed.json'), 'utf8')).tables.items.key,
    ]
    await other.dispose()
    await until(() => routed.storageDomain === undefined)
    await namedBackend(routed, 'other', join(root, 'other'))
    await until(() => routed.storageDomain !== undefined)
    const fresh = routed.storageDomain
    rows.push({mode: 'routing', gates, withdrawn: old !== fresh, persisted,
      recovered: [(await fresh.open(spec('normal'))).table('items').get('key'),
                  (await fresh.open(spec('routed'))).table('items').get('key')]})

    const cut = await cacheContext(join(root, 'cut'))
    contexts.push(cut)
    const session = cut.sessions.create(SessionId('cut'))
    append(session, 1)
    await until(() => cut.sessionProjectionCache.cachedSnapshot(session.header) !== undefined)
    const creation = cut.sessionProjectionCache.cachedSnapshot(session.header)
    const pending = cut.sessionProjectionCache.write(session)
    append(session, 2)
    await pending
    rows.push({mode: 'call-cut', creation, written: cut.sessionProjectionCache.cachedSnapshot(session.header)})

    const threshold = await cacheContext(join(root, 'threshold'), 3)
    contexts.push(threshold)
    const counted = threshold.sessions.create(SessionId('threshold'))
    await until(() => threshold.sessionProjectionCache.cachedSnapshot(counted.header) !== undefined)
    const changes: any[] = []
    threshold.on('domain/changed', change => {
      if (change.domain === 'session_projcache' && change.key === counted.id && change.operation === 'put') {
        changes.push((change.value as any).rows.count)
      }
    })
    for (let value = 0; value < 6; value++) append(counted, value)
    await until(() => changes.length === 2)
    rows.push({mode: 'threshold', writes: changes})

    const invalid = await cacheContext(join(root, 'invalid'))
    contexts.push(invalid)
    const bad = invalid.sessions.create(SessionId('invalid'))
    await until(() => invalid.sessionProjectionCache.cachedSnapshot(bad.header) !== undefined)
    const unregister = invalid.sessionProjections.register({
      key: 'invalid', stateVersion: 1, stateSchema: z.custom(() => true),
      init: () => new Set(['not-json']), apply: (state: unknown) => state,
    } as any)
    let rejected = false
    try { await invalid.sessionProjectionCache.write(bad) } catch { rejected = true }
    const document = JSON.parse(await readFile(recordPath(join(root, 'invalid'), 'invalid'), 'utf8'))
    unregister()
    append(bad, 1)
    await invalid.sessionProjectionCache.write(bad)
    rows.push({mode: 'non-json', rejected, invalidPersisted: 'invalid' in document.record.rows,
      recovered: invalid.sessionProjectionCache.cachedSnapshot(bad.header)})
    await writeFile(process.env.STORAGE_CACHE_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
  } finally {
    for (const ctx of contexts.reverse()) await ctx.fiber.dispose()
    await rm(root, {recursive: true, force: true})
  }
})
