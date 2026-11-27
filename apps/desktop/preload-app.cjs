'use strict';
const {contextBridge,ipcRenderer}=require('electron');
if (location.protocol==='dsh-app:' && location.host==='app' && process.isMainFrame) {
  const subscribe=(channel,callback)=>{
    const listener=(_event,payload)=>callback(payload);
    ipcRenderer.on(channel,listener);
    return ()=>ipcRenderer.removeListener(channel,listener);
  };
  let pluginNavigationObserver;
  let pluginNavigationDeadline;
  const stopPluginNavigation=()=>{
    pluginNavigationObserver?.disconnect();
    clearTimeout(pluginNavigationDeadline);
  };
  ipcRenderer.on('dsh-desktop:open-plugins',()=>{
    stopPluginNavigation();
    // The pinned sidebar exposes Plugins as a fixed, labelled navigation button.
    const labels=new Set(['Plugins','插件','プラグイン','Complementos','Плагины','Plug-ins']);
    const open=()=>{
      const entry=Array.from(document.querySelectorAll('nav button[aria-label]'))
        .find(button=>labels.has(button.getAttribute('aria-label')));
      if(!entry)return false;
      stopPluginNavigation();
      entry.click();
      return true;
    };
    if(open())return;
    pluginNavigationObserver=new MutationObserver(open);
    pluginNavigationObserver.observe(document,{childList:true,subtree:true});
    pluginNavigationDeadline=setTimeout(stopPluginNavigation,10000);
  });
  window.addEventListener('pagehide',stopPluginNavigation,{once:true});
  const browser={
    acquire:workspace=>ipcRenderer.invoke('dsh-desktop:browser-acquire',workspace),
    release:lease=>ipcRenderer.invoke('dsh-desktop:browser-release',lease),
    onOpenRequested(lease,callback) {
      const listener=(_event,request)=>{if (request.lease===lease) callback(request.url);};
      ipcRenderer.on('dsh-desktop:browser-open-requested',listener);
      return ()=>ipcRenderer.removeListener('dsh-desktop:browser-open-requested',listener);
    },
  };
  contextBridge.exposeInMainWorld('dshDesktop',{protocolVersion:1,browser,
  deviceInfo:()=>ipcRenderer.invoke('dsh-desktop:device-info'),updates:{
    status:()=>ipcRenderer.invoke('dsh-desktop:updates-status'),
    open:()=>ipcRenderer.invoke('dsh-desktop:updates-open'),
    subscribe:callback=>subscribe('dsh-desktop:updates-presentation',callback),
  },shortcuts:{
    get:definitions=>ipcRenderer.invoke('dsh-desktop:shortcuts-get',definitions),
    edit:(edit,revision)=>ipcRenderer.invoke('dsh-desktop:shortcuts-edit',edit,revision),
    recording:active=>ipcRenderer.invoke('dsh-desktop:shortcuts-recording',active),
    subscribe:callback=>subscribe('dsh-desktop:shortcuts-changed',callback),
  },keyboard:{
    closeWindow:revision=>ipcRenderer.invoke('dsh-desktop:shortcuts-close-window',revision),
    subscribe:callback=>subscribe('dsh-desktop:shortcuts-input',callback),
  },fileActions:{
    save:request=>ipcRenderer.invoke('dsh-desktop:file-save',request),
    readClipboardImage:url=>ipcRenderer.invoke('dsh-desktop:clipboard-read-image',url),
  },fileDrag:{
    prepare:(source,requestId)=>ipcRenderer.invoke('dsh-desktop:drag-prepare',source,requestId),
    cancel:requestId=>{void ipcRenderer.invoke('dsh-desktop:drag-cancel',requestId).catch(console.error);},
    start:handle=>ipcRenderer.invoke('dsh-desktop:drag-start',handle),
    release:handle=>{void ipcRenderer.invoke('dsh-desktop:drag-release',handle).catch(console.error);},
  }});
  contextBridge.exposeInMainWorld('__DSH_DIRECTORY_PICKER__',{
    pick:()=>ipcRenderer.invoke('dsh-desktop:directory-pick'),
  });
  contextBridge.exposeInMainWorld('__DSH_LOCALE__',{
    read:()=>ipcRenderer.invoke('dsh-desktop:locale-bootstrap'),
    onChange:language=>{void ipcRenderer.invoke('dsh-desktop:locale-changed',language).catch(console.error);},
  });
  contextBridge.exposeInMainWorld('dshOnboarding',{
    hasApiKey:()=>ipcRenderer.invoke('dsh-desktop:onboarding-api-key'),
    setActive:active=>{void ipcRenderer.invoke('dsh-desktop:onboarding-active',active).catch(console.error);},
  });
  // Electron 22 exposes the backing path as File.path.
  contextBridge.exposeInMainWorld('__DSH_HOST_PATHS__',{
    pathFor:file=>file instanceof File && typeof file.path==='string' ? file.path : '',
  });
  const markPlatform=()=>{document.documentElement.dataset.platform=process.platform;};
  if (document.documentElement) markPlatform();
  else window.addEventListener('DOMContentLoaded',markPlatform,{once:true});
  ipcRenderer.on('dsh-desktop:window-fullscreen',(_event,fullscreen)=>{
    const root=document.documentElement;
    if (!root) return;
    if (fullscreen) root.dataset.fullscreen='true';
    else delete root.dataset.fullscreen;
  });
}
window.addEventListener('DOMContentLoaded',async()=>{
  if(location.protocol!=='dsh-app:'||location.hostname!=='app'||window.top!==window)return;
  const root=document.documentElement;
  const syncOverlay=()=>{
    if (navigator.windowControlsOverlay.visible) root.dataset.windowsTitlebar='';
    else delete root.dataset.windowsTitlebar;
  };
  if (navigator.windowControlsOverlay) {
    root.style.setProperty('--dsh-windows-titlebar-height','40px');
    syncOverlay();
    navigator.windowControlsOverlay.addEventListener('geometrychange',syncOverlay);
  }
  const syncTheme=()=>{
    const theme=root.getAttribute('data-ds-theme-source');
    if (theme) ipcRenderer.invoke('dsh-desktop:theme-set',theme).catch(console.error);
  };
  const themeObserver=new MutationObserver(syncTheme);
  themeObserver.observe(root,{attributeFilter:['data-ds-theme-source']});
  syncTheme();
  window.addEventListener('pagehide',()=>{
    themeObserver.disconnect();
    navigator.windowControlsOverlay?.removeEventListener('geometrychange',syncOverlay);
  },{once:true});
  try{
    const state=await ipcRenderer.invoke('dsh-desktop:environment-get');
    if(!state.limitedShell||localStorage.getItem('dsh-win7-environment-dismissed')==='1')return;
    const chinese=state.locale==='zh-CN',notice=document.createElement('aside');
    notice.id='dsh-win7-environment-notice';notice.setAttribute('role','status');
    Object.assign(notice.style,{position:'fixed',top:'8px',left:'50%',transform:'translateX(-50%)',zIndex:'2147483647',
      padding:'10px 14px',border:'1px solid #82a7de',borderRadius:'8px',background:'#eef5ff',color:'#18314d',font:'14px Segoe UI,sans-serif',maxWidth:'85vw',boxShadow:'0 2px 8px #0002'});
    const text=document.createElement('span');text.textContent=chinese?'基础环境可继续使用；升级 PowerShell 5.1 可改善终端与自动化兼容性。':'Basic use is available. PowerShell 5.1 improves terminal and automation compatibility. ';
    const guide=document.createElement('button');guide.textContent=chinese?'查看离线升级指南':'Offline setup guide';guide.type='button';
    guide.addEventListener('click',()=>{ipcRenderer.invoke('dsh-desktop:setup-guide').catch(()=>{});});
    const close=document.createElement('button');close.textContent='×';close.type='button';close.setAttribute('aria-label',chinese?'关闭环境提示':'Dismiss environment notice');
    close.addEventListener('click',()=>{localStorage.setItem('dsh-win7-environment-dismissed','1');notice.remove();});
    notice.append(text,guide,close);document.body.append(notice);
  }catch(error){console.error('Desktop environment notice:',error);}
},{once:true});
