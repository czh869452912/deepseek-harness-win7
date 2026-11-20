import {createHash} from 'node:crypto';
/** External CDP observer: run the actual packaged executable with its own Python. */
import assert from 'node:assert/strict';
import {spawn,execFile} from 'node:child_process';
import {mkdir,writeFile,readFile,readdir,lstat,rename} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {credentialFreeEnvironment,deferProviderOnboarding} from '../browser_onboarding.mjs';

const options=Object.fromEntries(process.argv.slice(2).reduce((rows,value,index,args)=>{
  if(value.startsWith('--'))rows.push([value.slice(2),args[index+1]]);return rows;
},[]));
assert.ok(options.executable&&options.output,'Explicit packaged executable and fresh output required');
const output=resolve(options.output),executable=resolve(options.executable);
const development=Boolean(options['development-root']);
assert.equal(Boolean(options['development-python']),development,'Development root and interpreter must be explicit together');
await mkdir(output);
if(options['prepared-home'])await rename(resolve(options['prepared-home']),join(output,'home'));
const report={status:'running',mode:development?'development':'packaged',checks:[],errors:[],consoleErrors:[],stderr:'',timeline:[]};
let phase='startup';
function enter(value){phase=value;report.timeline.push({phase,time:new Date().toISOString()});}
function observation(value){return {phase,time:new Date().toISOString(),value};}
const env={...credentialFreeEnvironment(process.env),DSH_HOME:options.home?resolve(options.home):join(output,'home'),PYTHONDONTWRITEBYTECODE:'1'};
if(options['live-provider']){
 assert.ok(process.env.DEEPSEEK_API_KEY&&options.workspace,'Explicit live-provider key and owned workspace required');
 env.DEEPSEEK_API_KEY=process.env.DEEPSEEK_API_KEY;
}
const launchArgs=development?[join(resolve(options['development-root']),'apps/desktop'),'--root',resolve(options['development-root']),
  '--python',resolve(options['development-python']),'--home',env.DSH_HOME]:[];

async function historySnapshot(){
 const rows=[];
 async function walk(directory,depth=0){
  for(const item of await readdir(directory,{withFileTypes:true}).catch(error=>{if(error.code==='ENOENT')return [];throw error;})){
   const file=join(directory,item.name),metadata=await lstat(file);
   if(metadata.isSymbolicLink())continue;
   if(metadata.isDirectory()&&depth<2)await walk(file,depth+1);
   else if(metadata.isFile()&&/^session(?:\.v[1-9]\d*)?\.jsonl(?:\.zstd)?$/.test(item.name))rows.push([file,metadata.size,metadata.mtimeMs,createHash('sha256').update(await readFile(file)).digest('hex')]);
  }
 }
 await walk(join(env.DSH_HOME,'sessions'));return rows.sort((a,b)=>a[0].localeCompare(b[0]));
}
if(options.seed==='plaintext'){
 for(const [id,version] of [['desktop-upgrade',0],['newer-history',options['current-onboarding']?5:4]]){
  const directory=join(env.DSH_HOME,'sessions','_no-cwd',id);await mkdir(directory,{recursive:true});
  await writeFile(join(directory,version?`session.v${version}.jsonl`:'session.jsonl'),JSON.stringify({type:'session',version,id,createdAt:1,delegationDepth:0,...(version>=2?{isSeeded:false}:{})})+'\n',{flag:'wx'});
 }
}
const originalHistory=await historySnapshot();
report.historyBefore={files:originalHistory.length,sha256:createHash('sha256').update(JSON.stringify(originalHistory)).digest('hex')};
const child=spawn(executable,[...launchArgs,'--inspect=0','--remote-debugging-port=0'],{windowsHide:true,env,stdio:['ignore','pipe','pipe']});
child.once('exit',(code,signal)=>{report.processExit={time:new Date().toISOString(),phase,code,signal};});
child.stdout.on('data',data=>{report.stdout=(report.stdout??'')+data.toString();});
let address;
child.stderr.on('data',data=>{report.stderr+=data.toString();address??=report.stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/)?.[1];});
const delay=ms=>new Promise(done=>setTimeout(done,ms));
async function until(read,description,timeout=60000){
  const end=Date.now()+timeout;let value;
  while(Date.now()<end){value=await read();if(value)return value;await delay(100);}
  throw new Error('Timed out: '+description+'; last='+JSON.stringify(value));
}
class CDP{
  constructor(socket){this.socket=socket;this.pending=new Map();this.next=1;
    socket.addEventListener('close',()=>{for(const owned of this.pending.values()){
      clearTimeout(owned.timer);owned.reject(new Error('CDP connection closed'));}this.pending.clear();});
    socket.addEventListener('message',event=>{
      const message=JSON.parse(event.data);
      if(message.id){const owned=this.pending.get(message.id);if(owned){clearTimeout(owned.timer);this.pending.delete(message.id);message.error?owned.reject(new Error(JSON.stringify(message.error))):owned.resolve(message.result);}}
      else if(message.method==='Runtime.exceptionThrown')report.errors.push(observation(message.params));
      else if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')report.consoleErrors.push(observation(message.params.args.map(arg=>arg.value??arg.description)));
    });
  }
  call(method,params={}){const id=this.next++;return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('CDP deadline: '+method));},15000);
    this.pending.set(id,{resolve,reject,timer});this.socket.send(JSON.stringify({id,method,params}));
  });}
  async evaluate(expression){const result=await this.call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
    if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));return result.result.value;}
}
let cdp;
try{
  await until(()=>address,'packaged Electron debugger');

  const early=spawn(executable,launchArgs,{windowsHide:true,env,stdio:['ignore','pipe','pipe']});early.stdout.resume();early.stderr.resume();
  await until(()=>early.exitCode!==null,'early second instance exits',15000);assert.equal(early.exitCode,0);report.checks.push('second-instance-during-host-startup');
  const base='http://'+new URL(address).host;
  report.browser=await(await fetch(base+'/json/version',{signal:AbortSignal.timeout(5000)})).json();
  assert.match(report.browser.Browser,/Chrome\/108\./);
  const page=await until(async()=>{const rows=await(await fetch(base+'/json/list',{signal:AbortSignal.timeout(5000)})).json();return rows.find(row=>row.type==='page'&&row.url.startsWith('dsh-app://app/'));},'packaged application target');
  const socket=new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((done,reject)=>{socket.addEventListener('open',done,{once:true});socket.addEventListener('error',reject,{once:true});});
  cdp=new CDP(socket);
  await cdp.call('Runtime.enable');await cdp.call('Page.enable');
  await until(()=>cdp.evaluate(`document.readyState==='complete'&&!!document.querySelector('#root')?.children.length&&!!globalThis.__DSH_TRANSPORT__`),'original packaged application');
  enter('onboarding');
  const notice='[role="dialog"][aria-label="Internal Testing Notice"], [role="dialog"][aria-label="内测声明"]';
  if(!options.home&&!options['current-onboarding']){
    const point=await until(()=>cdp.evaluate(`(()=>{const button=document.querySelector(${JSON.stringify(notice)})?.querySelector('button');if(!button||button.disabled)return false;const b=button.getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2}})()`),'first-use notice');
    await cdp.call('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});
    await cdp.call('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});
    await until(()=>cdp.evaluate(`!document.querySelector(${JSON.stringify(notice)})`),'first-use notice acknowledged');
    report.checks.push('original-first-use-notice-acknowledged');
  }
  if(options['current-onboarding']){
   report.currentOnboarding={deferred:await deferProviderOnboarding(cdp,until,false),phase:options.home?'cold':'fresh'};
   report.checks.push('current-original-onboarding-interactive-without-credentials');
  }else{
   await deferProviderOnboarding(cdp,until,!options['live-provider']);
  }
  report.renderer=await cdp.evaluate(`({url:location.href,node:typeof process,require:typeof require,transport:window.__DSH_TRANSPORT__?.ownsHost,text:document.body.innerText.slice(0,4000)})`);
  assert.equal(report.renderer.node,'undefined');assert.equal(report.renderer.require,'undefined');
  assert.equal(report.renderer.transport,true);report.checks.push('original-packaged-renderer-without-node');
  if(options['live-provider']){
   enter('real-provider');
   const rpc=async(method,args)=>cdp.evaluate(`(async()=>{const response=await fetch('/api/'+${JSON.stringify(method)},{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type:'client-request',rpcId:'live-provider',method:${JSON.stringify(method)},payload:{args:{request:${JSON.stringify(args)}}}})});return response.json()})()`);
   const click=async selector=>{
    const point=await until(()=>cdp.evaluate(`(()=>{const n=document.querySelector(${JSON.stringify(selector)});if(!n||n.disabled)return false;const b=n.getBoundingClientRect();return b.width&&b.height&&n.contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2))&&{x:b.x+b.width/2,y:b.y+b.height/2}})()`),'live original control '+selector);
    await cdp.call('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});
    await cdp.call('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});
   };
   if(!options.home){
    const workspace=await rpc('workspace/create',{path:resolve(options.workspace)});assert.equal(workspace.result.ok,true,JSON.stringify(workspace));
   }
   const row='[role="treeitem"][class*="sessionRow"]';
   await until(()=>cdp.evaluate(`!!document.querySelector('[role="treeitem"][class*="projectRow"]')`),'live workspace row');
   if(!options.home){
    const hover=await cdp.evaluate(`(()=>{const b=document.querySelector('[class*="projectRow"]').getBoundingClientRect();return {x:b.x+b.width/2,y:b.y+b.height/2}})()`);
    await cdp.call('Input.dispatchMouseEvent',{type:'mouseMoved',...hover});
    await click('[class*="projectRow"] [class*="rowActions"] > button');
   }
   else{
    if(await cdp.evaluate(`!!document.querySelector('[role="treeitem"][class*="projectRow"][aria-expanded="false"]')`))
     await click('[role="treeitem"][class*="projectRow"][aria-expanded="false"]');
    await click(row);
   }
   const composer='[data-composer-input][contenteditable="true"]';
   await click(composer);
   const expected=options['live-provider']+(options.home?'_COLD':'');
   const prompt=options.home?'Recall the exact complete text from the document you read in the previous turn. Append _COLD to it and reply only with the result. Do not call tools.':
    'Read this generated test document using the read tool: '+join(resolve(options.workspace),'probe.txt')+'. Reply only with its complete text. Do not write files or call other tools.';
   await cdp.call('Input.insertText',{text:prompt});
   await click('[data-composer-card] button[aria-label="Send message"], [data-composer-card] button[aria-label="发送消息"]');
   report.liveProvider=await until(()=>cdp.evaluate(`(()=>{const rows=[...document.querySelectorAll('[data-chat-flow-kind="assistant-step"]')];const answer=rows.find(n=>n.textContent.includes(${JSON.stringify(expected)}));return answer&&!document.querySelector('[data-composer-card] button[aria-label="Stop generating"], [data-composer-card] button[aria-label="停止生成"]')&&{answer:answer.textContent}})()`),'real provider answer in original Desktop UI',150000);
   report.checks.push(options.home?'real-provider-desktop-cold-context-resume':'real-provider-desktop-message-and-read-tool');
  }
  enter('settings');report.settings=await cdp.evaluate(`(async()=>{const response=await fetch('/api/settings/describe',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type:'client-request',rpcId:'packaged',method:'settings/describe',payload:{args:{}}})});return response.json()})()`);
  assert.equal(report.settings.result.ok,true);assert.ok(report.settings.result.value.namespaces.length);report.checks.push('packaged-python-settings-rpc');
  enter('stream');report.baseline=await cdp.evaluate(`(async()=>{const abort=new AbortController();const response=await fetch('/.dsh/remote-stream',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({endpoint:'workspace/follow',payload:{args:{}}}),signal:abort.signal});const reader=response.body.getReader();let text='';while(!text.includes('\\n')){const next=await reader.read();if(next.done)throw new Error('premature workspace EOF');text+=new TextDecoder().decode(next.value)}abort.abort();return JSON.parse(text.split('\\n')[0])})()`);
  assert.equal(report.baseline.type,'baseline');report.checks.push('packaged-stream-baseline-and-cancellation');
  enter('single-instance');const second=spawn(executable,launchArgs,{windowsHide:true,env,stdio:['ignore','pipe','pipe']});
  second.stdout.resume();second.stderr.resume();
  await until(()=>second.exitCode!==null,'second packaged instance exited',15000);
  assert.equal(second.exitCode,0);assert.equal(child.exitCode,null);report.checks.push('actual-single-instance-ownership');
  enter('stable');await delay(2000);
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.consoleErrors,[]);
  const screenshot=await cdp.call('Page.captureScreenshot');await writeFile(join(output,'main.png'),Buffer.from(screenshot.data,'base64'));

  enter('desktop-style');
  const nodeAddress=report.stderr.match(/Debugger listening on (ws:\/\/[^\s]+)/)?.[1];assert.ok(nodeAddress);
  const mainSocket=new WebSocket(nodeAddress);await new Promise((done,reject)=>{mainSocket.addEventListener('open',done,{once:true});mainSocket.addEventListener('error',reject,{once:true});});
  const mainCdp=new CDP(mainSocket);
  report.menu=await mainCdp.evaluate(`(()=>{const e=process.mainModule.require('electron'),menu=e.Menu.getApplicationMenu();return {labels:menu.items.map(row=>row.label),pluginLabel:menu.items[0].submenu.items[0].label,accelerator:menu.items[0].submenu.items[0].accelerator}})()`);
  assert.equal(report.menu.accelerator,'CmdOrCtrl+,');assert.equal(report.menu.labels.length,1);
  await mainCdp.evaluate(`process.mainModule.require('electron').Menu.getApplicationMenu().items[0].submenu.items[0].click()`);
  const shellPage=await until(async()=>{const rows=await(await fetch(base+'/json/list')).json();return rows.find(row=>row.url==='dsh-app://shell/plugin-manager.html');},'native menu plugin target');
  const shellSocket=new WebSocket(shellPage.webSocketDebuggerUrl);await new Promise((done,reject)=>{shellSocket.addEventListener('open',done,{once:true});shellSocket.addEventListener('error',reject,{once:true});});
  const shellCdp=new CDP(shellSocket);await shellCdp.call('Runtime.enable');await shellCdp.call('Page.enable');
  await until(()=>shellCdp.evaluate(`!!document.querySelector('#title')?.textContent&&!document.querySelector('#refresh').disabled`),'plugin manager ready');
  report.pluginStyle={};
  for(const theme of ['light','dark']){
   await shellCdp.call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme}]});
   report.pluginStyle[theme]=await shellCdp.evaluate(`(()=>{const root=getComputedStyle(document.documentElement),button=getComputedStyle(document.querySelector('#install'));return {title:document.title,width:innerWidth,font:root.fontFamily,background:root.backgroundColor,color:root.color,buttonBackground:button.backgroundColor,buttonColor:button.color,accentSupported:CSS.supports('background','AccentColor'),buttonBorderSupported:CSS.supports('border-color','ButtonBorder'),node:typeof require}})()`);
   assert.equal(report.pluginStyle[theme].node,'undefined');
   const shot=await shellCdp.call('Page.captureScreenshot');await writeFile(join(output,'plugins-'+theme+'.png'),Buffer.from(shot.data,'base64'));
  }
  report.checks.push('localized-native-menu-and-original-plugin-manager-light-dark');
  shellSocket.close();mainSocket.close();
  enter('closing');try{await cdp.call('Browser.close');}catch(error){if(socket.readyState!==3)throw error;}
  await until(()=>child.exitCode!==null,'packaged application graceful quit',20000);
  assert.equal(child.exitCode,0);report.checks.push('packaged-graceful-shutdown');assert.ok(!report.stderr.includes('Error: Desktop Host is stopping'));
  const finalHistory=await historySnapshot();
  if(options['live-provider']){assert.notDeepEqual(finalHistory,originalHistory);report.historyAfter=finalHistory.map(([file,bytes,mtimeMs,sha256])=>({file,bytes,mtimeMs,sha256}));report.checks.push('real-provider-durable-session-growth');}
  else{assert.deepEqual(finalHistory,originalHistory);report.checks.push('session-bytes-and-mtimes-unchanged');}
  enter('closed');assert.deepEqual(report.errors,[]);assert.deepEqual(report.consoleErrors,[]);
  report.checks.push('complete-observed-lifecycle-without-renderer-errors');
  if(development)report.checks=report.checks.map(value=>value.replace('packaged','development'));
  report.status=development?'development-checks-passed':'qualified';
}catch(error){report.status='rejected';report.failure=error.stack;process.exitCode=1;if(cdp){try{report.failureRenderer=await cdp.evaluate('document.body.innerText');const shot=await cdp.call('Page.captureScreenshot');await writeFile(join(output,'failure.png'),Buffer.from(shot.data,'base64'));}catch{}}}
finally{
  if(child.exitCode===null){
    await new Promise(done=>execFile(join(process.env.SystemRoot||'C:\\Windows','System32/taskkill.exe'),['/PID',String(child.pid),'/T','/F'],{windowsHide:true},()=>done()));
    await until(()=>child.exitCode!==null,'owned packaged tree terminated',15000).catch(error=>{report.cleanupFailure=String(error);});
  }
  cdp?.socket.close();
  const serialized=JSON.stringify(report,null,2).split(process.env.DEEPSEEK_API_KEY||'__absent_secret__').join('[REDACTED]');
  await writeFile(join(output,'report.json'),serialized+'\n',{flag:'wx'});
  console.log(JSON.stringify({status:report.status,checks:report.checks,failure:report.failure}));
}
