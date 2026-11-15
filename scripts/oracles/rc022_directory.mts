import {readFileSync} from 'node:fs'
import {mkdir,rmdir} from 'node:fs/promises'
import {join} from 'node:path'
import {setup} from './rc022_subagent_fixture.mts'
const root=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source');await mkdir(join(root,'child','nested'),{recursive:true})
const fixture=await setup(join(root,'journal'),root),{ctx}=fixture,rows:any[]=[]
try{
 const agent=(await ctx.agents.create({sessionId:'one',meta:{cwd:root}})).agent,other=(await ctx.agents.create({sessionId:'two',meta:{cwd:root}})).agent,service=ctx.workingDirectory
 async function result(name:string,callback:any){try{rows.push({name,value:await callback()})}catch(error:any){rows.push({name,error:{code:error.code,message:error.message}})}}
 await result('initial',()=>service.ensure(agent));await result('change',()=>service.set(agent,'child'));rows.push({name:'independent',other:service.get(other.session),original:agent.session.header.cwd})
 rows.push({name:'serialized',values:await Promise.all([service.set(agent,'nested'),service.set(agent,'..')])})
 await result('empty',()=>service.set(agent,''));await result('missing',()=>service.set(agent,'missing'));await rmdir(join(root,'child','nested'));await rmdir(join(root,'child'));await result('recover',()=>service.ensure(agent))
 const assembly=await ctx.systemPrompt.assemble({agent,scope:agent,signal:fixture.signal});rows.push({name:'context',value:assembly.contexts.filter((entry:any)=>entry.name==='working-directory:current')})
 rows.push({name:'changes',values:agent.session.snapshotEvents().filter((event:any)=>event.type==='working-directory/change').map((event:any)=>event.data.cwd),notices:agent.inbox.nextStep.filter((message:any)=>message.source.kind==='working-directory').map((message:any)=>message.content[0].text)})
}finally{await ctx.fiber.dispose()}
function normalize(value:any):any{if(typeof value==='string')return value.split(JSON.stringify(root).slice(1,-1)).join('<root>').split(root).join('<root>');if(Array.isArray(value))return value.map(normalize);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)]));return value}
process.stdout.write(JSON.stringify(normalize(rows)))
