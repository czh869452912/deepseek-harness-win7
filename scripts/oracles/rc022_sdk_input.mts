import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const workspace=readFileSync(process.argv[3]!,'utf8'),{ctx}=await setup(join(workspace,'source')),{default:Commands}=await load('packages/interaction/commands/src/index.ts'),{builtinCommandName,resolveCommand}=await load('packages/interaction/commands/src/builtin.ts'),{queryCommand}=await load('packages/sdk/server/src/query-input.ts'),{queryContent,queryCommandImages}=await load('packages/sdk/server/src/query-content.ts'),rows:any[]=[]
try{
 await ctx.plugin(Commands);const parent=await ctx.agents.create({sessionId:'root',agentOptions:{provider:'script',model:'model'}})
 const identities={goal:'@deepseek-ai/dsh-command-goal',compact:'@deepseek-ai/dsh-command-compact',permission:'@deepseek-ai/dsh-permission-presets',plan:'@deepseek-ai/dsh-plan-mode',feedback:'@deepseek-ai/dsh-command-feedback',export:'@deepseek-ai/dsh-session-log-export'}
 for(const [kind,name] of [['goal','wish'],['compact','compress'],['permission','access'],['plan','design'],['feedback','feedback'],['export','archive']] as const)ctx.commands.register({name,description:kind,definitionId:identities[kind],handler:async()=>({kind:'success'})})
 ctx.commands.register({name:'goal',description:'third-party',handler:async()=>({kind:'success'})});const catalog=ctx.commands.list(parent.agent);rows.push({name:'catalog',value:catalog})
 for(const token of ['goal','目标','wish','compact','压缩','compress','permission','权限','access','plan','计划','design','feedback','export','missing']){
  const descriptor=resolveCommand(token,catalog);rows.push({name:'resolve',token,value:descriptor===undefined?null:{name:descriptor.name,builtin:builtinCommandName(descriptor)??null}})
  for(const separator of ['',' ','\t','\v','\u00a0','\u0085','\ufeff','\u2028'])for(const tail of ['','arg']){const text='/'+token+separator+tail;rows.push({name:'route',text,value:queryCommand(text,catalog)??null})}
 }
 const inputs=[null,[],[null],[{}],[{type:3}],[{type:'text'}],[{type:'text',text:'a',extra:1}],[{type:'text',text:' \ufeff'}],[{type:'text',text:'hello'}],[{type:'image',data:'AA==',mimeType:'image/png',name:'x'}],[{type:'image',data:3,mimeType:'image/png'}],[{type:'image',data:'AA==',mimeType:'text/plain'}],[{type:'image',attachment:{}}],[{type:'image',attachment:[]}],[{type:'custom',data:1}]]
 for(const input of inputs){let result;try{result={value:queryContent(input)}}catch(error:any){result={error:error.message}}rows.push({name:'content',input,result})}
 const text={type:'text',text:'/plan'},image={type:'image',data:'AA==',mimeType:'image/png'}
 for(const blocks of [[text],[image,text,image],[text,{...text}],[text,{type:'image',attachment:{}}],[text,{type:'custom'}]]){let result;try{result={value:queryCommandImages(blocks,text)}}catch(error:any){result={error:error.message}}rows.push({name:'images',blocks,result})}
 process.stdout.write(JSON.stringify(rows))
}finally{await ctx.fiber.dispose()}
