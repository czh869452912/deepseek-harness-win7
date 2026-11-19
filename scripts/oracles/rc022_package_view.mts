import {readFileSync} from 'node:fs'
import {mkdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {viewProfilePackage}=await load('packages/boot/plugin-manager/src/operations.ts'),input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),home=join(input.workspace,'source'),script=join(home,'package.py'),rows:any[]=[]
await mkdir(home,{recursive:true});await writeFile(script,input.program)
process.env.DSH_PRIVATE_VALUE='must-not-inherit';process.env.EXAMPLE_SESSION_TOKEN='must-not-inherit'
for(const mode of input.cases){
 const control=new AbortController(),options:any={command:input.python,args:[script,mode],fields:['name','version','dsh'],timeoutMs:mode==='slow'?150:5000,signal:control.signal}
 if(mode==='registry')options.registry='https://corp.example/'
 if(mode==='environment')options.env={EXPLICIT_SECRET:'explicit',CUSTOM_DATA:'value',DSH_PRIVATE_VALUE:'explicit'}
 if(mode==='missing')options.command=join(home,'not-a-program.exe')
 if(mode==='pre-cancel')control.abort(new Error('closed'))
 const timer=mode==='cancel'?setTimeout(()=>control.abort(),150):undefined
 let result:any;try{result=await viewProfilePackage(home,'@scope/pkg@^1.0',options)}finally{clearTimeout(timer)}
 if(result.cause!==undefined)result.cause={code:result.cause.code}
 if(mode==='missing')result={launchFailed:result.exitCode!==0&&!!(result.cause||result.stderr)}
 if(['normal','registry','environment'].includes(mode)){const value=JSON.parse(result.stdout);value.cwd='<profile>';result.stdout=value}
 if(['slow','cancel'].includes(mode)&&result.stdout!=='')throw new Error('Silent deadline fixture emitted output')
 rows.push({name:mode,result})
}
console.log(JSON.stringify(rows))
