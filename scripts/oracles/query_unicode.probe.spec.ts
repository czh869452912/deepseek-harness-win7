import { writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import { it } from 'vitest'
import { requestFingerprint } from '../../reference/packages/session-query/session-query-sqlite/src/query.ts'
import { SqliteSessionQueryEngine } from '../../reference/packages/session-query/session-query-sqlite/src/index.ts'

it('observes original Unicode collation, fingerprints and actual cursor boundaries', async () => {
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
    const entries = pair.map((cwd,index)=>({header:{id:index?'beta':'alpha',version:0,createdAt:1,cwd},events:[{type:'user/message',seq:0,time:1,surfaceOp:'append',data:{id:'message-0',role:'user',content:[{type:'text',text:'needle'}],source:{kind:'user'}}}]}))
    ctx.provide('sessionPersistence',{listSnapshots:async()=>entries.map(entry=>({header:entry.header,revision:'1'})),inspect:async(id:string)=>{const entry=entries.find(entry=>entry.header.id===id)!;return {meta:entry.header,events:entry.events}}} as any)
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
  await writeFile(process.env.QUERY_UNICODE_OUTPUT!,JSON.stringify({node:process.version,icu:process.versions.icu,unicode:process.versions.unicode,cldr:process.versions.cldr,locale:new Intl.Collator().resolvedOptions().locale,comparisons,fingerprints,cursors},null,2)+'\n')
})
