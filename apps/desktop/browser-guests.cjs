'use strict';

const {randomUUID}=require('node:crypto');
const {session}=require('electron');

function httpUrl(value) {
  try {
    const url=new URL(value);
    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) return url;
  } catch {}
  return null;
}

function createBrowserGuests(owner, attachInput) {
  const partitions=new Map(), leases=new Map();
  function acquire(workspace) {
    if (typeof workspace!=='string' || !workspace || workspace.length>4096) {
      throw new Error('Desktop browser requires a workspace identity');
    }
    let partition=partitions.get(workspace);
    if (!partition) {
      partition='dsh-sidebar-browser-'+randomUUID();
      const isolated=session.fromPartition(partition);
      isolated.setPermissionCheckHandler(()=>false);
      isolated.setPermissionRequestHandler((_contents, _permission, callback)=>callback(false));
      isolated.setDevicePermissionHandler(()=>false);
      isolated.setDisplayMediaRequestHandler((_request,callback)=>callback({}));
      isolated.on('will-download',event=>event.preventDefault());
      isolated.webRequest.onBeforeRequest(({url}, callback)=>{
        const target=new URL(url);
        const allowed=httpUrl(url) || (['ws:', 'wss:'].includes(target.protocol) &&
          !target.username && !target.password) || ['about:', 'data:', 'blob:'].includes(target.protocol);
        callback({cancel:!allowed});
      });
      partitions.set(workspace,partition);
    }
    const lease=randomUUID();
    leases.set(lease,{partition,attached:false});
    return {lease,partition};
  }
  async function release(id) {
    const lease=leases.get(id);
    if (!lease) return;
    leases.delete(id);
    lease.detachInput?.();
    const guest=lease.guest;
    if (guest && !guest.isDestroyed()) {
      const destroyed=new Promise(resolve=>guest.once('destroyed',resolve));
      guest.close({waitForBeforeUnload:false});
      await destroyed;
    }
  }
  function releaseAll() {
    for (const id of leases.keys()) void release(id).catch(console.error);
  }
  owner.on('will-attach-webview',(event,preferences,params)=>{
    const bootstrap='about:blank#';
    const id=typeof params.src==='string' && params.src.startsWith(bootstrap) ? params.src.slice(bootstrap.length) : '';
    const lease=leases.get(id);
    if (!lease || lease.attached || params.partition!==lease.partition) {
      event.preventDefault();
      return;
    }
    lease.attached=true;
    for (const key of Object.keys(preferences)) {
      if (key!=='disablePopups') delete preferences[key];
    }
    Object.assign(preferences,{
      partition:lease.partition, nodeIntegration:false, nodeIntegrationInWorker:false,
      nodeIntegrationInSubFrames:false, contextIsolation:true, sandbox:true, webSecurity:true,
      allowRunningInsecureContent:false, webviewTag:false, plugins:false, navigateOnDragDrop:false,
      disableDialogs:true,
    });
    params.httpreferrer='';
  });
  owner.on('did-attach-webview',(_event,guest)=>{
    let id;
    guest.once('dom-ready',()=>{
      const url=guest.getURL();
      const bootstrap='about:blank#';
      id=url.startsWith(bootstrap) ? url.slice(bootstrap.length) : '';
      const lease=leases.get(id);
      if (!lease || !lease.attached || lease.guest) {
        guest.close({waitForBeforeUnload:false});
        return;
      }
      lease.guest=guest;
      lease.detachInput=attachInput(guest,id);
      guest.once('destroyed',()=>leases.delete(id));
    });
    guest.setWindowOpenHandler(({url,postBody})=>{
      const target=httpUrl(url);
      if (target && !postBody && leases.get(id)?.guest===guest && !owner.isDestroyed()) {
        owner.send('dsh-desktop:browser-open-requested',{lease:id,url:target.href});
      }
      return {action:'deny'};
    });
    guest.on('will-navigate',(event,url)=>{if (!httpUrl(url)) event.preventDefault();});
    guest.on('will-redirect',(event,url,_inPlace,isMainFrame)=>{
      if (isMainFrame && !httpUrl(url)) event.preventDefault();
    });
    guest.on('login',(event,_details,_authInfo,callback)=>{event.preventDefault();callback();});
  });
  owner.on('did-start-navigation',(_event,_url,inPlace,isMainFrame)=>{
    if (isMainFrame && !inPlace) releaseAll();
  });
  owner.on('render-process-gone',releaseAll);
  owner.once('destroyed',releaseAll);
  return {acquire,release};
}

module.exports={createBrowserGuests,httpUrl};
