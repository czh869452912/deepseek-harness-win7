import {readFileSync,mkdirSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {resolveShell,discoverShells,findShell}=await load('packages/api/terminal-controller/src/shells.ts'),{SubprocessExecutableNotFoundError}=await load('packages/subprocess/subprocess/src/index.ts'),rows:any[]=[],signal=new AbortController().signal
for(const [platform,path] of [['windows',null],['posix',null],['windows','C:\\Tools\\PowerShell.EXE'],['posix','/bin/zsh']]){
 const calls:any[]=[],provider={terminalEnvironment:async()=>{calls.push('environment');return {platform,...path===null?{}:{defaultShell:path}}},resolveExecutable:async(command:string)=>{calls.push(command);return command}}
 rows.push({name:'default-'+platform+'-'+String(rows.length),value:await resolveShell(provider,undefined,signal),calls})
}
const calls:string[]=[],provider={terminalEnvironment:async()=>({platform:'posix'}),resolveExecutable:async(command:string)=>{calls.push(command);if(command==='missing')throw new SubprocessExecutableNotFoundError('not installed');if(command==='offline')throw Error('transport offline');return command}},configured={path:'/bin/bash',args:['--noprofile','-i'],name:'Configured'}
const shells=await discoverShells(provider,configured,['/usr/bin/BASH','powershell.exe','C:\\tools\\PWSH.EXE','missing','cmd'],signal);rows.push({name:'discovered',value:shells,calls:[...calls]})
for(const name of ['Bash.exe','C:\\bin\\PwSh','powershell','missing'])rows.push({name:'find-'+name,value:findShell(shells,name)??null})
try{await discoverShells(provider,configured,['offline'],signal)}catch(error){rows.push({name:'transport-failure',message:(error as Error).message})}
const base=join(JSON.parse(readFileSync(process.argv[3]!,'utf8')),'source'),first=join(base,'first'),second=join(base,'second');mkdirSync(first,{recursive:true});mkdirSync(second);writeFileSync(join(first,'dsh-shell.exe'),'');writeFileSync(join(second,'dsh-shell.exe'),'');mkdirSync(join(first,'directory.exe'))
const {Context}=await load('vendor/cordis/src/index.ts'),ctx=new Context()
try{
 await ctx.plugin((await load('packages/subprocess/subprocess-local/src/index.ts')).default);const runtime=ctx.subprocess,env={PATH:first+';'+second,PATHEXT:'.EXE;.CMD'}
 rows.push({name:'local-path',value:await runtime.resolveExecutable('dsh-shell',env,signal)},{name:'local-absolute',value:await runtime.resolveExecutable(join(second,'dsh-shell.exe'),undefined,signal)})
 for(const name of ['absent','directory',join(first,'missing.exe'),'./relative','']){try{await runtime.resolveExecutable(name,env,signal)}catch(error){rows.push({name:'lookup-'+name.replace(first,'<first>'),message:(error as Error).message,code:(error as any).code??null,typed:(error as Error).name==='SubprocessExecutableNotFoundError'})}}
 const controller=new AbortController(),failure=Error('cancel lookup');controller.abort(failure);try{await runtime.resolveExecutable('dsh-shell',env,controller.signal)}catch(error){rows.push({name:'lookup-cancellation',same:error===failure})}
 const result=await runtime.terminalEnvironment(signal);rows.push({name:'local-environment',platform:result.platform,hasDefault:typeof result.defaultShell==='string'})
}finally{await ctx.fiber.dispose()}
const normalize=(value:any):any=>typeof value==='string'?value.replaceAll(base,'<work>').replaceAll(JSON.stringify(base).slice(1,-1),'<work>'):Array.isArray(value)?value.map(normalize):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)])):value
process.stdout.write(JSON.stringify(normalize(rows)))
