import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Registry=(await load('packages/typert/registry/src/index.ts')).default
const {callResources,eventResources}=await load('packages/api/gateway/src/access.ts')
const cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],signal=new AbortController().signal
function reader(spec:any){return (...values:any[])=>{
 if(spec[0]==='throw')throw Error('fixture private failure')
 if(spec[0]==='undefined')return undefined
 if(spec[0]==='constant')return spec[1]
 if(spec[0]==='arg')return values[spec[1]]
 if(spec[0]==='signal')return values[spec[1]]===signal?'signal':'wrong'
 if(spec[0]==='named')return values[0].args[spec[1]]
 throw Error('bad fixture reader')
}}
for(const c of cases){const ctx=new Context();await ctx.plugin(Registry);try{
 const t=ctx.typert,readers=Object.fromEntries(Object.entries(c.readers??{}).map(([kind,spec])=>[kind,reader(spec)]));let value
 if(c.event)value=eventResources(readers,c.args)
 else{
  for(const d of c.declarations){const {kind,...provider}=d;if('resolve'in provider)provider.resolve=reader(provider.resolve);t.resources.register(kind,provider)}
  const parameters=c.parameters.map((name:string)=>{const p:any={name,wire:name};if(c.lookups?.[name]!==undefined){p.lookup=name;t.lookups.register(name,{parameter:name,wire:name,hostTypeSymbol:'host',wireTypeSymbol:'wire',resource:c.lookups[name],resolve:()=>undefined});t.lookups.configure(name,()=>undefined)}return p})
  let invocation:any={kind:'direct'}
  if('context'in c){t.contexts.registerHost('scope',{wire:'scopeId',wireTypeSymbol:'wire',resource:c.context,resolve:()=>undefined,identity:()=>undefined});t.contexts.configureHost('scope',()=>undefined);invocation={kind:'context',context:'scope',wire:'scopeId'}}
  const descriptor:any={parameters,invocation};if(c.cancellation)descriptor.cancellation={parameter:'signal'}
  value=callResources(t,readers,descriptor,c.args,signal)
 }rows.push({name:c.name,value:value??null})
}finally{await ctx.fiber.dispose()}}
const ctx=new Context();await ctx.plugin(Registry);const changes:any[]=[];try{
 ctx.typert.resources.subscribe((change:any)=>changes.push(change))
 class Resolver{resolve(){return 'prototype'}}const undo=ctx.typert.resources.register('shelf',new Resolver()),errors=[]
 for(const [kind,declaration] of [['shelf',{field:'id'}],['global',{field:'id'}],['empty',{}]]){try{ctx.typert.resources.register(kind,declaration)}catch(error:any){errors.push(error.message)}}
 let frozen=false;try{ctx.typert.resources.entries()[0].kind='changed'}catch{frozen=true}
 undo();undo();rows.push({name:'ownership',value:{changes,errors,frozen,empty:ctx.typert.resources.entries().length===0}})
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
