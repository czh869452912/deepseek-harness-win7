import fs from 'node:fs/promises'
import path from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {readRequestImageFile,requestImageVariantId}=await load('packages/attachment/attachment-local/src/request-image.ts')
const input=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [index,entry] of input.entries.entries()){
 const root=path.join(input.files,'source-'+index),ref=entry.ref,target=entry.target,original=new Uint8Array(await fs.readFile(entry.file))
 const stored={ref,data:original},initial=await readRequestImageFile(root,stored,target)
 const variant=String(initial.variantId),cache=path.join(root,'request-images',variant.slice(7,9),variant.slice(7))
 let cached=true;try{await fs.access(cache)}catch{cached=false}
 if(cached)await fs.writeFile(cache,'corrupt owned cache')
 const repeated=await readRequestImageFile(root,stored,target)
 const controller=new AbortController(),reason=new Error('caller aborted');controller.abort(reason)
 let sameAbortReason=false;try{await readRequestImageFile(root,stored,target,controller.signal)}catch(error){sameAbortReason=error===reason}
 const ids=[{width:target.width+1},{height:target.height+1},{maxBytes:target.maxBytes+1}].map(override=>String(requestImageVariantId(ref,{...target,...override})))
 rows.push({kind:'encoded',index,width:initial.width,height:initial.height,mediaType:initial.mediaType,hasAlpha:initial.hasAlpha,depth:initial.depth,space:initial.space,
  withinBytes:initial.bytes<=target.maxBytes,original:Buffer.from(initial.data).equals(original),cached,repairEqual:Buffer.from(repeated.data).equals(initial.data),sameAbortReason,
  identityStable:variant===String(requestImageVariantId(ref,{...target})),identityChanges:ids.map(other=>variant!==other),durableUnchanged:Buffer.from(await fs.readFile(entry.file)).equals(original)})
}
const first=input.entries[0],stored={ref:first.ref,data:new Uint8Array(await fs.readFile(first.file))}
for(const [index,target] of input.invalid.entries()){
 let result:any;try{await readRequestImageFile(path.join(input.files,'source-invalid'),stored,target);result={value:'accepted'}}catch(error:any){result={error:error.message,code:error.code??null}}
 rows.push({kind:'invalid',index,...result})
}
process.stdout.write(JSON.stringify(rows))
