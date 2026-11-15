import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Store}=await load('packages/core/session/src/index.ts'),{default:Registry}=await load('packages/session/session-projection/src/index.ts'),{default:Agents}=await load('packages/core/agent/src/index.ts'),{default:Titles}=await load('packages/session/session-title/src/index.ts')
const config={fallbackMaxWords:5,fallbackMaxBytes:40,maxTitleBytes:80},message=(text:string)=>({id:'input',role:'user',content:[{type:'text',text}],source:{kind:'user'}}),rows:any[]=[],oldNow=Date.now;Date.now=()=>1000
try{for(const action of ['overlap','caller-cancel','session-detach','service-drain','queued-dispose','empty-fallback']){
 const ctx=new Context(),releases:any[]=[],pending:any[]=[];try{
  await ctx.plugin(Store);await ctx.plugin(Registry);await ctx.plugin(Agents);const fiber=await ctx.plugin(Titles,action==='empty-fallback'?{...config,fallbackMaxBytes:1}:config),titles=ctx.sessionTitle,store=ctx.sessions,session=store.prepare('lifecycle'),detach=store.enter(session);store.announce(session);session.append('user/message',message(action==='empty-fallback'?'中文':'A human prompt'),{surfaceOp:'append'});const row:any={action}
  if(action==='queued-dispose'){
   const job=titles.refresh(session);pending.push(job);void job.catch(()=>{});const closing=fiber.dispose();try{await job}catch(error:any){row.error=error.message}await closing;row.title=titles.get(session)??null
  }else{
   await titles.refresh(session);const requests:any[]=[],signals:any[]=[];let enter:any,release:any;const entered=new Promise(resolve=>{enter=resolve}),gate=new Promise(resolve=>{release=resolve});releases.push(release)
   titles.register({id:'provider',automatic:'first-prompt',generate:async(request:any)=>{const index=requests.length;requests.push({messages:request.messages,currentTitle:request.currentTitle??null});signals.push(request.signal);enter();if(index===0)await gate;return {title:index===0?'Older':'Newer',messageSeqs:[request.messages[0].seq]}}})
   const controller=new AbortController(),primary=new Error('caller cancelled'),job=titles.refresh(session,action==='caller-cancel'?controller.signal:undefined);pending.push(job);void job.catch(()=>{});await entered;let closing:any,done=false
   if(action==='overlap')row.new=await titles.refresh(session)
   else if(action==='caller-cancel')controller.abort(primary)
   else if(action==='session-detach')detach()
   else if(action==='service-drain'){const aborted=new Promise(resolve=>{if(signals[0].aborted)resolve(undefined);else signals[0].addEventListener('abort',resolve,{once:true})});closing=fiber.dispose().then(()=>{done=true});await aborted;row.draining=!done}
   row.aborted=signals[0].aborted;release();try{row.result=await job}catch(error:any){row.error=error.message;if(action==='caller-cancel')row.sameReason=error===primary}if(action==='service-drain')await closing;row.requests=requests;row.title=titles.get(session)??null
  }
  if(!['service-drain','queued-dispose'].includes(action))await fiber.dispose();row.released=['title','titleInput'].map(key=>ctx.sessionProjections.stateOf(session,key)!==undefined);row.titleEvents=session.snapshotEvents().filter((event:any)=>event.type==='session/title').map((event:any)=>event.data);rows.push(row)
 }finally{for(const release of releases)release();await Promise.allSettled(pending);await ctx.fiber.dispose()}
}}finally{Date.now=oldNow}
process.stdout.write(JSON.stringify(rows))
