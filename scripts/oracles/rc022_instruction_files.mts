import {readFileSync,mkdirSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const base=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source-work'),home=join(base,'home'),agents=join(base,'agents'),project=join(base,'project'),child=join(project,'child'),collision=join(project,'agents-global')
for(const directory of [home,agents,child,collision])mkdirSync(directory,{recursive:true})
for(const [path,text] of [[join(home,'AGENTS.md'),'global\r\n'],[join(agents,'AGENTS.md'),'\ufeff global\r\n '],[join(project,'.git'),'marker'],[join(project,'AGENTS.md'),'project'],[join(project,'CLAUDE.md'),' project '],[join(project,'AGENTS.local.md'),'overlay'],[join(child,'AGENTS.md'),'nested'],[join(collision,'AGENTS.md'),'collision']])writeFileSync(path!,text!)
const options={cwd:child,dshHome:home,agentsHome:agents,maxBytes:2000,maxSourceBytes:128},rows:any[]=[],files=await load('packages/context/agent-instructions/src/files.ts'),config=await load('packages/context/agent-instructions/src/config.ts'),{Context}=await load('vendor/cordis/src/index.ts'),ctx=new Context()
try{
 rows.push({name:'host-discovery',value:await files.discoverBaselineInstructionFiles(options)},{name:'host-load',value:await files.loadBaselineInstructionSet(options)})
 await ctx.plugin((await load('packages/fs/fs-local/src/index.ts')).default,{cwd:base});const filesystem=ctx.fs
 rows.push({name:'provider-load',value:await files.loadBaselineInstructionSet(options,filesystem)})
 const bom=join(base,'bom.txt');writeFileSync(bom,Buffer.concat([Buffer.from([239,187,191,239,187,191]),Buffer.from('value')]));const target=await filesystem.resolve(bom),text=await filesystem.readText(target),chunks=[];for await(const chunk of await filesystem.streamText(target))chunks.push(chunk);const edited=await filesystem.editText(target,{oldString:'value',newString:'changed'});rows.push({name:'provider-bom',text,stream:chunks.join(''),before:edited.before,after:edited.after,bytes:[...readFileSync(bom)]})
 const resolved=config.resolveDiscoveryConfig(options)
 for(const [name,scope] of [['harness','user-global\0AGENTS.md'],['shared','agents-global\0AGENTS.md'],['project','.\0AGENTS.md'],['collision','.\\agents-global\0AGENTS.md'],['missing','child\0CLAUDE.md']]){
  const result=await files.probeScopeInstruction(scope,project,resolved,filesystem),value:any={kind:result.kind};if(result.kind==='present'){const file=result.file;value.file=Object.fromEntries(['absolutePath','displayPath','size'].filter(key=>key in file).map(key=>[key,file[key]]));value.read=await files.readScopeInstruction(file,128,filesystem)}rows.push({name:'scope-'+name,value})
 }
 rows.push({name:'collision-discovery',value:await files.discoverBaselineInstructionFiles({...options,cwd:collision})})
 writeFileSync(join(child,'AGENTS.md'),'x'.repeat(129));rows.push({name:'oversized-source',value:await files.loadBaselineInstructionSet(options,filesystem)})
 writeFileSync(join(home,'not-directory'),'file');rows.push({name:'host-enotdir',value:await files.loadBaselineInstructionSet({...options,dshHome:join(home,'not-directory','child')})})
 rows.push({name:'disabled',value:await files.loadBaselineInstructionSet({...options,maxBytes:0},filesystem)??null})
 const empty=join(base,'empty');mkdirSync(empty);const emptyOptions={...options,dshHome:empty,agentsHome:empty,instructionFileCandidates:[],localInstructionFileCandidates:[]}
 rows.push({name:'empty',value:await files.loadBaselineInstructionSet(emptyOptions)??null},{name:'empty-replacement',value:await files.loadBaselineInstructionSet({...emptyOptions,replacePreviousBaseline:true})})
}finally{await ctx.fiber.dispose()}
const normalize=(value:any):any=>typeof value==='string'&&value.includes(base)?value.replaceAll(base,'<work>'):Array.isArray(value)?value.map(normalize):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,item])=>[key,key==='version'?'<opaque-version>':normalize(item)])):value
process.stdout.write(JSON.stringify(normalize(rows)))
