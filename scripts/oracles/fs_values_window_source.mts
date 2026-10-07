import {execFileSync} from 'node:child_process'
import {readFileSync,writeFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {buildWindow,formatReadOutput,langFromPath,readMetaFromMeta} from '../../reference/packages/fs/tool-fs/src/read-render.ts'

const root=fileURLToPath(new URL('../../',import.meta.url))
const fixtures=JSON.parse(readFileSync(new URL('./read-window-fixtures-v2.json',import.meta.url),'utf8'))
const rows:any[]=[]
for(const fixture of fixtures.windows){
  const request={offset:1,limit:2000,maxLineLength:2000,maxBytes:51200,...fixture.request}
  for(const delivery of ['sync','async']){
    const chunks=delivery==='sync'?fixture.chunks:(async function*(){for(const chunk of fixture.chunks)yield chunk})()
    const row:any={name:'window/'+fixture.name+'/'+delivery}
    try{
      const outcome=await buildWindow(chunks,request,'fixture.txt')
      row.value={outcome,rendered:formatReadOutput('fixture.txt',{offset:request.offset,...outcome})}
    }catch(error:any){row.error={message:error.message,code:error.code??null}}
    rows.push(row)
  }
}
for(const [index,path] of fixtures.paths.entries())rows.push({name:'language/'+index,value:langFromPath(path)??null})
for(const [index,meta] of fixtures.metadata.entries())rows.push({name:'metadata/'+index,value:readMetaFromMeta(meta)??null})
writeFileSync(process.env.DSH_FS_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',root+'reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
