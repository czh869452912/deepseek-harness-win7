import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Registry=(await load('packages/typert/registry/src/index.ts')).default,Access=(await load('packages/api/remote-access/src/index.ts')).default,Gateway=(await load('packages/api/gateway/src/index.ts')).default
const {Remote,TypertRemoteService}=await load('packages/typert/protocol/src/index.ts'),{Peer}=await load('packages/client/connection/src/peer.ts'),{z}=await load('node_modules/zod/index.js')
const cases=['plain','root-bytes','nested-bytes','empty-bytes','shared','undefined','function','json-omissions','cycle','to-json-bytes','getter','date','strict-encode','strict-absent-encode','strict-nullish-fallback','numeric-keys'],rows:any[]=[],bytes=(text:string)=>new TextEncoder().encode(text)
function fixture(name:string,calls:any[]):any{
 const shared={data:bytes('abc')}
 if(name==='plain')return {text:'中文',number:2,empty:null}
 if(name==='root-bytes')return bytes('abc')
 if(name==='nested-bytes')return {'a.b/c':[bytes('01234').subarray(1,4),{data:bytes('xy')}],['__proto__']:{data:bytes('z')}}
 if(name==='empty-bytes')return {data:new Uint8Array()}
 if(name==='numeric-keys')return {'10':bytes('ten'),'2':bytes('two'),x:bytes('x')}
 if(name==='shared')return {a:shared,b:shared}
 if(name==='undefined')return undefined
 if(name==='function')return ()=>undefined
 if(name==='json-omissions')return {missing:undefined,fn:()=>undefined,array:[undefined,()=>undefined,NaN,Infinity]}
 if(name==='cycle'){const value:any={};value.cycle=value;return value}
 if(name==='to-json-bytes')return {nested:{toJSON(key:string){calls.push(key);return {data:bytes('json')}}}}
 if(name==='getter')return {get data(){calls.push('data');return bytes('getter')}}
 if(name==='date')return new Date('2026-01-02T03:04:05.006Z')
 return {raw:bytes('strict')}
}
for(const name of cases){const ctx=new Context();await ctx.plugin(Registry);await ctx.plugin(Access);await ctx.plugin(Gateway);const calls:any[]=[]
 class Fixture extends TypertRemoteService{constructor(child:any){super(child,'fixture')}@Remote value(){return fixture(name,calls)}}
 try{await ctx.plugin(Fixture)
  if(name.startsWith('strict')){const codec:any={mode:'strict',typeSymbol:'Result',create:()=>z.unknown()};if(name!=='strict-absent-encode')codec.encode=(value:any,write:any)=>{const projected={data:write(value.raw,['data'])};return name==='strict-nullish-fallback'?null:projected};ctx.typert.register({package:'fixture',face:'host',model:{},schemas:[],invocations:[{id:'fixture#value',service:'fixture',namespace:'fixture',method:'value',parameters:[],invocation:{kind:'direct'},result:codec}]})}
  const peer=new Peer(ctx,{principal:{kind:'owner'}}),result=await ctx.typertGateway.invokeRpc('fixture/value',{args:{}},new AbortController().signal,peer)
  if(result.attachments)result.attachments=result.attachments.map((item:any)=>({path:item.path,bytes:[...item.bytes]}))
  rows.push({name,result,calls})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
