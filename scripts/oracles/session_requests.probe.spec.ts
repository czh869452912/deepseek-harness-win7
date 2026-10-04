import { readFile, writeFile } from 'node:fs/promises'
import { DatabaseSync } from 'node:sqlite'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import { SqliteSessionQueryEngine } from '../../reference/packages/session-query/session-query-sqlite/src/index.ts'
import { normalizeSessionRequest, normalizeEventRequest, buildSessionWhere, buildEventWhere,
  assertPortableBindingCount, assertFts5OuterPredicateCount, quoteFtsData, sanitizeFtsText,
  makeSnippet } from '../../reference/packages/session-query/session-query-sqlite/src/query.ts'

it('observes typed request ownership, actual SQL bindings, budgets and public validation order', async () => {
  const cases = JSON.parse(await readFile('scripts/oracles/session_requests_cases.json','utf8'))
  const rows: any[] = []
  for (const input of cases) {
    const request = structuredClone(input.request)
    if (input.special === 'nan') request.limit = NaN
    if (input.special === 'infinity') request.limit = Infinity
    const observed: any = {}
    let ctx: Context | undefined
    let query: SqliteSessionQueryEngine | undefined
    try {
      if (input.mode === 'session' || input.mode === 'event') {
        observed.value = (input.mode === 'session' ? normalizeSessionRequest : normalizeEventRequest)(
          request, input.limits ?? {defaultLimit:2,maxLimit:3})
        if (input.mutate) request.sessionFilters[0].values[0] = 'foreign'
      } else if (input.mode.endsWith('-sql')) {
        observed.value = (input.mode === 'session-sql' ? buildSessionWhere : buildEventWhere)(input.filters)
        const db = new DatabaseSync(':memory:')
        try {
          db.exec('CREATE TABLE docs(session_id TEXT,cwd TEXT,parent_session TEXT,created_at INTEGER,live INTEGER,persisted INTEGER,seq INTEGER,time INTEGER,type TEXT,surface TEXT)')
          const insert = db.prepare('INSERT INTO docs VALUES(?,?,?,?,?,?,?,?,?,?)')
          for (const document of [
            ['a','/workspace',null,10,1,0,1,100,'message/created','current'],
            ['b',null,'a',20,0,1,2,200,'turn/start','log-only'],
            ['c','/workspace','a',30,1,1,3,300,'message/created','shadowed'],
          ]) insert.run(...document)
          const where = observed.value.sql ? ' WHERE '+observed.value.sql : ''
          observed.matches = db.prepare('SELECT session_id FROM docs'+where+' ORDER BY session_id')
            .all(...observed.value.params).map((row: any) => row.session_id)
        } finally {db.close()}
      } else if (input.mode === 'outer' || input.mode === 'binding') {
        (input.mode === 'outer' ? assertFts5OuterPredicateCount : assertPortableBindingCount)(input.count)
        observed.value = 'accepted'
      } else if (input.mode === 'snippet') observed.value = makeSnippet(input.text,input.maxChars)
      else if (input.mode === 'quote') observed.value = quoteFtsData(input.text)
      else if (input.mode === 'sanitize') observed.value = sanitizeFtsText(input.text)
      else {
        ctx = new Context()
        await ctx.plugin(SessionStore)
        observed.lists = 0
        ctx.provide('sessionPersistence',{list:async () => {observed.lists += 1; throw new Error('unexpected persistence access')}} as any)
        query = new SqliteSessionQueryEngine(ctx,{path:':memory:',openAt:input.openAt})
        observed.opened = false
        const controller = new AbortController()
        if (input.abort) controller.abort(new TypeError('caller abort reason'))
        await query.searchSessions(request,{signal:controller.signal})
        throw new Error('validation unexpectedly succeeded')
      }
    } catch (error: any) {
      observed.error = {name:error.name,message:error.message,code:error.code ?? null}
    } finally {
      if (query) {
        observed.opened = (query as any)._db !== undefined
        await query.close()
      }
      if (ctx) await ctx.fiber.dispose()
    }
    rows.push({name:input.name,observed})
  }
  await writeFile(process.env.SESSION_REQUESTS_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
})
