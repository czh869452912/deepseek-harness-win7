'use strict';
// Electron 22 / Node16 adapter: no Fetch globals or Node lifecycle IPC ABI.
const {spawn,execFile}=require('node:child_process');
const {join}=require('node:path');
const {PassThrough}=require('node:stream');
const {createInterface}=require('node:readline');
const wire=require('./wire.cjs');

class DesktopHostProcess{
  constructor({python,root,profile,home}){
    this.options={python,root,profile,home};this.pending=new Map();this.next=1;
    this.decoder=new wire.DesktopHostResponseDecoder();this.writes=Promise.resolve();this.closing=false;
  }
  start(){
    if(this.ready)return this.ready;
    this.ready=new Promise((resolve,reject)=>{
      const {python,root,profile,home}=this.options;
      const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>
        key!=='NODE_OPTIONS'&&!/^DSH_DESKTOP_/i.test(key)&&!/^(?:npm|pnpm|corepack)_/i.test(key)));
      env.DSH_CLIENT_VERSION=require('./package.json').version;
      const child=this.child=spawn(python,['-m','dsh.host.desktop.process','--profile-dir',profile,'--home',home],
        {cwd:root,env,windowsHide:true,stdio:['pipe','pipe','pipe']});
      const timer=setTimeout(()=>{reject(new Error('Desktop Host readiness timed out'));this.terminate();},60000);
      this.exit=new Promise(done=>child.once('exit',(code)=>{
        clearTimeout(timer);const error=new Error('Desktop Host exited '+code);
        reject(error);this.fail(error);done(code);
      }));
      child.once('error',error=>{clearTimeout(timer);reject(error);this.fail(error);});
      child.stdin.on('error',error=>this.fail(error));child.stdout.on('error',error=>this.fail(error));
      child.stdout.on('data',chunk=>{
        try{for(const frame of this.decoder.push(chunk))this.accept(frame);}
        catch(error){reject(error);this.fail(error);child.stdin.end();}
      });
      child.stdout.once('end',()=>{try{this.decoder.finish();}catch(error){this.fail(error);}});
      const lines=createInterface({input:child.stderr});this.logs=[];
      lines.on('line',line=>{
        if(line.startsWith('DSH_DESKTOP_CONTROL ')){
          try{
            const event=JSON.parse(line.slice('DSH_DESKTOP_CONTROL '.length));
            if(event.type==='ready'&&event.protocolVersion===3){clearTimeout(timer);resolve(event);}
            else if(event.type==='fatal'){clearTimeout(timer);const error=new Error(event.message);reject(error);this.fail(error);}
            else throw new Error('Invalid desktop lifecycle event');
          }catch(error){reject(error);this.fail(error);}
        }else{this.logs.push(line);if(this.logs.length>500)this.logs.shift();}
      });
    });
    return this.ready;
  }
  fail(error){
    for(const item of this.pending.values()){
      clearTimeout(item.timer);item.reject(error);item.body?.destroy(error);item.cleanup();
    }
    this.pending.clear();
  }
  enqueue(frame){
    const write=this.writes.then(async()=>{
      if(!this.child||this.child.stdin.destroyed)throw new Error('Desktop request pipe is closed');
      const stream=this.child.stdin;
      await new Promise((resolve,reject)=>{
        const closed=()=>{stream.removeListener('close',closed);reject(new Error('Desktop request pipe closed while writing'));};
        stream.once('close',closed);
        stream.write(frame,error=>{stream.removeListener('close',closed);if(error)reject(error);else resolve();});
      });
    });
    this.writes=write.catch(()=>{});return write;
  }
  accept(frame){
    const item=this.pending.get(frame.streamId);if(!item)return;
    if(frame.type==='start'){
      if(item.started)throw new Error('Duplicate desktop response start');
      item.started=true;clearTimeout(item.timer);
      item.body=new PassThrough({highWaterMark:65536});
      item.body.on('error',()=>{});
      item.body.once('close',()=>{if(!item.ended)this.cancel(frame.streamId,new Error('Desktop response consumer closed'));});
      item.resolve({status:frame.status,headers:frame.headers,body:item.body,hasBody:frame.hasBody});
    }else if(frame.type==='data'){
      if(!item.started)throw new Error('Desktop data before start');
      if(!item.body.write(frame.data)){
        this.child.stdout.pause();
        item.body.once('drain',()=>this.child?.stdout.resume());
      }
    }else{
      item.ended=true;clearTimeout(item.timer);item.cleanup();this.pending.delete(frame.streamId);
      if(frame.type==='error'){
        const error=new Error(frame.message);item.reject(error);item.body?.destroy(error);
      }else if(!item.started)throw new Error('Desktop end before start');
      else item.body.end();
    }
  }
  cancel(identity,error){
    const item=this.pending.get(identity);if(!item)return;
    item.ended=true;clearTimeout(item.timer);item.cleanup();this.pending.delete(identity);
    item.reject(error);item.body?.destroy(error);
    this.child?.stdout.resume();this.enqueue(wire.encodeDesktopRequestCancel(identity)).catch(()=>{});
  }
  async fetch({url,method='GET',headers=[],body=null,signal}){
    await this.start();
    if(this.closing)throw new Error('Desktop Host is stopping');
    if(signal?.aborted)throw signal.reason??new Error('Aborted');
    if(this.next>0xffffffff)throw new Error('Desktop request ids exhausted');
    const identity=this.next++,hasBody=body!==null;
    const response=new Promise((resolve,reject)=>{
      const abort=()=>this.cancel(identity,signal.reason??new Error('Desktop request aborted'));
      const item={resolve,reject,started:false,ended:false,cleanup:()=>signal?.removeEventListener('abort',abort)};
      item.timer=setTimeout(()=>this.cancel(identity,new Error('Desktop response start timed out')),60000);
      this.pending.set(identity,item);signal?.addEventListener('abort',abort,{once:true});
    });
    const upload=async()=>{
      await this.enqueue(wire.encodeDesktopRequestStart(identity,{url,method,headers,hasBody}));
      if(hasBody){
        const chunks=Buffer.isBuffer(body)||typeof body==='string'?[Buffer.from(body)]:body;
        for await(const data of chunks){
          if(!this.pending.has(identity))return;
          const bytes=Buffer.from(data);
          for(let offset=0;offset<bytes.length;offset+=65536)await this.enqueue(wire.encodeDesktopRequestData(identity,bytes.subarray(offset,offset+65536)));
        }
      }
      await this.enqueue(wire.encodeDesktopRequestEnd(identity));
    };
    upload().catch(error=>this.cancel(identity,error));
    return response;
  }
  async stop(){
    if(this.closing)return this.exit;
    this.closing=true;
    if(!this.child)return;
    this.fail(new Error('Desktop Host stopped'));
    const timer=setTimeout(()=>this.terminate(),15000);
    try{
      this.child.stdout.resume();await this.writes;this.child.stdin.end();
      return await this.exit;
    }finally{clearTimeout(timer);}
  }
  terminate(){
    terminateOwnedProcess(this.child);
  }
}
function terminateOwnedProcess(child){
  if(!child||child.exitCode!==null||!child.pid)return;
  // Windows venv redirectors own the actual Python process and its lease.
  if(process.platform==='win32')execFile(join(process.env.SystemRoot||'C:\\Windows','System32','taskkill.exe'),
    ['/PID',String(child.pid),'/T','/F'],{windowsHide:true},()=>{});
  else child.kill('SIGKILL');
}
module.exports={DesktopHostProcess,terminateOwnedProcess};
