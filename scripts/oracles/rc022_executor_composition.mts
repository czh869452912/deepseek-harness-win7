import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const source=process.argv[2]!,data=JSON.parse(readFileSync(process.argv[3]!,'utf8'))
const load=(path:string)=>import(pathToFileURL(resolve(source,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Loader}=await load('vendor/loader/src/index.ts')
const {composeEntries}=await load('packages/boot/app-boot/src/profile.ts')
const paths:any={tools:'packages/core/tools/src/index.ts','tool-executor-native':'packages/core/tool-executor-native/src/index.ts',
 'tool-executor-ptc':'packages/core/tool-executor-ptc/src/index.ts','ptc-runtime':'packages/ptc-runtime/ptc-runtime-node/src/index.ts',
 'system-prompt':'packages/core/system-prompt/src/index.ts'}
const dependencies=[]
for(const path of ['packages/core/session/src/index.ts','packages/fs/fs-local/src/index.ts','packages/subprocess/subprocess-local/src/index.ts','packages/sandbox/sandbox-local/src/index.ts','packages/session/session-projection/src/index.ts','packages/sandbox/sandbox-policy/src/index.ts'])dependencies.push((await load(path)).default)
const classes:any={};for(const [id,path] of Object.entries(paths)){const module=await load(path as string);classes[id]=module.default??module}
const original=process.env.DSH_TOOLS_MODE,results:any[]=[]
try{for(const action of ['native','env-ptc','ptc','env-native','missing','duplicate','mode-native','mode-null','parallel']){
 process.env.DSH_TOOLS_MODE=action==='env-ptc'?'ptc':'native'
 let patches:any[]=[]
 if(['ptc','env-native'].includes(action))patches=data.ptc.slice(0,2)
 else if(action==='missing')patches=[{id:'tool-executor-native',disabled:true}]
 else if(action==='duplicate')patches=[{id:'tool-executor-ptc',disabled:false}]
 else if(action.startsWith('mode-'))patches=[{id:'tools',config:{mode:action==='mode-null'?null:'native'}}]
 else if(action==='parallel')patches=[{id:'tools',config:{maxParallelSubCalls:2}}]
 const rows=composeEntries([[{insert:data.rows}],patches]),ctx=new Context();await ctx.plugin(Loader);for(const dependency of dependencies)await ctx.plugin(dependency,{})
 for(const row of rows){ctx.loader.builtins[row.id]=classes[row.id];row.name='cordis:'+row.id}
 const failures:string[]=[]
 try{for(const row of rows)await ctx.loader.create(row);await ctx.loader.await()
  for(const row of rows){const fiber=ctx.loader.store[row.id].fiber;if(fiber)try{await fiber.await()}catch{failures.push(row.id)}}
  let names=null,code=null
  if(ctx.get('tools'))try{names=(await ctx.systemPrompt.assemble({})).tools.map((schema:any)=>schema.name)}catch(error:any){code=error.code??error.name}
  results.push({action,failed:failures.sort(),names,code,runtime:!!ctx.get('ptcRuntime')})
 }finally{await ctx.fiber.dispose()}
}}finally{if(original===undefined)delete process.env.DSH_TOOLS_MODE;else process.env.DSH_TOOLS_MODE=original}
process.stdout.write(JSON.stringify(results))
