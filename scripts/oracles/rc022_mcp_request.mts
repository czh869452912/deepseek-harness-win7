import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
import {getEventListeners} from 'node:events'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const {Client,StreamableHTTPClientTransport,SdkError}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')).href)
const records=()=>fs.existsSync(input.log)?fs.readFileSync(input.log,'utf8').split('\n').filter(Boolean).map(line=>JSON.parse(line)):[]
const output=[],realNow=Date.now
try{
 for(const [index,fixture] of input.cases.entries()){
  const urlPath='/source/'+index+'/'+fixture.mode,client=new Client({name:'dsh-mcp-client',version:'0.0.1'},{capabilities:{},versionNegotiation:{mode:'auto'}}),transport=new StreamableHTTPClientTransport(new URL(input.url+urlPath)),controller=new AbortController(),progress:any[]=[]
  let clock=0;Date.now=()=>clock
  const reason=({text:'stop',null:null,object:{stop:true},error:new Error('stop'),sdk:new SdkError('OWNED_ABORT','stop',{owned:true}),zero:0,false:false,array:['a',2]} as any)[fixture.abort]
  let result,elapsed
  try{
   await client.connect(transport)
   const original=transport.onmessage
   transport.onmessage=(packet:any,...args:any[])=>{if(packet.method==='notifications/progress'&&client._responseHandlers.has(Number(packet.params.progressToken)))clock=100*packet.params.progress;return original?.(packet,...args)}
   const options:any={...fixture.options,signal:controller.signal}
   if(options.onprogress)options.onprogress=(value:any)=>progress.push(value)
   if(fixture.pre)controller.abort(reason)
   const pending=client.listTools(undefined,options)
   // Keep an immediately rejected pre-abort owned while inspecting the peer.
   pending.catch(()=>{})
   if(('abort' in fixture&&!fixture.pre)||fixture.disconnect){
    let observed=false
    for(let attempt=0;attempt<1000;attempt++){
     if(records().some(item=>item.path===urlPath&&item.packet.method==='tools/list')){observed=true;break}
     await new Promise(resolve=>setTimeout(resolve,2))
    }
    if(!observed)throw Error('serving request not observed')
    if(fixture.disconnect)await client.close();else controller.abort(reason)
   }
   try{result={value:await pending}}
   catch(error:any){result={error:{name:error.name,message:error.message,...error.code!==undefined?{code:error.code}:{},...error.data!==undefined?{data:error.data}:{}},reasonIdentity:error===reason}}
   const expectsCancellation=fixture.mode.startsWith('legacy-')&&!fixture.pre&&!fixture.disconnect&&('abort' in fixture||fixture.mode.endsWith('hold')||(fixture.options.onprogress&&!fixture.options.resetTimeoutOnProgress))
   if(expectsCancellation){
    const deadline=performance.now()+1000
    while(!records().some(item=>item.path===urlPath&&item.packet.method==='notifications/cancelled')){
     if(performance.now()>=deadline)throw Error('legacy cancellation not observed')
     await new Promise(resolve=>setTimeout(resolve,2))
    }
   }else if('abort' in fixture||fixture.mode.endsWith('hold')||(fixture.options.onprogress&&!fixture.options.resetTimeoutOnProgress))await new Promise(resolve=>setTimeout(resolve,30))
   elapsed=clock
  }finally{await client.close();await transport.close()}
  const packets=records().filter(item=>item.path===urlPath&&['tools/list','notifications/cancelled'].includes(item.packet.method)).map(item=>item.packet)
  output.push({case:fixture,result,progress,elapsed,packets,listeners:getEventListeners(controller.signal,'abort').length})
 }
}finally{Date.now=realNow}
process.stdout.write(JSON.stringify(output))
