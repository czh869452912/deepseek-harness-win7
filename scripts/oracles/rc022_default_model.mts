import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Loader}=await load('vendor/loader/src/index.ts'),{default:Model}=await load('packages/core/agent-default-model/src/index.ts')
const rows:any[]=[],ctx=new Context()
try{
 await ctx.plugin(Loader);ctx.loader.builtins.model=Model
 const key=await ctx.loader.create({name:'cordis:model',config:{provider:'p',model:'m'}}),entry=ctx.loader.resolve(key),fiber=entry.fiber!
 await fiber.await();const service=ctx.agentDefaultModel
 const replace=async(value:any)=>{await entry.update({config:value});await entry.fiber!.await()}
 rows.push({step:'initial',value:service.currentSelection()})
 await replace({provider:'q',model:'n',reasoningEffort:'high'})
 const detached=service.currentSelection();detached.model='mutated'
 rows.push({step:'live',value:service.currentSelection(),sameFiber:entry.fiber===fiber})
 await replace({provider:'p',model:'m'});await service.saveSelection({provider:'ignored',model:'ignored'})
 rows.push({step:'no-editor',value:service.currentSelection()})
 const entered=Promise.withResolvers<void>(),release=Promise.withResolvers<void>(),calls:any[]=[]
 ctx.provide('configEditor',{async edit(owner:any,change:any){const value=change();calls.push({owner:owner===entry,value});if(value.model==='rejected'){entered.resolve();await release.promise;throw Error('read-only document')}await replace(value)}} as any)
 const first=service.saveSelection({provider:'p',model:'rejected'});const caught=first.catch(error=>error.message)
 const next:any={provider:'test',model:'final',reasoningEffort:7},last=service.saveSelection(next);next.model='mutated';await entered.promise
 rows.push({step:'held',calls:[...calls]});release.resolve();rows.push({step:'rejected',error:await caught});await last
 rows.push({step:'saved',calls:[...calls],value:service.currentSelection()})
 await service.saveSelection({provider:'test',model:'clear'});rows.push({step:'cleared',value:service.currentSelection()})
 const policy:any[]=[];ctx.provide('settings',{configure(value:any,owner:any){policy.push({policy:value,owner:owner.entry===entry});return ()=>policy.push('released')}} as any)
 await ctx.fiber.await();rows.push({step:'settings',calls:[...policy]});await fiber.dispose();rows.push({step:'disposed',calls:[...policy]})
}finally{await ctx.fiber.dispose()}
const standalone=new Context()
try{await standalone.plugin(Model,{provider:'alone',model:'original'});standalone.provide('configEditor',{edit(){throw Error('no entry')}} as any);await standalone.agentDefaultModel.saveSelection({provider:'ignored',model:'ignored'});rows.push({step:'no-entry',value:standalone.agentDefaultModel.currentSelection()})}finally{await standalone.fiber.dispose()}
console.log(JSON.stringify(rows))
