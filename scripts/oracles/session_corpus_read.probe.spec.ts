import { writeFile } from 'node:fs/promises'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import { foldSessionTitle } from '@deepseek-ai/dsh-session-title'
import { SessionCorpus } from '../../reference/packages/session-query/session-query/src/corpus.ts'
import { TestSessionQueryEngine } from '../../reference/packages/session-query/session-query/tests/test-service.ts'

it('observes exact corpus loads and bounded title batches', async () => {
  const rows: any[] = []
  const names = ['load-live', 'load-cold', 'load-missing-provider', 'load-missing-record', 'load-corrupt', 'load-failure',
    'load-foreign-failure', 'load-header-conflict', 'load-attach-wins', 'batch-live-only', 'batch-mixed-duplicates',
    'batch-list-failure', 'batch-foreign-failure', 'batch-inspect-isolated', 'batch-list-attach', 'batch-clone',
    'batch-concurrency', 'batch-abort-drain', 'pre-abort']
  for (const name of names) {
    const ctx = new Context()
    const header = (id: string, createdAt = 9) => ({version: 0, id: SessionId(id), createdAt, cwd: '/controlled/cwd'})
    const title = (id: string) => ({type: 'session/title', seq: 0, time: 3,
      data: {title: 'Title ' + id, messageSeqs: [], source: {kind: 'user'}}}) as any
    const controller = new AbortController()
    const failure: any = name.includes('foreign-failure') ? 'offline' : new TypeError('controlled corpus failure')
    if (name === 'load-corrupt') failure.name = 'SessionPersistenceCorruptionError'
    const counters = {lists: 0, inspections: [] as string[], signals: true, inFlight: 0, peak: 0, settled: 0}
    const timeline: string[] = []
    const releases = new Map<string, () => void>()
    let autoRelease = false
    let inspected: any
    const observed: any = {}
    const ids = name === 'batch-concurrency' || name === 'batch-abort-drain' ? ['a','b','c','d','e'] : ['a','b']
    let listed = ids.map(id => header(id))
    if (name === 'load-missing-record') listed = []
    const live = (id: string) => ctx.sessions.enter(Session.create(SessionId(id), [title(id)], header(id)))
    const normalizeError = (error: any) => ({name: error.name, message: error.message, code: error.code ?? null,
      sameCause: error.cause === failure, sameFailure: error === failure})
    const normalizeSource = (loaded: any) => ({id: loaded.header.id, createdAt: loaded.header.createdAt,
      cwd: loaded.header.cwd, eventTypes: loaded.events.map((event: any) => event.type), title: foldSessionTitle(loaded.events) ?? null})
    try {
      await ctx.plugin(SessionStore)
      if (['load-live', 'batch-live-only', 'batch-mixed-duplicates', 'batch-list-failure', 'batch-foreign-failure', 'batch-clone'].includes(name)) live('a')
      if (name === 'batch-live-only') live('b')
      if (!['load-missing-provider'].includes(name)) ctx.provide('sessionPersistence', {
        list: async (signal: any) => {
          counters.lists += 1
          counters.signals &&= signal === controller.signal
          if (['batch-list-failure', 'batch-foreign-failure'].includes(name)) throw failure
          if (name === 'batch-list-attach') {live('b'); listed = [header('a')]}
          return listed
        },
        inspect: async (id: string, signal: any) => {
          counters.inspections.push(id)
          counters.signals &&= signal === controller.signal
          counters.inFlight += 1
          counters.peak = Math.max(counters.peak, counters.inFlight)
          timeline.push('inspect:' + id)
          try {
            if (['load-corrupt','load-failure','load-foreign-failure'].includes(name) || name === 'batch-inspect-isolated' && id === 'b') throw failure
            if (name === 'load-attach-wins') live(id)
            if (['batch-concurrency','batch-abort-drain'].includes(name) && !autoRelease) await new Promise<void>(resolve => releases.set(id, resolve))
            if (name === 'batch-abort-drain') throw failure
            const event = title(id)
            if (name === 'batch-concurrency') Object.defineProperty(event.data, 'messageSeqs', {get() {timeline.push('project:' + id); return []}})
            inspected = {meta: header(id, name === 'load-header-conflict' ? 8 : 9), events: [event]}
            return inspected
          } finally {counters.inFlight -= 1; counters.settled += 1}
        },
      } as any)
      const corpus = new SessionCorpus(ctx, 2)
      const query = new TestSessionQueryEngine(ctx, {persistedInspectConcurrency: 2})
      await Promise.resolve(); await Promise.resolve()
      if (name === 'pre-abort') controller.abort(failure)
      try {
        if (name.startsWith('load-')) {
          const loaded = await corpus.load(SessionId('a'), controller.signal)
          observed.loaded = normalizeSource(loaded)
          loaded.header.cwd = '/mutated'
          loaded.events[0].data.title = 'mutated'
          const owner = ctx.sessions.get(SessionId('a')) ?? {header: inspected.meta, events: inspected.events}
          observed.detached = owner.header.cwd === '/controlled/cwd' && owner.events[0]?.data.title === 'Title a'
        } else {
          let selected = ids
          if (name === 'batch-mixed-duplicates') selected = ['a','b','a','missing','b']
          const pending = query.readTitleSnapshots(selected.map(SessionId), controller.signal)
          if (['batch-concurrency','batch-abort-drain'].includes(name)) {
            while (releases.size < 2) await new Promise(resolve => setTimeout(resolve, 1))
            if (name === 'batch-abort-drain') {
              controller.abort(failure)
              let settled = false
              pending.then(() => {settled = true}, () => {settled = true})
              await new Promise(resolve => setTimeout(resolve, 5))
              observed.settledBeforeDrain = settled
              for (const release of releases.values()) release()
            } else {
              releases.get('a')!()
              while (!counters.inspections.includes('c')) await new Promise(resolve => setTimeout(resolve, 1))
              autoRelease = true
              for (const release of releases.values()) release()
            }
          }
          const results = await pending
          observed.results = results.map((result: any) => result.status === 'fulfilled'
            ? {id: result.sessionId, status: result.status, value: {id: result.value.session.id,
                cwd: result.value.session.cwd, title: result.value.title ?? null}}
            : {id: result.sessionId, status: result.status, error: normalizeError(result.reason)})
          if (name === 'batch-clone') {
            const value = (results[0] as any).value
            value.session.cwd = '/mutated'
            try {value.title.source.kind = 'foreign'} catch (error) {observed.titleMutationRefused = error instanceof TypeError}
            observed.detached = ctx.sessions.get(SessionId('a'))?.header.cwd === '/controlled/cwd'
              && ctx.sessions.get(SessionId('a'))?.events[0]?.data.source.kind === 'user'
          }
          if (name === 'batch-concurrency') observed.projectBeforeNext = timeline.indexOf('project:a') < timeline.indexOf('inspect:c')
        }
      } catch (error: any) {observed.error = normalizeError(error)}
      observed.counters = counters
      rows.push({name, observed})
    } finally {for (const release of releases.values()) release(); await ctx.fiber.dispose()}
  }
  await writeFile(process.env.SESSION_CORPUS_READ_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
}, 30000)
