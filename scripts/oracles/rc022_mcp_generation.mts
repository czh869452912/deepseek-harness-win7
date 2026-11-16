import {load} from './rc022_subagent_fixture.mts'
const {McpGeneration}=await load('packages/mcp/mcp-client/src/generation.ts')
const {describeError}=await load('packages/mcp/mcp-client/src/diagnostic.ts')
const modes=['normal','no-close-event','close-throw','close-throw-after-event','local-unsettled','operation-timeout','connect-timeout','invalid-config']
const rows=[],keepAlive=setInterval(()=>{},100)
try{
 for(const mode of modes){
  const events:any[]=[];let release:any;const held=new Promise<void>(resolve=>release=resolve)
  const client:any={transport:undefined,
   async connect(transport:any,_options:any){this.transport=transport;await transport.start();events.push('started');if(mode==='connect-timeout')await held},
   async close(){events.push('close');if(mode==='no-close-event')return;if(mode==='close-throw')throw new Error('cleanup failed');await this.transport.close();if(mode==='close-throw-after-event')throw new Error('cleanup failed')}
  }
  const generation=new McpGeneration(client,10,describeError)
  const config={transport:'streamable-http',url:mode==='invalid-config'?'::':'http://127.0.0.1:1',headers:{}}
  let connected:any
  try{await generation.connect(config,mode==='connect-timeout'?1:1000);connected={ok:true}}catch(error){connected={error:describeError(error)}}
  let pending:any,pendingOutcome:any
  if(['local-unsettled','operation-timeout'].includes(mode)){
   pending=generation.run(async()=>{events.push('work-started');await held;events.push('work-finished');return 'late'},mode==='operation-timeout'?1:undefined)
   pendingOutcome=pending.then((value:any)=>({value}),(error:any)=>({error:describeError(error)}))
   for(let i=0;i<4;i++)await Promise.resolve()
   if(mode==='operation-timeout')await pendingOutcome
  }
  const beforePending=(generation as any).pending.size
  const closing=generation.close(),sameClose=generation.close()===closing,result=await closing
  const interrupted=pendingOutcome===undefined?null:await pendingOutcome
  const beforeRelease={pending:(generation as any).pending.size,events:[...events]}
  release();if(client.transport)await client.transport.close()
  for(let i=0;i<16;i++)await Promise.resolve()
  const repeated=await generation.close()
  rows.push({mode,connected,beforePending,sameClose,result,interrupted,beforeRelease,afterPending:(generation as any).pending.size,events,resultIdentity:result===repeated,repeatResult:repeated})
 }
 process.stdout.write(JSON.stringify(rows))
}finally{clearInterval(keepAlive)}
