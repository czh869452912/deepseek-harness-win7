import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],{Context}=await load('vendor/cordis/src/index.ts'),{SessionMediaReferences}=await load('packages/api/session-controller/src/media-references.ts'),{FsError}=await load('packages/fs/fs/src/index.ts')
for(const item of cases){
 const ctx=new Context(),calls:any[]=[],routes:any[]=[],withdrawn:any[]=[],signal=new AbortController().signal,target={displayPath:item.displayPath??'C:/photo.png'}
 const failure=(stage:string)=>{if(item.stage===stage){if(item.error==='unexpected')throw Error('unexpected provider failure');throw new FsError('provider failed',item.error)}}
 ctx.provide('connection',{fetch:{register:(route:any)=>{routes.push(route);return()=>withdrawn.push(true)}}});ctx.provide('attachments',{imageLimits:{maxImageBytes:4}})
 ctx.provide('fs',{resolve:async(path:string,options:any)=>{calls.push({method:'resolve',path,signal:options.signal===signal});failure('resolve');return target},stat:async(received:any,receivedSignal:any)=>{calls.push({method:'stat',sameTarget:received===target,signal:receivedSignal===signal});failure('stat');return 'info'in item?item.info===null?undefined:item.info:{type:'file',size:4,version:item.version??'v1'}},readBytes:async(received:any,receivedSignal:any,maxBytes:number)=>{calls.push({method:'read',sameTarget:received===target,signal:receivedSignal===signal,maxBytes});failure('read');return new Uint8Array([0,1,2,255])}})
 try{
  const provider=await ctx.plugin(SessionMediaReferences),params=new URLSearchParams();if(!('path'in item)||item.path!==null)params.set('path',item.path??'C:/photo.png');if('v'in item)params.set('v',item.v)
  let value:any;try{
   // Keep the exact request signal identity at the FS boundary.
   const request={url:'https://host/prefix/api/file?'+params.toString(),method:item.method??'GET',signal,headers:new Headers({range:item.range??''})}
   const result=await routes[0].fetch(request);value={status:result.status,headers:Object.fromEntries(result.headers),hex:Buffer.from(await result.arrayBuffer()).toString('hex')}
  }catch(error:any){value={error:error.message}}
  await provider.dispose();rows.push({name:item.name,value,calls,withdrawn:JSON.stringify(withdrawn)==='[true]'})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
