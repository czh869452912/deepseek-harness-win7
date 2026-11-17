import {readFileSync,writeFileSync,existsSync,unlinkSync} from 'node:fs'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{ClientModuleRegistry}=await load('packages/client/modules/src/index.ts')
const {workspace}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),name='@fixture/assets',directory=join(workspace,'node_modules',name),chunk=join(directory,'client.terminal.js')
const manifest=(target='client.js'):any=>({name,version:'1.0.0',type:'module',exports:{'.':'./host.js','./client':'./'+target},dsh:{client:{platform:'web'}}})
writeFileSync(join(directory,'package.json'),JSON.stringify(manifest()));if(existsSync(chunk))unlinkSync(chunk)
const ctx=new Context(),rows:any[]=[],entry={options:{name},fiber:{},disabled:false,parent:{tree:{ctx:{baseUrl:pathToFileURL(workspace).href+'/'}}}}
ctx.provide('loader',{entries:()=>[entry].values(),internal:{version:'v2',resolveSync:(base:string,input:any)=>({url:pathToFileURL(createRequire(base).resolve(input.specifier)).href})}})
try{
 const registry=new ClientModuleRegistry(ctx),revision=registry.graph().entries[0]!.rev
 const url=(file:string,rev=revision)=>`/plugins/${name}/${file}?rev=${rev}`
 const request=async(stage:string,target:string,method='GET')=>{
  const result=await registry.fetchBundle(new Request('http://x'+target,{method}))
  rows.push({stage,status:result.status,headers:Object.fromEntries(result.headers),body:await result.text()})
 }
 const refresh=()=>{registry.dirty.add(name);registry.flush((error:any)=>{throw error})}
 await request('missing',url('client.terminal.js'));writeFileSync(chunk,'module.exports={generation:1};')
 await request('head',url('client.terminal.js'),'HEAD');await request('script',url('client.terminal.js'));await request('map',url('client.terminal.js.map'))
 await request('stale',url('client.terminal.js','stale'));await request('extra-query',url('client.terminal.js')+'&extra=1')
 for(const file of ['client.node.js','client.node.helper.js','client.node.js.map','client.node.helper.js.map','client.js','other.js','client..js'])await request('blocked-'+file,url(file))
 writeFileSync(chunk,'module.exports={generation:2};');await request('cached',url('client.terminal.js'))
 const changed=manifest();changed.dsh.client.immediately=true;writeFileSync(join(directory,'package.json'),JSON.stringify(changed));refresh()
 await request('cached-after-compose',url('client.terminal.js'))
 writeFileSync(join(directory,'package.json'),JSON.stringify(manifest('next.js')));refresh();const nextRev=registry.graph().entries[0]!.rev
 await request('prior-rejected',url('client.terminal.js'));await request('next-generation',url('client.terminal.js',nextRev))
 entry.disabled=true;refresh();await request('removed',url('client.terminal.js',nextRev))
}finally{await ctx.fiber.dispose()}
console.log(JSON.stringify(rows))
