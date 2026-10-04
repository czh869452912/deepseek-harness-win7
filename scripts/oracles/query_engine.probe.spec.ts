import { writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import { it } from 'vitest'
import { SqliteSessionQueryEngine } from '../../reference/packages/session-query/session-query-sqlite/src/index.ts'

const header = (id: string) => ({id,version:0,createdAt:1})
const event = (text: string, seq=0) => ({type:'user/message',seq,time:seq+1,surfaceOp:'append',
  data:{id:'message-'+seq,role:'user',content:[{type:'text',text}],source:{kind:'user'}}})
const sessions = (page: any) => page.items.map((item: any) => ({id:item.header.id,live:item.live,persisted:item.persisted,
  seq:item.bestMatch.seq,snippet:item.bestMatch.snippet}))

it('observes actual query lifecycle, FTS selection, stable revisions and cursor generations', async () => {
  const rows: any[] = []
  const record = (name: string, observed: any) => rows.push({name,observed})
  const ctx = new Context()
  await ctx.plugin(SessionStore)
  let entries = new Map<string, any>([['alpha',{header:header('alpha'),revision:'1',events:[event('needle needle')]}],
    ['beta',{header:header('beta'),revision:'2',events:[event('needle')]}]])
  let inspected = 0
  let snapshots = 0
  let unstable = 0
  const persistence = {listSnapshots: async () => {
    snapshots += 1
    if (unstable > 0) {entries.get('alpha').revision = String(100+snapshots);unstable -= 1}
    return [...entries.values()].map(({header,revision}) => ({header:structuredClone(header),revision}))
  }, inspect:async (id: string) => {inspected += 1;const entry=entries.get(id);return {meta:structuredClone(entry.header),events:structuredClone(entry.events)}}}
  const provider = ctx.provide('sessionPersistence',persistence as any)
  const query = new SqliteSessionQueryEngine(ctx,{path:':memory:',openAt:'first-search',defaultLimit:1,maxLimit:2})
  try {
    const first = await query.searchSessions({query:'needle'})
    record('persisted-ranked',sessions(first))
    record('persisted-next-page',sessions(await query.searchSessions({query:'needle',cursor:first.nextCursor})))
    const inspections = inspected
    record('unchanged-no-inspect',{items:sessions(await query.searchSessions({query:'needle'})),inspections:inspected-inspections})
    const events = await query.searchEvents({sessionId:'alpha' as any,query:'needle'})
    record('event-header',{header:events.session,items:events.items})
    entries.get('alpha').events.push(event('needle newest',1));entries.get('alpha').revision='3'
    try {await query.searchSessions({query:'needle',cursor:first.nextCursor});throw Error('expected stale')}
    catch(error:any) {record('cross-session-stale',{code:error.code,message:error.message})}
    const changed = await query.searchEvents({sessionId:'alpha' as any,query:'needle'})
    record('event-page',{seqs:changed.items.map(item=>item.seq),hasNext:changed.nextCursor!==undefined})
    entries.get('beta').events.push(event('needle outside',1));entries.get('beta').revision='4'
    const continued = await query.searchEvents({sessionId:'alpha' as any,query:'needle',cursor:changed.nextCursor})
    record('unrelated-event-cursor',{seqs:continued.items.map(item=>item.seq)})
    const live = ctx.sessions.prepare('alpha' as any,{meta:{createdAt:1},seed:[event('needle LIVE')] as any})
    const detach = ctx.sessions.enter(live)
    ctx.sessions.announce(live)
    record('live-preference',sessions(await query.searchSessions({query:'needle',limit:2})))
    record('literal-operators',sessions(await query.searchSessions({query:'needle OR unrelated',limit:2})))
    record('empty-availability',sessions(await query.searchSessions({query:'needle',sessionFilters:[{kind:'availability',values:[]}]})))
    unstable = 2
    const beforeRetry=inspected
    record('one-stable-retry',{items:sessions(await query.searchSessions({query:'needle',limit:2})),inspections:inspected-beforeRetry})
    detach()
    await query.searchSessions({query:'needle'})
    unstable = 4
    try {await query.searchSessions({query:'needle'});throw Error('expected unstable')}
    catch(error:any) {record('unstable-refusal',{code:error.code,message:error.message})}
    unstable=0
    provider()
    record('unmounted-hidden',sessions(await query.searchSessions({query:'needle',limit:2})))
    const replacement = ctx.provide('sessionPersistence',{...persistence} as any)
    const beforeReplace=inspected
    record('replacement-reloads',{items:sessions(await query.searchSessions({query:'needle',limit:2})),inspections:inspected-beforeReplace})
    replacement()
    const controller = new AbortController();controller.abort(new TypeError('reason'))
    const beforeAbort = snapshots
    try {await query.searchSessions({query:'needle'},{signal:controller.signal});throw Error('expected abort')}
    catch(error:any) {record('preabort-zero-observation',{code:error.code,message:error.message,snapshots:snapshots-beforeAbort})}
    await query.close()
    try {await query.searchSessions({query:'needle'});throw Error('expected closed')}
    catch(error:any) {record('closed-refusal',{code:error.code,message:error.message})}
  } finally {await query.close();await ctx.fiber.dispose()}
  await writeFile(process.env.QUERY_ENGINE_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
})
