import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {lstat,mkdir,readFile,rm,unlink,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {dirname,join,resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {closeOriginalBrowser,credentialFreeEnvironment,deferProviderOnboarding,isolatedBrowserArguments,navigateOriginalPage} from '../../browser_onboarding.mjs';

const options=Object.fromEntries(process.argv.slice(2).reduce((pairs,value,index,args)=>{
  if(value.startsWith('--'))pairs.push([value.slice(2),args[index+1]]);
  return pairs;
},[]));
if(!options.browser||!options.output||!options['run-dir']||!['source','native'].includes(options.side)
    ||!['minimal','standard','cordis'].includes(options.preset))throw new Error('Explicit actual browser journey options required');
const output=resolve(options.output),stage=dirname(fileURLToPath(import.meta.url));
await mkdir(output);
const report={side:options.side,preset:options.preset,phases:[],errors:[],consoleErrors:[],consoleLogs:[],responses:[],clicks:[],wire:[],requests:[]};
const delay=milliseconds=>new Promise(done=>setTimeout(done,milliseconds));

async function until(read,description,timeout=30000){
  const deadline=Date.now()+timeout;
  let last;
  while(Date.now()<deadline){last=await read();if(last)return last;await delay(100);}
  throw new Error('Timed out: '+description+'; last='+JSON.stringify(last));
}

class CDP{
  constructor(socket){
    this.socket=socket;this.next=1;this.pending=new Map();
    this.responses=new Map();this.jobs=new Set();
    socket.addEventListener('message',event=>{
      const message=JSON.parse(event.data);
      if(message.id){
        const owned=this.pending.get(message.id);
        if(owned){this.pending.delete(message.id);clearTimeout(owned.timer);message.error?owned.reject(new Error(JSON.stringify(message.error))):owned.resolve(message.result);}
      }else{
        if(message.method==='Runtime.exceptionThrown')report.errors.push(message.params.exceptionDetails);
        if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')report.consoleErrors.push(message.params.args.map(value=>value.value??value.description));
        if(message.method==='Runtime.consoleAPICalled')report.consoleLogs.push(message.params);
        if(message.method==='Network.responseReceived'&&new URL(message.params.response.url).pathname.startsWith('/api/')){
          const response={...message.params};
          report.responses.push(response);this.responses.set(response.requestId,response);
        }
        if(message.method==='Network.loadingFinished'&&this.responses.has(message.params.requestId)){
          const response=this.responses.get(message.params.requestId);
          const job=this.call('Network.getResponseBody',{requestId:message.params.requestId})
            .then(value=>response.body=value).catch(error=>response.bodyError=String(error)).finally(()=>this.jobs.delete(job));
          this.jobs.add(job);
        }
        if(message.method.startsWith('Network.webSocket'))report.wire.push(message);
        if(message.method==='Network.requestWillBeSent')report.requests.push(message.params);
      }
    });
  }
  async call(method,params={}){
    const id=this.next++;
    return await new Promise((resolveCall,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('CDP timeout: '+method));},15000);
      this.pending.set(id,{resolve:resolveCall,reject,timer});
      this.socket.send(JSON.stringify({id,method,params}));
    });
  }
  async evaluate(expression){
    const result=await this.call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
}

async function click(cdp,selector,text){
  const point=await until(()=>cdp.evaluate(`(()=>{
    const element=Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find(value=>${JSON.stringify(text)}===undefined||value.textContent.trim().startsWith(${JSON.stringify(text)}));
    if(!element||element.disabled)return false;
    element.scrollIntoView({block:'center'});
    const rect=element.getBoundingClientRect(),x=rect.x+rect.width/2,y=rect.y+rect.height/2;
    return rect.width&&rect.height&&element.contains(document.elementFromPoint(x,y))&&{x,y};
  })()`),'visible original control '+selector);
  await cdp.evaluate(`(()=>{
    const element=Array.from(document.querySelectorAll(${JSON.stringify(selector)})).find(value=>${JSON.stringify(text)}===undefined||value.textContent.trim().startsWith(${JSON.stringify(text)})),events=[];
    const listener=event=>events.push({trusted:event.isTrusted,matched:element.contains(event.target)});
    document.addEventListener('click',listener,true);
    window.__journeyClick={events,detach:()=>document.removeEventListener('click',listener,true)};
  })()`);
  await cdp.call('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});
  await cdp.call('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});
  const events=await cdp.evaluate('(()=>{const owned=window.__journeyClick;owned.detach();delete window.__journeyClick;return owned.events;})()');
  report.clicks.push({selector,text,point,events});
  assert.deepEqual(events,[{trusted:true,matched:true}]);
}

async function phase(name){
  const receipt=join(output,name+'.host.json'),state={name,snapshots:[],hostLog:'',hostErrors:'',browserErrors:''};
  report.phases.push(state);
  const environment=credentialFreeEnvironment(process.env);
  let host,browser,cdp,nextHost=1;
  const pending=new Map();
  let readyResolve,readyReject;
  const ready=new Promise((resolveReady,reject)=>{readyResolve=resolveReady;readyReject=reject;});
  const common=['--run-dir',resolve(options['run-dir']),'--output',receipt,'--preset',options.preset,'--phase',name];
  if(!options.workspace||!options.clock||!options['approval-artifact'])throw new Error('Controlled workspace, clock and approval artifact required');
  common.push('--workspace',resolve(options.workspace),'--clock',options.clock,'--approval-artifact',resolve(options['approval-artifact']));
  if(options['source-receipt']){
    const sourceReport=JSON.parse(await readFile(join(resolve(options['source-receipt']),'report.json'),'utf8'));
    assert.equal(sourceReport.status,'qualified');
    assert.equal(sourceReport.preset,options.preset);
    common.push('--port',new URL(sourceReport.phases.find(value=>value.name===name).boot.url).port);
  }
  let executable,argumentsValue;
  if(options.side==='native'){
    if(!options.python||!options.root)throw new Error('Owned native root and interpreter required');
    executable=resolve(options.python);
    argumentsValue=['-I','-u',join(stage,'web_journey_native_host.py'),'--root',resolve(options.root),...common];
  }else{
    if(!options['source-root'])throw new Error('Pinned actual Source root required');
    const source=resolve(options['source-root']);
    executable=process.execPath;
    environment.TSX_TSCONFIG_PATH=join(source,'tsconfig.json');
    argumentsValue=['--import',pathToFileURL(join(source,'node_modules/tsx/dist/esm/index.mjs')).href,
      join(stage,'web_journey_source_host.mts'),'--source-root',source,...common];
  }
  const command=async commandName=>await new Promise((resolveCommand,reject)=>{
    const id=nextHost++,timer=setTimeout(()=>{pending.delete(id);reject(new Error('Host timeout: '+commandName));},20000);
    pending.set(id,{resolve:resolveCommand,reject,timer});
    host.stdin.write(JSON.stringify({id,command:commandName})+'\n');
  });
  const snapshot=async()=>{const value=await command('snapshot');state.snapshots.push(value);return value;};
  try{
    host=spawn(executable,argumentsValue,{windowsHide:true,env:environment,cwd:output});
    host.stderr.on('data',value=>state.hostErrors+=value);
    host.on('error',readyReject);
    host.on('exit',code=>{
      readyReject(new Error('Actual host exited '+code+'; '+state.hostErrors));
      for(const owned of pending.values()){clearTimeout(owned.timer);owned.reject(new Error('Actual host exited '+code));}
      pending.clear();
    });
    createInterface({input:host.stdout}).on('line',line=>{
      if(!line.startsWith('DSH_JOURNEY ')){state.hostLog+=line+'\n';return;}
      const value=JSON.parse(line.slice(12));
      if(value.ready)readyResolve(value);
      else{
        const owned=pending.get(value.id);
        if(owned){pending.delete(value.id);clearTimeout(owned.timer);value.ok?owned.resolve(value.value):owned.reject(new Error(JSON.stringify(value)));}
      }
    });
    let bootTimer;
    const boot=await Promise.race([ready,new Promise((_,reject)=>{
      bootTimer=setTimeout(()=>reject(new Error('Actual host boot timeout')),60000);
    })]).finally(()=>clearTimeout(bootTimer));
    state.boot=boot;
    const browserHome=join(output,'browser');
    if(name==='cold'){
      const previous=report.phases[report.phases.length-2];
      assert.equal(previous.passed,true);
      const marker=join(browserHome,'DevToolsActivePort');
      const homeStat=await lstat(browserHome),markerStat=await lstat(marker);
      assert.equal(homeStat.isSymbolicLink(),false);
      assert.equal(markerStat.isSymbolicLink(),false);
      assert.equal(markerStat.isFile(),true);
      const content=await readFile(marker,'utf8');
      assert.equal(content.split('\n')[0],previous.devToolsPort);
      await unlink(marker);
      state.expiredDevToolsMarker={path:marker,content,previousBrowserClosed:true};
    }
    browser=spawn(resolve(options.browser),isolatedBrowserArguments(browserHome),{windowsHide:true});
    browser.stderr.on('data',value=>state.browserErrors+=value);
    const port=await until(async()=>{try{return (await readFile(join(browserHome,'DevToolsActivePort'),'utf8')).split('\n')[0];}catch{return false;}},'actual browser DevTools port');
    state.devToolsPort=port;
    const target=(await (await fetch('http://127.0.0.1:'+port+'/json/list')).json()).find(value=>value.type==='page');
    const socket=new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolveSocket,reject)=>{socket.addEventListener('open',resolveSocket,{once:true});socket.addEventListener('error',reject,{once:true});});
    cdp=new CDP(socket);
    state.browserIdentity=await cdp.call('Browser.getVersion');
    state.browserBinarySha256=createHash('sha256').update(await readFile(resolve(options.browser))).digest('hex');
    if(options['expected-browser-major'])assert.equal(state.browserIdentity.product.match(/\/(\d+)\./)?.[1],options['expected-browser-major']);
    state.capabilitiesBefore=await cdp.evaluate('({any:typeof AbortSignal.any,withResolvers:typeof Promise.withResolvers,timeout:typeof AbortSignal.timeout})');
    state.browser=await cdp.call('Browser.getVersion');
    await cdp.call('Runtime.enable');await cdp.call('Network.enable');await cdp.call('Page.enable');
    await cdp.call('Emulation.setDeviceMetricsOverride',{width:1680,height:1000,deviceScaleFactor:1,mobile:false});
    await cdp.call('Emulation.setLocaleOverride',{locale:'en-US'});
    await navigateOriginalPage(cdp,until,boot.url);
    await until(()=>cdp.evaluate('document.getElementById("root")?.childElementCount>0'),'original frontend mounted');
    state.capabilitiesAfter=await cdp.evaluate('({any:typeof AbortSignal.any,withResolvers:typeof Promise.withResolvers,timeout:typeof AbortSignal.timeout})');
    const notice='[role="dialog"][aria-label="Internal Testing Notice"]';
    if(name==='fresh'){
      await until(()=>cdp.evaluate('document.querySelector('+JSON.stringify(notice)+')!==null'),'original testing notice');
      await click(cdp,notice+' button');
    }
    state.providerOnboardingDeferred=await deferProviderOnboarding(cdp,until,false);
    const row='[role="treeitem"][class*="sessionRow"]';
    if(name==='cold'){
      await until(()=>cdp.evaluate('Array.from(document.querySelectorAll('+JSON.stringify(row)+')).filter(value=>value.textContent.trim().startsWith("Controlled browser journey")).length===1'),'one controlled original persisted Session row');
      await click(cdp,row,'Controlled browser journey');
    }else{
      await until(()=>cdp.evaluate('document.querySelectorAll('+JSON.stringify(row)+').length===1'),'one controlled original blank Session row');
      await click(cdp,row);
    }
    const submit=async scenario=>{
      await click(cdp,'[data-composer-input][contenteditable="true"]');
      await cdp.call('Input.insertText',{text:scenario});
      await click(cdp,'[data-composer-card] button[aria-label="Send message"], [data-composer-card] button[aria-label="发送消息"]');
    };
    const complete=async scenario=>await until(async()=>{
      const value=await snapshot();
      return value.agentStatus==='idle'&&value.events.some(event=>event.type==='assistant/message'
        &&JSON.stringify(event.data).includes(scenario+'_FINAL'))&&value;
    },'actual model/tool next request '+scenario,60000);
    const scenarios=name==='cold'?['WEB_REOPEN']:options.preset==='minimal'?['WEB_TOOL','WEB_CANCEL']:
      ['WEB_TOOL','WEB_QUESTION','WEB_APPROVAL','WEB_PLAN','WEB_CANCEL',...(options.preset==='cordis'?['WEB_CORDIS']:[])];
    state.scenarios=scenarios;
    for(const scenario of scenarios){
      if(scenario==='WEB_PLAN'){
        await submit('/plan');
        await until(async()=>{const value=await snapshot();return value.events.some(event=>event.type==='plan/mode'&&event.data.active===true);},'logged plan-mode entry');
      }
      await submit(scenario);
      if(scenario==='WEB_PLAN'){
        state.planReviewPanel=await until(()=>cdp.evaluate(`(()=>{
          const panel=document.querySelector('[data-plan-review-key]');
          if(!panel)return false;
          const button=panel.querySelector('button:last-child');
          if(!button||button.disabled)return false;
          return {text:panel.textContent,approveLabel:button.textContent};
        })()`),'original plan review panel');
        await click(cdp,'[data-plan-review-key] button:last-child');
      }else if(scenario==='WEB_QUESTION'){
        await click(cdp,'[data-question-key] button[role="radio"][aria-label="Proceed"]');
        await click(cdp,'[data-question-key] footer > div:last-child button:last-child');
      }else if(scenario==='WEB_APPROVAL'){
        await click(cdp,'[data-approval-key] button:last-child');
      }else if(scenario==='WEB_CANCEL'){
        await until(async()=>{const value=await snapshot();return value.cancellation.some(item=>item.attached===1&&!item.detached);},'actual model stream awaiting cancellation');
        await click(cdp,'[data-composer-card] button[aria-label="Stop generating"], [data-composer-card] button[aria-label="停止生成"]');
        await until(async()=>{const value=await snapshot();return value.agentStatus==='idle'&&value.cancellation.some(item=>item.finallyAborted&&item.detached===1);},'real browser cancellation disposed model listener');
        continue;
      }
      await complete(scenario);
    }
    state.final=await snapshot();
    state.finalText=await cdp.evaluate('document.body.innerText');
    await Promise.allSettled([...cdp.jobs]);
    const selectedPreset=state.final.events.findLast(event=>event.type==='agent-preset/selected');
    assert.equal(selectedPreset?.data.agentPreset??state.final.header.agentPreset,options.preset);
    if(options.preset==='minimal'){
      state.toolRegistrationOrder=state.final.tools;
      assert.deepEqual([...state.final.tools].sort(),['pwsh','str_replace_editor']);
      if(options.side==='native'&&JSON.stringify(state.final.tools)!==JSON.stringify(['str_replace_editor','pwsh'])){
        (report.openFindings??=[]).push({kind:'minimal-tool-registration-order',actual:state.final.tools,
          observedSource:['str_replace_editor','pwsh'],scope:'Functional browser research only; complete wire/preset parity remains unqualified.'});
      }
    }
    assert.deepEqual(report.errors,[]);assert.deepEqual(report.consoleErrors,[]);
    await closeOriginalBrowser(cdp,browser,until);
    await command('shutdown');
    await until(()=>host.exitCode!==null||host.signalCode!==null,'actual host naturally exited',15000);
    assert.equal(host.exitCode,0);
    assert.equal(state.hostErrors,'');
    state.hostReceipt=JSON.parse(await readFile(receipt,'utf8'));
    state.passed=true;
  }catch(error){
    state.failure=String(error);
    throw error;
  }finally{
    if(cdp?.socket.readyState===1){
      try{
        state.finalText??=await cdp.evaluate('document.body.innerText');
        await Promise.allSettled([...cdp.jobs]);
        const screenshot=await cdp.call('Page.captureScreenshot');
        await writeFile(join(output,name+'.png'),Buffer.from(screenshot.data,'base64'));
        await closeOriginalBrowser(cdp,browser,until);
      }catch(error){
        state.browserCleanupFailure=String(error);
        if(!state.failure)throw error;
      }
    }
    if(host?.exitCode===null&&host.signalCode===null){
      try{await command('shutdown');await until(()=>host.exitCode!==null||host.signalCode!==null,'failed host owned shutdown',15000);}
      catch(error){state.shutdownFailure=String(error);host.kill();}
    }
  }
}

try{
  if(options.side==='native')report.compatibilitySha256=createHash('sha256').update(await readFile(join(resolve(options.root),'dsh/host/browser_compat/compat.js'))).digest('hex');
  if(options.archive)report.archiveSha256=createHash('sha256').update(await readFile(resolve(options.archive))).digest('hex');
  await assert.rejects(lstat(resolve(options['approval-artifact'])),error=>error.code==='ENOENT');
  await phase('fresh');
  await phase('cold');
  report.status='qualified';
}catch(error){report.status='rejected';report.failure=String(error);process.exitCode=1;}
finally{
  if(report.status==='qualified'){
    const profile=join(output,'browser');
    assert.equal((await lstat(profile)).isSymbolicLink(),false);
    assert.equal(resolve(dirname(profile)),output);
    await rm(profile,{recursive:true,maxRetries:5,retryDelay:100});
    report.cleanup={browserProfile:'removed after both physical browser/Host exits'};
  }
  const safe=JSON.stringify(report,null,2).replace(/([?&]token=)[^&"\s]*/g,'$1[redacted]');
  await writeFile(join(output,'report.json'),safe+'\n',{flag:'wx',encoding:'utf8'});
}
