import fs from 'node:fs/promises'
import http from 'node:http'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:OTel}=await load('packages/telemetry/otel/src/index.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
const session={sessionId:'fixture-session',event:{seq:1,time:1700000000123.5,type:'fixture',data:{text:'synthetic'}},attributes:{flag:true,count:2,fraction:1.25}}
const event={eventName:'fixture',body:'synthetic',timestamp:1700000000123.5,attributes:{flag:true,count:2,fraction:1.25}}
for(const entry of inputs){
 const captures:any[]=[],warnings:any[]=[],channels:any[]=[],ctx=new Context();let error:any=null
 const server=http.createServer(async(req,res)=>{
  const chunks=[];for await(const chunk of req)chunks.push(chunk)
  const data=Buffer.concat(chunks);captures.push({path:req.url,document:JSON.parse(data.toString('utf8')),bytes:data.length})
  res.writeHead(200,{'content-length':2});res.end('{}')
 })
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
 const address=server.address() as any
 try{
  const fiber=await ctx.plugin(OTel),service=ctx.otel,mounted=service!==undefined
  function options(label:string){return {scope:{name:label,version:'1'},resourceAttributes:{'service.name':label},
   exporter:{url:`http://127.0.0.1:${address.port}/${label}`},processor:{maxExportBatchSize:512,scheduledDelayMillis:2147483647},
   onFailure(message:string,error?:Error){warnings.push({message,error:error?.message??null})}}}
  if(entry.mode.startsWith('invalid')){
   const selected:any=options('invalid');selected.maxRequestBytes=0;selected.exporter.timeoutMillis=0
   try{if(entry.mode==='invalid-session')service.createSessionLogReporter(selected);else service.createEventReporter(selected)}
   catch(failure:any){error=failure.message}
  }else if(entry.mode!=='mount-only'){
   for(const label of ['event-a','event-b','session-a','session-b'])channels.push(label.startsWith('event')?service.createEventReporter(options(label)):service.createSessionLogReporter(options(label)))
   if(entry.mode==='provider-unmounted')await fiber.dispose()
   function emit(index:number){
    const original=Date.now;Date.now=()=>1700000000999
    try{if(index<2)channels[index].emit(event);else channels[index].reportSessionLog(session)}finally{Date.now=original}
   }
   for(let i=0;i<4;i++)emit(i)
   await channels[0].shutdown();await channels[2].shutdown()
   for(let i=0;i<4;i++)emit(i)
   await channels[1].shutdown();await channels[3].shutdown()
  }
  await fiber.dispose()
  rows.push({mounted,after:ctx.get('otel',false)!==undefined,captures:captures.sort((a,b)=>a.path.localeCompare(b.path)),warnings,error})
 }finally{for(const channel of channels)await channel.shutdown();await ctx.fiber.dispose();await new Promise<void>(resolve=>server.close(()=>resolve()))}
}
process.stdout.write(JSON.stringify(rows))
