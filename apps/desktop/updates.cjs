'use strict';
const https=require('node:https');
const {createHash,createPublicKey,verify,X509Certificate}=require('node:crypto');
const {createSecureContext}=require('node:tls');
const {mkdtemp,open,unlink,rmdir,readFile,writeFile}=require('node:fs/promises');
const {join}=require('node:path');
const {spawn}=require('node:child_process');
const {tmpdir}=require('node:os');

function exact(value,keys){return value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join('\0')===[...keys].sort().join('\0');}
function url(value){
  const parsed=new URL(value);
  if(typeof value!=='string'||parsed.protocol!=='https:'||parsed.username||parsed.password||parsed.hash)throw new Error('Win7 updates require an HTTPS URL without credentials or fragment');
  return parsed;
}
function version(value){
  const match=typeof value==='string'&&/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-rc\.(0|[1-9]\d*)(?:-r([1-9]\d*))?)?$/.exec(value);
  if(!match||match.slice(1).some(part=>part!==undefined&&!Number.isSafeInteger(Number(part))))throw new Error('Invalid Win7 release version');
  return match.slice(1,4).map(Number).concat(match[4]===undefined?Infinity:Number(match[4]),match[5]===undefined?0:Number(match[5]));
}
function newer(left,right){const a=version(left),b=version(right);for(let i=0;i<a.length;i++){if(a[i]!==b[i])return a[i]>b[i];}return false;}
function configuration(value){
  const customCA=value&&Object.prototype.hasOwnProperty.call(value,'caCertificate');
  if(!exact(value,['schemaVersion','channel','manifestUrl','publicKey',...(customCA?['caCertificate']:[])])||value.schemaVersion!==1||value.channel!=='win7-electron22')throw new Error('Invalid Win7 updater configuration');
  url(value.manifestUrl);
  const key=createPublicKey(value.publicKey);
  if(key.asymmetricKeyType!=='ed25519')throw new Error('Win7 updater requires an Ed25519 public key');
  if(customCA){
    const pem=value.caCertificate;
    if(typeof pem!=='string'||Buffer.byteLength(pem)>8192)throw new Error('Invalid Win7 updater CA certificate');
    const certificates=pem.match(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g);
    if(!certificates?.length||certificates.join('').replace(/\s/g,'')!==pem.replace(/\s/g,''))throw new Error('Invalid Win7 updater CA certificate');
    for(const certificate of certificates)new X509Certificate(certificate);
    createSecureContext({ca:pem});
  }
  return value;
}
function runtimeArchitecture(){return process.arch==='ia32'?'x86':process.arch;}
function signedRelease(bytes,config,current,now=Date.now(),architecture=runtimeArchitecture()){
  if(!['x86','x64'].includes(architecture))throw new Error('Unsupported Win7 update architecture');
  configuration(config);version(current);
  const envelope=JSON.parse(bytes.toString('utf8'));
  if(!exact(envelope,['payload','signature'])||typeof envelope.payload!=='string'||typeof envelope.signature!=='string')throw new Error('Invalid signed update envelope');
  const payload=Buffer.from(envelope.payload,'base64'),signature=Buffer.from(envelope.signature,'base64');
  if(payload.toString('base64')!==envelope.payload||signature.toString('base64')!==envelope.signature||signature.length!==64||!verify(null,payload,config.publicKey,signature))throw new Error('Win7 release signature differs');
  const release=JSON.parse(payload.toString('utf8'));
  if(!exact(release,['schemaVersion','channel','version','architecture','electron','python','publishedAt','expiresAt','artifact'])
    ||release.schemaVersion!==1||release.channel!=='win7-electron22'||release.architecture!==architecture
    ||release.electron!=='22.3.27'||release.python!=='3.8.10'
    ||!Number.isSafeInteger(release.publishedAt)||!Number.isSafeInteger(release.expiresAt)
    ||release.publishedAt>now||release.expiresAt<=now||release.expiresAt-release.publishedAt>90*86400000)throw new Error('Win7 release identity or validity window differs');
  version(release.version);
  const artifact=release.artifact;
  if(!exact(artifact,['url','bytes','sha256'])||!Number.isSafeInteger(artifact.bytes)||artifact.bytes<=0||artifact.bytes>1024*1024*1024
    ||typeof artifact.sha256!=='string'||!/^[a-f0-9]{64}$/.test(artifact.sha256))throw new Error('Invalid Win7 installer identity');
  if(decodeURIComponent(url(artifact.url).pathname.split('/').pop())!=='dsh-desktop-standard-setup-v'+release.version+'-'+architecture+'.exe')throw new Error('Win7 installer filename differs');
  return newer(release.version,current)?release:undefined;
}
function response(address,redirects=0,ca){
  url(address);
  return new Promise((resolve,reject)=>{
    const request=https.get(address,{...(ca?{ca}:{}),headers:{'user-agent':'DeepSeek-Harness-Win7-Updater','accept-encoding':'identity'}},incoming=>{
      if([301,302,303,307,308].includes(incoming.statusCode)){
        incoming.resume();if(redirects>=5||!incoming.headers.location)return reject(new Error('Update redirect limit or destination missing'));
        let next;try{next=url(new URL(incoming.headers.location,address).href).href;}catch(error){reject(error);return;}
        resolve(response(next,redirects+1,ca));return;
      }
      if(incoming.statusCode!==200||incoming.headers['content-encoding']&&incoming.headers['content-encoding']!=='identity'){
        incoming.resume();reject(new Error('Update HTTP response differs'));return;
      }
      resolve(incoming);
    });
    request.setTimeout(30000,()=>request.destroy(new Error('Update HTTP idle deadline')));
    request.on('error',reject);
  });
}
async function transfer(address,limit,sink,ca){
  const incoming=await response(address,0,ca);let total=0;
  const timer=setTimeout(()=>incoming.destroy(new Error('Update transfer deadline')),600000);
  try{
    for await(const chunk of incoming){total+=chunk.length;if(total>limit)throw new Error('Update response exceeds its byte limit');await sink(chunk);}
    return total;
  }finally{clearTimeout(timer);incoming.destroy();}
}
const psLiteral=value=>"'"+value.replaceAll("'","''")+"'";
function installerHandoff(installer,sha256,parentPid,log,installRoot,releaseVersion){
  // A background helper waits for this exact live process handle to exit before
  // UAC/setup's running-file check. It never kills a process or runs silently.
  const restart=installRoot?"$shortcut=Join-Path ([Environment]::GetFolderPath('CommonStartMenu')) 'Programs\\DeepSeek Harness\\DeepSeek Harness.lnk';$shell=New-Object -ComObject WScript.Shell;$target=$shell.CreateShortcut($shortcut).TargetPath;"+
    '$prefix='+psLiteral(join(installRoot,'versions',releaseVersion+'-'))+";if(-not $target.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($target) -ne 'DeepSeek Harness.exe'){throw 'Installed restart target differs'};Start-Process -FilePath $target;":"";
  const script="$ErrorActionPreference='Stop';try { $parent=Get-Process -Id "+parentPid+" -ErrorAction SilentlyContinue;if($null -ne $parent){if(-not $parent.WaitForExit(120000)){throw 'Desktop did not exit before update'}};"+
    '$file='+psLiteral(installer)+';$stream=[System.IO.File]::OpenRead($file);try {$hash=[System.Security.Cryptography.SHA256]::Create();$actual=[System.BitConverter]::ToString($hash.ComputeHash($stream)).Replace(\'-\',\'\').ToLowerInvariant()}finally{$stream.Dispose()};'+
    'if($actual -ne '+psLiteral(sha256)+"){throw 'Downloaded installer changed before launch'};$setup=Start-Process -FilePath $file -Verb RunAs -Wait -PassThru;if($setup.ExitCode -eq 3010){exit 0};if($setup.ExitCode -ne 0){throw ('Installer exit code: '+$setup.ExitCode)};"+restart+"Remove-Item -LiteralPath $file -Force }catch { $_ | Out-File -LiteralPath "+psLiteral(log)+" -Encoding UTF8;exit 1 }";
  const binary=join(process.env.SystemRoot||'C:\\Windows','System32','WindowsPowerShell','v1.0','powershell.exe');
  return {binary,args:['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand',Buffer.from(script,'utf16le').toString('base64')]};
}
class Win7Updater {
  constructor({config,currentVersion,installRoot,temp=tmpdir(),fetch,launch=spawn,quit=()=>{},onError=()=>{}}){
    this.config=config&&configuration(config);this.currentVersion=currentVersion;this.temp=temp;
    this.fetch=fetch||((address,limit,sink)=>transfer(address,limit,sink,this.config?.caCertificate));this.launch=launch;this.quit=quit;this.release=undefined;this.download=undefined;
    this.autoDownload=false;this.autoInstallOnAppQuit=false;
    this.installRoot=installRoot;this.onError=onError;
  }
  async checkForUpdates(){
    this.release=undefined;
    if(!this.config)return {isUpdateAvailable:false};
    const chunks=[];await this.fetch(this.config.manifestUrl,65536,chunk=>chunks.push(chunk));
    this.release=signedRelease(Buffer.concat(chunks),this.config,this.currentVersion);
    return this.release?{isUpdateAvailable:true,updateInfo:{version:this.release.version}}:{isUpdateAvailable:false};
  }
  async downloadUpdate(){
    const release=this.release;if(!release)throw new Error('No verified Win7 release available');
    if(release.expiresAt<=Date.now())throw new Error('Verified Win7 release expired before download');
    const directory=await mkdtemp(join(this.temp,'dsh-win7-update-'));
    const file=join(directory,'dsh-desktop-standard-setup-v'+release.version+'-'+release.architecture+'.exe');
    let stream;
    try{
      stream=await open(file,'wx');const hash=createHash('sha256');
      const bytes=await this.fetch(release.artifact.url,release.artifact.bytes,async chunk=>{
        hash.update(chunk);let offset=0;
        while(offset<chunk.length){const written=await stream.write(chunk,offset,chunk.length-offset);if(!written.bytesWritten)throw new Error('Update write made no progress');offset+=written.bytesWritten;}
      });
      if(bytes!==release.artifact.bytes||hash.digest('hex')!==release.artifact.sha256)throw new Error('Downloaded Win7 installer bytes differ');
      await stream.sync();await stream.close();stream=undefined;
      this.download={file,sha256:release.artifact.sha256,log:join(directory,'install.log')};return [file];
    }catch(error){
      if(stream)await stream.close();await unlink(file).catch(failure=>{if(failure.code!=='ENOENT')throw failure;});await rmdir(directory);throw error;
    }
  }
  quitAndInstall(){
    if(!this.download)throw new Error('No verified Win7 installer downloaded');
    if(!this.release||this.release.expiresAt<=Date.now())throw new Error('Verified Win7 release expired before handoff');
    const command=installerHandoff(this.download.file,this.download.sha256,process.pid,this.download.log,this.installRoot,this.release.version);
    const child=this.launch(command.binary,command.args,{detached:true,stdio:'ignore',windowsHide:true});
    child.once('error',error=>{
      void writeFile(this.download.log,String(error.stack||error),{encoding:'utf8'}).catch(()=>{});
      this.onError(error);
    });
    child.once('spawn',()=>{child.unref();this.quit();});
  }
}
async function loadConfiguration(path){
  try {const data=await readFile(path);if(data.length>16384)throw new Error('Update configuration exceeds its byte limit');return configuration(JSON.parse(data.toString('utf8')));}
  catch(error){if(error.code==='ENOENT')return undefined;throw error;}
}
module.exports={Win7Updater,configuration,signedRelease,newer,installerHandoff,loadConfiguration};
