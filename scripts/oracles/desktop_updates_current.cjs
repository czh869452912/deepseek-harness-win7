'use strict';
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs/promises');
const {join,resolve}=require('node:path');
const {tmpdir}=require('node:os');
const Module=require('node:module');
const https=require('node:https');
const {EventEmitter}=require('node:events');
const {spawnSync}=require('node:child_process');
const root=resolve(__dirname,'../..');
const {Win7Updater,configuration,signedRelease,newer,installerHandoff}=require(join(root,'apps/desktop/updates.cjs'));
const oldLoad=Module._load;
Module._load=function(name,...rest){return name==='electron'?{app:{isPackaged:false}}:oldLoad.call(this,name,...rest);};
const {DesktopUpdateCoordinator}=require(join(root,'apps/desktop/update-coordinator.cjs'));
Module._load=oldLoad;
async function main(){
  assert.equal(process.versions.node,'16.17.1');
  const checks=[];
  const architecture=process.arch==='ia32'?'x86':process.arch;
  const keys=crypto.generateKeyPairSync('ed25519');
  const config={schemaVersion:1,channel:'win7-electron22',manifestUrl:'https://updates.example.invalid/win7.json',publicKey:keys.publicKey.export({format:'pem',type:'spki'})};
  const data=Buffer.from('owned fake installer bytes - never executed');
  const now=Date.now();
  const release={schemaVersion:1,channel:'win7-electron22',version:'0.1.5-rc.4',architecture,electron:'22.3.27',python:'3.8.10',
    publishedAt:now-1000,expiresAt:now+600000,artifact:{url:'https://updates.example.invalid/dsh-desktop-standard-setup-v0.1.5-rc.4-'+architecture+'.exe',bytes:data.length,sha256:crypto.createHash('sha256').update(data).digest('hex')}};
  const sign=value=>{const bytes=Buffer.from(JSON.stringify(value));return Buffer.from(JSON.stringify({payload:bytes.toString('base64'),signature:crypto.sign(null,bytes,keys.privateKey).toString('base64')}));};
  assert.deepEqual(signedRelease(sign(release),config,'0.1.5-rc.3'),release);checks.push('signed-compatible-release');
  const foreign=architecture==='x86'?'x64':'x86';
  assert.throws(()=>signedRelease(sign({...release,architecture:foreign,artifact:{...release.artifact,url:release.artifact.url.replace('-'+architecture+'.exe','-'+foreign+'.exe')}}),config,'0.1.5-rc.3'));
  checks.push('reject-other-windows-architecture');
  assert.equal(signedRelease(sign(release),config,'0.1.5-rc.4'),undefined);
  assert.equal(signedRelease(sign(release),config,'0.1.5'),undefined);
  assert.equal(newer('0.1.6-rc.0','0.1.5'),true);checks.push('monotonic-version');
  assert.equal(newer('0.1.5-rc.3-win7.1','0.1.5-rc.3'),true);
  assert.equal(newer('0.1.5-rc.3-win7.2','0.1.5-rc.3-win7.1'),true);
  assert.equal(newer('0.1.5-rc.3-win7.1','0.1.5-rc.3-win7.1'),false);
  assert.equal(newer('0.1.5-rc.3','0.1.5-rc.3-win7.1'),false);checks.push('monotonic-win7-revision');
  assert.equal(newer('0.1.5-rc.4','0.1.5-rc.3-win7.99'),true);
  assert.equal(newer('0.1.5','0.1.5-rc.3-win7.99'),true);
  assert.equal(newer('0.1.5-rc.3-win7.99','0.1.5'),false);checks.push('win7-revision-before-next-upstream');
  for(const value of ['0.1.5-rc.3-win7.0','0.1.5-rc.3-win7.01','0.1.5-rc.3-win7.9007199254740992','0.1.5-rc.3-win7.1-extra'])assert.throws(()=>newer(value,'0.1.5-rc.3'));
  checks.push('reject-invalid-win7-revision');
  const revision={...release,version:'0.1.5-rc.3-win7.1',artifact:{...release.artifact,url:'https://updates.example.invalid/dsh-desktop-standard-setup-v0.1.5-rc.3-win7.1-'+architecture+'.exe'}};
  assert.deepEqual(signedRelease(sign(revision),config,'0.1.5-rc.3'),revision);
  assert.equal(signedRelease(sign(revision),config,revision.version),undefined);checks.push('signed-win7-revision-release');
  for(const damage of ['schemaVersion','channel','architecture','electron','python','expired','future','window','extra','artifact-size','artifact-sha','artifact-http','artifact-name']){
    const value=JSON.parse(JSON.stringify(release));
    if(damage==='expired')value.expiresAt=now-1;
    else if(damage==='future')value.publishedAt=now+60000;
    else if(damage==='window')value.expiresAt=now+91*86400000;
    else if(damage==='extra')value.extra=true;
    else if(damage==='artifact-size')value.artifact.bytes=1024**3+1;
    else if(damage==='artifact-sha')value.artifact.sha256='0'.repeat(63);
    else if(damage==='artifact-http')value.artifact.url=value.artifact.url.replace('https:','http:');
    else if(damage==='artifact-name')value.artifact.url=value.artifact.url.replace('standard','aio');
    else value[damage]='foreign';
    assert.throws(()=>signedRelease(sign(value),config,'0.1.5-rc.3'));checks.push('reject-'+damage);
  }
  const tampered=JSON.parse(sign(release));tampered.payload=Buffer.from('{}').toString('base64');
  assert.throws(()=>signedRelease(Buffer.from(JSON.stringify(tampered)),config,'0.1.5-rc.3'));checks.push('reject-signature');
  assert.throws(()=>configuration({...config,manifestUrl:'https://user:password@example.invalid/feed'}));
  assert.throws(()=>configuration({...config,publicKey:crypto.generateKeyPairSync('rsa',{modulusLength:2048}).publicKey.export({format:'pem',type:'spki'})}));checks.push('reject-channel-configuration');
  for(const caCertificate of ['',null,'C:\\private-ca.pem','not a certificate','x'.repeat(8193)])assert.throws(()=>configuration({...config,caCertificate}));
  checks.push('reject-invalid-private-CA-configuration');
  const directory=await fs.mkdtemp(join(tmpdir(),'dsh-update-observer-'));
  try{
    let requests=0,launched;
    const fetch=async(address,limit,sink)=>{
      requests++;const bytes=address===config.manifestUrl?sign(release):data;
      assert.ok(bytes.length<=limit);
      for(let i=0;i<bytes.length;i+=7)await sink(bytes.subarray(i,i+7));return bytes.length;
    };
    const order=[];
    let child;
    const updater=new Win7Updater({config,currentVersion:'0.1.5-rc.3',installRoot:"C:\\owned app's root",temp:directory,fetch,
      launch:(binary,args,options)=>{launched={binary,args,options};order.push('handoff');child=new EventEmitter();child.unref=()=>{};queueMicrotask(()=>child.emit('spawn'));return child;},quit:()=>order.push('quit')});
    const states=[];
    const coordinator=new DesktopUpdateCoordinator(state=>{states.push(state);return state;},async()=>order.push('host-stopped'),updater,()=>true);
    const a=coordinator.check(),b=coordinator.check(),c=coordinator.install(),d=coordinator.install();
    assert.deepEqual(await a,{phase:'available',version:release.version});
    assert.deepEqual(await b,{phase:'available',version:release.version});
    assert.deepEqual(await c,{phase:'ready',version:release.version});
    assert.deepEqual(await d,{phase:'ready',version:release.version});
    assert.deepEqual(states.map(state=>state.phase),['checking','available','installing','ready']);
    assert.deepEqual(order,['host-stopped','handoff','quit']);assert.equal(requests,2);
    assert.deepEqual(await fs.readFile(updater.download.file),data);
    assert.equal(launched.options.windowsHide,true);assert.equal(launched.options.detached,true);assert.equal(launched.options.stdio,'ignore');
    const command=Buffer.from(launched.args.at(-1),'base64').toString('utf16le');
    assert.ok(command.includes('WaitForExit(120000)')&&command.includes('-Verb RunAs -Wait')&&command.includes(release.artifact.sha256));
    assert.ok(command.includes("owned app''s root")&&command.includes('Installed restart target differs')&&command.includes('$setup.ExitCode -ne 0'));
    const parse=spawnSync(launched.binary,['-NoProfile','-NonInteractive','-Command',"$tokens=$null;$errors=$null;[void][Management.Automation.Language.Parser]::ParseInput([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('"+launched.args.at(-1)+"')),[ref]$tokens,[ref]$errors);if($errors.Count){$errors|Out-String|Write-Error;exit 1}"],{encoding:'utf8'});
    assert.equal(parse.status,0,parse.stderr);
    assert.equal(command.includes('/S'),false);checks.push('coordinator-dedupe-download-host-stop-handoff');
    await fs.unlink(updater.download.file);await fs.rmdir(require('node:path').dirname(updater.download.file));
    const bad=new Win7Updater({config,currentVersion:'0.1.5-rc.3',temp:directory,fetch:async(address,limit,sink)=>{
      if(address===config.manifestUrl){const bytes=sign(release);await sink(bytes);return bytes.length;}
      await sink(Buffer.from('corrupt'));return 7;
    }});
    await bad.checkForUpdates();await assert.rejects(bad.downloadUpdate(),/bytes differ/);
    assert.deepEqual(await fs.readdir(directory),[]);checks.push('download-corruption-cleans-owned-output');
    const idle=new DesktopUpdateCoordinator(state=>state,async()=>assert.fail('disabled host stop'),new Win7Updater({currentVersion:'0.1.5-rc.3'}),()=>false);
    assert.deepEqual(await idle.check(),{phase:'idle'});await assert.rejects(idle.install(),/no verified update/);checks.push('unconfigured-idle');
    const failed=new DesktopUpdateCoordinator(state=>state,async()=>{},new Win7Updater({config,currentVersion:'0.1.5-rc.3',fetch:async()=>{throw new Error('actual fixture offline');}}),()=>true);
    assert.deepEqual(await failed.check(),{phase:'error',message:'actual fixture offline'});checks.push('check-error-state');
    const escaped=installerHandoff("C:\\fixture's path\\setup.exe",'0'.repeat(64),123,"C:\\fixture's path\\log.txt");
    assert.ok(Buffer.from(escaped.args.at(-1),'base64').toString('utf16le').includes("fixture''s path"));checks.push('literal-path-quoting');
    const failedSpawn=new Win7Updater({config,currentVersion:'0.1.5-rc.3',temp:directory,fetch,
      launch:()=>{const emitter=new EventEmitter();queueMicrotask(()=>emitter.emit('error',new Error('fixture spawn refused')));return emitter;},
      quit:()=>assert.fail('must retain application after failed helper spawn'),onError:error=>order.push(error.message)});
    await failedSpawn.checkForUpdates();await failedSpawn.downloadUpdate();failedSpawn.quitAndInstall();
    await new Promise(resolve=>setImmediate(resolve));assert.ok(order.includes('fixture spawn refused'));
    // Await the actual diagnostic write before cleaning this owned fixture.
    for(let i=0;i<100;i++){try{if((await fs.readFile(failedSpawn.download.log,'utf8')).includes('fixture spawn refused'))break;}catch(error){if(error.code!=='ENOENT')throw error;}await new Promise(resolve=>setTimeout(resolve,10));}
    assert.match(await fs.readFile(failedSpawn.download.log,'utf8'),/fixture spawn refused/);
    await fs.unlink(failedSpawn.download.file);await fs.unlink(failedSpawn.download.log);await fs.rmdir(require('node:path').dirname(failedSpawn.download.file));checks.push('helper-spawn-error-retains-app-and-diagnostic');
    let mode='good',base;
    const fixture=join(root,'tests/fixtures/tls');
    const server=https.createServer({key:await fs.readFile(join(fixture,'localhost-key.pem')),cert:await fs.readFile(join(fixture,'localhost-cert.pem'))},(request,response)=>{
      if(request.url==='/redirect'){response.writeHead(302,{location:base+'/feed'});response.end();return;}
      if(request.url==='/feed'){
        if(mode==='http'){response.writeHead(302,{location:'http://127.0.0.1/feed'});response.end();return;}
        if(mode==='loop'){response.writeHead(302,{location:base+'/feed'});response.end();return;}
        if(mode==='status'){response.writeHead(503);response.end('unavailable');return;}
        if(mode==='encoded'){response.writeHead(200,{'content-encoding':'gzip'});response.end('not a gzip');return;}
        if(mode==='oversize'){response.end(Buffer.alloc(65537));return;}
        response.end(sign({...release,artifact:{...release.artifact,url:base+'/'+release.artifact.url.split('/').pop()}}));return;
      }
      response.end(mode==='corrupt'?Buffer.from('corrupt'):mode==='artifact-oversize'?Buffer.alloc(data.length+1):data);
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));base='https://127.0.0.1:'+server.address().port;
    const originalCA=https.globalAgent.options.ca;
    try{
      const network=new Win7Updater({config:{...config,manifestUrl:base+'/redirect'},currentVersion:'0.1.5-rc.3',temp:directory});
      await assert.rejects(network.checkForUpdates(),/self signed certificate/);checks.push('https-reject-untrusted-certificate');
      const caCertificate=await fs.readFile(join(fixture,'localhost-cert.pem'),'utf8');
      const intranet=new Win7Updater({config:{...config,manifestUrl:base+'/redirect',caCertificate},currentVersion:'0.1.5-rc.3',temp:directory});
      assert.equal((await intranet.checkForUpdates()).isUpdateAvailable,true);await intranet.downloadUpdate();
      assert.deepEqual(await fs.readFile(intranet.download.file),data);
      await fs.unlink(intranet.download.file);await fs.rmdir(require('node:path').dirname(intranet.download.file));checks.push('actual-explicit-private-CA-through-HTTPS-redirect');
      https.globalAgent.options.ca=await fs.readFile(join(fixture,'localhost-cert.pem'));
      assert.equal((await network.checkForUpdates()).isUpdateAvailable,true);await network.downloadUpdate();
      assert.deepEqual(await fs.readFile(network.download.file),data);
      await fs.unlink(network.download.file);await fs.rmdir(require('node:path').dirname(network.download.file));checks.push('actual-verified-https-redirect-and-download');
      for(const rejected of ['http','loop','status','encoded','oversize']){mode=rejected;await assert.rejects(network.checkForUpdates());checks.push('https-reject-'+rejected);}
      for(const rejected of ['corrupt','artifact-oversize']){mode=rejected;await network.checkForUpdates();await assert.rejects(network.downloadUpdate());assert.deepEqual(await fs.readdir(directory),[]);checks.push('https-reject-'+rejected);}
    }finally{https.globalAgent.options.ca=originalCA;await new Promise(resolve=>server.close(resolve));}
    const keyPath=join(directory,'fixture-private.pem'),installer=join(directory,release.artifact.url.split('/').pop()),output=join(directory,'fixture-signed.json');
    await fs.writeFile(keyPath,keys.privateKey.export({format:'pem',type:'pkcs8'}),{flag:'wx'});await fs.writeFile(installer,data,{flag:'wx'});
    try{
      const args=[join(root,'scripts/sign_desktop_update.cjs'),'--architecture',architecture,'--installer',installer,'--version',release.version,
        '--artifact-url',release.artifact.url,'--manifest-url',config.manifestUrl,'--private-key',keyPath,'--output',output];
      const signed=spawnSync(process.execPath,args,{encoding:'utf8',env:{...process.env,ELECTRON_RUN_AS_NODE:'1'}});
      assert.equal(signed.status,0,signed.stderr);
      assert.equal(signedRelease(await fs.readFile(output),config,'0.1.5-rc.3').artifact.sha256,release.artifact.sha256);checks.push('actual-release-signing-command');
      const previous=await fs.readFile(output),duplicate=spawnSync(process.execPath,args,{encoding:'utf8',env:{...process.env,ELECTRON_RUN_AS_NODE:'1'}});
      assert.equal(duplicate.status,1);assert.match(duplicate.stderr,/EEXIST/);assert.deepEqual(await fs.readFile(output),previous);checks.push('release-signing-refuses-overwrite');
    }finally{await fs.unlink(keyPath);await fs.unlink(installer);await fs.unlink(output).catch(error=>{if(error.code!=='ENOENT')throw error;});}
  }finally{await fs.rmdir(directory);}
  process.stdout.write(JSON.stringify({status:'qualified',versions:process.versions,checks,installationExecuted:false})+'\n');
}
main().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
