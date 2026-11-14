import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,{Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/context.ts')).href)
const result:any={},ctx=new Context(),seen:any[]=[]
const listener=(...args:any[])=>{const next=args.pop();seen.push(args);return next('ignored',42)}
ctx.on('chain',listener);ctx.on('chain',listener)
result.inner=ctx.waterfall('chain','a',1,(...args:any[])=>args);result.listener_args=seen
for(const [mode,values] of [['no-inner',[]],['seed-only',['seed']],['non-callable',[1,false]]]as const){
  const ctx=new Context();try{ctx.waterfall('chain',...values)}catch(error:any){result[mode]=error.name}await ctx.fiber.dispose()
}
const veto=new Context();veto.on('chain',()=> 'veto');result.veto=veto.waterfall('chain')
const named=new Context();named.on('chain',(next:any)=>next);result.named_next=named.waterfall('chain','original',()=> 'end')
const asyncCtx=new Context(),trace:string[]=[];let release!:()=>void;const gate=new Promise<void>(r=>release=r)
async function inner(){trace.push('inner-before');await gate;trace.push('inner-after');return 'end'}
asyncCtx.on('chain',async(_value:any,next:any)=>{trace.push('outer-before');const pending=next();trace.push('outer-next-returned');const value=await pending;trace.push('outer-after');return value+'!'})
const pending=asyncCtx.waterfall('chain','input',inner);result.prefix=[...trace];release();result.async_result=await pending;result.trace=trace
const awaitSync=new Context(),syncTrace:string[]=[]
awaitSync.on('chain',async(_value:any,next:any)=>{syncTrace.push('before');const pending=next();syncTrace.push('next-returned');const answer=await pending;syncTrace.push('after');return answer})
result.await_sync=await awaitSync.waterfall('chain','input',()=>{syncTrace.push('inner');return 42});result.await_sync_trace=syncTrace
await awaitSync.fiber.dispose()
for(const owner of [ctx,veto,named,asyncCtx])await owner.fiber.dispose()
process.stdout.write(JSON.stringify(result))
