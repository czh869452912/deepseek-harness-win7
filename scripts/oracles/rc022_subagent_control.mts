import {join} from 'node:path'
import {readFileSync} from 'node:fs'
import {load,setup} from './rc022_subagent_fixture.mts'
const {validateControlRequest,rejectPrompt}=await load('packages/subagent/subagent/src/control.ts'),{SubagentError}=await load('packages/subagent/subagent/src/error.ts'),{AttachmentError}=await load('packages/attachment/attachment/src/index.ts')
const input=JSON.parse(readFileSync(process.argv[4]!,'utf8')),fixture=await setup(join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source')),{ctx,service,signal}=fixture,rows:any[]=[]
const failure=(error:any)=>({code:error.code??null,message:error.message??String(error),details:error.details??null})
try{
 for(const test of input.validation){let value:any;try{validateControlRequest(test.method,test.payload);value={accepted:true}}catch(error){value=failure(error)}rows.push({kind:'validation',value})}
 for(const code of [...input.codes,'attachment','internal']){const error=code==='attachment'?new AttachmentError('image refused','TOO_MANY_IMAGES'):code==='internal'?Error('private detail'):new SubagentError('private detail',code);try{rejectPrompt(error,'child',signal)}catch(rejected:any){rows.push({kind:'rejection',value:failure(rejected),cause:rejected.cause===error})}}
 const parent=(await ctx.agents.create({sessionId:'root',agentOptions:{provider:'script',model:'model'}})).agent
 const receipt=await service.startActivation({provider:'spawn',parent,childId:'child',name:'worker',label:'Task',prompt:[{type:'text',text:'Task'}],signal,delivery:'caller'})
 while(ctx.agents.get('child').status!=='running')await new Promise(r=>setTimeout(r,1))
 const received:any[]=[];ctx.on('agent/inbox/inserted',({agent,message}:any)=>{if(message.source.rpcId)received.push({target:agent.id,source:message.source,content:message.content})})
 for(const delivery of ['queue','steer','cold']){
  if(delivery==='cold')await receipt.dispose()
  const callerService=ctx.extend({invocation:{peer:{principal:delivery==='queue'?{kind:'owner'}:{kind:'test-guest',guest:'g1'}}}}).subagents
  const answer=await callerService.prompt({requestId:'rpc-'+delivery,childSessionId:'child',delivery:delivery==='steer'?'steer':'queue',content:[{type:'text',text:delivery}],clientTimeZone:'Asia/Shanghai'},signal)
  rows.push({kind:'delivery',name:delivery,accepted:!!answer.messageId,message:received.at(-1)})
 }
 for(const request of [{childSessionId:'',delivery:'queue'},{childSessionId:'child',delivery:'later'},{childSessionId:'child',delivery:'queue',clientTimeZone:'bad-zone'}]){
  try{await service.prompt({requestId:'invalid',content:[{type:'text',text:'invalid'}],...request},signal)}catch(error){rows.push({kind:'invalid',value:failure(error)})}
 }
 for(const target of ['child','absent','']){try{rows.push({kind:'interrupt',target,value:service.interruptByUser(target)})}catch(error){rows.push({kind:'interrupt',target,value:failure(error)})}}
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
