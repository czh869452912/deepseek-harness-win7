import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {RequestFiles}=await load('packages/llm/llm-deepseek/src/request-files.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [index,detail] of input.details.entries()){
 const invalidated:any[]=[];let pulses=0
 const files={async ensureUploaded(version:any){return {record:{fileId:version.variantId[7]==='0'?'file-1':'file-10'}}},
  async invalidate(records:any){invalidated.push(structuredClone(records))}}
 const request=new RequestFiles(files,{baseURL:'https://example.test',headers:{}},{},1000,new AbortController().signal,()=>pulses++)
 request.beginAttempt()
 for(const [occurrence,version] of [input.versions[0],input.versions[1],input.versions[0]].entries())await request.resolve(version,{message:occurrence+1,image:1})
 const message=request.errorMessage(400,'provider said no',detail),other=request.errorMessage(401,'provider said no',detail)
 const first=await request.retry(detail),second=await request.retry(detail)
 request.beginAttempt();const empty=await request.retry(detail)
 rows.push({index,message,other,retry:[first,second,empty],invalidated,pulses})
}
process.stdout.write(JSON.stringify(rows))
