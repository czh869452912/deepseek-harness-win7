import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{Session}=await load('packages/core/session/src/index.ts'),{default:Projections}=await load('packages/session/session-projection/src/index.ts'),{default:Questions}=await load('packages/interaction/user-questions/src/index.ts'),Tool=await load('packages/interaction/tool-ask-user/src/index.ts'),ctx=new Context()
await ctx.plugin(Projections)
const session=Session.create('question-probe'),agent:any={id:'agent-1',session,inbox:{nextTurn:[],nextStep:[]}},definitions:any[]=[],services:any={agents:{get:(id:string)=>id===agent.id?agent:undefined},tools:{register:(definition:any)=>{definitions.push(definition);return()=>{}}}}
agent.steer=(message:any)=>agent.inbox.nextTurn.push(message)
for(const [name,value] of Object.entries(services)){ctx.provide(name);ctx[name]=value}
const owner=await ctx.plugin(Questions),service=ctx.userQuestions,rows:any[]=[],q={id:'scope',question:'Which scope?'},request={questions:[q],agent},row=(name:string,value:any)=>rows.push({name,...value}),failure=(error:any)=>({code:error.code??null,message:error.message})
try{
 row('unattended',{result:await service.askTimed(request,'unattended',5)})
 for(const value of [0,true,1.5,2147483648]){try{await service.askTimed(request,'bad',value)}catch(error){row('invalid-timeout',{error:failure(error)})}}
 let done=false;const task=service.askTimed(request,'held',25).then((value:any)=>{done=true;return value});await Promise.resolve();const client=new AbortController(),stream=service.attachWait(agent,'held',client.signal),frame=await stream.next();await new Promise(resolve=>setTimeout(resolve,40));row('held',{range:frame.value.remainingMs>=0&&frame.value.remainingMs<=25,pending:!done});client.abort();await stream.return(undefined);row('disconnected',{result:await task})
 const release=ctx.on('user-questions/request',()=>({answers:[{id:'scope',selected:[]}]}));row('answered',{result:await service.askTimed(request,'answered',1000)});release()
 session.append('request/header',{header:{config:{provider:'fixture',model:'fixture'},tools:[{name:'ask_user_question',description:'Question',parameters:{properties:{timeout:{}}}}]},reason:'initial'})
 session.append('tool/call',{turn:1,step:1,callId:'late',name:'ask_user_question',arguments:JSON.stringify({questions:[q]})})
 session.append('tool/result',{turn:1,step:1,message:{id:'result-1',role:'tool',toolCallId:'late',content:[{type:'text',text:'{"pending":true}'}],isError:false}},{surfaceOp:'append'})
 const batch={answers:[{id:'scope',selected:[],custom:'Later'}]};row('late',{accepted:service.answer(agent,'late',batch)});let message=agent.inbox.nextTurn.pop();row('late-message',{source:message.source,payload:JSON.parse(message.content[0].text)})
 try{service.answer(agent,'late',batch)}catch(error){row('duplicate',{error:failure(error)})}
 ctx.emit('agent/inbox/discarded',{agent,message});service.answer(agent,'late',batch);message=agent.inbox.nextTurn.pop();session.append('user/message',message,{surfaceOp:'append'});row('admitted',{accepted:service.answer(agent,'late',batch),projection:service.userQuestionProjectionHandle.stateOf(session).questions})
 for(const mode of ['legacy','timed']){const toolOwner=await ctx.plugin(Tool,{mode}),definition=definitions.at(-1);row('tool-'+mode,{description:definition.description,parameters:definition.parameters,output:definition.output.schema});if(mode==='timed'){service.askTimed=async(request:any,callId:string,timeout:number)=>{row('tool-request',{questions:request.questions,waitMs:timeout,callId,sameAgent:request.agent===agent});return{pending:true,callId}};row('tool-result',{result:await definition.execute({questions:[q]},{agent,callId:'tool-1',signal:new AbortController().signal})})}await toolOwner.dispose()}
 await owner.dispose();row('unload',{service:ctx.get('userQuestions')!==undefined,projection:ctx.sessionProjections.snapshot(session,['userQuestions']).values});console.log(JSON.stringify(rows))
}finally{await ctx.fiber.dispose()}
