import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const catalog=await load('packages/subagent/subagent/src/catalog.ts'),names=await load('packages/subagent/subagent/src/names.ts'),definition=catalog.subagentCatalogProjectionDefinition
const data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=data.names.map((value:string)=>({kind:'name',value,valid:names.isAgentName(value)}))
for(const path of [undefined,'','a','a/b'])for(const name of [undefined,'c']){const joined=names.joinAgentPath(path,name);rows.push({kind:'path',address:names.agentAddress(path,'legacy-id'),joined:joined??null,parent:joined===undefined||joined===''?null:names.parentAgentPath(joined)})}
const reservations=new names.SiblingNameReservations(),left={},right={},committed=new Set(['agent-1','saved'])
const first=reservations.reserve(left,committed),second=reservations.reserve(left,committed),other=reservations.reserve(right,committed),errors:any[]=[]
for(const name of ['saved',first.name,'lead','Bad'])try{reservations.reserve(left,committed,name)}catch(error:any){errors.push({code:error.code,message:error.message})}
first.release();first.release();const replacement=reservations.reserve(left,committed);first.release();const after=reservations.reserve(left,committed)
rows.push({kind:'reservations',names:[first.name,second.name,other.name,replacement.name,after.name],errors})
for(const entry of [second,other,replacement,after])entry.release();const fresh=reservations.reserve(left,new Set());rows.push({kind:'released',name:fresh.name});fresh.release()
const next=reservations.reserve(left,new Set());fresh.release();const concurrent=reservations.reserve(left,new Set());rows.push({kind:'stale-pool',names:[next.name,concurrent.name]});next.release();concurrent.release()
for(const fact of data.facts){const initial={inheritedEventCount:1},ignored=definition.apply(initial,{type:'subagent/catalog',seq:0,data:fact}),row:any={kind:'fact',fact,inheritedSame:ignored===initial}
 try{const state=definition.apply(initial,{type:'subagent/catalog',seq:1,data:fact}),restored=definition.stateSchema.parse(state);Object.assign(row,{accepted:true,view:definition.wire.viewSchema.parse(definition.wire.view(restored)),detached:restored!==state,previousSame:definition.apply(state,{type:'session/title',seq:2})===state})}catch{row.accepted=false}rows.push(row)
}
let state:any={inheritedEventCount:0};const retained:any[]=[],valid=data.facts[6]
for(let index=0;index<190;index++){state=definition.apply(state,{type:'subagent/catalog',seq:index,data:{...valid,childId:String(index)}});if([63,127].includes(index))retained.push(state.head)}
const restored=definition.stateSchema.parse(state);rows.push({kind:'chunks',capacity:state.head.values.length,count:definition.wire.view(restored).length,shared:state.head.previous===retained[1]&&retained[1].previous===retained[0],names:[...catalog.catalogNames(definition.wire.view(state))].sort()})
for(const bad of [{inheritedEventCount:0,head:null},{inheritedEventCount:0,head:{values:[]}},{inheritedEventCount:0,head:{values:[valid],previous:null}},{inheritedEventCount:0,head:{values:Array(65).fill(valid)}},{inheritedEventCount:0,surprise:true}]){rows.push({kind:'checkpoint',accepted:definition.stateSchema.safeParse(bad).success})}
const recorded:any[]=[],parent={append:(type:string,data:any)=>recorded.push({type,data})}
catalog.establishCatalogChild(parent,{id:'local',createdAt:10},{mode:'continuable',label:'Local'},'local');const now=Date.now
try{Date.now=()=>100;catalog.establishExternalCatalogChild(parent,'remote','External','remote')}finally{Date.now=now}
rows.push({kind:'recorded',rows:recorded});process.stdout.write(JSON.stringify(rows))
