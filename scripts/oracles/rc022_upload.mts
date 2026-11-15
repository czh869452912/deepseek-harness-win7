import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load,setup} from './rc022_subagent_fixture.mts'
const {AttachmentStore}=await load('packages/attachment/attachment/src/index.ts'),Uploads=(await load('packages/client/file-upload/src/index.ts')).default
const fixture=await setup(join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source')),{ctx}=fixture,rows:any[]=[],resolvers:any[]=[],routes:any[]=[],writes:any[]=[]
const limits={maxImageBytes:4,maxImagesPerMessage:2,maxMessageImageBytes:6,mediaTypes:['image/png']},image={attachmentId:'sha256:'+'12'.repeat(32),mediaType:'image/png',bytes:2,width:1,height:1}
class Store extends AttachmentStore{
 imageLimits=limits
 constructor(){super(ctx,'attachments')}
 override async saveImages(inputs:any[]){this.validateImageBatch(inputs);writes.push(inputs.map(item=>item.data.length));return inputs.map(()=>image)}
 override async saveFileStream(request:any){const parts=[];for await(const chunk of request.data)parts.push(chunk);return {attachmentId:'file',bytes:Buffer.concat(parts).length,name:request.name??'file'}}
}
new Store();ctx.provide('commands',{registerFileReceiptResolver:(resolver:any)=>{resolvers.push(resolver);return()=>resolvers.splice(resolvers.indexOf(resolver),1)}});ctx.provide('connection',{fetch:{register:(route:any)=>{routes.push(route);return()=>routes.splice(routes.indexOf(route),1)}}})
async function* chunks(...values:number[][]){for(const value of values)yield Uint8Array.from(value)}
async function result(name:string,callback:any){try{const value=await callback();rows.push({name,value});return value}catch(error:any){rows.push({name,error:{code:error.code,details:error.details??{}}})}}
try{
 const fiber=await ctx.plugin(Uploads),uploads=ctx.fileUploads,agent=(await ctx.agents.create({sessionId:'one'})).agent,other=(await ctx.agents.create({sessionId:'two'})).agent
 const first=await uploads.uploadImageStream({sessionId:'one',mediaType:'image/png',data:chunks([1,2],[3])}),staged=uploads.resolve(agent,first.receiptId)
 rows.push({name:'typed-image',value:staged,foreign:uploads.resolve(other,first.receiptId)??null,command:resolvers[0](agent,first.receiptId)??null})
 const file=await uploads.uploadStream({sessionId:'one',data:chunks([4,5]),name:'file.bin'});rows.push({name:'typed-file',value:uploads.resolve(agent,file.receiptId),command:resolvers[0](agent,file.receiptId)})
 let binding=uploads.bindPrompt(agent,[first.receiptId],'rollback');binding[Symbol.dispose]();uploads.retirePrompt(agent,'rollback');rows.push({name:'rollback',retained:uploads.resolve(agent,first.receiptId)!==undefined})
 binding=uploads.bindPrompt(agent,[first.receiptId],'accepted');binding.commit();binding[Symbol.dispose]();uploads.retirePrompt(agent,'accepted');rows.push({name:'committed',retained:uploads.resolve(agent,first.receiptId)!==undefined})
 await result('stored-only',()=>ctx.attachments.admitPromptContent([staged]));const encoded={type:'image',data:'AQID',mediaType:'image/png'}
 await result('mixed-at-limit',()=>ctx.attachments.admitPromptContent([staged,encoded]));await result('mixed-over-bytes',()=>ctx.attachments.admitPromptContent([{...staged,encodedBytes:4},encoded]));await result('mixed-over-count',()=>ctx.attachments.admitPromptContent([staged,staged,encoded]))
 await result('upload-over-limit',()=>uploads.uploadImageStream({sessionId:'one',mediaType:'image/png',data:chunks([1,2,3],[4,5])}));await result('unsupported',()=>uploads.uploadImageStream({sessionId:'one',mediaType:'',data:chunks([1])}))
 const controller=new AbortController();controller.abort();await result('cancelled',()=>uploads.uploadImageStream({sessionId:'one',mediaType:'image/png',data:chunks([1]),signal:controller.signal}))
 const response=await routes[0].fetch(new Request('http://host/api/session/uploadFileBinary?sessionId=one&mediaType=image%2Fpng',{method:'POST',headers:{'content-type':'application/octet-stream'},body:Uint8Array.from([7,8])})),body=await response.json();rows.push({name:'image-route',status:response.status,ok:body.ok,image:body.value.image})
 rows.push({name:'writes',values:writes});await fiber.dispose();rows.push({name:'unloaded',routes:routes.length,resolvers:resolvers.length})
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
