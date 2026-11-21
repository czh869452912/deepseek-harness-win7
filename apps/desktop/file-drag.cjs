'use strict';

const {nativeImage}=require('electron');
const {randomUUID}=require('node:crypto');
const {mkdir, writeFile, unlink, rmdir}=require('node:fs/promises');
const {join}=require('node:path');
const {safeName}=require('./file-actions.cjs');

function installFileDrag(appHandler, getWindow, directory) {
  const requests=new Map(), handles=new Map();
  const icon=nativeImage.createFromPath(join(__dirname,'tray.png'));
  async function release(handle) {
    const row=handles.get(handle);
    if (!row) return;
    handles.delete(handle);
    clearTimeout(row.timer);
    await unlink(row.path);
    await rmdir(row.directory);
  }
  function attach(contents) {
    const reset=()=>{
      for (const row of requests.values()) if (row.contents===contents) row.cancelled=true;
      for (const [handle,row] of handles) if (row.contents===contents) {
        // Explorer can still be completing a native drop after the renderer closes.
        if (!row.started) void release(handle).catch(console.error);
      }
    };
    contents.on('did-start-navigation',(_event,_url,inPlace,isMainFrame)=>{if (isMainFrame&&!inPlace) reset();});
    contents.once('destroyed',reset);
  }
  appHandler('dsh-desktop:drag-prepare',async (source,requestId)=>{
    if (!source || typeof requestId!=='string' || !requestId || requestId.length>128 || requests.has(requestId)) {
      throw new Error('Invalid drag preparation');
    }
    // Serialized browser bytes already passed the resource owner's read path.
    if (source.kind==='resource') return undefined;
    if (source.kind!=='bytes' || !(source.bytes instanceof Uint8Array) || source.bytes.byteLength>128*1024*1024) {
      throw new Error('Invalid drag bytes');
    }
    const handle=randomUUID();
    const folder=join(directory,handle);
    const path=join(folder,safeName(source.name));
    const row={contents:getWindow().webContents,directory:folder,path,cancelled:false,started:false};
    requests.set(requestId,row);
    try {
      await mkdir(folder,{recursive:true});
      handles.set(handle,row);
      await writeFile(path,source.bytes,{flag:'wx'});
      if (row.cancelled) {await release(handle);return undefined;}
      row.timer=setTimeout(()=>void release(handle).catch(console.error),5*60*1000);
      row.timer.unref();
      return handle;
    } catch (error) {
      handles.delete(handle);
      await unlink(path).catch(failure=>{if (failure.code!=='ENOENT') throw failure;});
      await rmdir(folder).catch(failure=>{if (failure.code!=='ENOENT') throw failure;});
      throw error;
    } finally {
      requests.delete(requestId);
    }
  });
  appHandler('dsh-desktop:drag-cancel',requestId=>{
    const row=requests.get(requestId);
    if (row?.contents===getWindow().webContents) row.cancelled=true;
  });
  appHandler('dsh-desktop:drag-start',handle=>{
    const row=handles.get(handle);
    if (!row || row.started || row.contents!==getWindow().webContents) return false;
    row.contents.startDrag({file:row.path,icon});
    row.started=true;
    return true;
  });
  appHandler('dsh-desktop:drag-release',handle=>{
    const row=handles.get(handle);
    if (row?.contents===getWindow().webContents && !row.started) return release(handle);
  });
  return {attach,dispose:()=>Promise.all([...handles.keys()].map(release))};
}

module.exports={installFileDrag};
