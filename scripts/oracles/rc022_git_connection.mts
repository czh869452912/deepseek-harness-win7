import {readFileSync} from 'node:fs'
import {mkdir,writeFile,readFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const transport=await load('packages/boot/plugin-manager/src/git-transport.ts'),connection=await load('packages/boot/plugin-manager/src/github-connection.ts'),{parseInstallSpec}=await load('packages/boot/plugin-manager/src/install-spec.ts')
const data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const spec of data.specs){let result:any;try{result={value:transport.sshGitSpec(parseInstallSpec(spec))??null}}catch{result={error:true}}rows.push({kind:'ssh',spec,result})}
function configFor(mode:string):string{
 const info=data.fixture
 if(['http-success','check-success'].includes(mode))return `[url "${info.repository}"]\n insteadOf = https://git.example/team/repo.git\n`
 const endpoint=['transport-cancel','check-timeout','check-cancel'].includes(mode)?'slow':['check-auth','check-credentials'].includes(mode)?'auth':'failure'
 let config=`[url "${info.url}/${endpoint}/"]\n insteadOf = https://git.example/\n insteadOf = https://user:secret@git.example/\n insteadOf = https://sub.github.com/\n[http]\n proxy =\n`
 config+=mode==='ssh-success'?`[url "${info.repository}"]\n insteadOf = ssh://git@git.example/team/repo.git\n`:'[url "file:///definitely-no-dsh-repository"]\n insteadOf = ssh://git@git.example/team/repo.git\n'
 return config
}
async function normalize(result:any):Promise<any>{
 if(result===undefined)return null
 const {logPath,output,...value}=result,bytes=await readFile(logPath)
 Object.assign(value,{logBytes:bytes.length,logEndsWithOutput:bytes.subarray(bytes.length-Buffer.byteLength(output)).equals(Buffer.from(output)),hasDiagnostic:!!output})
 if(value.timedOut)value.timeoutDiagnostic=output.includes('timed out after 300ms')
 if(value.timedOut||value.kind==='unknown'){delete value.logBytes;delete value.logEndsWithOutput;value.exitCode=value.exitCode!==0}
 value.argv=value.argv.map((arg:string)=>arg.replace(data.fixture.url,'<loopback>'))
 return value
}
for(const mode of data.modes){
 const dir=join(data.workspace,'source',mode);await mkdir(dir,{recursive:true});const config=join(dir,'git.config'),trace=join(dir,'trace.jsonl');await writeFile(config,configFor(mode))
 const controller=new AbortController(),options={timeoutMs:mode==='check-timeout'?300:3000,outputBytes:mode==='check-tail'?4:4096,signal:controller.signal,env:{GIT_CONFIG_GLOBAL:config,GIT_CONFIG_NOSYSTEM:'1',GIT_TRACE2_EVENT:trace}}
 const timer=['transport-cancel','check-cancel'].includes(mode)?setTimeout(()=>controller.abort(),300):undefined
 const text=mode==='check-credentials'?'https://user:secret@git.example/team/repo.git#main':mode==='github-subdomain'?'https://sub.github.com/team/repo.git':'https://git.example/team/repo.git#main',parsed=parseInstallSpec(text)
 let result:any
 try{
  if(['http-success','ssh-success','both-fail','transport-cancel'].includes(mode))result=await transport.chooseGitTransport(parsed,dir,options)
  else result=await normalize(await (['github-skip','github-subdomain'].includes(mode)?connection.checkGithubConnection:connection.checkGitConnection)(parsed,dir,options))
 }finally{if(timer)clearTimeout(timer)}
 let commands:any[]=[]
 try{commands=(await readFile(trace,'utf8')).trim().split('\n').map(line=>JSON.parse(line)).filter(row=>row.event==='start'&&row.argv?.includes('ls-remote')).map(row=>row.argv.slice(1))}catch{}
 rows.push({kind:'actual',mode,result,commands})
}
console.log(JSON.stringify(rows))
