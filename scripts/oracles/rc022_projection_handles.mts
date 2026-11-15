import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Store}=await load('packages/core/session/src/index.ts'),{default:Registry}=await load('packages/session/session-projection/src/index.ts')
const rows=[]
for(const action of ['retained','shared','lazy','summary','conflicts','legacy','return','effect','yield','drive','listener-failure','unit-failure','handoff','mutated','reader-failure','undefined','double-release']){
 const ctx=new Context(),calls:any={},changes:any[]=[],events:any[]=[];let registration:any,ownerCtx:any
 function definition(key='count',version:any=1,step=1,wire=true,summary=true):any{
  calls[key]??={init:0,apply:0}
  return {key,stateVersion:version,stateSchema:{parse:(v:any)=>v},init:()=>{calls[key].init++;return 0},apply:(state:number)=>{calls[key].apply++;if(action==='unit-failure'&&key==='second')throw new Error('unit failed');return state+step},...wire?{wire:{viewSchema:{parse:(v:any)=>v},view:(v:any)=>v,summary}}:{}}
 }
 try{
  await ctx.plugin(Store);await ctx.plugin(Registry);const store=ctx.sessions,registry=ctx.sessionProjections,session=store.create('live')
  const owner=await ctx.plugin({inject:['sessionProjections'],apply(inner:any){ownerCtx=inner;registration=inner.sessionProjections.register(definition());if(action==='return')return registration;if(action==='effect')inner.effect(()=>registration);if(action==='yield')inner.effect(function*(){yield registration})}})
  const handle=await registration,row:any={action};const append=()=>session.append('turn/start',{turn:session.seq+1})
  if(action==='retained'){
   const reader=handle.readerFor(session);row.before={...calls.count};await owner.dispose();row.unreadReleased=registry.checkpoint(session);append();row.retained=reader();row.released=registry.checkpoint(session)
   const replacement=await registry.register(definition('count',2,10));row.old=reader();row.new=replacement.stateOf(session);row.checkpoint=registry.checkpoint(session)
  }else if(action==='shared'){
   const second=await registry.register(definition());append();row.initial=[handle.stateOf(session),second.stateOf(session)];await handle.dispose();append();row.one=registry.snapshot(session);await second.dispose();append();row.releasedBefore=registry.checkpoint(session);row.old=handle.stateOf(session);row.releasedAfter=registry.checkpoint(session);row.floor=registry.restoreFloor({})??null;row.snapshot=registry.snapshot(session)
  }else if(action==='lazy'){
   await registry.register(definition('unrelated',1,1,false));const reader=handle.readerFor(session);row.before=structuredClone(calls);row.value=reader();row.after=structuredClone(calls);const other=store.create('other');other.append('turn/start',{turn:1});row.bound=[reader(),handle.readerFor(other)()]
  }else if(action==='summary'){
   await registry.register(definition('excluded',1,1,true,false));await registry.register(definition('host',1,1,false));const keys=registry.summaryKeys(),second=await registry.register(definition());row.sharedStable=keys===registry.summaryKeys();row.snapshot=registry.snapshot(session,keys);row.calls=structuredClone(calls);await second.dispose();row.partialStable=keys===registry.summaryKeys();await handle.dispose();row.keys=[...registry.summaryKeys()].sort();row.invalidated=keys!==registry.summaryKeys()
  }else if(action==='conflicts'){
   row.errors=[];for(const value of [definition('count',2),definition('count',1,1,true,false),definition('count',1,1,false),definition('bad',-1),definition('bad',1.5),definition('bad',true)]){const valueRegistration:any=registry.register(value);try{await valueRegistration}catch(error:any){row.errors.push(error.message)}await valueRegistration()}row.snapshot=registry.snapshot(session)
  }else if(action==='legacy'){
   await registration();append();Object.assign(row,{value:handle.stateOf(session),snapshot:registry.snapshot(session),checkpoint:registry.checkpoint(session)})
  }else if(['return','effect','yield'].includes(action)){
   row.before=registry.snapshot(session);await owner.dispose();append();row.after=registry.snapshot(session);row.retained=handle.stateOf(session)
  }else if(['drive','listener-failure','unit-failure'].includes(action)){
   await registry.register(definition('second'));registry.onChanged((s:any,key:string,value:any,seq:number)=>{changes.push([key,value,seq]);if(action==='listener-failure')throw new Error('listener failed')});registry.onEventChanged((s:any,value:any,seq:number)=>events.push([value,seq]));append();Object.assign(row,{changes,events,checkpoint:action==='unit-failure'?null:registry.checkpoint(session)})
  }else if(action==='mutated'){
   const value=definition('mutable'),wire=value.wire,mutable=await registry.register(value);value.init=()=>5;value.apply=(state:number)=>state+10;wire.view=(state:number)=>state*2;row.before=mutable.stateOf(session);append();row.after=registry.snapshot(session)
  }else if(action==='reader-failure'){
   const failure=new Error('reader cannot initialize'),value=definition('broken');value.init=()=>{throw failure};const broken=await registry.register(value),reader=broken.readerFor(session);row.before={...calls.broken};try{reader()}catch(error:any){row.error=error.message;row.same=error===failure}
  }else if(action==='undefined'){
   const value=definition('optional',1,1,false);value.init=()=>undefined;value.apply=(state:any,event:any)=>event.data.turn;const optional=await registry.register(value);row.undefined=optional.readerFor(session)()===undefined;append();row.value=optional.stateOf(session)
  }else if(action==='double-release'){
   const second=await registry.register(definition());await handle.dispose();await handle.dispose();await owner.dispose();append();row.before=registry.snapshot(session);await second.dispose();await second.dispose();row.after=registry.snapshot(session)
  }else if(action==='handoff'){
   const pending=ownerCtx.sessionProjections.register(definition('handoff')),disposed=owner.dispose();try{await pending;row.exposed=true}catch(error:any){row.error=error.message}await disposed;row.snapshot=registry.snapshot(session)
  }
  rows.push(row)
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
