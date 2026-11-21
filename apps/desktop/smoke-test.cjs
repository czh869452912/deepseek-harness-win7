'use strict';
// Development-only integration entry, unavailable in packaged applications.
const {mkdir,writeFile,readFile,cp}=require('node:fs/promises');
const {join,resolve}=require('node:path');
const assert=require('node:assert/strict');
const {createServer}=require('node:http');
const {release:osRelease}=require('node:os');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function evaluate(window,expression,timeout=45000){
  let timer;
  try{return await Promise.race([window.webContents.executeJavaScript(expression),
    new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Desktop evaluation deadline: '+expression.slice(0,160))),timeout);})]);}
  finally{clearTimeout(timer);}
}
async function wait(window,predicate){
  const deadline=Date.now()+45000;
  while(Date.now()<deadline){
    if(await evaluate(window,predicate))return;
    await pause(150);
  }
  throw new Error('Desktop renderer did not become ready: '+predicate);
}
async function run({app,mainWindow,openPlugins,pluginWindow,guideWindow,environment,manager,output}){
  await mkdir(output,{recursive:true});
  const report={versions:process.versions,errors:[],transitionErrors:[]};
  const interruptedRequests=new Set([
    '[session-controller] control stream failed: RemoteError: network error',
    '[session-controller] control stream failed: RemoteError: Failed to fetch',
    '[ui-cordis] reading the Cordis inventory failed: Error: gateway/internal: client api: dynamicCordisRunner/inventory failed: Failed to fetch',
    '[cordis-client-runner] syncing inspect providers failed: Error: gateway/internal: client api: dynamicCordisRunner/syncInspectManifest failed: Failed to fetch',
  ]);
  let phase='initial';
  mainWindow.webContents.on('console-message',(_event,level,message)=>{
    if(level!==3)return;
    if(phase==='mutating'&&interruptedRequests.has(message))report.transitionErrors.push(message);
    else report.errors.push(message);
  });
  try{
    await wait(mainWindow,"Boolean(document.querySelector('#root')?.children.length && globalThis.__DSH_TRANSPORT__)");
    if(environment.limitedShell){
      await wait(mainWindow,"!!document.getElementById('dsh-win7-environment-notice')");
      const clickNotice=async selector=>{
        const point=await evaluate(mainWindow,`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`);
        mainWindow.webContents.sendInputEvent({type:'mouseDown',...point,button:'left',clickCount:1});
        mainWindow.webContents.sendInputEvent({type:'mouseUp',...point,button:'left',clickCount:1});
      };
      await clickNotice('#dsh-win7-environment-notice button:first-of-type');
      const deadline=Date.now()+10000;
      while(!guideWindow()&&Date.now()<deadline)await pause(100);
      assert.ok(guideWindow());
      await wait(guideWindow(),"document.body.innerText.includes('upgrade-win7.bat')");
      report.environmentGuide=await evaluate(guideWindow(),"({url:location.href,node:typeof require,text:document.body.innerText})");
      assert.equal(report.environmentGuide.node,'undefined');
      guideWindow().close();
      await clickNotice('#dsh-win7-environment-notice button:last-of-type');
      await wait(mainWindow,"!document.getElementById('dsh-win7-environment-notice')&&localStorage.getItem('dsh-win7-environment-dismissed')==='1'");
      report.environmentNotice={limitedShell:true,guideOpened:true,dismissed:true};
    }
    report.main=await evaluate(mainWindow,`({
      url:location.href,node:typeof require,process:typeof process,ownsHost:globalThis.__DSH_TRANSPORT__.ownsHost,
      text:document.body.innerText.slice(0,1500),preload:{protocolVersion:globalThis.dshDesktop.protocolVersion,
        browser:typeof globalThis.dshDesktop.browser?.acquire,directoryPicker:typeof globalThis.__DSH_DIRECTORY_PICKER__?.pick,
        titlebar:navigator.windowControlsOverlay?.visible, titlebarHeight:document.documentElement.style.getPropertyValue('--dsh-windows-titlebar-height')},
      workers:globalThis.__DSH_BROWSER_COMPAT__?.workers
    })`);
    assert.equal(report.main.node,'undefined');assert.equal(report.main.process,'undefined');assert.equal(report.main.ownsHost,true);
    assert.equal(report.main.preload.browser,'function');
    const apiKeyPresent=await evaluate(mainWindow,'window.dshOnboarding.hasApiKey()');
    assert.equal(typeof apiKeyPresent,'boolean');
    await evaluate(mainWindow,"(window.dshOnboarding.setActive(true), true)");
    const deadline=Date.now()+5000;
    while(mainWindow.getMinimumSize()[0]!==960&&Date.now()<deadline)await pause(50);
    assert.deepEqual(mainWindow.getMinimumSize(),[960,600]);
    await evaluate(mainWindow,"(window.dshOnboarding.setActive(false), true)");
    const resetDeadline=Date.now()+5000;
    while(mainWindow.getMinimumSize()[0]!==520&&Date.now()<resetDeadline)await pause(50);
    assert.deepEqual(mainWindow.getMinimumSize(),[520,600]);
    report.onboarding={credentialMetadata:true,minimumSizeRestored:true};
    const deviceInfo=await evaluate(mainWindow,'window.dshDesktop.deviceInfo()');
    const deviceKeys=deviceInfo.split('; ').map(field=>field.split('=')[0]);
    assert.deepEqual(deviceKeys,['platform','os','app_arch','cpu','memory_gib']);
    assert.ok(deviceInfo.includes('app_arch='+process.arch+';'));
    report.deviceInfo={keys:deviceKeys,arch:process.arch};
    report.shortcuts=await evaluate(mainWindow,`(async()=>{
      const {shortcuts}=window.dshDesktop;
      const definitions=[{id:'smoke.shortcut',defaults:{}}];
      const before=await shortcuts.get(definitions);
      const edit=await shortcuts.edit({type:'set',id:'smoke.shortcut',binding:{code:'KeyJ',modifiers:['control','shift']}},before.revision);
      return {initial:before.status,edit:edit.status,platform:document.documentElement.dataset.platform};
    })()`);
    assert.deepEqual(report.shortcuts,{initial:'ready',edit:'saved',platform:process.platform});
    if (process.platform==='win32' && Number(osRelease().split('.')[0])>=10) {
      assert.equal(report.main.preload.titlebar,true);
      assert.equal(report.main.preload.titlebarHeight,'40px');
    }
    mainWindow.show();
    mainWindow.setFullScreen(true);
    await wait(mainWindow,"document.documentElement.dataset.fullscreen==='true'");
    mainWindow.setFullScreen(false);
    await wait(mainWindow,"!document.documentElement.hasAttribute('data-fullscreen')");
    report.fullscreen={entered:true,restored:true};
    const downloads=join(output,'downloads');
    await mkdir(downloads);
    app.setPath('downloads',downloads);
    const pngFixture=Buffer.from('89504e470d0a1a0a','hex');
    const localPage=createServer((request,response)=>{
      if (request.url==='/image.png') {
        response.writeHead(200,{'Content-Type':'image/png'});
        response.end(pngFixture);
        return;
      }
      response.writeHead(200,{'Content-Type':'text/html','X-Frame-Options':'DENY'});
      response.end('<title>Desktop sidebar guest fixture</title><p>Guest loaded</p>');
    });
    await new Promise((resolve,reject)=>{localPage.once('error',reject);localPage.listen(0,'127.0.0.1',resolve);});
    try {
      const source='http://127.0.0.1:'+localPage.address().port;
      report.guest=await evaluate(mainWindow,`(async()=>{
        const browser=window.dshDesktop.browser,reservation=await browser.acquire('smoke-workspace');
        const guest=document.createElement('webview');
        const wait=event=>new Promise(resolve=>guest.addEventListener(event,resolve,{once:true}));
        guest.partition=reservation.partition;guest.setAttribute('allowpopups','');
        guest.src='about:blank#'+reservation.lease;
        const ready=wait('dom-ready');document.body.append(guest);await ready;
        try {
          await guest.loadURL(${JSON.stringify(source)});
          const state=await guest.executeJavaScript('({title:document.title,node:typeof require,bridge:typeof dshDesktop})');
          const popup=new Promise(resolve=>{const off=browser.onOpenRequested(reservation.lease,url=>{off();resolve(url);});});
          await guest.executeJavaScript("window.open('/next','_blank'); void 0");
          return {...state,popup:await popup};
        } finally {await browser.release(reservation.lease);guest.remove();}
      })()`);
      assert.deepEqual(report.guest,{title:'Desktop sidebar guest fixture',node:'undefined',bridge:'undefined',popup:source+'/next'});
      report.fileActions=await evaluate(mainWindow,`(async()=>{
        const files=window.dshDesktop.fileActions,drag=window.dshDesktop.fileDrag;
        const image=await files.readClipboardImage(${JSON.stringify(source+'/image.png')});
        const url=URL.createObjectURL(new Blob(['native download'],{type:'text/plain'}));
        try{
          const saved=await files.save({url,mode:'download',name:'smoke.txt'});
          const handle=await drag.prepare({kind:'bytes',bytes:new Uint8Array([1,2]),name:'drag.bin'},'smoke-drag');
          drag.release(handle);
          return {mediaType:image.mediaType,size:image.bytes.length,saved,drag:typeof handle==='string'};
        }finally{URL.revokeObjectURL(url);}
      })()`);
      assert.equal(report.fileActions.mediaType,'image/png');
      assert.equal(report.fileActions.size,pngFixture.length);
      assert.equal(report.fileActions.saved.path,join(downloads,'smoke.txt'));
      assert.equal(await readFile(report.fileActions.saved.path,'utf8'),'native download');
      assert.equal(report.fileActions.drag,true);
    } finally {await new Promise(resolve=>localPage.close(resolve));}
    report.settings=await evaluate(mainWindow,`fetch('/api/settings/describe',{
      method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type:'client-request',rpcId:'desktop-smoke',
      method:'settings/describe',payload:{args:{}}})}).then(async response=>({status:response.status,body:await response.json()}))`);
    assert.equal(report.settings.status,200);assert.equal(report.settings.body.result.ok,true);
    assert.ok(report.settings.body.result.value.namespaces.length>0);
    report.locale=await evaluate(mainWindow,`(async()=>{
      const method='settings/update';
      const response=await fetch('/api/'+method,{method:'POST',headers:{'content-type':'application/json'},
        body:JSON.stringify({type:'client-request',rpcId:'smoke-locale',method,
          payload:{args:{ns:'locale',patch:{preference:'zh-CN'}}}})});
      if(!(await response.json()).result.ok)throw Error('Could not save locale during Desktop smoke');
      return window.__DSH_LOCALE__.read();
    })()`);
    assert.equal(report.locale.preference,'zh-CN');
    assert.ok(report.locale.languages.length);
    await evaluate(mainWindow,"(window.__DSH_LOCALE__.onChange('zh-CN'), true)");
    report.upload=await evaluate(mainWindow,`(async()=>{
      const rpc=async(method,args)=>{
        const response=await fetch('/api/'+method,{method:'POST',headers:{'content-type':'application/json'},
          body:JSON.stringify({type:'client-request',rpcId:method,method,payload:{args}})});
        return (await response.json()).result;
      };
      const session=await rpc('session/create',{request:{}});
      const canvas=document.createElement('canvas');
      canvas.width=canvas.height=1;
      const png=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
      const response=await fetch('/api/session/uploadFileBinary?sessionId='+session.value.sessionId+'&mediaType=image/png',
        {method:'POST',headers:{'content-type':'application/octet-stream'},body:png});
      const result=await response.json();
      return {ok:result.ok,receipt:typeof result.value?.receiptId==='string',error:result.error};
    })()`);
    assert.deepEqual(report.upload,{ok:true,receipt:true,error:undefined});
    report.stream=await evaluate(mainWindow,`(async()=>{
      const controller=new AbortController();
      const iterator=globalThis.__DSH_TRANSPORT__.openStream('workspace/follow',{args:{}},controller.signal);
      const first=await iterator.next();
      controller.abort();
      let cancelled=false;try{await iterator.next();}catch(error){cancelled=error.name==='AbortError';}
      return {first,cancelled};
    })()`);
    assert.equal(report.stream.first.done,false);assert.equal(report.stream.cancelled,true);
    openPlugins();const shell=pluginWindow();
    await wait(shell,"Boolean(document.querySelector('#title')?.textContent && !document.querySelector('#refresh').disabled)");
    report.shell=await evaluate(shell,`(async()=>({url:location.href,node:typeof require,process:typeof process,
      title:document.querySelector('#title').textContent,status:document.querySelector('#status').textContent,
      plugins:await globalThis.dshDesktop.plugins.list(),locale:await globalThis.dshDesktop.locale()}))()`);
    assert.equal(report.shell.node,'undefined');assert.equal(report.shell.process,'undefined');assert.equal(report.shell.status,'');
    assert.equal(report.shell.locale.id,'zh-CN');
    await evaluate(mainWindow,`(window.__updateStates=[], window.__updateDispose=window.dshDesktop.updates.subscribe(state=>window.__updateStates.push(state)), true)`);
    assert.deepEqual(await evaluate(shell,'window.dshDesktop.updates.check()'),{phase:'idle'});
    await wait(mainWindow,"window.__updateStates.some(state=>state.phase==='checking') && window.__updateStates.at(-1)?.phase==='idle'");
    report.updates=await evaluate(mainWindow,`(async()=>{
      window.__updateDispose();
      const bridge=window.dshDesktop.updates;
      return {states:window.__updateStates,status:await bridge.status(),keys:Object.keys(bridge).sort()};
    })()`);
    assert.deepEqual(report.updates.status,{phase:'idle'});
    assert.deepEqual(report.updates.keys,['open','status','subscribe']);
    const example=resolve(__dirname,'../../examples/python-echo');
    const source=join(output,'broken-upgrade');
    await cp(example,source,{recursive:true,filter:file=>!file.includes('__pycache__')});
    const manifest=JSON.parse(await readFile(join(source,'package.json'),'utf8'));
    manifest.version='0.2.0';
    await writeFile(join(source,'package.json'),JSON.stringify(manifest));
    await writeFile(join(source,'python/echo/plugin.py'),"raise RuntimeError('Desktop health rejection fixture')\n");
    phase='mutating';
    await evaluate(shell,'globalThis.dshDesktop.plugins.add('+JSON.stringify(example)+')',180000);
    report.installed=await manager.list();
    assert.equal(report.installed.find(row=>row.name==='@example/python-echo').version,'0.1.0');
    let rejected=false;
    try{await evaluate(shell,'globalThis.dshDesktop.plugins.update("@example/python-echo",'+JSON.stringify(source)+')',180000);}
    catch(error){rejected=true;report.upgradeFailure=error.message;}
    assert.equal(rejected,true,'Broken upgrade must fail readiness');
    report.afterRollback=await manager.list();
    assert.equal(report.afterRollback.find(row=>row.name==='@example/python-echo').version,'0.1.0');
    await evaluate(shell,'globalThis.dshDesktop.plugins.remove("@example/python-echo")',180000);
    assert.deepEqual(await manager.list(),[]);
    await wait(mainWindow,"Boolean(document.querySelector('#root')?.children.length && globalThis.__DSH_TRANSPORT__)");
    phase='settled';
    report.reconnected=await evaluate(mainWindow,`(async()=>{
      const controller=new AbortController();
      const iterator=globalThis.__DSH_TRANSPORT__.openStream('workspace/follow',{args:{}},controller.signal);
      const first=await iterator.next();controller.abort();try{await iterator.next();}catch{}
      return first;
    })()`);
    assert.equal(report.reconnected.value.type,'baseline');
    report.security={main:mainWindow.webContents.getLastWebPreferences(),shell:shell.webContents.getLastWebPreferences()};
    for(const prefs of Object.values(report.security)){
      assert.equal(prefs.nodeIntegration,false);assert.equal(prefs.contextIsolation,true);assert.equal(prefs.sandbox,true);assert.equal(prefs.webSecurity,true);
    }
    await writeFile(join(output,'main.png'),(await mainWindow.webContents.capturePage()).toPNG());
    await writeFile(join(output,'plugin-manager.png'),(await shell.webContents.capturePage()).toPNG());
    assert.deepEqual(report.errors,[]);
    report.status='qualified';
  }catch(error){report.status='rejected';report.failure=error.stack;throw error;}
  finally{
    report.hostLogs=manager.host.logs;
    await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n');
    app.quit();
  }
}
module.exports={run};
