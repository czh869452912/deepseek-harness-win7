import {execFileSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {readFileSync,writeFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {Context} from '@deepseek-ai/cordis'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import {FileSystem,FsError} from '@deepseek-ai/dsh-fs'
import * as ToolFs from '@deepseek-ai/dsh-tool-fs'

const root=fileURLToPath(new URL('../../',import.meta.url))
const fixturePath=fileURLToPath(new URL('./read_tool_fixtures_v1.json',import.meta.url))
const fixtures=JSON.parse(readFileSync(fixturePath,'utf8'))
const rows:any[]=[]
for(const fixture of fixtures.cases){
  const ctx=new Context(),trace:any[]=[]
  const signal=new AbortController().signal
  class Provider extends FileSystem{
    check(kind:string){if(fixture.reject===kind)throw new FsError('provider '+kind+' failed','FS_IO_ERROR')}
    override async resolve(path:string,options:any){trace.push({kind:'resolve',path,signalSame:options.signal===signal,...options.cwd===undefined?{}:{cwd:options.cwd}});return {targetKey:'key:'+path,displayPath:'/abs/'+path} as any}
    override async stat(target:any,liveSignal:any){trace.push({kind:'stat',signalSame:liveSignal===signal});this.check('stat');return fixture.missing?undefined:{version:'v1',type:fixture.type??'file',...fixture.size===undefined?{}:{size:fixture.size}} as any}
    override async readText(target:any,liveSignal:any){trace.push({kind:'readText',signalSame:liveSignal===signal});this.check('readText');return fixture.chunks.join('')}
    override async streamText(target:any,liveSignal:any){trace.push({kind:'streamText',signalSame:liveSignal===signal});this.check('streamText');return (async function*(){for(const chunk of fixture.chunks){trace.push({kind:'chunk',text:chunk});yield chunk;if(fixture.reject==='chunk')throw new FsError('provider chunk failed','FS_IO_ERROR')}})()}
  }
  try{
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolRuntime)
    await ctx.plugin(Provider)
    const caps={limit:3,maxLineLength:2000,maxBytes:51200,streamMinSize:10,...fixture.caps}
    const mounted=await ctx.plugin(ToolFs,{readLimit:caps.limit,readMaxLineLength:caps.maxLineLength,readMaxBytes:caps.maxBytes,readStreamMinSize:caps.streamMinSize})
    ctx.on('fs/observed',(target,observation)=>trace.push({kind:'observed',path:target.displayPath,...observation}))
    const agent:any=fixture.noAgent?undefined:{session:{header:{cwd:'C:/fixture'}}}
    const result=await ctx.tools.execute({name:'read',arguments:fixture.args,callId:'read-fixture',signal,...agent===undefined?{}:{agent}} as any)
    const tool=ctx.tools.get('read')!
    const replay:any[]=[]
    for(const [name,damage] of [['original',{}],['error',{isError:true}],['missing-meta',{meta:undefined}],['bad-meta',{meta:{}}],['wrong-envelope',{content:[{type:'text',text:'obsolete'}]}],['extra-block',{content:[...result.content,{type:'text',text:'extra'}]}]] as const){
      replay.push({name,value:tool.presentResult?.(fixture.args,{...result,...damage})??null})
    }
    const row:any={name:fixture.name,trace,result,schema:ctx.tools.schemas().find(tool=>tool.name==='read'),call:tool.presentCall?.(fixture.args)??null,replay}
    await mounted.dispose()
    row.afterUnload=ctx.tools.get('read')!==undefined
    rows.push(row)
  }finally{await ctx.fiber.dispose()}
}
writeFileSync(process.env.DSH_FS_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',root+'reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,fixtureSha256:createHash('sha256').update(readFileSync(fixturePath)).digest('hex'),rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
