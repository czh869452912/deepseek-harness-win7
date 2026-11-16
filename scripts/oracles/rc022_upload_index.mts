import fs from 'node:fs/promises'
import path from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {DeepSeekUploadIndex,deepSeekFileScope}=await load('packages/llm/llm-deepseek/src/upload-index.ts')
const inputPath=process.argv[3]!,inputs=JSON.parse(await fs.readFile(inputPath,'utf8')),rows:any[]=[]
const record=(changes:any={})=>({scope:'a'.repeat(64),attachmentId:'sha256:'+'b'.repeat(64),variantId:'sha256:'+'c'.repeat(64),fileId:'file-雪',bytes:4,createdAt:1000,expiresAt:100000,...changes})
for(const [index,entry] of inputs.entries()){
 const file=path.join(path.dirname(inputPath),'files','source-'+index,'index.json');await fs.mkdir(path.dirname(file),{recursive:true})
 if(entry.text!==null)await fs.writeFile(file,entry.text,'utf8')
 const store=new DeepSeekUploadIndex(file),events:any[]=[]
 const step=async(name:string,promise:Promise<any>)=>{
  const value=await promise;let text=null;try{text=await fs.readFile(file,'utf8')}catch(error:any){if(error.code!=='ENOENT')throw error}
  events.push({name,value:value??null,text})
 }
 await step('get',store.get('a'.repeat(64),'sha256:'+'c'.repeat(64),1000,2))
 await step('commit',store.commit(record({fileId:'new'}),1000,2))
 await step('second',store.commit(record({variantId:'sha256:'+'f'.repeat(64),fileId:'second',bytes:1.0}),1000,2))
 await step('remove',store.remove('a'.repeat(64),[{variantId:'sha256:'+'c'.repeat(64),fileId:'old'},{variantId:'sha256:'+'f'.repeat(64),fileId:'second'},{variantId:'sha256:'+'f'.repeat(64),fileId:'second'}]))
 await step('clear-other',store.clear('d'.repeat(64)))
 await step('get-after',store.get('a'.repeat(64),'sha256:'+'c'.repeat(64),99998,2))
 await step('expire',store.commit(record({fileId:'successor',bytes:0}),99998,2))
 await step('remove-stale',store.remove('a'.repeat(64),[{variantId:'sha256:'+'c'.repeat(64),fileId:'new'}]))
 await step('clear',store.clear('a'.repeat(64)))
 rows.push({index,events,leftovers:(await fs.readdir(path.dirname(file))).sort()})
}
for(const base of ['https://a/v1','https://a/v1///','https://a/雪'])for(const credential of ['','secret','雪','a\0b','\ud800','\ud800\udc00'])rows.push({base,credential,scope:deepSeekFileScope(base,credential)})
process.stdout.write(JSON.stringify(rows))
