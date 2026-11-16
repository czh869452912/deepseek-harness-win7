import {readFileSync} from 'node:fs'
import {mkdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const d=await load('packages/util/plugin-detail/src/index.ts'),document=await load('packages/util/plugin-detail/src/document.ts'),{data,workspace}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],signal=new AbortController().signal
function result(operation:any){try{return {value:operation()??null}}catch(error:any){return {error:error.reason??'error'}}}
for(const language of data.languages)rows.push({kind:'language',input:language,result:result(()=>d.languageChain(language))})
for(const path of data.paths)rows.push({kind:'path',input:path,result:result(()=>document.detailPath(path,'meta.detail'))})
for(const item of data.images)rows.push({kind:'image',input:item,value:d.detailImage(item.document,item.authored)??null})
for(const text of data.markdown)rows.push({kind:'markdown',input:text,value:d.markdownOf(new TextEncoder().encode(text))})
rows.push({kind:'sources',value:d.npmFileSourceOrder(['jsdelivr','unpkg','npmmirror'],['unknown','npmmirror','jsdelivr'])},{kind:'encoding',value:d.encodePath('guide/a b/中文%?#.png')})
for(const item of data.documents){
 const reads:string[]=[]
 const read=async(path:string,max:number)=>{reads.push(path);if(!(path in item.files))return undefined;const value=new TextEncoder().encode(item.files[path]);if(value.byteLength>max)throw new d.DetailFailure('too-large',path);return value}
 const files={key:'memory',read,readme:async(dir:string,max:number)=>{const prefix=dir===''?'':dir+'/';const name=d.readmeName(Object.keys(item.files).filter(path=>path.startsWith(prefix)).map(path=>path.slice(prefix.length)));return name===undefined?undefined:{path:prefix+name,bytes:await read(prefix+name,max)}}}
 let answer:any;try{answer={value:(await d.readPackageDocument(files,'',d.languageChain(item.language),100,signal))??null}}catch(error:any){answer={error:error.reason??'error'}}
 rows.push({kind:'document',name:item.name,result:answer,reads})
}
const home=join(workspace,'source');await mkdir(home,{recursive:true})
for(const [filename,text] of [['README.md','# One'],['README.markdown','fallback'],['guide/x.md','guide']]){const path=join(home,filename!);await mkdir(join(path,'..'),{recursive:true});await writeFile(path,text!)}
await writeFile(join(workspace,'outside.md'),'outside');await mkdir(join(home,'directory'));const files=d.localFiles(home,'1')
for(const path of ['README.md','missing.md','../outside.md','directory','guide/x.md']){let answer:any;try{const value=await files.read(path,100,signal);answer={value:value===undefined?null:new TextDecoder().decode(value)}}catch(error:any){answer={error:error.reason??'error'}}rows.push({kind:'local',path,result:answer})}
let tooLarge:any;try{tooLarge={value:await files.read('README.md',2,signal)}}catch(error:any){tooLarge={error:error.reason??'error'}}rows.push({kind:'local-too-large',result:tooLarge})
const readme=await files.readme('',100,signal);rows.push({kind:'local-readme',value:readme===undefined?null:{path:readme.path,text:new TextDecoder().decode(readme.bytes)}})
for(const outcome of [undefined,'invalid','too-large','network','denied','git-unavailable',{bytes:new TextEncoder().encode('<svg/>'),mediaType:'image/svg+xml'}]){const response=d.detailImageResponse(outcome,'private, max-age=30');rows.push({kind:'response',value:{status:response.status,body:await response.text(),headers:Object.fromEntries([...response.headers].map(([key,value])=>[({'content-type':'Content-Type','cache-control':'Cache-Control','x-content-type-options':'X-Content-Type-Options','content-security-policy':'Content-Security-Policy'} as any)[key]??key,value]))}})}
console.log(JSON.stringify(rows))
