/** Compare unchanged pinned renderers on both engines, using one Python Host.
 * The Electron44 observer shell uses an owned copy with its engine assertion
 * adjusted. Both shells read their locale from isolated settings.
 */
import assert from 'node:assert/strict';
import {spawn,execFile,execFileSync} from 'node:child_process';
import {readFile,writeFile,mkdir,cp} from 'node:fs/promises';
import {join,resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {credentialFreeEnvironment,deferProviderOnboarding} from '../browser_onboarding.mjs';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
const args=Object.fromEntries(process.argv.slice(2).reduce((rows,value,i,all)=>{if(value.startsWith('--'))rows.push([value.slice(2),all[i+1]]);return rows;},[]));
for(const name of ['electron22','electron44','python','output'])assert.ok(args[name],name);
const output=resolve(args.output);await mkdir(output);
const report={scope:'Pinned original renderers on Electron22/44 with the same Python Host; excludes upstream npm Host, native OS dialog pixels and Win7',runs:[],assets:[],status:'running'};
const delay=ms=>new Promise(done=>setTimeout(done,ms));
async function until(read,label,timeout=60000){const end=Date.now()+timeout;while(Date.now()<end){const value=await read();if(value)return value;await delay(100);}throw new Error('Deadline: '+label);}
class CDP{
  constructor(socket){this.socket=socket;this.pending=new Map();this.id=0;
    socket.addEventListener('message',event=>{const value=JSON.parse(event.data),owned=this.pending.get(value.id);if(owned){clearTimeout(owned.timer);this.pending.delete(value.id);value.error?owned.reject(new Error(JSON.stringify(value.error))):owned.done(value.result);}});
    socket.addEventListener('close',()=>{for(const owned of this.pending.values()){clearTimeout(owned.timer);owned.reject(new Error('CDP closed'));}this.pending.clear();});
  }
  call(method,params={}){const id=++this.id;return new Promise((done,reject)=>{const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('CDP deadline '+method));},20000);this.pending.set(id,{done,reject,timer});this.socket.send(JSON.stringify({id,method,params}));});}
  async evaluate(expression){const value=await this.call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(value.exceptionDetails)throw new Error(JSON.stringify(value.exceptionDetails));return value.result.value;}
}
async function connect(address){const socket=new WebSocket(address);await new Promise((done,reject)=>{socket.addEventListener('open',done,{once:true});socket.addEventListener('error',reject,{once:true});});return new CDP(socket);}
async function click(cdp,selector,text){const point=await until(()=>cdp.evaluate(`(()=>{
  for(const node of document.querySelectorAll(${JSON.stringify(selector)})){
    if(node.disabled||node.getAttribute('aria-disabled')==='true')continue;
    const label=node.cloneNode(true);
    label.querySelectorAll('[aria-hidden="true"],[hidden]').forEach(child=>child.remove());
    const expected=${JSON.stringify(text??null)};
    if(expected&&node.getAttribute('aria-label')!==expected&&label.textContent.trim()!==expected)continue;
    node.scrollIntoView({block:'nearest'});
    const bounds=node.getBoundingClientRect();
    const x=bounds.x+bounds.width/2,y=bounds.y+bounds.height/2;
    if(bounds.width&&bounds.height&&node.contains(document.elementFromPoint(x,y)))return {x,y};
  }
  return false;
})()`),'click '+selector+' '+text);
  await cdp.call('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});await cdp.call('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});}
async function escape(cdp){await cdp.call('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await cdp.call('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});}
try{
  const provenance=JSON.parse(await readFile(join(root,'apps/desktop/compatibility-source-input.json'),'utf8'));
  for(const row of provenance.inputs.filter(row=>row.target.startsWith('apps/desktop/renderer/'))){
    const bytes=await readFile(join(root,row.target));
    const original=execFileSync('git',['-C',join(root,'reference'),'show',provenance.sourceCommit+':'+row.source]);
    assert.deepEqual(bytes,original);
    const sha256=createHash('sha256').update(bytes).digest('hex');
    assert.equal(sha256,row.sourceSha256);
    report.assets.push({path:row.target,sourceCommit:provenance.sourceCommit,sha256});
  }
  for(const engine of ['22','44'])for(const locale of ['en','zh']){
    const directory=join(output,'e'+engine+'-'+locale);await mkdir(directory);const shell=join(directory,'observer-shell');
    await cp(join(root,'apps/desktop'),shell,{recursive:true,filter:path=>!path.split(/[\\/]/).includes('node_modules')});
    const main=join(shell,'main.cjs');let source=await readFile(main,'utf8');
    source=source.replace("process.versions.electron!=='22.3.27'",`process.versions.electron!==${JSON.stringify(engine==='22'?'22.3.27':'44.0.0')}`);
    await writeFile(main,source);
    const home=join(directory,'home');await mkdir(home);await writeFile(join(home,'settings.yaml'),`locale:\n  preference: ${locale}\nui-onboarding:\n  welcomeNoticeVersion: 2026-08-13.1\nui-theme:\n  preference: system\n`);
    const run={engine,locale,views:[],stderr:'',errors:[]};report.runs.push(run);
    const child=spawn(resolve(args['electron'+engine]),[shell,'--root',root,'--python',resolve(args.python),'--home',home,'--inspect=0','--remote-debugging-port=0','--lang='+locale],{windowsHide:true,env:{...credentialFreeEnvironment(process.env),DSH_HOME:home,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','pipe','pipe']});child.stdout.resume();child.stderr.on('data',data=>run.stderr+=data.toString());
    const connections=[];
    try{
      const address=await until(()=>run.stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/)?.[1],'renderer debugger');const base='http://'+new URL(address).host;
      run.browser=await(await fetch(base+'/json/version')).json();assert.match(run.browser.Browser,engine==='22'?/Chrome\/108\./:/Chrome\/152\./);
      const target=await until(async()=>{const rows=await(await fetch(base+'/json/list')).json();return rows.find(row=>row.url==='dsh-app://app/index.html');},'main page');
      const cdp=await connect(target.webSocketDebuggerUrl);connections.push(cdp);await cdp.call('Page.enable');await cdp.call('Runtime.enable');
      cdp.socket.addEventListener('message',event=>{const v=JSON.parse(event.data);if(v.method==='Runtime.exceptionThrown')run.errors.push(v.params);});
      await until(()=>cdp.evaluate(`!!document.querySelector('#root')?.children.length && document.documentElement.lang.startsWith(${JSON.stringify(locale)})`),'localized React root');await deferProviderOnboarding(cdp,until,false);
      const mainCdp=await connect(await until(()=>run.stderr.match(/Debugger listening on (ws:\/\/[^\s]+)/)?.[1],'main debugger'));connections.push(mainCdp);
      run.menu=await mainCdp.evaluate(`process.mainModule.require('electron').Menu.getApplicationMenu().items.map(n=>({label:n.label,items:n.submenu.items.map(i=>({label:i.label,accelerator:i.accelerator}))}))`);
      await mainCdp.evaluate(`process.mainModule.require('electron').Menu.getApplicationMenu().getMenuItemById('dsh-plugin-manager').click()`);
      const plugin=await until(async()=>{const rows=await(await fetch(base+'/json/list')).json();return rows.find(row=>row.url==='dsh-app://shell/plugin-manager.html');},'plugins');
      const plugins=await connect(plugin.webSocketDebuggerUrl);connections.push(plugins);await plugins.call('Page.enable');await plugins.call('Runtime.enable');await until(()=>plugins.evaluate(`!!document.querySelector('#title')?.textContent&&!document.querySelector('#refresh').disabled`),'plugin list');
      async function focus(host){
        await mainCdp.evaluate(`(()=>{const window=process.mainModule.require('electron').BrowserWindow.getAllWindows().find(w=>w.webContents.getURL().startsWith(${JSON.stringify('dsh-app://'+host+'/')}));window.show();window.focus();return true;})()`);
      }
      async function capture(connection,page,theme,scale){
        await connection.call('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:theme},{name:'prefers-reduced-motion',value:'reduce'}]});
        await connection.call('Emulation.setDeviceMetricsOverride',{width:Math.round((page==='plugins'?900:1280)/scale),height:Math.round((page==='plugins'?620:840)/scale),deviceScaleFactor:scale,mobile:false});
        await delay(750);
        const observed=await connection.evaluate(`(()=>{const n=document.documentElement,s=getComputedStyle(n),button=document.querySelector('#install');return {lang:n.lang,width:innerWidth,height:innerHeight,scrollWidth:n.scrollWidth,scrollHeight:n.scrollHeight,font:s.fontFamily,background:s.backgroundColor,color:s.color,accentSupported:CSS.supports('background','AccentColor'),buttonBackground:button&&getComputedStyle(button).backgroundColor,buttonColor:button&&getComputedStyle(button).color,focus:document.activeElement?.tagName,dialogs:document.querySelectorAll('[role="dialog"]').length,disclosures:[...document.querySelectorAll('details')].map(n=>({open:n.open})),controls:[...document.querySelectorAll('input,textarea,select,button')].filter(n=>{if(n.closest('details:not([open])')&&!n.closest('summary'))return false;const r=n.getBoundingClientRect();return r.width&&r.height}).map(n=>({tag:n.tagName,label:n.getAttribute('aria-label')||n.textContent.trim().slice(0,50),rect:(()=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()}))}})()`);
        const name=page+'-'+theme+'-'+scale+'.png';const shot=await connection.call('Page.captureScreenshot');await writeFile(join(directory,name),Buffer.from(shot.data,'base64'));run.views.push({page,theme,scale,screenshot:name,...observed});
      }
      const settings='[data-shortcut-modal="settings"]';
      for(const theme of ['light','dark'])for(const scale of [1,1.25,1.5]){
        await focus('app');
        await capture(cdp,'main',theme,scale);
        const openSidebar=locale==='en'?'Open sidebar':'打开侧边栏';
        if(await cdp.evaluate(`[...document.querySelectorAll('button')].some(button=>button.getAttribute('aria-label')===${JSON.stringify(openSidebar)}&&button.getBoundingClientRect().width>0)`)){
          await click(cdp,'button',openSidebar);
        }
        await click(cdp,'button',locale==='en'?'Account menu':'账号菜单');
        await click(cdp,'[role="menuitem"]',locale==='en'?'Settings':'设置');
        await until(()=>cdp.evaluate(`!!document.querySelector('${settings} nav')?.getBoundingClientRect().width`),'settings');
        await capture(cdp,'settings',theme,scale);
        await click(cdp,settings+' nav button',locale==='en'?'Models':'模型');await capture(cdp,'models',theme,scale);
        await click(cdp,settings+' button',locale==='en'?'Add model provider':'添加模型提供商');
        await until(()=>cdp.evaluate(`!!document.querySelector('[role="dialog"] [role="tab"]')`),'provider editor');await capture(cdp,'model-editor',theme,scale);
        await click(cdp,'[role="dialog"] button',locale==='en'?'Cancel':'取消');await escape(cdp);await until(()=>cdp.evaluate(`!document.querySelector('${settings}')`),'close settings');
        await focus('shell');
        await capture(plugins,'plugins',theme,scale);
        await plugins.call('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await plugins.call('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
        assert.notEqual(await plugins.evaluate('document.activeElement.tagName'),'BODY');
      }
      assert.deepEqual(run.errors,[]);mainCdp.socket.close();plugins.socket.close();await cdp.call('Browser.close').catch(()=>{});await until(()=>child.exitCode!==null,'graceful exit',20000);assert.equal(child.exitCode,0);run.exitCode=child.exitCode;run.status='passed';
    }finally{
      for(const connection of connections)connection.socket.close();
      if(child.exitCode===null)await new Promise(done=>execFile(join(process.env.SystemRoot,'System32/taskkill.exe'),['/PID',String(child.pid),'/T','/F'],{windowsHide:true},()=>done()));
    }
    await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n');
  }
  assert.equal(report.runs.reduce((n,r)=>n+r.views.length,0),120);
  for(const locale of ['en','zh']){
    const older=report.runs.find(r=>r.engine==='22'&&r.locale===locale),modern=report.runs.find(r=>r.engine==='44'&&r.locale===locale);
    for(const view of older.views){assert.ok(view.scrollWidth<=view.width,'horizontal page overflow');if(view.page==='plugins'){const peer=modern.views.find(v=>v.page===view.page&&v.theme===view.theme&&v.scale===view.scale);for(const field of ['background','color','buttonBackground','buttonColor'])assert.equal(view[field],peer[field],field);}}
  }
  report.status='passed';
}catch(error){report.status='failed';report.failure=error.stack;process.exitCode=1;}
await writeFile(join(output,'report.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({status:report.status,runs:report.runs.map(r=>({engine:r.engine,locale:r.locale,views:r.views.length,status:r.status})),failure:report.failure}));
