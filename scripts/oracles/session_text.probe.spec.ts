import { readFile, writeFile } from 'node:fs/promises'
import { it } from './official/node_modules/vitest/dist/index.js'
import { compileSessionTextFilter } from '../../reference/packages/session-query/session-query/src/filters.ts'
import { extractSessionEventText } from '../../reference/packages/session-query/session-query/src/extraction.ts'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { Session } from '@deepseek-ai/dsh-session'
import { TestSessionQueryEngine } from '../../reference/packages/session-query/session-query/tests/test-service.ts'

it('observes literal Unicode regex and all semantic extraction whitespace boundaries', async () => {
  const input = JSON.parse(await readFile(process.env.SESSION_TEXT_INPUT!, 'utf8'))
  const cases = input.cases.map((row: any) => {
    try { return {name: row.name, matched: compileSessionTextFilter(row.text).test(row.document)} }
    catch(error: any) { return {name: row.name, error: {code: error.code, message: error.message}} }
  })
  const events = input.events.map((event: any) => extractSessionEventText(event))
  const orders = []
  for (const row of input.orders) {
    const ctx = new Context()
    await ctx.plugin(SessionStore)
    const live = row.headers.filter((_: any, index: number) => row.provider === 'live' || row.provider === 'mixed' && index % 2 === 0)
    const persisted = row.headers.filter((_: any, index: number) => row.provider === 'persisted' || row.provider === 'mixed' && index % 2 === 1)
    for (const header of live) ctx.sessions.enter(Session.create(header.id, [], header))
    ctx.provide('sessionPersistence', {list: async () => persisted} as any)
    const query = new TestSessionQueryEngine(ctx)
    await Promise.resolve()
    await Promise.resolve()
    try {
      const records = await query.listSessions()
      const trace = await query.traceSession('root' as any)
      orders.push({name:row.name, listed:records.map(record=>record.header.id), children:trace.descendants.map(child=>child.session.header.id)})
    } finally { await ctx.fiber.dispose() }
  }
  await writeFile(process.env.SESSION_TEXT_OUTPUT!, JSON.stringify({node:process.version, icu:process.versions.icu, unicode:process.versions.unicode, cldr:process.versions.cldr, locale:new Intl.Collator().resolvedOptions().locale, caseFoldingSha256:input.caseFoldingSha256, cases, events, orders}, null, 2)+'\n')
})
