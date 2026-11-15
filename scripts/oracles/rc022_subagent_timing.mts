import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const projection=await load('packages/subagent/subagent/src/projection.ts'),fork=await load('packages/subagent/subagent-fork-in-process/src/index.ts')
const data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),definitions=[projection.subagentTimingProjectionDefinition,projection.subagentIdentityProjectionDefinition],rows:any[]=[]
for(const [index,events] of data.timelines.entries()){
 const states=definitions.map(def=>def.init(null,0)),steps:any[]=[]
 for(const [seq,raw] of events.entries()){
  const values:any[]=[],same:boolean[]=[]
  for(const [position,definition] of definitions.entries()){
   const previous=states[position];states[position]=definition.apply(previous,{...raw,seq});definition.stateSchema.parse(states[position]);values.push(definition.wire.viewSchema.parse(definition.wire.view(states[position])));same.push(states[position]===previous)
  }steps.push({values,same})
 }rows.push({kind:'timeline',index,steps})
}
for(const value of data.schemas)rows.push({kind:'schema',value,valid:definitions[0].wire.viewSchema.safeParse(value).success})
let provider:any;fork.apply({subagents:{registerProvider:(value:any)=>provider=value}},{providerName:'fork'})
for(const cut of [0,1,3,4,5]){
 const events=['turn/start','assistant/message','turn/end','turn/start','assistant/chunk'].slice(0,cut).map((type,seq)=>({type,seq,time:seq,data:{}}))
 const spec=await provider.prepareContinuable({parent:{session:{snapshotEvents:()=>events.slice()}}}),captured=JSON.stringify(spec)
 events.push({type:'turn/end',seq:events.length,time:10,data:{}});rows.push({kind:'fork',cut,spec,unchanged:JSON.stringify(spec)===captured})
}
process.stdout.write(JSON.stringify(rows))
