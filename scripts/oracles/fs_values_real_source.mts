import {execFileSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {existsSync,mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {Context} from '@deepseek-ai/cordis'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import FsLocal from '@deepseek-ai/dsh-fs-local'
import * as ObservationPolicy from '@deepseek-ai/dsh-fs-observation-policy'
import * as ToolFs from '@deepseek-ai/dsh-tool-fs'

const root=fileURLToPath(new URL('../../',import.meta.url))
const work=process.env.DSH_FS_WORK!
const fixturePath=fileURLToPath(new URL('./fs-real-tool-fixtures-v1.json',import.meta.url))
const fixtures=JSON.parse(readFileSync(fixturePath,'utf8'))
const rows:any[]=[]
for(const fixture of fixtures.cases){
  const destination=resolve(work,'fs-real-tool-shared-v1',fixture.name)
  mkdirSync(destination,{recursive:true})
  const target=resolve(destination,'target.txt')
  if(existsSync(target))throw new Error('Fresh Source fixture required')
  if(fixture.initial!==null)writeFileSync(target,fixture.initial,'utf8')
  const ctx=new Context(),signal=new AbortController().signal
  const agent:any=fixture.noAgent?undefined:{session:{header:{cwd:destination}}}
  const steps:any[]=[]
  try{
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolRuntime)
    await ctx.plugin(FsLocal,{cwd:destination})
    let policy=await ctx.plugin(ObservationPolicy)
    const tools=await ctx.plugin(ToolFs,{readLimit:10,readStreamMinSize:1,...fixture.caps})
    for(const step of fixture.steps){
      if('external' in step){writeFileSync(target,step.external,'utf8');steps.push({external:step.external});continue}
      if('policy' in step){if(step.policy==='unload')await policy.dispose();else policy=await ctx.plugin(ObservationPolicy);steps.push({policy:step.policy});continue}
      const result=await ctx.tools.execute({name:step.tool,arguments:step.args,callId:'real-fixture',signal,...agent===undefined?{}:{agent}} as any)
      const tool=ctx.tools.get(step.tool)!
      steps.push({tool:step.tool,result,call:tool.presentCall?.(step.args)??null,replay:tool.presentResult?.(step.args,result)??null})
    }
    await tools.dispose()
    rows.push({name:fixture.name,steps,afterHex:existsSync(target)?readFileSync(target).toString('hex'):null,afterUnload:['read','write','edit'].map(name=>ctx.tools.get(name)!==undefined)})
  }finally{await ctx.fiber.dispose()}
}
writeFileSync(process.env.DSH_FS_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',root+'reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,fixtureSha256:createHash('sha256').update(readFileSync(fixturePath)).digest('hex'),rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
