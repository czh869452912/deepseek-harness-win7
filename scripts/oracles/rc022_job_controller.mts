import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {JobController}=await load('packages/api/job-controller/src/index.ts'),{OutputRing}=await load('packages/jobs/jobs-local/src/ring.ts'),{JobError}=await load('packages/jobs/jobs/src/error.ts'),rows:any[]=[]
for(const item of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const name=item.name,ring=new OutputRing(),listeners:any[]=[],calls:any[]=[],error=Error('producer cancel failed');let status=['live','removed','kill-running','kill-cancel-failed'].includes(name)?'running':'completed',deleted=false
 for(const text of item.texts??[])ring.append(text,{channel:'stdout'},item.cap??65536)
 const view=()=>({id:'job',...name==='unowned'?{}:{owner:'owner'},status,kind:'bash',label:'work',startedAt:1,output:{earliest:ring.earliest,total:ring.total}}),emit=(event:any)=>{for(const listener of [...listeners])listener(event)}
 const registry:any={events:{subscribe:(filter:any,listener:any)=>{calls.push({subscribe:filter});listeners.push(listener);return ()=>{calls.push('unsubscribe');listeners.splice(listeners.indexOf(listener),1)}}},get:(id:string,caller?:string)=>{calls.push({get:[id,caller??null]});if(name==='kill-lookup-text')throw 'lookup unavailable';if(name==='kill-lookup-error')throw Error('lookup unavailable');if(deleted||['missing','kill-missing'].includes(name))throw new JobError('unknown job '+id,'JOB_NOT_FOUND');if(['foreign','kill-foreign'].includes(name))throw new JobError('job '+id+' belongs to another session','JOB_FOREIGN_SESSION');return view()},readAt:(id:string,offset:number,caller?:string)=>{calls.push({readAt:[id,offset,caller??null]});return name==='loss-empty'?{chunks:[],next:0,lossy:true}:ring.readFrom(offset)},list:(caller:string)=>{calls.push({list:caller});return [view()]},kill:(id:string,caller:string,reason:string)=>{calls.push({kill:[id,caller,reason]});if(name==='kill-cancel-failed')throw error;return status==='completed'?'already-finished':'requested'}}
 const controller:any=Object.create(JobController.prototype);controller.ctx={jobs:registry};controller.observeFlushMs=1;controller.observeMaxFrameBytes=item.budget??65536
 const abort=new AbortController(),reason=Error('carrier stopped'),frames:any[]=[];let early:any=null,result:any=null,stream:any
 if(name==='aborted')abort.abort(reason)
 const request:any={jobId:'job',sessionId:'owner',...'offset' in item?{from:item.offset}:{}};if(name==='unowned')delete request.sessionId
 try{
  if(name.startsWith('kill-'))result=controller.kill(request)
  else if(name==='rows'){
   stream=controller.list({sessionId:'owner'},abort.signal);frames.push((await stream.next()).value)
   let done=false;const pending=stream.next().then((value:any)=>{done=true;return value});await Promise.resolve();emit({type:'output',id:'job'});emit({type:'progress',job:{id:'foreign',owner:'other'}});await Promise.resolve();early=done
   emit({type:'progress',job:view()});frames.push((await pending).value);const end=stream.next();await Promise.resolve();abort.abort(reason);await end
  }else if(['removed','live'].includes(name)){
   stream=controller.follow(request,abort.signal);frames.push((await stream.next()).value)
   if(name==='removed'){status='killed';deleted=true;emit({type:'removed',job:view()});frames.push((await stream.next()).value)}
   else{const pending=stream.next();await Promise.resolve();ring.append('live 🐱',{channel:'stderr'},65536);emit({type:'output',id:'job'});frames.push((await pending).value);status='completed';emit({type:'settled',job:view()});frames.push((await stream.next()).value)}
   for await(const frame of stream)frames.push(frame)
  }else{stream=controller.follow(request,abort.signal);for await(const frame of stream)frames.push(frame)}
 }catch(failure:any){result={error:{name:failure.name,message:failure.message,code:failure.code??null,details:failure.details??null,original:failure===error||failure===reason}}}
 finally{if(stream)await stream.return()}
 rows.push({name,frames,result,early,calls,listeners:listeners.length})
}
console.log(JSON.stringify(rows))
