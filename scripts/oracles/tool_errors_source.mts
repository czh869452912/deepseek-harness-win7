import {execFileSync} from 'node:child_process'
import {readFileSync,writeFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {Context} from '@deepseek-ai/cordis'
import Prompt from '@deepseek-ai/dsh-system-prompt'
import Tools,{defineTool} from '@deepseek-ai/dsh-tools'
import {HarnessError,ToolCallId} from '@deepseek-ai/dsh-llm'

const root=fileURLToPath(new URL('../../',import.meta.url))
const output=resolve(process.env.DSH_TOOL_ERRORS_OUTPUT)
const rows=[]
const ownership=new Context()
try{
  await ownership.plugin(Tools)
  rows.push({name:'before-prompt',present:ownership.get('tools')!==undefined})
  const prompt=await ownership.plugin(Prompt)
  rows.push({name:'after-prompt',present:ownership.get('tools')!==undefined})
  await prompt.dispose()
  await new Promise(done=>setImmediate(done))
  rows.push({name:'after-prompt-dispose',present:ownership.get('tools')!==undefined})
  await ownership.plugin(Prompt)
  rows.push({name:'after-prompt-restore',present:ownership.get('tools')!==undefined})
}finally{await ownership.fiber.dispose()}
for(const name of ['plain','typed','unknown','pre-aborted','body-aborted']){
  const ctx=new Context()
  let calls=0
  const controller=new AbortController()
  try{
    await ctx.plugin(Prompt)
    await ctx.plugin(Tools)
    ctx.tools.register(defineTool({name:'sample',description:'Controlled error result.',parameters:{},
      output:{schema:{type:'string'},render:(_args,value)=>[{type:'text',text:value}]},
      async execute(){
        calls++
        if(name==='plain')throw new Error('plain failure')
        if(name==='typed')throw new HarnessError('typed failure','CONTROLLED_TYPED')
        if(name==='body-aborted')controller.abort(new Error('body cancelled'))
        return 'body value'
      }}))
    if(name==='pre-aborted')controller.abort(new Error('pre cancelled'))
    const result=await ctx.tools.execute({callId:ToolCallId('controlled-call'),name:name==='unknown'?'missing':'sample',arguments:{},signal:controller.signal})
    rows.push({name,calls,result})
  }finally{await ctx.fiber.dispose()}
}
const report={sourceCommit:execFileSync('git',['-C',resolve(root,'reference'),'rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  node:process.version,fixtureSha256:createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex'),rows}
writeFileSync(output,JSON.stringify(report,null,2)+'\n',{encoding:'utf8',flag:'wx'})
