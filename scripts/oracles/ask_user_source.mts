import {execFileSync} from 'node:child_process'
import {readFileSync,writeFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {Context} from '../../reference/vendor/cordis/src/index.ts'
import Prompt from '../../reference/packages/core/system-prompt/src/index.ts'
import Tools from '../../reference/packages/core/tools/src/index.ts'
import Questions from '../../reference/packages/interaction/user-questions/src/index.ts'
import * as Ask from '../../reference/packages/interaction/tool-ask-user/src/index.ts'
import {ToolCallId} from '../../reference/packages/llm/llm/src/index.ts'

const root=fileURLToPath(new URL('../../',import.meta.url))
const output=process.env.DSH_ASK_USER_OUTPUT!
const rows=[]
const owner=new Context()
try{
  await owner.plugin(Prompt)
  await owner.plugin(Tools)
  await owner.plugin(Ask)
  rows.push({name:'before-questions',schemas:owner.tools.schemas()})
  const questions=await owner.plugin(Questions)
  const definition=owner.tools.get('ask_user_question')!
  rows.push({name:'with-questions',schema:owner.tools.schemas()[0],outputSchema:definition.output.schema})
  await questions.dispose()
  await new Promise(done=>setImmediate(done))
  rows.push({name:'questions-disposed',schemas:owner.tools.schemas()})
}finally{await owner.fiber.dispose()}
for(const name of ['answers','empty-questions','no-provider','pre-aborted','provider-aborted','custom-null','selected-invalid','question-extra']){
  const ctx=new Context()
  const controller=new AbortController()
  const requests=[]
  try{
    await ctx.plugin(Prompt)
    await ctx.plugin(Tools)
    await ctx.plugin(Questions)
    await ctx.plugin(Ask)
    if(name!=='no-provider')ctx.on('user-questions/request',async request=>{
      const {signal,agent,...body}=request
      requests.push({...body,signalPresent:signal!==undefined,signalAborted:signal?.aborted===true,agentPresent:agent!==undefined})
      if(name==='provider-aborted'){
        controller.abort(new Error('question cancelled'))
        throw new Error('question cancelled')
      }
      if(name==='custom-null')return {answers:[{id:'choice',selected:[],custom:null}]}
      if(name==='selected-invalid')return {answers:[{id:'choice',selected:[7]}]}
      return {answers:[{id:'choice',selected:['A','B'],custom:'中文🙂',extra:'not projected'},{id:'notes',selected:[]}]}
    })
    if(name==='pre-aborted')controller.abort(new Error('question cancelled'))
    const questions=name==='empty-questions'?[]:[{id:'choice',question:'Choose?',header:'选择',multi_select:true,
      options:[{label:'A',description:'First',extra:'retained option'}, {label:'B'}],extra:'not projected'}]
    const result=await ctx.tools.execute({callId:ToolCallId('controlled-question'),name:'ask_user_question',arguments:{questions,extra:'accepted'},signal:controller.signal})
    rows.push({name,requests,result})
  }finally{await ctx.fiber.dispose()}
}
writeFileSync(output,JSON.stringify({sourceCommit:execFileSync('git',['-C',resolve(root,'reference'),'rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  node:process.version,fixtureSha256:createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex'),rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
