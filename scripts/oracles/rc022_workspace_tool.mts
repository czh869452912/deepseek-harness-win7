import fs from 'node:fs/promises'
import {join,dirname} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Tool=await load('packages/skill/tool-workspace-dependencies/src/index.ts')
const Prompt=(await load('packages/core/system-prompt/src/index.ts')).default,Tools=(await load('packages/core/tools/src/index.ts')).default
const input=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [index,entry]of input.cases.entries()){
 const directory=join(input.directory,String(index)),source=join(directory,'payload'),root=join(directory,'installed')
 const manifest={desktopVersion:'fixture',platform:process.platform,arch:process.arch,python:'3.8.10',pythonPackages:{Pillow:'10.4.0'}},paths=Tool.workspaceDependencyPaths(source,manifest)
 await fs.mkdir(dirname(paths.python),{recursive:true});await fs.writeFile(paths.python,'interpreter');await fs.mkdir(paths.pythonPackages,{recursive:true})
 const raw=JSON.stringify(manifest);await fs.writeFile(join(source,'runtime.json'),raw)
 const config:any={source};if(['install','retry'].includes(entry.action))config.root=root
 if(entry.action==='config'){if(entry.omit)delete config[entry.field];else config[entry.field]=entry.value}
 const ctx=new Context(),row:any={action:entry.action};let stage='schema'
 try{
  Tool.Config(config);stage='mount';await ctx.plugin(Prompt);await ctx.plugin(Tools);const fiber=await ctx.plugin(Tool,config)
  const tool=ctx.tools.get('load_workspace_dependencies');stage='execute'
  Object.assign(row,{description:tool.description,parameters:tool.parameters,output:tool.output.schema,presentation:tool.presentCall({})})
  if(entry.action==='retry'){await fs.unlink(join(source,'runtime.json'));try{await tool.execute({})}catch(e:any){if(e.code!=='ENOENT')throw e;row.firstFailed=true}await fs.writeFile(join(source,'runtime.json'),raw)}
  const first=await tool.execute({}),second=await tool.execute({});row.sameValue=first===second
  if(entry.action==='cached'){await fs.unlink(join(source,'runtime.json'));if(await tool.execute({})!==first)throw Error('cache lost');row.cachedAfterRemoval=true}
  row.value=first;row.render=await tool.output.render({},first);await fiber.dispose();row.removed=ctx.tools.get('load_workspace_dependencies')===undefined;stage='done'
 }catch(error:any){if(!['schema','mount'].includes(stage))throw error;if(stage==='mount'&&error.code!=='ERR_INVALID_ARG_TYPE'&&error.message!=='workspace dependencies: source and root must be absolute paths')throw error;row.error=stage==='schema'?'schema':error.code==='ERR_INVALID_ARG_TYPE'?'type':error.message}
 finally{await ctx.fiber.dispose()}
 function normalize(value:any):any{if(typeof value==='string')return value.replaceAll(directory.replaceAll('\\','\\\\'),'<base>').replaceAll(directory,'<base>').replaceAll('\\','/');if(Array.isArray(value))return value.map(normalize);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,normalize(v)]));return value}
 rows.push(normalize({...row,stage}))
}
console.log(JSON.stringify(rows))
