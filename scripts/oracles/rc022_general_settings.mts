import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Loader}=await load('vendor/loader/src/index.ts'),General=await load('packages/client/ui-settings-general/src/index.ts'),ctx=new Context(),rows:any[]=[],calls:any[]=[]
try{
 await ctx.plugin(Loader);ctx.provide('settings',{configure(policy:any,owner:any){calls.push({policy,entry:owner.entry.id});return ()=>calls.push('released')}} as any);ctx.loader.builtins.general=General
 const key=await ctx.loader.create({id:'general',name:'cordis:general',config:{}}),entry=ctx.loader.resolve(key),fiber=entry.fiber!;await fiber.await()
 for(const value of [{},{welcomeNoticeVersion:'v1'},{welcomeNoticeVersion:'0.2'},{}]){await entry.update({config:value});await entry.fiber!.await();const ref=fiber.effectiveConfig.welcomeNoticeVersion.get();rows.push({step:'value',value:ref===undefined?{}:{welcomeNoticeVersion:ref},sameFiber:entry.fiber===fiber})}
 for(const value of [null,7,false,[]]){let accepted=true;try{fiber.resolveConfig({welcomeNoticeVersion:value})}catch{accepted=false}rows.push({step:'invalid',input:value,accepted})}
 rows.push({step:'settings',calls:[...calls]});await fiber.dispose();rows.push({step:'disposed',calls:[...calls]})
}finally{await ctx.fiber.dispose()}
console.log(JSON.stringify(rows))
