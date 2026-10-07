import {execFileSync} from 'node:child_process'
import {existsSync,mkdirSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {Context} from '@deepseek-ai/cordis'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import LocalFileSystem from '@deepseek-ai/dsh-fs-local'
import LocalAttachmentStore from '@deepseek-ai/dsh-attachment-local'
import {LlmAdapter,LlmRuntime,ToolCallId} from '@deepseek-ai/dsh-llm'
import * as ToolFs from '@deepseek-ai/dsh-tool-fs'
import {formatImageReadOutput,imageMediaTypeForPath,imageRefFromValue} from '../../reference/packages/fs/tool-fs/src/read-image.ts'

const root=fileURLToPath(new URL('../../',import.meta.url))
const work=process.env.DSH_FS_WORK!
const fixture=join(work,'read-image-fixture-v2')
mkdirSync(fixture,{recursive:true})
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC','base64')
const largePng=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAMAAAADCAIAAADZSiLoAAAAEElEQVR4nGP4z8AAQQxYWACPjgj4kWPEuQAAAABJRU5ErkJggg==','base64')
const rows:any[]=[]
for(const path of ['red.png','RED.JPG','red.jpeg','red.webp','red.gif','red.txt','.png','red.png/leaf']){
  rows.push({name:'extension:'+path,value:imageMediaTypeForPath(path)??null})
}
const image={attachmentId:'sha256:'+'a'.repeat(64),mediaType:'image/png' as const,bytes:69,width:8,height:8,name:'red.png'}
for(const [name,dimensions] of [['plain',undefined],['same',{width:16,height:16}],['axes',{width:16,height:24}],['tie',{width:5,height:5}]] as const){
  const value={...image,...dimensions===undefined?{}:{originalDimensions:dimensions}}
  rows.push({name:'render:'+name,value:{text:formatImageReadOutput('red.png',value),reference:imageRefFromValue(value)}})
}
const cases=['positive','fallback','latest-header','text-model','unknown-modalities','missing-llm','missing-provider','missing-model','missing-agent','bad-extension','blank-path','missing-file','directory','type-mismatch','pixel-limit','dimension-limit','byte-cap','disallowed-type','attachment-gate','unmount-store','remount-store','cancel-before']
for(const name of cases){
  const directory=join(fixture,name)
  mkdirSync(directory,{recursive:true})
  mkdirSync(join(directory,'folder.png'),{recursive:true})
  if(!existsSync(join(directory,'red.png')))writeFileSync(join(directory,'red.png'),['pixel-limit','dimension-limit'].includes(name)?largePng:png)
  if(!existsSync(join(directory,'red.jpg')))writeFileSync(join(directory,'red.jpg'),png)
  const ctx=new Context()
  const lookups:any[]=[],observed:any[]=[]
  class Adapter extends LlmAdapter{
    override resolveModel(provider:string,model:string){
      lookups.push({provider,model})
      return Promise.resolve({provider,id:model,name:model,...model==='unknown'?{}:{inputModalities:model==='text'?['text']:['text','image']}})
    }
    override stream(){throw new Error('image observer must not stream')}
  }
  const record:any={name,lookups,observed}
  try{
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolRuntime)
    await ctx.plugin(LocalFileSystem,{cwd:directory})
    if(name!=='missing-llm'){
      await ctx.plugin(LlmRuntime)
      ctx.llm.registerAdapter(['image-fixture'],new Adapter())
    }
    const configuration:any={dshHome:join(directory,'source-home')}
    if(name==='pixel-limit')configuration.maxImagePixels=4
    if(name==='dimension-limit')configuration.maxImageDimension=2
    if(name==='byte-cap')configuration.maxImageBytes=32
    let store:any
    if(name!=='attachment-gate')store=await ctx.plugin(LocalAttachmentStore,configuration)
    await ctx.plugin(ToolFs)
    if(name==='unmount-store'||name==='remount-store'){
      await store.dispose()
      if(name==='remount-store')store=await ctx.plugin(LocalAttachmentStore,configuration)
    }
    if(name==='disallowed-type'){
      const original=ctx.attachments.imageLimits
      Object.defineProperty(ctx.attachments,'imageLimits',{value:{...original,mediaTypes:['image/jpeg']}})
    }
    ctx.on('fs/observed',(target,observation)=>observed.push({path:target.displayPath,...observation}))
    let model=name==='text-model'?'text':name==='unknown-modalities'?'unknown':'vision'
    const provider=name==='missing-provider'?undefined:'image-fixture'
    const header=name==='fallback'?undefined:{config:{provider,model:name==='missing-model'?undefined:model}}
    const agent:any={options:name==='fallback'?{provider,model}:name==='latest-header'?{provider,model:'text'}:{},
      session:{header:{cwd:directory},requestHeader:()=>header,deriveMessages:()=>[],append:()=>{}}}
    const signal=new AbortController()
    if(name==='cancel-before')signal.abort()
    const file_path=name==='bad-extension'?'red.txt':name==='blank-path'?'  ':name==='missing-file'?'missing.png':name==='directory'?'folder.png':name==='type-mismatch'?'red.jpg':'red.png'
    const result=await ctx.tools.execute({signal:signal.signal,callId:ToolCallId('image-call'),name:'read_image',arguments:{file_path},...name==='missing-agent'?{}:{agent}})
    record.result=result
    record.allSchemas=ctx.tools.schemas()
    record.schema=ctx.tools.schemas().find((tool:any)=>tool.name==='read_image')??null
    const content=result.content.find((block:any)=>block.type==='image')
    if(content){
      const stored=await ctx.attachments.readImage(content.attachment)
      record.stored={dataHex:Buffer.from(stored.data).toString('hex'),ref:stored.ref}
    }
  }catch(error:any){record.error={name:error.name,message:error.message}}
  finally{await ctx.fiber.dispose()}
  rows.push(record)
}
writeFileSync(process.env.DSH_FS_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',root+'reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
