import { writeFile } from 'node:fs/promises'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import { SessionCorpus } from '../../reference/packages/session-query/session-query/src/corpus.ts'

it('observes actual corpus listing with declared listing failure and publication seams', async () => {
  const rows: any[] = []
  for (const name of ['no-provider', 'persisted-live', 'tie-order', 'duplicate-durable', 'foreign-header',
    'listing-failure', 'foreign-rejection', 'pre-abort', 'list-abort', 'signal-forwarded', 'post-list-attach', 'clone-detachment']) {
    const ctx = new Context()
    const header = {version: 0, id: SessionId('owned'), createdAt: 9, cwd: '/controlled/cwd'}
    const controller = new AbortController()
    const failure: any = name === 'foreign-rejection' ? 'offline' : new TypeError('controlled listing failure')
    const counters = {lists: 0, sameSignal: false}
    const observed: any = {}
    try {
      await ctx.plugin(SessionStore)
      let headers = [header]
      if (name === 'tie-order') headers = ['b', 'a', 'new'].map(id => ({...header, id: SessionId(id), createdAt: id === 'new' ? 10 : 9}))
      if (name === 'duplicate-durable') headers = [header, {...header, createdAt: 10}]
      if (['persisted-live', 'foreign-header', 'clone-detachment'].includes(name)) {
        ctx.sessions.enter(Session.create(header.id, [], {...header, createdAt: name === 'foreign-header' ? 8 : 9}))
      }
      if (name !== 'no-provider') ctx.provide('sessionPersistence', {list: async (signal: any) => {
        counters.lists += 1
        counters.sameSignal = signal === controller.signal
        if (['listing-failure', 'foreign-rejection'].includes(name)) throw failure
        if (name === 'list-abort') controller.abort(failure)
        if (name === 'post-list-attach') ctx.sessions.enter(Session.create(header.id, [], header))
        return headers
      }} as any)
      const corpus = new SessionCorpus(ctx, 4)
      await Promise.resolve()
      await Promise.resolve()
      if (name === 'pre-abort') controller.abort(failure)
      try {
        const records = await corpus.listSessions(controller.signal)
        observed.records = records.map(record => ({id: record.header.id, createdAt: record.header.createdAt,
          cwd: record.header.cwd ?? null, live: record.live, persisted: record.persisted}))
        if (name === 'clone-detachment') {
          records[0].header.cwd = '/mutated'
          observed.originalCwd = ctx.sessions.get(header.id)?.header.cwd
        }
      } catch (error: any) {
        observed.error = {name: error.name, message: error.message, code: error.code ?? null,
          sameCause: error.cause === failure, sameFailure: error === failure}
      }
      observed.counters = counters
      rows.push({name, observed})
    } finally {await ctx.fiber.dispose()}
  }
  await writeFile(process.env.SESSION_CORPUS_LIST_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
}, 30000)
