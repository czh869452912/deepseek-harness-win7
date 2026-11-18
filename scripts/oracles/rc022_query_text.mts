/** Actual current Source APIs over the retained exhaustive Unicode/text inputs. */
import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const source=process.argv[2]!
const load=(path:string)=>import(pathToFileURL(resolve(source,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts')
const {default:SessionStore}=await load('packages/core/session/src/index.ts')
const {requestFingerprint}=await load('packages/session-query/session-query-sqlite/src/query.ts')
const {SqliteSessionQueryEngine}=await load('packages/session-query/session-query-sqlite/src/index.ts')
const {compileSessionTextFilter}=await load('packages/session-query/session-query/src/filters.ts')
const {extractSessionEventText}=await load('packages/session-query/session-query/src/extraction.ts')
const {TestSessionQueryEngine}=await load('packages/session-query/session-query/tests/test-service.ts')
async function unicode(){
  const values = ['', 'a', 'A', 'á', 'a\u0301', 'ä', 'z', '中', '文', '阿', '😀', '🐍', '\ud800', '\udc00', 'a\0b', 'ab', 'a\u200bb', 'a\u00adb', '10', '2', '-', '_', 'é', 'e\u0301', 'Å', 'å', 'Ａ', 'ａ', 'ß', 'ss', 'İ', 'i', 'ı', '💻', '👩\u200d💻', '👩💻', '\u034f', '\u2060', 'a\u0315\u0300', 'a\u0300\u0315', '\u00e0\u0315', 'a\u0300\u034f\u0315', 'a\u2060b']
  const comparisons = values.flatMap(left => values.map(right => [left, right, Math.sign(left.localeCompare(right))]))
  const requests: any[] = []
  for (const list of [values, [...values].reverse(), ...values.map((value, index) => [null, value, values[(index+1)%values.length]])]) {
    for (const clauses of [[{kind:'cwd',values:list}], [{kind:'cwd',values:list},{kind:'cwd',values:[...list].reverse()}]]) {
      requests.push({query:'needle',sessionFilters:clauses,eventFilters:[],limit:1})
      requests.push({sessionId:'中😀',query:'needle',filters:clauses.map(clause=>({...clause,kind:'type',values:clause.values.filter(value=>value!==null)})),limit:1})
    }
  }
  const fingerprints = requests.map(request => ({request, fingerprint:requestFingerprint(request)}))
  const cursors: any[] = []
  for (const [name, pair] of [['nfc',['é','e\u0301']], ['zero-width',['ab','a\u200bb']], ['soft-hyphen',['ab','a\u00adb']], ['word-joiner',['ab','a\u2060b']], ['canonical-order',['a\u0315\u0300','\u00e0\u0315']]] as const) {
    const ctx = new Context()
    await ctx.plugin(SessionStore)
    const entries = pair.map((cwd,index)=>({header:{id:index?'beta':'alpha',version:4,createdAt:1,cwd,isSeeded:false},events:[{type:'user/message',seq:0,time:1,surfaceOp:'append',data:{id:'message-0',role:'user',content:[{type:'text',text:'needle'}],source:{kind:'user'}}}]}))
    ctx.provide('sessionPersistence',{list:async()=>entries.map(entry=>({header:structuredClone(entry.header),revision:'1'})),
      open:async(id:string,mode:string)=>{
        if(mode!=='read')throw Error('observer only allows cold reads')
        const entry=structuredClone(entries.find(entry=>entry.header.id===id)!)
        return {header:entry.header,inheritedEventCount:0,
          read:async()=>({events:entry.events,eventState:'detached'}),close:async()=>{}}
      }} as any)
    const query = new SqliteSessionQueryEngine(ctx,{path:':memory:',openAt:'first-search',defaultLimit:1,maxLimit:2})
    try {
      const request={query:'needle',sessionFilters:[{kind:'cwd',values:[...pair]}],limit:1} as any
      const first=await query.searchSessions(request)
      const same=await query.searchSessions({...request,cursor:first.nextCursor})
      let reversed: any
      try {const page=await query.searchSessions({...request,sessionFilters:[{kind:'cwd',values:[...pair].reverse()}],cursor:first.nextCursor});reversed={ids:page.items.map(item=>item.header.id)}}
      catch(error:any){reversed={code:error.code,message:error.message}}
      cursors.push({name,first:first.items.map(item=>item.header.id),same:same.items.map(item=>item.header.id),reversed})
    }finally{await query.close();await ctx.fiber.dispose()}
  }
  return {comparisons,fingerprints,cursors}
}
async function text(){
  const input = JSON.parse(readFileSync(process.argv[3]!, 'utf8'))
  for(const row of input.orders)for(const header of row.headers)header.version=4
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
    for (const header of live) ctx.sessions.enter(ctx.sessions.prepare(header.id, {meta: header}))
    ctx.provide('sessionPersistence', {list: async () => persisted.map(header => ({header,revision:'controlled'}))} as any)
    const query = new TestSessionQueryEngine(ctx)
    await Promise.resolve()
    await Promise.resolve()
    try {
      const records = await query.listSessions()
      const trace = await query.traceSession('root' as any)
      orders.push({name:row.name, listed:records.map(record=>record.header.id), children:trace.descendants.map(child=>child.session.header.id)})
    } finally { await ctx.fiber.dispose() }
  }
  return {cases,events,orders}
}
process.stderr.write(JSON.stringify({node:process.version,icu:process.versions.icu,unicode:process.versions.unicode,cldr:process.versions.cldr,locale:new Intl.Collator().resolvedOptions().locale})+"\n")
process.stdout.write(JSON.stringify({unicode:await unicode(),text:await text()}))
