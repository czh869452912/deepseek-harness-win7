import {readFileSync,mkdirSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Registry}=await load('packages/typert/registry/src/index.ts'),TypertLoader=await load('packages/typert/loader/src/index.ts')
const {files}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),ctx=new Context(),name='@deepseek-ai/dsh-schedule',rows=[{options:{name},fiber:{},disabled:false},{options:{name},fiber:{},disabled:false}],answer:any[]=[]
ctx.baseUrl=pathToFileURL(join(files,'anchor.cjs')).href;ctx.provide('loader',{entries:()=>rows} as any)
const directory=join(files,'source-package');mkdirSync(directory);const manifestPath=join(directory,'package.json'),artifact=join(directory,'host.mjs'),manifest={name,exports:{'./typert':{default:'./host.mjs'}}}
writeFileSync(manifestPath,JSON.stringify(manifest));writeFileSync(artifact,readFileSync(join(files,'generated.mjs'),'utf8'))
// Resolve generated imports from the fixed Source installation without copying packages.
const {createRequire}=await import('node:module');const require=createRequire(pathToFileURL(join(process.argv[2]!,'package.json')))
let text=readFileSync(artifact,'utf8');text=text.replace("'zod'",JSON.stringify(pathToFileURL(require.resolve('zod')).href)).replace("'@deepseek-ai/dsh-typert-protocol/remote-info'",JSON.stringify(pathToFileURL(require.resolve('@deepseek-ai/dsh-typert-protocol/remote-info')).href));writeFileSync(artifact,text)
ctx.provide('pluginPackages',{packageOf:(entry:string)=>entry===name?{manifestPath,manifest}:undefined} as any)
await ctx.plugin(Registry);const fiber=await ctx.plugin(TypertLoader,{packages:[]})
function snapshot(step:string){const row=ctx.typert.local.get('fixture/echo');answer.push({step,packages:ctx.typert.listPackages().length,strict:row!==undefined,...(row===undefined?{}:{value:row.parameters[0]!.codec.create().parse('native')})})}
async function change(row:any){ctx.emit('internal/plugin',{entry:row} as any);for(let i=0;i<10;i++)await Promise.resolve()}
try{snapshot('mounted');rows[0]!.disabled=true;await change(rows[0]);snapshot('one-disabled');rows[1]!.disabled=true;await change(rows[1]);snapshot('all-disabled');writeFileSync(artifact,'broken after initial import');rows[0]!.disabled=false;await change(rows[0]);snapshot('cached-remount');await fiber.dispose();snapshot('disposed')}finally{await ctx.fiber.dispose()}
console.log(JSON.stringify(answer))
