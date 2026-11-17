import {readFileSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{ClientModuleRegistry}=await load('packages/client/modules/src/index.ts')
const {workspace}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),directory=join(workspace,'node_modules/fixture-client')
const ctx=new Context(),rows:any[]=[],entry:any={options:{name:'fixture-client'},fiber:{},disabled:false,parent:{tree:{ctx:{baseUrl:pathToFileURL(workspace).href+'/'}}}},entries=[entry]
ctx.provide('loader',{entries:()=>entries.values(),internal:{version:'v2',resolveSync:(base:string,input:any)=>({url:pathToFileURL(createRequire(base).resolve(input.specifier)).href})}})
const write=(declaration=true,target='client.js',external?:string[])=>{
 const value:any={name:'fixture-client',version:'1.0.0',type:'module',exports:{'.':'./host.js','./client':'./'+target}}
 if(declaration)value.dsh={client:{platform:'web',...(external?{external}:{})}}
 writeFileSync(join(directory,'package.json'),JSON.stringify(value))
}
write()
try{
 const registry=new ClientModuleRegistry(ctx),notifications:any[]=[];registry.onGraphChanged(()=>{notifications.push(true)})
 const row=(stage:string)=>{rows.push({stage,graph:registry.graph(),notifications:notifications.length})}
 const refresh=()=>{registry.dirty.add('fixture-client');registry.flush((error:any)=>{throw error})}
 row('initial');refresh();row('unchanged')
 write(true,'next.js');refresh();row('export-replaced')
 write(true,'next.js',['fixture-dependency']);refresh();row('metadata-replaced')
 entry.disabled=true;refresh();row('disabled');entry.disabled=false;refresh();row('enabled')
 write(false);refresh();row('declaration-removed');write();refresh();row('declaration-added')
 const before=registry.graph(),rev=registry.rebuilt('fixture-client');rows.push({stage:'unchanged-rebuilt',rev,graphSame:registry.graph()===before,notifications:notifications.length})
 entries.length=0;refresh();row('removed')
}finally{await ctx.fiber.dispose()}
console.log(JSON.stringify(rows))
