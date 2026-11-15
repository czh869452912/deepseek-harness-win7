import {PassThrough} from 'node:stream'
import {load} from './rc022_subagent_fixture.mts'
const {BrowserTerminal}=await load('packages/api/terminal-controller/src/terminal.ts'),{AgentTerminalHandle}=await load('packages/api/terminal-controller/src/agent.ts'),{inputChannel}=await load('packages/api/terminal-controller/tests/input.ts'),rows:any[]=[]
async function until(predicate:()=>boolean){const end=Date.now()+3000;while(!predicate()){if(Date.now()>end)throw Error('condition timed out');await new Promise<void>(done=>setTimeout(done,1))}}
function fixture(){
 const output=new PassThrough(),outcome=Promise.withResolvers<any>(),released:string[]=[]
 const handle:any={pid:123,output,done:outcome.promise,writes:[],sizes:[],signals:[],terminated:0,retry:false,
  async write(data:string){this.writes.push(data)},async resize(cols:number,rows:number){this.sizes.push([cols,rows])},
  async inspectActivity(){return {state:'unknown',revision:0}},async inspectForeground(){return {pgid:123,input:'unknown'}},
  async signalForeground(signal:string){this.signals.push(signal);return 123},
  async terminate(){this.terminated++;if(this.retry&&this.terminated===1)throw Error('cleanup failed');if(!this.completed){output.end('FINAL\r\n');outcome.resolve({exitCode:0,signal:null});this.completed=true}else if(!output.writableEnded)output.end()}}
 const terminal=new BrowserTerminal(handle,{id:'terminal-test',title:'shell',shell:{path:'/bin/sh',name:'sh',args:['-i']},cwd:'/workspace',cols:20,rows:4,state:'running',exitCode:null,origin:'agent',control:'agent'},6,100000,async()=>{released.push('release')})
 return {terminal,handle,released,outcome,output}
}
async function attach(terminal:any){
 const channel=inputChannel(),abort=new AbortController(),frames:any[]=[],errors:string[]=[],stream=terminal.attach(channel.source,{maxInputBytes:12,maxCols:200,maxRows:100},abort.signal,{maxBufferedBytes:4096})[Symbol.asyncIterator]()
 frames.push((await stream.next()).value)
 const pump=(async()=>{try{for await(const frame of {[Symbol.asyncIterator]:()=>stream})frames.push(frame)}catch(error:any){errors.push(error.message)}})()
 return {channel,abort,frames,errors,pump,async close(){abort.abort();await pump;await stream.return?.()}}
}
function record(name:string,terminal:any,handle:any,released:any,views:any[]=[]){rows.push(structuredClone({name,info:terminal.info,revision:terminal.revision,writes:handle.writes,sizes:handle.sizes,signals:handle.signals,terminated:handle.terminated,released,views:views.map(v=>({frames:v.frames,errors:v.errors}))}))}
async function failure(operation:Promise<any>){try{await operation;return null}catch(error:any){return {name:error.name,code:error.code??null,message:error.message}}}
{
 const {terminal,handle,released,outcome,output}=fixture(),agent=new AgentTerminalHandle(terminal,()=>terminal.close()),views:any[]=[]
 try{
  const first=await attach(terminal);views.push(first)
  output.write(Buffer.from([0xef,0xbb,0xbf,...Buffer.from('hello\r\n'),0xe4]));await until(()=>terminal.sequence===1)
  output.write(Buffer.from([0xb8,0xad,...Buffer.from('\r\n$ ')]));await until(()=>terminal.sequence===2)
  await until(()=>first.frames.length===3);record('split-bom',terminal,handle,released,views)
  await agent.write('echo agent\r');await agent.signal('interrupt')
  rows.push({name:'agent',id:agent.id,pid:agent.pid,activity:await terminal.inspectActivity(),foreground:await agent.inspectForeground(),page:agent.read({offset:0,count:10,maxBytes:1000})})
  const second=await attach(terminal);views.push(second);await until(()=>first.frames.length===4)
  first.channel.push({type:'write',sequence:1,data:'old'});await until(()=>first.frames.some(f=>f.type==='ack'))
  second.channel.push({type:'resize',sequence:1,cols:12,rows:5});await until(()=>second.frames.some(f=>f.type==='ack'))
  second.channel.push({type:'write',sequence:2,data:'person',typed:true});await until(()=>second.frames.filter(f=>f.type==='ack').length===2)
  rows.push({name:'takeover',write:await failure(agent.write('denied')),signal:await failure(agent.signal('interrupt')),close:await failure(agent.close())})
  record('exclusive',terminal,handle,released,views)
  await first.close();await second.close();record('detached',terminal,handle,released,views)
  terminal.rename('renamed');const mark=terminal.markScreen();await terminal.drain()
  output.write('new\r\nline');await until(()=>terminal.sequence===3)
  rows.push({name:'mark',page:terminal.readScreen({offset:0,count:100,maxBytes:1000}),mark:mark.lines()})
  handle.completed=true;outcome.resolve({exitCode:7,signal:null});output.end();await terminal.drained
  const third=await attach(terminal);views.push(third);third.channel.push({type:'write',sequence:1,data:'exited'});await until(()=>third.frames.some(f=>f.type==='ack'))
  record('exit-reconnect',terminal,handle,released,views)
  await terminal.close();await third.pump;record('closed',terminal,handle,released,views)
  try{mark.lines()}catch(error:any){rows.push({name:'released-mark',code:error.code,message:error.message})}
 }finally{for(const view of views)await view.close();await terminal.dispose()}
}
for(const [name,command] of [['gap',{type:'write',sequence:2,data:'x'}],['bytes',{type:'write',sequence:1,data:'中'.repeat(5)}],['resize',{type:'resize',sequence:1,cols:1,rows:2}]] as const){
 const {terminal,handle,released}=fixture(),view=await attach(terminal)
 try{view.channel.push(command);await view.pump;record(name,terminal,handle,released,[view])}finally{await view.close();await terminal.dispose()}
}
{
 const {terminal,handle,released}=fixture(),view=await attach(terminal);handle.retry=true
 try{rows.push({name:'retry-first',error:(await failure(terminal.close()))!.message,released:terminal.screenReleased});await terminal.close();await view.pump;record('retry-closed',terminal,handle,released,[view])}finally{await view.close();await terminal.dispose()}
}
{
 const {terminal,handle,released,outcome,output}=fixture()
 try{
  const abort=new AbortController(),reason=Error('exact abort'),waiting=terminal.changed(terminal.revision,abort.signal);abort.abort(reason)
  try{await waiting}catch(error){rows.push({name:'abort-wait',same:error===reason,waiters:terminal.waiters.size})}
  handle.completed=true;outcome.reject(Error('wait failed'));output.end();await terminal.drained;record('failed',terminal,handle,released)
 }finally{await terminal.dispose()}
}
rows.push({name:'disposed',engines:0,workers:0});process.stdout.write(JSON.stringify(rows))
