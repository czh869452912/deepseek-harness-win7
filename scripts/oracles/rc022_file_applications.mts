import {readFileSync,existsSync} from 'node:fs'
import {join,dirname} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],signal=new AbortController().signal
const {nativeFileApplications,openNativeFileApplication}=await load('packages/util/native-command/src/file-applications.ts'),{Context}=await load('vendor/cordis/src/index.ts'),{default:Controller}=await load('packages/api/session-controller/src/index.ts')
const apps=[{id:'app',name:'Editor',default:true,icon:null}]
for(const action of ['query','long-open','wsl','cancel','failure']){
 const scripts:string[]=[],calls:string[]=[],controller=new AbortController()
 const run=async(command:string,args:string[],signal:AbortSignal)=>{
  calls.push(command);if(command==='wslpath')return{stdout:'C:\\translated.txt\r\n',stderr:''}
  const script=args.at(-1)!,text=readFileSync(script,'utf8'),encoded=[...text.matchAll(/FromBase64String\('([^']*)'\)/g)].map(match=>Buffer.from(match[1]!,'base64').toString('utf8'));scripts.push(script)
  rows.push({name:action+'-invocation',command,bom:text.startsWith('\uFEFF'),path:action==='long-open'?encoded[0]!.length:encoded[0],application:encoded[1],fileArgument:args.includes('-File'),smallArgv:args.reduce((a,b)=>a+b.length,0)<500,sourceHelper:text.includes('public static class DshFileAssociations')})
  if(action==='cancel'){controller.abort(new Error('cancelled'));signal.throwIfAborted()}if(action==='failure')throw Error('helper failed');return{stdout:JSON.stringify(apps),stderr:''}
 }
 const options={platform:action==='wsl'?'linux':'win32',env:action==='wsl'?{WSL_INTEROP:'yes'}:{},osRelease:'linux',run}
 try{if(action==='long-open')await openNativeFileApplication('C:/'+'a'.repeat(35000)+"\u6d4b\u8bd5' &.txt",'app',controller.signal,options);else rows.push({name:action+'-result',value:await nativeFileApplications("C:/file' &.txt",controller.signal,options)})}catch(error:any){rows.push({name:action+'-error',message:error.message})}
 rows.push({name:action+'-cleanup',gone:scripts.every(path=>!existsSync(path)&&!existsSync(dirname(path))),calls})
}
const mac=[{id:'/Apps/old.app',name:'Editor',default:false,icon:null,bundle:'bundle',version:'1.9'},{id:'/Apps/new.app',name:'Editor',default:false,icon:null,bundle:'bundle',version:'2.0'},{id:'/Apps/preferred.app',name:'Editor',default:true,icon:null,bundle:'bundle',version:'1.0'},{id:'/Apps/side.app',name:'Editor Beta',default:false,icon:null,bundle:'bundle',version:'9'}];let calls:any[]=[]
const macRun=async(command:string,args:string[])=>{calls.push([command,...command==='osascript'?[args.at(-1)]:args]);return{stdout:JSON.stringify(mac),stderr:''}}
const macOptions={platform:'darwin',env:{},run:macRun}
rows.push({name:'mac-dedupe',value:await nativeFileApplications('/file.txt',signal,macOptions)});await openNativeFileApplication('/file.txt','/Apps/old.app',signal,macOptions)
try{await openNativeFileApplication('/file.txt','/arbitrary.app',signal,macOptions)}catch(error:any){rows.push({name:'mac-stale',message:error.message})}rows.push({name:'mac-launch-calls',value:calls});calls=[]
const linuxRun=async(command:string,args:string[])=>{calls.push([command,...args]);return{stdout:command==='gio'&&args[0]==='info'?'standard::content-type: text/plain':'Default application for text/plain: nested-editor.desktop\nRegistered applications:\n  nested-editor.desktop\n  hidden.desktop\n  missing.desktop\n',stderr:''}}
const linuxOptions={platform:'linux',env:{HOME:workspace,XDG_DATA_HOME:join(workspace,'xdg'),XDG_DATA_DIRS:'',LANG:'zh_CN.UTF-8'},osRelease:'linux',run:linuxRun}
const applications=await nativeFileApplications('/file.txt',signal,linuxOptions);rows.push({name:'linux-catalog',value:applications});await openNativeFileApplication('/file.txt',applications[0].id,signal,linuxOptions);rows.push({name:'linux-launch-calls',value:calls})
const associationCalls:any[]=[],associated=async(command:string,args:string[])=>{associationCalls.push([command,...args]);return{stdout:'',stderr:''}},{openNativeAssociatedPath}=await load('packages/util/native-command/src/path-opener.ts')
await openNativeAssociatedPath('/page.html',signal,{platform:'linux',env:{BROWSER:'browser'},osRelease:'linux',run:associated});await openNativeAssociatedPath('/page.html',signal,{platform:'darwin',env:{},run:associated});rows.push({name:'associated-html',value:associationCalls})
const ctx=new Context(),trace:any[]=[]
try{
 await ctx.plugin((await load('packages/typert/registry/src/index.ts')).default);await ctx.plugin((await load('packages/fs/fs-local/src/index.ts')).default,{cwd:workspace})
 const api=new Controller(ctx,{nativeOpen:true},{openPath:async(path:string)=>trace.push({kind:'open',path}),revealPath:async(path:string)=>trace.push({kind:'reveal',path}),openFileApplication:async(path:string,application:string)=>trace.push({kind:'explicit',path,application}),fileApplications:async(path:string)=>{trace.push({kind:'catalog',path});return apps}})
 for(const request of [{path:join(workspace,'file.txt')},{path:join(workspace,'file.txt'),action:'reveal',application:'ignored'},{path:join(workspace,'file.txt'),application:'app'}])rows.push({name:'desktop-open',value:await api.openWorkspacePath(request,signal)})
 rows.push({name:'desktop-catalog',value:await api.workspacePathApplications({path:join(workspace,'file.txt')},signal)},{name:'desktop-trace',value:trace})
 for(const kind of ['empty','unmapped','roundtrip','cancelled','native-error']){
  const abort=new AbortController(),originalMapping=ctx.fs.processPathFromHostPath,originalProcess=ctx.fs.processPath,originalOpen=(api as any).openPath
  if(kind==='unmapped')ctx.fs.processPathFromHostPath=()=>undefined;if(kind==='roundtrip')ctx.fs.processPath=()=> 'different';if(kind==='cancelled')abort.abort();if(kind==='native-error')(api as any).openPath=async()=>{throw Error('native failure')}
  try{await api.openWorkspacePath({path:kind==='empty'?'':join(workspace,'file.txt')},abort.signal)}catch(error:any){rows.push({name:'desktop-'+kind,code:error.code,message:error.message,hasCause:error.cause!==undefined})}finally{ctx.fs.processPathFromHostPath=originalMapping;ctx.fs.processPath=originalProcess;(api as any).openPath=originalOpen}
 }
 (api as any).canOpenPath=()=>false;const abort=new AbortController();abort.abort();rows.push({name:'disabled-catalog',value:await api.workspacePathApplications({path:''},abort.signal)})
}finally{await ctx.fiber.dispose()}
const normalize=(v:any):any=>typeof v==='string'?v.replaceAll(workspace,'<workspace>').replaceAll('\\','/'):Array.isArray(v)?v.map(normalize):v!==null&&typeof v==='object'?Object.fromEntries(Object.entries(v).map(([k,value])=>[k,normalize(value)])):v
process.stdout.write(JSON.stringify(normalize(rows)))
