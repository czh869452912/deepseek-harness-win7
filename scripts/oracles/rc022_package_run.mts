import {existsSync,readFileSync} from 'node:fs'
import {mkdir,writeFile,readFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {runProfilePnpm}=await load('packages/boot/plugin-manager/src/operations.ts'),data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const mode of data.cases){
 const home=join(data.workspace,'source',mode),dir=join(home,'profile');await mkdir(dir,{recursive:true});const anchor=join(home,'package.json'),script=join(dir,'package.py')
 await writeFile(anchor,JSON.stringify({name:'installation'}));await writeFile(join(dir,'package.json'),JSON.stringify({name:'profile',dsh:{profile:{bundles:[]}}}));await writeFile(script,data.program)
 const controller=new AbortController(),output:any={stdout:'',stderr:''},options:any={command:mode==='missing'?join(dir,'missing.exe'):data.python,args:[script,mode],execution:'service',outputBytes:['large','unicode'].includes(mode)?13:4096,signal:controller.signal,activateNewBundles:false,onOutput:(text:string,stream:string)=>{output[stream]+=text}}
 if(['idle','progress'].includes(mode))options.idleTimeoutMs=500
 const timer=mode==='cancel'?setTimeout(()=>controller.abort(),400):undefined
 if(mode==='pre-cancel')controller.abort()
 let result:any
 try{result=await runProfilePnpm({profile:'test',dir,installAnchor:anchor,cwd:home,home},['probe'],options)}finally{if(timer)clearTimeout(timer)}
 let log:any=await readFile(result.logPath,'utf8');delete result.logPath
 if(mode==='unicode')for(const key of Object.keys(output))output[key]=!!output[key]
 if(['silent-failure','pre-cancel','missing'].includes(mode)){
  result.output=!!result.output;log=!!log
  for(const key of Object.keys(output))output[key]=!!output[key]
  if(mode==='pre-cancel'){process.stderr.write(JSON.stringify({sourcePreCancelledExitCode:result.exitCode})+'\n');delete result.exitCode}
  if(mode==='missing')result.exitCode=result.exitCode!==0
 }
 rows.push({mode,result,log,output,recordRemoved:!existsSync(join(dir,'.plugin-manager/run.json'))})
}
console.log(JSON.stringify(rows))
