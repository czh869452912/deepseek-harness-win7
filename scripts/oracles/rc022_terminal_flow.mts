import {load} from './rc022_subagent_fixture.mts'
const {TerminalFollower}=await load('packages/api/terminal-controller/src/stream.ts'),{TerminalRetention}=await load('packages/api/terminal-controller/src/retention.ts'),rows:any[]=[]
const frame={type:'output',sequence:1,data:'终端😀\ufeff'},maximum=Buffer.byteLength(JSON.stringify(frame),'utf8')
let follower=new TerminalFollower(maximum),controller=new AbortController(),stream=follower.read(controller.signal)[Symbol.asyncIterator]()
follower.push(frame);const one=(await stream.next()).value;follower.push(frame);follower.finish();follower.fail(Error('ignored after finish'));const frames=[one];for await(const item of {[Symbol.asyncIterator]:()=>stream})frames.push(item);rows.push({name:'exact-follower-bound',maximum,frames,active:follower.active})
follower=new TerminalFollower(maximum);follower.push(frame);follower.push(frame);try{await follower.read(new AbortController().signal)[Symbol.asyncIterator]().next()}catch(error){rows.push({name:'follower-overflow',error:String((error as Error).message),active:follower.active})}
follower=new TerminalFollower(1000);follower.push(frame);controller=new AbortController();controller.abort();const aborted=[];for await(const item of follower.read(controller.signal))aborted.push(item);rows.push({name:'preaborted-follower',frames:aborted})
follower=new TerminalFollower(1000);controller=new AbortController();stream=follower.read(controller.signal)[Symbol.asyncIterator]();const reading=stream.next();await Promise.resolve();follower.push(frame);const first=(await reading).value,ending=stream.next();await Promise.resolve();controller.abort();await ending;rows.push({name:'waiting-follower',first,active:follower.active});await stream.return?.()
const originalSetTimeout=globalThis.setTimeout,originalClearTimeout=globalThis.clearTimeout,originalNow=performance.now
class Clock{
 time=0;order=0;timers:any[]=[]
 now(){return this.time}
 later(delay:number,callback:()=>void){const timer={due:this.time+delay,callback,cancelled:false,order:++this.order,unref:()=>{}};this.timers.push(timer);return timer}
 async pump(){for(let i=0;i<20;i++)await Promise.resolve()}
 async advance(amount:number){const end=this.time+amount;while(true){const ready=this.timers.filter(timer=>!timer.cancelled&&timer.due<=end).sort((a,b)=>a.due-b.due||a.order-b.order);if(!ready.length)break;const timer=ready[0];timer.cancelled=true;this.time=timer.due;timer.callback();await this.pump()}this.time=end;await this.pump()}
 count(){return this.timers.filter(timer=>!timer.cancelled).length}
}
try{
 for(const scenario of ['idle','holds','busy','unknown','revision','retry','huge-retry']){
  const clock=new Clock(),calls:number[]=[],errors:string[]=[],activity={state:'idle',revision:1};let failedOnce=['retry','huge-retry'].includes(scenario)
  Object.defineProperty(performance,'now',{value:()=>clock.now(),configurable:true});globalThis.setTimeout=((callback:any,delay:number)=>clock.later(delay,callback)) as any;globalThis.clearTimeout=((timer:any)=>{if(timer)timer.cancelled=true}) as any
  const inspect=async()=>({...activity}),terminate=async()=>{calls.push(clock.now());if(failedOnce){failedOnce=false;throw Error('still alive')}},policy={unattendedTimeoutMs:100,activityPollIntervalMs:10,cleanupRetryMs:20}
  if(scenario==='huge-retry')Object.assign(policy,{unattendedTimeoutMs:0,cleanupRetryMs:3000000000})
  const owner=new TerminalRetention(policy,inspect,terminate,(error:Error)=>errors.push(error.message)),streams:any[]=[]
  try{
   if(scenario==='holds'){const a=new AbortController(),b=new AbortController(),first=owner.retain(a.signal)[Symbol.asyncIterator](),second=owner.retain(b.signal)[Symbol.asyncIterator]();streams.push(first,second);await first.next();await second.next();a.abort();await clock.advance(500);b.abort();await clock.advance(99)}
   else if(['busy','unknown'].includes(scenario)){activity.state=scenario;await clock.advance(1000);Object.assign(activity,{state:'idle',revision:2});await clock.advance(109)}
   else if(scenario==='revision'){await clock.advance(90);owner.invalidate();activity.revision=2;await clock.advance(109)}
   else if(scenario==='huge-retry'){try{await owner.close()}catch(error){errors.push((error as Error).message)}await clock.advance(2999999999)}
   else await clock.advance(99)
   rows.push({name:scenario+'-before',calls:[...calls],errors:[...errors]});await clock.advance(1)
   if(scenario==='retry'){try{await owner.retain(new AbortController().signal)[Symbol.asyncIterator]().next()}catch(error){rows.push({name:'closed-on-failure',code:(error as any).code})}await clock.advance(20)}
   rows.push({name:scenario+'-after',calls:[...calls],errors:[...errors]})
  }finally{await owner.dispose();for(const stream of streams)await stream.return?.()}
  rows.push({name:scenario+'-disposed',timers:clock.count()})
 }
}finally{globalThis.setTimeout=originalSetTimeout;globalThis.clearTimeout=originalClearTimeout;Object.defineProperty(performance,'now',{value:originalNow,configurable:true})}
process.stdout.write(JSON.stringify(rows))
