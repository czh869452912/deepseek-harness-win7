'use strict';

const {app, net, session}=require('electron');
const {randomUUID}=require('node:crypto');
const {open, unlink}=require('node:fs/promises');
const {join, extname}=require('node:path');
const {httpUrl}=require('./browser-guests.cjs');

const maxImageBytes=64*1024*1024;

function safeName(name) {
  let leaf=String(name ?? '').split(/[\\/]/).pop().replace(/[<>:"|?*\x00-\x1f]/g,'_').replace(/[. ]+$/,'').slice(0,180);
  if (!leaf || /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(leaf)) leaf='file-'+leaf;
  return leaf;
}

async function reserveDownload(directory,name) {
  const extension=extname(name), stem=name.slice(0,name.length-extension.length);
  for (let number=0; number<10000; number++) {
    const path=join(directory,number ? stem+' ('+number+')'+extension : name);
    try {
      const file=await open(path,'wx');
      await file.close();
      return path;
    } catch (error) {
      if (error.code!=='EEXIST') throw error;
    }
  }
  throw new Error('Could not reserve a download path');
}

function installFileActions(appHandler, getWindow) {
  const pending=new Map();
  const downloads=session.defaultSession;
  const images=session.fromPartition('dsh-clipboard-images');
  downloads.on('will-download',(_event,item,contents)=>{
    const url=item.getURLChain()[0];
    const row=pending.get(url);
    if (!row || row.contents!==contents) return;
    row.item=item;
    const path=join(app.getPath('downloads'),safeName(row.name??item.getFilename()));
    if (row.destination) item.setSavePath(row.destination);
    else item.setSaveDialogOptions({defaultPath:path,properties:['showOverwriteConfirmation','createDirectory']});
    item.once('done',(_event,state)=>{
      if (state==='completed') row.finish({status:'saved',path:item.getSavePath()});
      else if (state==='cancelled') row.finish({status:'cancelled'});
      else row.finish(new Error('File download interrupted'));
    });
  });
  appHandler('dsh-desktop:file-save',async request=>{
    if (!request || typeof request.url!=='string' || !['download','saveAs'].includes(request.mode) ||
        (request.name!==undefined && typeof request.name!=='string')) throw new Error('Invalid file save request');
    const url=new URL(request.url);
    const local=url.protocol==='dsh-app:' && url.host==='app';
    const rendererBlob=url.protocol==='blob:' && url.pathname.startsWith('dsh-app://app/');
    if ((!httpUrl(url.href) && !local && !rendererBlob && url.protocol!=='data:') || url.username || url.password) {
      throw new Error('Unsupported file source');
    }
    url.hash='dsh-download='+randomUUID();
    const contents=getWindow().webContents;
    const name=safeName(request.name ?? decodeURIComponent(url.pathname.split('/').pop()));
    const destination=request.mode==='download' ? await reserveDownload(app.getPath('downloads'),name) : undefined;
    let saved=false;
    try {
      const outcome=await new Promise((resolve,reject)=>{
        const row={contents,name:request.name,destination,item:null,finish};
        const cancel=()=>{finish({status:'cancelled'});row.item?.cancel();};
        const navigate=(_event,_url,inPlace,isMainFrame)=>{if (isMainFrame && !inPlace) cancel();};
        const timer=setTimeout(()=>{finish(new Error('File download timed out'));row.item?.cancel();},300000);
        function finish(value) {
          if (!pending.delete(url.href)) return;
          clearTimeout(timer);
          contents.removeListener('destroyed',cancel);
          contents.removeListener('did-start-navigation',navigate);
          if (value instanceof Error) reject(value);
          else resolve(value);
        }
        pending.set(url.href,row);
        contents.once('destroyed',cancel);
        contents.on('did-start-navigation',navigate);
        try {contents.downloadURL(url.href);}
        catch (error) {finish(error);}
      });
      saved=outcome.status==='saved';
      return outcome;
    } finally {
      if (!saved && destination) await unlink(destination).catch(error=>{if (error.code!=='ENOENT') throw error;});
    }
  });
  appHandler('dsh-desktop:clipboard-read-image',value=>{
    const url=typeof value==='string' && httpUrl(value);
    if (!url) throw new Error('Invalid image URL');
    return new Promise((resolve,reject)=>{
      const request=net.request({url:url.href,session:images,useSessionCookies:false,redirect:'manual'});
      const contents=getWindow().webContents;
      const close=()=>finish(new Error('Image read cancelled'));
      const navigate=(_event,_url,inPlace,isMainFrame)=>{if (isMainFrame && !inPlace) close();};
      const timer=setTimeout(()=>finish(new Error('Image read timed out')),30000);
      let redirects=0, done=false;
      function finish(error,value) {
        if (done) return;
        done=true;clearTimeout(timer);
        contents.removeListener('destroyed',close);
        contents.removeListener('did-start-navigation',navigate);
        if (error) {request.abort();reject(error);}
        else resolve(value);
      }
      contents.once('destroyed',close);
      contents.on('did-start-navigation',navigate);
      request.on('redirect',(_code,_method,target)=>{
        if (++redirects>10 || !httpUrl(target)) finish(new Error('Invalid image redirect'));
        else request.followRedirect();
      });
      request.on('login',(_info,callback)=>callback());
      request.on('error',finish);
      request.on('response',response=>{
        const header=response.headers['content-type'];
        const mediaType=((Array.isArray(header) ? header[0] : header) ?? '').split(';')[0].trim();
        if (response.statusCode!==200 || !/^image\//i.test(mediaType)) {
          finish(new Error('Original image unavailable (HTTP '+response.statusCode+')'));return;
        }
        const chunks=[];
        let size=0;
        response.on('data',chunk=>{
          size+=chunk.length;
          if (size>maxImageBytes) finish(new Error('Original image exceeds the download limit'));
          else chunks.push(chunk);
        });
        response.on('error',finish);
        response.on('end',()=>{if (!done) finish(null,{bytes:new Uint8Array(Buffer.concat(chunks)),mediaType});});
      });
      request.end();
    });
  });
}

module.exports={installFileActions,safeName};
