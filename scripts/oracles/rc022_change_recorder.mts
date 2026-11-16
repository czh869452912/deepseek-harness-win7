import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const Runtime=(await load('packages/subprocess/subprocess-local/src/index.ts')).default
const {GitRunner}=await load('packages/deliverables/workspace-changes/src/git.ts')
const {TurnRecorder}=await load('packages/deliverables/workspace-changes/src/recorder.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),ctx=new Context(),rows:any[]=[]
function state(repo:string){
 const result:any={},base=path.join(repo,'.git')
 function visit(file:string){if(!fs.existsSync(file))return;const st=fs.statSync(file);if(st.isDirectory()){for(const name of fs.readdirSync(file))visit(path.join(file,name))}else result[path.relative(base,file)]=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')}
 for(const part of ['index','HEAD','refs','objects'])visit(path.join(base,part));return result
}
await ctx.plugin(Runtime)
try{
 for(const [index,test] of input.cases.entries()){
  const base=path.join(input.root,'source',String(index)),cwd=path.join(base,'cwd'),events:any[]=[],warnings:any[]=[],snapshots:any[]=[]
  process.env.TEMP=path.join(base,'temp')
  const session={append(type:string,data:any){const event={seq:events.length,type,data};events.push(event);return event}}
  const before=test.git?state(cwd):null
  const recorder=new TurnRecorder(session,cwd,{git:Promise.resolve(test.git?new GitRunner(ctx.subprocess,'git',{timeoutMs:30000,outputMaxBytes:1048576}):null),tempRoot:path.join(base,'temp'),maxFiles:test.maxFiles??500,maxFileBytes:test.maxFileBytes??1048576,diffTimeoutMs:1000,warn:(message:string)=>warnings.push(message)})
  let unknown
  try{
   recorder.start(1)
   await recorder.settled()
   for(const op of test.ops){
    if(op[0]==='start')recorder.start(op[1])
    else if(op[0]==='capture')recorder.capture(path.resolve(cwd,op[1]))
    else if(op[0]==='write')fs.writeFileSync(path.join(cwd,op[1]),op[2])
    else if(op[0]==='delete')fs.unlinkSync(path.join(cwd,op[1]))
    else if(op[0]==='result')recorder.observe({seq:op[1],data:{turn:op[2]}})
    else if(op[0]==='stop')await recorder.stopping(op[1])
    else if(op[0]==='end')recorder.end(op[1])
    else if(op[0]==='collect'){
     await recorder.settled();const records=[]
     for(const event of events){const summary=recorder.summary(event.seq),diffs=[];for(let i=0;i<=summary.files.length;i++)diffs.push(await recorder.diff(event.seq,i,new AbortController().signal)??null);records.push({summary:{...summary,cwd:'<cwd>'},diffs})}
     snapshots.push(records)
    }
    await recorder.settled()
   }
   unknown=await recorder.diff(999,0,new AbortController().signal)??null
  }finally{await recorder.dispose()}
  const current=test.git?state(cwd):null
  rows.push({name:test.name,snapshots,events,warnings,unknown,disposed:recorder.summary(0)??null,scratchRemoved:!fs.readdirSync(path.join(base,'temp')).some(name=>name.startsWith('dsh-workspace-changes-')),untouched:before===null||Object.keys(before).length===Object.keys(current).length&&Object.entries(before).every(([key,value])=>current[key]===value)})
 }
 process.stdout.write(JSON.stringify(rows))
}finally{await ctx.fiber.dispose()}
