import {load} from './rc022_subagent_fixture.mts'
const {LocalTerminalHandle}=await load('packages/subprocess/subprocess-local/src/terminal.ts'),{windowsProcessTree}=await load('packages/subprocess/subprocess-local/src/windows-inspector.ts'),rows:any[]=[],calls:any[]=[]
let table:any[]=[{pid:10,parentPid:1}],states:any={'10':{started:'shell',active:true}}
const snapshot=()=>({tree:(pid:number)=>windowsProcessTree(table,pid,(pid:number)=>states[String(pid)]?.started),session:()=>[],alive:(identity:any)=>states[String(identity.pid)]?.active===true&&states[String(identity.pid)].started===identity.started})
const inspector={snapshot,foregroundPgid:(pid:number)=>pid,isStdinWaiting:()=>false,signalGroup:(pid:number,signal:string)=>calls.push(['taskkill',pid,signal==='SIGKILL'])}
const pty={pid:10,onData:()=>({dispose(){}}),onExit:()=>({dispose(){}}),write:(data:string)=>calls.push(['write',data]),pause(){},resume(){}}
const terminal=new LocalTerminalHandle(pty,inspector,1,'win32')
const scenarios=[
 ['shell',[{pid:10,parentPid:1}],{'10':{started:'shell',active:true}}],
 ['child',[{pid:10,parentPid:1},{pid:11,parentPid:10}],{'10':{started:'shell',active:true},'11':{started:'child',active:true}}],
 ['same-child',[{pid:10,parentPid:1},{pid:11,parentPid:10}],{'10':{started:'shell',active:true},'11':{started:'child',active:true}}],
 ['orphan',[{pid:11,parentPid:1}],{'11':{started:'child',active:true}}],
 ['reused-root',[{pid:10,parentPid:1},{pid:12,parentPid:10}],{'10':{started:'unrelated',active:true},'11':{started:'child',active:true},'12':{started:'unrelated-child',active:true}}],
 ['reused-child',[],{'11':{started:'different-child',active:true}}],['gone',[],{}],
]
for(const [name,entries,current] of scenarios){table=entries as any;states=current;rows.push({name,tree:snapshot().tree(10),activity:await terminal.inspectActivity(),foreground:await terminal.inspectForeground()})}
terminal.quiescent=true;rows.push({name:'quiescent',activity:await terminal.inspectActivity()})
for(const signal of ['SIGINT','SIGTERM','SIGKILL','SIGHUP','SIGTSTP']){try{rows.push({name:signal,value:await terminal.signalForeground(signal)})}catch(error:any){rows.push({name:signal,error:error.message})}}
rows.push({name:'delivery',calls});terminal.output.end();process.stdout.write(JSON.stringify(rows))
