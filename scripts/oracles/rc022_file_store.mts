import fs from 'node:fs'
import crypto from 'node:crypto'
import {getEventListeners} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const {DeepSeekFileStore}=await load('packages/llm/llm-deepseek/src/file-store.ts')
const {DeepSeekFilesClient,DeepSeekFilesError}=await load('packages/llm/llm-deepseek/src/files-api.ts')
const rows:any[]=[],modes=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
for(const mode of modes){
 const events:any[]=[];let uploads=0,lists=0
 const connection={baseURL:'https://example.test/anthropic/',headers:{'Z-Key':'z','a-Key':'a'}}
 const scope=crypto.createHash('sha256').update('https://example.test/anthropic/v1\0'+JSON.stringify(Object.entries(connection.headers).sort(([a],[b])=>a.localeCompare(b)))).digest('hex')
 const version={attachment:{attachmentId:'sha256:'+'a'.repeat(64)},variantId:'sha256:'+'b'.repeat(64),bytes:mode==='oversized'?33554433:3,data:new Uint8Array([97,98,99]),mediaType:'image/png'}
 const policy={expiresAfterSeconds:3600,refreshMarginSeconds:10,quotaCleanupBatch:2}
 const cached={scope,attachmentId:version.attachment.attachmentId,variantId:version.variantId,fileId:'cached',bytes:3,createdAt:1000,expiresAt:4000000}
 const index={
  async get(...args:any[]){events.push({get:args});return ['cached','release'].includes(mode)?cached:undefined},
  async commit(candidate:any,now:any,margin:any){events.push({commit:candidate,now,margin});return {record:mode.startsWith('winner')?cached:candidate,accepted:!mode.startsWith('winner')}},
  async remove(scope:any,generations:any){events.push({remove:[scope,generations]})},
  async clear(scope:any){events.push({clear:scope})}
 }
 DeepSeekFilesClient.prototype.upload=async(input:any)=>{uploads++;events.push({upload:{filename:input.filename,expiry:input.expiresAfterSeconds,bytes:input.data.length}});if(mode.startsWith('quota')&&(uploads===1||mode==='quota-repeat'))throw new DeepSeekFilesError('quota',400,'storage quota');return{id:'uploaded',bytes:mode==='mismatch'?4:3,createdAt:2,expiresAt:3602}}
 DeepSeekFilesClient.prototype.delete=async(fileId:any)=>{events.push({delete:fileId});if(mode==='winner-cleanup-fail')throw new Error('cleanup unavailable')}
 DeepSeekFilesClient.prototype.list=async(options:any)=>{
  lists++;events.push({list:{after:options.after??null,limit:options.limit}})
  if(mode==='quota-empty'||mode==='release-all'&&lists>2)return{data:[],hasMore:false}
  if(options.after===undefined)return{data:[{id:'newer',createdAt:30,filename:'dsh-new'},{id:'foreign',createdAt:0,filename:'other'},{id:'middle',createdAt:20,filename:'dsh-mid'}],hasMore:true,lastId:'cursor'}
  return{data:[{id:'oldest',createdAt:1,filename:'dsh-old'},{id:'tied',createdAt:20,filename:'dsh-tie'}],hasMore:true,lastId:'cursor'}
 }
 const store=new DeepSeekFileStore({index,now:()=>10000});let result:any
 try{
  let value:any
  if(mode==='release-all')value=await store.releaseAll(connection)
  else if(mode.startsWith('release'))value=await store.release(version,connection,policy)
  else if(mode==='reclaim')value=await store.reclaimOldestOwned(connection,2)
  else if(mode==='invalidate')value=await store.invalidate([{variantId:version.variantId,fileId:'old'}],connection)
  else value=await store.ensureUploaded(version,connection,policy)
  result={value:value??null}
 }catch(error:any){result={error:{message:error.message,code:error.code??null}}}
 rows.push({mode,result,events})
}
function* permutations(items:any[]):Generator<any[]>{if(!items.length){yield [];return}for(let i=0;i<items.length;i++)for(const rest of permutations(items.filter((_,j)=>j!==i)))yield[items[i],...rest]}
for(const headers of [{'x-api-key':'a','Authorization':'b','_':'c'},{'雪':'a','a':'b','Z':'c'}])for(const entries of permutations(Object.entries(headers))){
 const index={async get(scope:string){return{scope}}},store=new DeepSeekFileStore({index})
 const result=await store.ensureUploaded({variantId:'v',bytes:0},{baseURL:'https://example.test/anthropic/',headers:Object.fromEntries(entries)},{refreshMarginSeconds:0})
 rows.push({headers:entries,scope:result.record.scope})
}
for(const mode of ['one-cancel','all-cancel','non-error-upload']){
 let entered!:()=>void,release!:()=>void;const started=new Promise<void>(resolve=>entered=resolve),gate=new Promise<void>(resolve=>release=resolve),signals:any[]=[]
 DeepSeekFilesClient.prototype.upload=async(input:any)=>{signals.push(input.signal);entered();await gate;if(mode==='non-error-upload')throw null;input.signal.throwIfAborted();return{id:'uploaded',bytes:3,createdAt:1,expiresAt:3601}}
 const index={async get(){return undefined},async commit(record:any){return{record,accepted:true}}},store=new DeepSeekFileStore({index,now:()=>1000})
 const connection={baseURL:'https://a/anthropic',headers:{}},version={attachment:{attachmentId:'sha256:'+'a'.repeat(64)},variantId:'sha256:'+'b'.repeat(64),bytes:3,data:new Uint8Array([97,98,99]),mediaType:'image/png'},policy={expiresAfterSeconds:3600,refreshMarginSeconds:1,quotaCleanupBatch:1}
 const one=new AbortController(),two=new AbortController()
 const capture=(promise:Promise<any>)=>promise.then(result=>({value:result.record.fileId}),error=>({error:error.message,causeNull:Object.hasOwn(error,'cause')&&error.cause===null}))
 const first=capture(store.ensureUploaded(version,connection,policy,one.signal)),second=capture(store.ensureUploaded(version,connection,policy,two.signal))
 await started;if(mode!=='non-error-upload')one.abort(new Error('first'));if(mode==='all-cancel')two.abort(null);release()
 const outcomes=await Promise.all([first,second])
 rows.push({mode,outcomes,uploads:signals.length,transportAborted:signals[0].aborted,listeners:[getEventListeners(one.signal,'abort').length,getEventListeners(two.signal,'abort').length]})
}
process.stdout.write(JSON.stringify(rows))
