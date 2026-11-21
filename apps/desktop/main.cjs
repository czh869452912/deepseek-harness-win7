'use strict';
require('./stdio.cjs').protectStdio();
const {app,BrowserWindow,protocol,ipcMain,Menu,Tray,nativeImage,dialog,shell:systemShell,nativeTheme,session}=require('electron');
const {join,resolve,extname,dirname}=require('node:path');
const {release:osRelease,cpus,totalmem}=require('node:os');
const {readFile}=require('node:fs/promises');
const {Readable}=require('node:stream');
const {DesktopProjectManager}=require('./project-manager.cjs');
const {resolveDesktopLocale}=require('./locale.cjs');
const {desktopHome}=require('./home.cjs');
const {desktopEnvironment}=require('./environment.cjs');
const {DesktopUpdateCoordinator}=require('./update-coordinator.cjs');
const {Win7Updater,loadConfiguration}=require('./updates.cjs');
const {createBrowserGuests,httpUrl}=require('./browser-guests.cjs');
const {installFileActions}=require('./file-actions.cjs');
const {installFileDrag}=require('./file-drag.cjs');
const {installDesktopShortcuts}=require('./shortcuts.cjs');

protocol.registerSchemesAsPrivileged([{scheme:'dsh-app',privileges:{standard:true,secure:true,supportFetchAPI:true,corsEnabled:false,stream:true}}]);
const development=!app.isPackaged;
const option=name=>{const index=process.argv.indexOf(name);return index<0?undefined:process.argv[index+1];};
if(!development&&process.argv.some(value=>['--root','--python','--home','--test-output'].includes(value)))throw new Error('Development overrides unavailable in packaged Desktop');
const root=development?resolve(option('--root')??join(__dirname,'../..')):join(process.resourcesPath,'harness');
const home=desktopHome(development&&option('--home')||process.env.DSH_HOME,app.getPath('home'));
app.setPath('userData',join(home,'desktop','electron'));
const primary=app.requestSingleInstanceLock();
let mainWindow,pluginWindow,guideWindow,manager,tray,stopping=false,allowQuit=false,shellReady=false;
let browserGuests,fileDrag,shortcuts;
function focus(){
  if(!app.isReady()||!shellReady||stopping)return;
  if(!mainWindow||mainWindow.isDestroyed())mainWindow=createWindow(false);
  if(mainWindow.isMinimized())mainWindow.restore();mainWindow.show();mainWindow.focus();
}
if(!primary)app.quit();
else app.on('second-instance',focus);
const mime={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.svg':'image/svg+xml'};
function assertSender(event,hosts=['shell']){
  const frame=event.senderFrame;
  const url=frame&&new URL(frame.url);
  if(!frame||frame!==event.sender.mainFrame||url.protocol!=='dsh-app:'||!hosts.includes(url.host)||url.username||url.password)throw new Error('Desktop IPC from unowned renderer');
}
function createWindow(shell){
  // The native frame keeps caption controls available on unqualified legacy Windows versions.
  const caption=process.platform==='win32'&&!shell&&Number(osRelease().split('.')[0])>=10;
  const colors=()=>nativeTheme.shouldUseDarkColors
    ? {color:'#1b1b1c',symbolColor:'#f9fafb'} : {color:'#f9fafb',symbolColor:'#0f1115'};
  const window=new BrowserWindow({width:shell?900:1280,height:shell?620:840,minWidth:shell?880:520,minHeight:600,show:false,
    ...(caption?{titleBarStyle:'hidden',titleBarOverlay:{height:40,...colors()},autoHideMenuBar:true}:{}),
    title:shell?'DeepSeek Harness — Desktop Plugins':'DeepSeek Harness',webPreferences:{
      preload:join(__dirname,shell?'preload.cjs':'preload-app.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true,
      webviewTag:!shell}});
  const expected=shell?'shell':'app';
  if (!shell) {
    shortcuts.attach(window);
    browserGuests=createBrowserGuests(window.webContents,(guest,id)=>shortcuts.attachGuest(window,guest,id));
    fileDrag.attach(window.webContents);
    let lastFullscreen;
    const publishFullscreen=(force=false)=>{
      if(window.isDestroyed())return;
      const value=window.isFullScreen();
      if(force||value!==lastFullscreen) {
        lastFullscreen=value;
        window.webContents.send('dsh-desktop:window-fullscreen',value);
      }
    };
    window.webContents.on('did-finish-load',()=>publishFullscreen(true));
    window.on('enter-full-screen',()=>setImmediate(publishFullscreen));
    window.on('leave-full-screen',()=>setImmediate(publishFullscreen));
    window.on('resize',()=>setImmediate(publishFullscreen));
  }
  if (caption) {
    const sync=()=>{if (!window.isDestroyed()) window.setTitleBarOverlay({height:40,...colors()});};
    nativeTheme.on('updated',sync);
    window.once('closed',()=>nativeTheme.removeListener('updated',sync));
  }
  window.webContents.setWindowOpenHandler(({url,postBody})=>{
    const target=!shell&&!postBody&&httpUrl(url);
    if (target) void systemShell.openExternal(target.href).catch(console.error);
    return {action:'deny'};
  });
  window.webContents.on('will-navigate',(event,url)=>{try{const parsed=new URL(url);if(parsed.protocol!=='dsh-app:'||parsed.hostname!==expected)event.preventDefault();}catch{event.preventDefault();}});
  window.once('ready-to-show',()=>{if(!window.isDestroyed())window.show();});
  window.on('close',event=>{if(!shell&&!stopping){event.preventDefault();window.hide();}});
  window.loadURL('dsh-app://'+expected+(shell?'/plugin-manager.html':'/index.html')).catch(error=>console.error(error));
  return window;
}
function openPlugins(){if(pluginWindow&&!pluginWindow.isDestroyed()){pluginWindow.show();pluginWindow.focus();}else pluginWindow=createWindow(true);}
function openGuide(){
  if(guideWindow&&!guideWindow.isDestroyed()){guideWindow.show();guideWindow.focus();return;}
  guideWindow=new BrowserWindow({width:920,height:760,title:'Windows 7 offline setup',webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
  guideWindow.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  guideWindow.webContents.on('will-navigate',(event,url)=>{if(url!=='dsh-app://shell/win7-setup.html')event.preventDefault();});
  guideWindow.loadURL('dsh-app://shell/win7-setup.html').catch(error=>console.error(error));
}
async function resource(request){
  if(stopping)return {status:503,headers:[],body:Readable.from([])};
  const url=new URL(request.url);
  if(url.protocol!=='dsh-app:'||!['app','shell'].includes(url.hostname))return {status:403,headers:[],body:Readable.from([])};
  if(url.hostname==='shell'){
    if(!['GET','HEAD'].includes(request.method))return {status:405,headers:[],body:Readable.from([])};
    let path;try{path=decodeURIComponent(url.pathname);}catch{return {status:400,headers:[],body:Readable.from([])};}
    const allowed=['/plugin-manager.html','/plugin-manager.js','/plugin-manager.css','/plugin-manager-compat.css','/win7-setup.html'];
    if(!allowed.includes(path))return {status:404,headers:[],body:Readable.from([])};
    let bytes=await readFile(join(__dirname,path==='/win7-setup.html'?'':'renderer',path.slice(1)));
    if(path==='/plugin-manager.html')bytes=Buffer.from(bytes.toString('utf8')
      .replace('placeholder="@scope/plugin@1.2.3"','placeholder="C:\\plugins\\package.zip"')
      .replace('</head>','<link rel="stylesheet" href="plugin-manager-compat.css">\n</head>'));
    return {status:200,headers:[['content-type',mime[extname(path)]??'application/octet-stream']],body:Readable.from(request.method==='HEAD'?[]:[bytes])};
  }
  const headers=Object.entries(request.headers??{});
  const uploads=request.uploadData??[];
  const body=uploads.length?(async function*(){
    const {createReadStream}=require('node:fs');
    for(const row of uploads){
      if(row.bytes)yield row.bytes;
      else if(row.file){for await(const data of createReadStream(row.file))yield data;}
      else if(row.blobUUID)yield await session.defaultSession.getBlobData(row.blobUUID);
      else throw new Error('Unsupported Electron upload body source');
    }
  })():null;
  return manager.host.fetch({url:request.url,method:request.method,headers,body});
}
async function main(){
  if(process.versions.electron!=='22.3.27')throw new Error('Pinned Electron22.3.27 required');
  manager=new DesktopProjectManager({python:development?resolve(option('--python')??join(root,'python.exe')):join(root,'python.exe'),root,home,profile:join(home,'profiles/desktop')});
  await manager.start();
  protocol.registerStreamProtocol('dsh-app',(request,callback)=>{
    resource(request).then(response=>{
      const headers={};for(const [name,value] of response.headers){if(headers[name])headers[name]=[].concat(headers[name],value);else headers[name]=value;}
      callback({statusCode:response.status,headers,data:response.body});
    },error=>{
      if(stopping&&error.message==='Desktop Host is stopping'){callback({statusCode:503,data:Readable.from([])});return;}
      console.error(error);callback({statusCode:500,data:Readable.from(['Desktop request failed'])});
    });
  });
  const languages=app.getPreferredSystemLanguages?.()??[];
  if (!languages.length) languages.push(app.getLocale());
  function shellLocale(language){
    const value=resolveDesktopLocale(language);
    return {...value,messages:{...value.messages,
      pluginManagerDescription:value.id==='zh-CN'?'安装本地 Python 插件文件夹或 ZIP 包，仅作用于桌面端。':'Install a local Python plugin folder or ZIP package in Desktop.',
      npmPackage:value.id==='zh-CN'?'插件文件夹或 ZIP 路径':'Plugin folder or ZIP path',
      targetVersion:value.id==='zh-CN'?'输入 {name} 的升级 ZIP 或文件夹路径':'Enter the upgrade ZIP or folder path for {name}'}};
  }
  let locale=shellLocale(languages[0]??app.getLocale());
  const environment=development&&option('--test-output')&&option('--test-limited-shell')==='true'
    ?{limitedShell:true,status:'limited'}:await desktopEnvironment();
  ipcMain.handle('dsh-desktop:environment-get',event=>{assertSender(event,['app']);return {...environment,locale:locale.id};});
  ipcMain.handle('dsh-desktop:setup-guide',event=>{assertSender(event,['app','shell']);openGuide();});
  const appHandler=(name, handler)=>ipcMain.handle(name,(event,...args)=>{
    assertSender(event,['app']);
    if (event.sender!==mainWindow?.webContents) throw new Error('Desktop IPC from unowned window');
    return handler(...args);
  });
  appHandler('dsh-desktop:browser-acquire',workspace=>browserGuests.acquire(workspace));
  appHandler('dsh-desktop:browser-release',lease=>browserGuests.release(lease));
  appHandler('dsh-desktop:directory-pick',async()=>{
    const selected=await dialog.showOpenDialog(mainWindow,{properties:['openDirectory']});
    return selected.canceled ? null : selected.filePaths[0] ?? null;
  });
  appHandler('dsh-desktop:theme-set',theme=>{
    if (['system','light','dark'].includes(theme)) nativeTheme.themeSource=theme;
  });
  appHandler('dsh-desktop:device-info',()=>{
    const fields=[['platform',()=>process.platform],['os',()=>process.getSystemVersion()],
      ['app_arch',()=>process.arch],['cpu',()=>cpus()[0]?.model],
      ['memory_gib',()=>(totalmem()/1024**3).toFixed(1)]];
    const result=[];
    for (const [key,read] of fields) {
      let value;
      try { value=read(); } catch { continue; }
      if (value) result.push(key+'='+value);
    }
    return result.join('; ');
  });
  async function hostRpc(host,method,args={}){
    const response=await host.fetch({url:'dsh-app://app/api/'+method,method:'POST',
      headers:[['content-type','application/json']],
      body:JSON.stringify({type:'client-request',rpcId:'desktop-shell',method,payload:{args}})});
    const chunks=[];
    for await (const chunk of response.body) chunks.push(Buffer.from(chunk));
    if(response.status!==200) throw new Error('Desktop Host RPC failed: '+method);
    const {result}=JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if(!result?.ok) throw new Error('Desktop Host RPC failed: '+method);
    return result.value;
  }
  appHandler('dsh-desktop:locale-bootstrap',async()=>{
    const {namespaces}=await hostRpc(manager.host,'settings/describe');
    const preference=namespaces.find(row=>row.ns==='locale')?.value?.preference??null;
    return {languages,preference};
  });
  appHandler('dsh-desktop:locale-changed',language=>{
    if(typeof language!=='string'||!language||language.length>64)return;
    const resolved=shellLocale(language);
    if(resolved.id===locale.id)return;
    locale=resolved;
    updateMenu();
    updateTray();
  });
  appHandler('dsh-desktop:onboarding-api-key',async()=>{
    const host=manager.host;
    const [{namespaces},providers]=await Promise.all([
      hostRpc(host,'settings/describe'),
      hostRpc(host,'llm/listConfigurableProviders'),
    ]);
    const settings=new Map(namespaces.map(row=>[row.ns,row.value]));
    const refs=new Set();
    const official=settings.get('llm-deepseek')?.apiKeyEnv;
    if(typeof official==='string')refs.add(official);
    for (const {settingsNs,settingsPath} of providers){
      let value=settings.get(settingsNs);
      for (const key of settingsPath) value=value?.[key];
      if(typeof value?.apiKeyEnv==='string')refs.add(value.apiKeyEnv);
    }
    const unique=[...refs];
    for(let offset=0;offset<unique.length;offset+=64){
      const states=await hostRpc(host,'credentials/describe',{refs:unique.slice(offset,offset+64)});
      if(Object.values(states).some(state=>state?.configured===true))return true;
    }
    return false;
  });
  appHandler('dsh-desktop:onboarding-active',active=>{
    if(typeof active==='boolean')mainWindow.setMinimumSize(active?960:520,600);
  });
  installFileActions(appHandler,()=>mainWindow);
  fileDrag=installFileDrag(appHandler,()=>mainWindow,join(home,'desktop','drag'));
  const register=(channel,handler)=>ipcMain.handle(channel,(event,...args)=>{assertSender(event);return handler(...args);});
  const updateConfiguration=development?undefined:await loadConfiguration(join(process.resourcesPath,'win7-update.json'));
  let updateState={phase:'idle'};
  let updatePresentation={phase:'idle'};
  const publishUpdate=state=>{
    const failure=state.phase==='error'?(updateState.phase==='checking'?'check':'install'):undefined;
    updateState=state;
    updatePresentation={phase:state.phase,...(state.version?{version:state.version}:{}),...(failure?{failure}:{})};
    for(const window of BrowserWindow.getAllWindows()){
      const url=window.webContents.getURL();
      if(url.startsWith('dsh-app://shell/'))window.webContents.send('dsh-desktop:updates-state',state);
      if(url.startsWith('dsh-app://app/'))window.webContents.send('dsh-desktop:updates-presentation',updatePresentation);
    }
    return state;
  };
  const updater=new Win7Updater({config:updateConfiguration,currentVersion:app.getVersion(),
    installRoot:development?undefined:resolve(dirname(app.getPath('exe')),'../..'),quit:()=>app.quit(),
    onError:error=>publishUpdate({phase:'error',message:error.message})});
  const updates=new DesktopUpdateCoordinator(publishUpdate,()=>manager.close(),updater,()=>Boolean(updateConfiguration));
  register('dsh-desktop:updates-check',()=>updates.check());
  register('dsh-desktop:updates-install',async()=>{await updates.install();});
  const showUpdate=async manual=>{
    const state=await updates.check(),messages=locale.messages;
    if(state.phase==='error'){
      if(manual)await dialog.showMessageBox({type:'error',title:messages.updateCheckFailedTitle,message:state.message??messages.unknownError});
      return;
    }
    if(state.phase!=='available'){
      if(manual)await dialog.showMessageBox({type:'info',title:messages.updateCheckTitle,message:state.message??messages.updateCurrent});
      return;
    }
    const result=await dialog.showMessageBox({type:'info',title:messages.updateTitle,message:messages.updateAvailable,
      detail:messages.updateDetail.replace('{version}',state.version??''),buttons:[messages.installAndRestart,messages.later],defaultId:0,cancelId:1});
    if(result.response!==0)return;
    const installed=await updates.install();
    if(installed.phase==='error')await dialog.showMessageBox({type:'error',title:messages.updateFailedTitle,message:installed.message??messages.unknownError});
  };
  let updatePrompt;
  const checkAndPrompt=manual=>{
    if (!updatePrompt) updatePrompt=showUpdate(manual).finally(()=>{updatePrompt=undefined;});
    return updatePrompt;
  };
  appHandler('dsh-desktop:updates-status',()=>updatePresentation);
  appHandler('dsh-desktop:updates-open',()=>checkAndPrompt(true));
  register('dsh-desktop:locale-get',()=>locale);
  register('dsh-desktop:plugins-list',()=>manager.list());
  const mutation=async(operation,value,name)=>{
    if(typeof value!=='string'||!value||value.length>32768||name!==undefined&&typeof name!=='string')throw new Error('Invalid Desktop package input');
    const window=mainWindow;
    if(window&&!window.isDestroyed())await window.loadURL('about:blank');
    try{await manager.mutate(operation,value,name);}
    finally{if(window&&!window.isDestroyed())await window.loadURL('dsh-app://app/index.html');}
  };
  register('dsh-desktop:plugins-add',spec=>mutation('add',spec));
  register('dsh-desktop:plugins-remove',name=>mutation('remove',name));
  register('dsh-desktop:plugins-update',(name,source)=>mutation('upgrade',source,name));
  const updateMenu=()=>Menu.setApplicationMenu(Menu.buildFromTemplate([shortcuts.fileMenu({
    fileMenu:locale.id==='zh-CN'?'文件':'File',closePage:locale.id==='zh-CN'?'关闭页面':'Close Page',
  }),{label:locale.messages.application,submenu:[
    {id:'dsh-plugin-manager',label:locale.messages.pluginsMenu,accelerator:'CmdOrCtrl+,',click:openPlugins},
    {label:locale.messages.checkUpdatesMenu,click:()=>{void checkAndPrompt(true);}},{type:'separator'},
    {label:locale.id==='zh-CN'?'退出':'Quit',click:()=>app.quit()}]}]));
  const updateTray=()=>tray?.setContextMenu(Menu.buildFromTemplate([
    {label:'DeepSeek Harness',click:focus},{label:locale.messages.pluginsMenu,click:openPlugins},
    {type:'separator'},{label:locale.id==='zh-CN'?'退出':'Quit',click:()=>app.quit()}]));
  shortcuts=installDesktopShortcuts(()=>mainWindow,app.getPath('userData'),'windows',updateMenu,
    ()=>({revision:0,blocked:false}));
  updateMenu();
  shellReady=true;
  mainWindow=createWindow(false);
  const icon=nativeImage.createFromPath(join(__dirname,'tray.png'));
  if(icon.isEmpty())throw new Error('Desktop tray image is missing or invalid');
  tray=new Tray(icon);tray.setToolTip('DeepSeek Harness');tray.on('double-click',focus);
  updateTray();
  app.on('activate',focus);
  publishUpdate(updateState);
  const updateTimer=setTimeout(()=>{void checkAndPrompt(false);},10000);updateTimer.unref();
  if(development&&option('--test-output'))await require('./smoke-test.cjs').run({app,mainWindow,openPlugins,
    pluginWindow:()=>pluginWindow,guideWindow:()=>guideWindow,environment,manager,output:resolve(option('--test-output'))});
}
app.on('window-all-closed',()=>{});
app.on('before-quit',event=>{
  if(allowQuit)return;
  event.preventDefault();if(stopping)return;stopping=true;
  // Release renderer subscriptions before closing the transport they consume.
  // Otherwise a live control stream receives a network failure during quit.
  for(const window of BrowserWindow.getAllWindows())if(!window.isDestroyed())window.destroy();
  shortcuts?.dispose();
  Promise.allSettled([manager?.close(),fileDrag?.dispose()]).then(results=>{
    for (const result of results) if (result.status==='rejected') console.error(result.reason);
  }).finally(()=>{
    tray?.destroy();allowQuit=true;app.quit();
  });
});
if(primary)app.whenReady().then(main).catch(async error=>{
  console.error(error);
  if(!development||!option('--test-output'))dialog.showErrorBox(resolveDesktopLocale(app.getLocale()).messages.startupFailed,error.message);
  await manager?.close().catch(()=>{});allowQuit=true;app.exit(1);
});
