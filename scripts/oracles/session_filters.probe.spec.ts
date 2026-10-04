import { readFile, writeFile } from 'node:fs/promises'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import { compileSessionTextFilter, materializeSessionResultFilters, materializeSessionEventResultFilters,
  filterSessionEventDocuments } from '../../reference/packages/session-query/session-query/src/filters.ts'
import { buildSessionEventSearchDocuments } from '../../reference/packages/session-query/session-query/src/documents.ts'
import { TestSessionQueryEngine } from '../../reference/packages/session-query/session-query/tests/test-service.ts'

it('observes owned filters, finite bounds, literal matching and concrete query consumers', async () => {
  const cases = JSON.parse(await readFile('scripts/oracles/session_filters_cases.json','utf8'))
  const events = JSON.parse(await readFile('scripts/oracles/session_event_trace_fixture.json','utf8'))
  const rows: any[] = []
  for (const input of cases) {
    const filters = structuredClone(input.filters)
    if (input.name === 'sessions-nan-range') filters[0].from = NaN
    if (input.name === 'sessions-infinite-range') filters[0].to = Infinity
    const failure = new TypeError('controlled filter listing failure')
    const observed: any = {}
    let ctx: Context | undefined
    try {
      if (input.mode.endsWith('-materialize')) {
        const owned = input.mode === 'sessions-materialize' ? materializeSessionResultFilters(filters)
          : materializeSessionEventResultFilters(filters)
        if (input.name === 'sessions-detached-values') filters[0].values[0] = 'foreign'
        observed.filters = owned
      } else if (input.mode === 'text') {
        const pattern = compileSessionTextFilter(input.text)
        observed.matches = input.documents.map((document: string) => pattern.test(document))
      } else if (input.mode === 'events-filter') {
        observed.documents = filterSessionEventDocuments([],filters)
      } else if (input.mode === 'documents') {
        observed.documents = buildSessionEventSearchDocuments(SessionId('owned'),events)
      } else {
        ctx = new Context()
        await ctx.plugin(SessionStore)
        const live = {version:0,id:SessionId('live'),createdAt:2,cwd:'/workspace'}
        const cold = {version:0,id:SessionId('cold'),createdAt:1}
        ctx.sessions.enter(Session.create(live.id,events,live))
        const controller = new AbortController()
        const counters = {lists:0,inspections:0,sameSignal:true}
        observed.counters = counters
        ctx.provide('sessionPersistence',{
          list: async (signal: any) => {
            counters.lists += 1
            counters.sameSignal &&= signal === (input.mode === 'public-sessions' ? controller.signal : undefined)
            if (input.name === 'public-sessions-failure') throw failure
            return [cold]
          },
          inspect: async () => {counters.inspections += 1; return {meta:cold,events}},
        } as any)
        const query = new TestSessionQueryEngine(ctx)
        await Promise.resolve(); await Promise.resolve()
        if (['public-sessions-pre-abort','public-sessions-invalid-before-abort'].includes(input.name))
          controller.abort(failure)
        if (input.mode === 'public-sessions') {
          const pending = query.filterSessions(filters,controller.signal)
          if (input.name === 'public-sessions-before-await') filters[0].values[0] = 'foreign'
          observed.records = (await pending).map((record: any) => ({id:record.header.id,live:record.live,persisted:record.persisted}))
        } else {
          const pending = query.filterEvents(input.name === 'public-events-cold' ? cold.id : live.id,filters)
          if (input.name === 'public-events-before-await') filters[0].values[0] = 'turn/start'
          observed.documents = await pending
        }
      }
    } catch (error: any) {
      observed.error = {name:error.name,message:error.message,code:error.code ?? null,
        sameCause:error.cause === failure,sameFailure:error === failure}
    } finally {if (ctx) await ctx.fiber.dispose()}
    rows.push({name:input.name,observed})
  }
  await writeFile(process.env.SESSION_FILTERS_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
})
