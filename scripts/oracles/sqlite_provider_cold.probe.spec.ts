import {writeFileSync, existsSync} from 'node:fs'
import {join} from 'node:path'
import {it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import SqlitePersistence from '@deepseek-ai/dsh-session-persistence-sqlite'
import {sql} from '../../reference/packages/session/session-persistence-sqlite/src/sql.ts'

it('observes original plugin inspection repair and new Context preparation', async () => {
  const path = join(process.env.SQLITE_PROVIDER_DIRECTORY!, 'source-cold.db')
  const context = new Context()
  await context.plugin(SessionStore)
  const fiber = await context.plugin(SqlitePersistence, {path})
  const persistence: any = context.sessionPersistence
  const lazy = !existsSync(path)
  if (!lazy) throw new Error('plugin initialization materialized a database')
  const meta: any = {id: 'cold-packed', version: 0, createdAt: 1234, cwd: process.cwd()}
  const events: any[] = [{type: 'turn/start', seq: 0, time: 0, data: {turn: 1}},
    {type: 'step/start', seq: 1, time: 1, data: {turn: 1, step: 1}},
    ...Array.from({length: 100}, (_, index) => ({type: 'assistant/chunk', seq: index + 2, time: index + 2,
      data: {turn: 1, step: 1, chunk: {type: 'text-delta', index: 0, text: 'piece'}}}))]
  await persistence.create(meta)
  await persistence.append(meta.id, events)
  const store = persistence.store
  const database = store.db
  const key = database.prepare(sql('select-session-key')).get(meta.id).id
  database.prepare(sql('insert-event')).run(key, 102, 'text-chunks', 102, '{invalid', null, null, 1)
  const before = await store.readStoredRevision(meta.id)
  const inspected = await persistence.inspect(meta.id)
  if (await store.readStoredRevision(meta.id) !== before) throw new Error('inspection changed revision')
  const loaded = await persistence.load(meta.id)
  if (await store.readStoredRevision(meta.id) === before) throw new Error('recovery retained stale revision')
  if ((await store.loadStored(meta.id)).tornMarker !== undefined) throw new Error('recovery retained torn marker')
  await fiber.dispose()
  const next = new Context()
  await next.plugin(SessionStore)
  const nextFiber = await next.plugin(SqlitePersistence, {path})
  const cold = await next.sessionPersistence.prepare(meta.id)
  const stored = await next.sessionPersistence.inspect(meta.id)
  const suffix = await next.sessionPersistence.readFrom(meta.id, 50)
  const last = cold.session.events.at(-1)!
  const output = {lazy, inspected: inspected.events.length, recovered: loaded.events.length,
    coldPrepared: cold.session.events.length, stored: stored.events.length, endSeedSeq: last.seq,
    suffix: suffix.events.length, unpublished: true}
  if (last.type !== 'session/end-seed' || next.sessions.get(meta.id) !== undefined) throw new Error('cold view ownership differs')
  cold[Symbol.dispose]()
  await nextFiber.dispose()
  writeFileSync(join(process.env.SQLITE_PROVIDER_DIRECTORY!, 'source-cold-observations.json'), JSON.stringify({node: process.version, ...output}))
})
