import { writeFile } from 'node:fs/promises'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection'
import { SessionPersistenceNotFoundError } from '../../reference/packages/session/session-persistence/src/errors.ts'
import { SessionPersistenceCorruptionError } from '../../reference/packages/session/session-persistence/src/coordinator.ts'
import { SessionObservationReader } from '../../reference/packages/session-query/session-query/src/observation.ts'

it('observes actual point-reader failure ownership and independently retained cuts', async () => {
  const rows: any[] = []
  const names = ['missing-provider', 'missing-record', 'corrupt-record', 'persistence-failure', 'foreign-rejection',
    'wrong-source', 'pre-abort', 'borrow-abort', 'projection-failure', 'live-projection-failure',
    'prepared-leases', 'live-leases', 'published-live', 'detached-live-retry', 'projection-none', 'prepared-projection']
  for (const name of names) {
    const ctx = new Context()
    const header = {version: 0, id: SessionId('owned'), createdAt: 9, cwd: '/controlled/cwd'}
    const events = [{type: 'controlled/event', seq: 0, time: 0, data: {}}] as any
    const controller = new AbortController()
    let failure: any = new TypeError('controlled read failure')
    if (name === 'missing-record') failure = new SessionPersistenceNotFoundError(header.id)
    if (name === 'corrupt-record') failure = new SessionPersistenceCorruptionError('controlled corrupt record', {})
    if (name === 'foreign-rejection') failure = 'offline'
    const counters = {borrows: 0, releases: 0, applied: 0}
    const observed: any = {}
    try {
      await ctx.plugin(SessionStore)
      await ctx.plugin(SessionProjectionRegistry)
      const broken = ['projection-failure', 'live-projection-failure', 'projection-none'].includes(name)
      const schema = {parse(value: any) {return value}}
      ctx.sessionProjections.register({key: 'controlled/count', stateVersion: 1, stateSchema: schema,
        init: () => {if (broken) throw failure; return 0},
        apply: (state: number) => {counters.applied += 1; return state + 1},
        wire: {viewSchema: schema, view: (state: number) => state}} as any)
      const meta = name === 'wrong-source' ? {...header, id: SessionId('foreign')} : header
      const preparedSession = Session.create(meta.id, events, meta)
      if (name === 'live-leases') ctx.sessions.enter(preparedSession)
      if (name !== 'missing-provider') ctx.provide('sessionPersistence', {
        borrowSession: async () => {
          counters.borrows += 1
          if (['missing-record', 'corrupt-record', 'persistence-failure', 'foreign-rejection'].includes(name)) throw failure
          if (name === 'borrow-abort') controller.abort(failure)
          if (['published-live', 'live-projection-failure'].includes(name)) ctx.sessions.enter(Session.create(header.id, [], header))
          return {source: name === 'detached-live-retry' && counters.borrows === 1 ? 'live' : 'prepared',
            inspection: {meta: preparedSession.header, events: preparedSession.events}, revision: 'controlled:0', preparedSession,
            [Symbol.dispose]: () => {counters.releases += 1}}
        },
      } as any)
      if (name === 'pre-abort') controller.abort(failure)
      try {
        const lease = await new SessionObservationReader(ctx).read(header.id, {signal: controller.signal,
          projectionMode: ['prepared-leases', 'live-leases', 'published-live', 'detached-live-retry', 'projection-none'].includes(name) ? 'none' : 'all'})
        observed.cut = {source: lease.source, id: lease.header.id, cursor: lease.cursor, length: lease.events.length,
          revision: lease.revision ?? null, projections: lease.projections ?? null}
        if (name.endsWith('leases')) {
          const retained = lease.retain()
          lease[Symbol.dispose]()
          lease[Symbol.dispose]()
          observed.releasesAfterFirst = counters.releases
          try {lease.retain()} catch (error: any) {observed.retainFailure = {message: error.message,ordinaryError: error.constructor === Error}}
          observed.retained = {source: retained.source, cursor: retained.cursor, length: retained.events.length}
          retained[Symbol.dispose]()
          retained[Symbol.dispose]()
        } else lease[Symbol.dispose]()
      } catch (error: any) {
        observed.error = {name: error.name, message: error.message, code: error.code ?? null,
          sameCause: error.cause === failure, sameFailure: error === failure}
      }
      observed.counters = counters
      rows.push({name, observed})
    } finally {await ctx.fiber.dispose()}
  }
  await writeFile(process.env.SESSION_OBSERVATION_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
}, 30000)
