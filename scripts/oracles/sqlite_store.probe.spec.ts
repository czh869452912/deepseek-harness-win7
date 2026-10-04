import {writeFileSync, copyFileSync} from 'node:fs'
import {join} from 'node:path'
import {it} from 'vitest'
import {SqliteStore} from '../../reference/packages/session/session-persistence-sqlite/src/store.ts'
import {sql} from '../../reference/packages/session/session-persistence-sqlite/src/sql.ts'
import {DatabaseSync} from 'node:sqlite'
import {readFileSync} from 'node:fs'

it('observes actual Source storage and mutual cross-file physical reads', async () => {
  const directory = process.env.SQLITE_STORE_DIRECTORY!
  const meta: any = {id: 'store-session', version: 0, createdAt: 1234, cwd: directory, origin: 'subagent', delegationDepth: 2, agentPreset: 'standard'}
  const chunk = (seq: number): any => ({type: 'assistant/chunk', seq, time: seq,
    data: {turn: 1, step: 1, chunk: {type: 'text-delta', index: 0, text: '界'.repeat(100)}}})
  const visible = (value: any): any => Array.isArray(value) ? value.map(visible) :
    value !== null && typeof value === 'object' ? Object.fromEntries(Object.entries(value).filter(([key]) => key !== 'revision').map(([key, item]) => [key, visible(item)])) : value
  const original = new SqliteStore({path: join(directory, 'source.db'), journalMode: 'delete', busyTimeoutMs: 5000})
  await original.appendBatch(meta, Array.from({length: 2051}, (_, seq) => chunk(seq)), false)
  writeFileSync(join(directory, 'source-file-initial-revision.txt'), (await original.readStoredRevision(meta.id))!)
  await original.close()
  copyFileSync(join(directory, 'source.db'), join(directory, 'source-produced.db'))
  const native = new SqliteStore({path: join(directory, 'native.db'), journalMode: 'delete', busyTimeoutMs: 5000})
  const rows: any[] = []
  const capture = async (name: string, operation: () => Promise<unknown>) => {
    try { rows.push({name, value: visible(await operation())}) }
    catch (error: any) { rows.push({name, error: error.message}) }
  }
  try {
    rows.push({name: 'exact-cross-file-revision', value: await native.readStoredRevision(meta.id) ===
      readFileSync(join(directory, 'native-file-initial-revision.txt'), 'utf8')})
    await capture('source-cross-read', () => native.loadStored(meta.id))
    await capture('source-cross-suffix', () => native.loadStoredFrom(meta.id, 1025))
    await capture('source-cross-list', () => native.list())
    await capture('source-cross-snapshots', () => native.listSnapshots())
    const before = await native.readStoredRevision(meta.id)
    await native.appendBatch(meta, [chunk(2051), chunk(2052), chunk(2053)], true)
    const after = await native.readStoredRevision(meta.id)
    rows.push({name: 'revision-advanced-once', value: before!.slice(0, before!.lastIndexOf(':')) === after!.slice(0, after!.lastIndexOf(':')) &&
      Number(after!.slice(after!.lastIndexOf(':') + 1)) === Number(before!.slice(before!.lastIndexOf(':') + 1)) + 1})
    await capture('stale-append', () => native.appendBatch(meta, [chunk(2051)], true))
    await capture('after-stale-append', () => native.loadStoredFrom(meta.id, 2051))
    await capture('stale-repair', () => native.commitRepair(meta, undefined, [{type: 'turn/end', seq: 1, time: 1, data: {turn: 1}} as any]))
    await capture('after-stale-repair', () => native.loadStoredFrom(meta.id, 2051))
    const database = (native as any).db
    database.exec('PRAGMA application_id=12345')
    await capture('ownership-changed-append', () => native.appendBatch(meta, [chunk(2054)], true))
    database.exec(sql('set-application-id'))
    await capture('after-ownership-refusal', () => native.loadStoredFrom(meta.id, 2051))
    rows.push({name: 'page-size', value: database.prepare('PRAGMA page_size').get().page_size})
    rows.push({name: 'physical-count', value: database.prepare('SELECT count(*) AS count FROM events').get().count})
    rows.push({name: 'physical-kind', value: database.prepare('SELECT DISTINCT typeof(data) AS kind FROM events').all()})
  } finally { await native.close() }
  const memory = new SqliteStore({path: ':memory:', journalMode: 'wal', busyTimeoutMs: 5000})
  const tornMeta = {...meta, id: 'torn-session'}
  try {
    await memory.appendBatch(tornMeta, [{type: 'turn/start', seq: 0, time: 0, data: {turn: 1}} as any], false)
    const database = (memory as any).db
    const key = database.prepare(sql('select-session-key')).get(tornMeta.id).id
    database.prepare(sql('insert-event')).run(key, 1, 'text-chunks', 1, '{invalid', null, null, 1)
    await capture('torn-load', () => memory.loadStored(tornMeta.id))
    await capture('torn-append-refusal', () => memory.appendBatch(tornMeta, [chunk(1)], true))
    await capture('repair-missing-marker', () => memory.commitRepair(tornMeta, undefined, [{type: 'turn/end', seq: 1, time: 1, data: {turn: 1}} as any]))
    await memory.commitRepair(tornMeta, 1, [{type: 'turn/end', seq: 1, time: 1, data: {turn: 1}} as any])
    await capture('repaired-load', () => memory.loadStored(tornMeta.id))
    await capture('repair-old-marker', () => memory.commitRepair(tornMeta, 1, []))
    database.prepare(sql('insert-event')).run(key, 2, 'text-chunks', 2, '{invalid', null, null, 1)
    database.prepare(sql('insert-event')).run(key, 3, 'turn/end', 3, '{"turn":1}', null, null, 0)
    await capture('committed-corruption', () => memory.loadStored(tornMeta.id))
  } finally { await memory.close() }
  for (const mode of ['wal', 'delete', 'truncate', 'persist'] as const) {
    const store = new SqliteStore({path: join(directory, `source-${mode}.db`), journalMode: mode, busyTimeoutMs: 5000})
    try {
      await store.open()
      const database = (store as any).db
      rows.push({name: `journal-${mode}`, value: {mode: database.prepare('PRAGMA journal_mode').get().journal_mode,
        sync: database.prepare('PRAGMA synchronous').get().synchronous, page: database.prepare('PRAGMA page_size').get().page_size,
        trusted: database.prepare('PRAGMA trusted_schema').get().trusted_schema, mmap: database.prepare('PRAGMA mmap_size').get().mmap_size}})
    } finally { await store.close() }
  }
  for (const [name, setup] of [['unversioned', 'CREATE TABLE unrelated (value TEXT)'],
    ['old-version', 'PRAGMA user_version=18'], ['future-version', 'PRAGMA user_version=20'],
    ['foreign-application', 'PRAGMA user_version=19; PRAGMA application_id=12345'],
    ['altered-schema', 'PRAGMA user_version=19; PRAGMA application_id=1146308688; CREATE TABLE unrelated(value TEXT)']]) {
    const path = join(directory, `source-refuse-${name}.db`)
    const foreign = new DatabaseSync(path)
    foreign.exec(setup!)
    foreign.close()
    const before = readFileSync(path)
    const refused = new SqliteStore({path, journalMode: 'wal', busyTimeoutMs: 5000})
    try { await refused.open(); throw new Error('foreign database accepted') }
    catch (error: any) { rows.push({name: `refuse-${name}`, value: {message: error.message.replace(path, '<database>'), unchanged: before.equals(readFileSync(path))}}) }
    finally { await refused.close() }
  }
  const peerPath = join(directory, 'source-peers.db')
  const first = new SqliteStore({path: peerPath, journalMode: 'wal', busyTimeoutMs: 5000})
  const second = new SqliteStore({path: peerPath, journalMode: 'wal', busyTimeoutMs: 5000})
  try {
    await first.materializeHeader(meta)
    await second.open()
    const initial = await second.readStoredRevision(meta.id)
    await first.appendBatch(meta, [chunk(0), chunk(1), chunk(2)], true)
    rows.push({name: 'peer-revision-observed', value: await second.readStoredRevision(meta.id) !== initial})
    await capture('peer-stale-append', () => second.appendBatch(meta, [chunk(0)], true))
    await capture('peer-winning-tail', () => second.loadStoredFrom(meta.id, 0))
  } finally { await second.close(); await first.close() }
  writeFileSync(join(directory, 'source-observations.json'), JSON.stringify({node: process.version, rows}))
})
