import {PassThrough} from 'node:stream'
import {load} from './rc022_subagent_fixture.mts'
const {JsonRpcLineTransport}=await load('packages/sdk/protocol/src/transport.ts'),rows:any[]=[]
for(const kind of ['close-before-start','eof','error','final-frame','pre-abort','write-failure','error-shape','error-array','missing-result','malformed-json','utf8-split']){
 const incoming=new PassThrough(),writes:string[]=[],output={write:(chunk:string)=>{writes.push(chunk);return true}},transport=new JsonRpcLineTransport(incoming,output as any),original=Error('first failure'),controller=new AbortController(),seen:any[]=[]
 transport.onNotification((method:any,params:any)=>seen.push({method,params}))
 if(kind==='close-before-start')transport.close();transport.start()
 const take=async(signal?:AbortSignal)=>{try{return {value:await transport.request('probe',{},signal)??null}}catch(error){const e=error as any;return {error:e.message,original:e===original,code:e.code??null,data:e.data??null}}}
 try{
  if(kind==='pre-abort')controller.abort('cancelled')
  if(kind==='write-failure')(transport as any).output={write:()=>{throw Error('write failed')}}
  const pending=take(controller.signal)
  if(kind==='eof'||kind==='error'){
   if(kind==='eof')incoming.emit('end');else incoming.emit('error',original)
   incoming.emit('error',Error('second failure'));incoming.emit('end');transport.close();controller.abort('later')
  }else if(!['close-before-start','pre-abort','write-failure'].includes(kind)){
   const id=JSON.parse(writes[0]!).id;let frame:any={id,result:{ok:true}}
   if(kind==='error-shape')frame={id,error:{code:'bad',message:4,data:{why:1}}}
   if(kind==='error-array')frame={id,error:[]}
   if(kind==='missing-result')frame={id}
   if(kind==='malformed-json')incoming.emit('data','not json\nnull\n[]\n{"method":"bad","params":{"n":NaN}}\n')
   if(kind==='utf8-split')for(const byte of Buffer.from(JSON.stringify({method:'unicode',params:{text:'你好'}})+'\n'))incoming.emit('data',Buffer.from([byte]))
   incoming.emit('data',JSON.stringify(frame)+'\n');if(kind==='final-frame')incoming.emit('end')
  }
  const first=await pending;let later:any=null
  if(kind==='write-failure'){
   (transport as any).output=output;const next=take();const id=JSON.parse(writes[0]!).id;incoming.emit('data',JSON.stringify({id,result:'recovered'})+'\n');later=await next
  }else if(['close-before-start','eof','error','final-frame'].includes(kind))later=await take(controller.signal)
  rows.push({name:kind,first,later,seen,pending:(transport as any).pending.size})
 }finally{transport.close();if(incoming.listenerCount('data')||incoming.listenerCount('error')||incoming.listenerCount('end'))throw Error('listeners retained')}
}
console.log(JSON.stringify(rows))
