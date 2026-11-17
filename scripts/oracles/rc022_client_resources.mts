import {readFileSync,writeFileSync} from 'node:fs'
import {join,basename,dirname} from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{ClientModuleRegistry}=await load('packages/client/modules/src/index.ts')
const {workspace}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),names=['fixture-lazy','fixture-neighbor']
const ctx=new Context(),rows:any[]=[],entries=names.map(name=>({options:{name},fiber:{},disabled:false,parent:{tree:{ctx:{baseUrl:pathToFileURL(workspace).href+'/'}}}}))
ctx.provide('loader',{entries:()=>entries.values(),internal:{version:'v2',resolveSync:(base:string,input:any)=>({url:pathToFileURL(createRequire(base).resolve(input.specifier)).href})}})
const mapPath=join(workspace,'node_modules',names[0]!,'client.js.map'),writeMap=(value:string)=>writeFileSync(mapPath,value)
writeMap('{')
try{
 const registry=new ClientModuleRegistry(ctx),reads:string[]=[],original=registry.readSourceMap
 registry.readSourceMap=(path:string)=>{reads.push(basename(dirname(path)));return original(path)}
 registry.responses=new Map();registry.composed=registry.compose()
 const batch=registry.graph().batches[0]!.url,single=registry.graph().entries[0]!.url,mapUrl=(url:string)=>url.replaceAll('/client.js','/client.js.map')
 const request=async(stage:string,url:string,method='GET')=>{
  const result=await registry.fetchBundle(new Request('http://x/'+url.replace(/^\//,''),{method}))
  rows.push({stage,status:result.status,headers:Object.fromEntries(result.headers),body:await result.text(),reads:[...reads]})
 }
 await request('script-head',batch,'HEAD');await request('script-first',batch);await request('map-head',mapUrl(batch),'HEAD')
 writeMap(JSON.stringify({version:3,names:[],sources:['src/first.ts'],mappings:'AAAA'}));await request('map-first',mapUrl(batch))
 writeMap(JSON.stringify({version:3,names:[],sources:['src/second.ts'],mappings:'AAAA'}));await request('map-cached',mapUrl(batch));await request('script-cached',batch)
 await request('single-map',mapUrl(single));entries[1]!.disabled=true;registry.dirty.add(names[1]);registry.flush((error:any)=>{throw error})
 await request('single-map-after-compose',mapUrl(single));await request('prior-batch',batch);await request('prior-batch-map',mapUrl(batch))
 await request('unknown','plugins/events');await request('post',batch,'POST')
 registry.responses=new Map();registry.composed=registry.compose();writeMap('{');await request('malformed-map',mapUrl(single))
}finally{await ctx.fiber.dispose()}
console.log(JSON.stringify(rows))
