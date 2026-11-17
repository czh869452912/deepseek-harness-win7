/** Private POSIX memory-volume adapters for the unchanged SDK worker bodies. */
import {Buffer} from 'buffer';
import {sha256} from '@noble/hashes/sha256';

let files = new Map(), directories = new Map(), descriptors = new Map(), nextFd = 1;
let allowedAssets = new Set(), messages = [];
let host={platform:'linux',home:'/profile',env:{}};
export function hostEnvironment(value) {host=value;globalThis.process={platform:host.platform,env:host.env};}
function physical(path) {return files.has(path)||directories.has(path)?path:'/physical/'+path;}
export let workerData;
export const parentPort = {postMessage(value) { messages.push(value); }};
export function request(data) {workerData = data; messages = [];}
export function received() {return messages;}
export function volume(manifest, assets) {
  files = new Map(Object.entries(manifest.files));
  directories = new Map(Object.entries(manifest.directories));
  descriptors = new Map(); nextFd = 1; allowedAssets = new Set(assets);
}
function absent(path) {const error = Error('Missing memory-volume entry: ' + path);error.code = 'ENOENT';return error;}
function fetchBytes(route) {
  const xhr = new XMLHttpRequest();xhr.open('GET', route, false);xhr.responseType = 'arraybuffer';xhr.send();
  if (xhr.status !== 200) throw Error('Office asset read failed (' + xhr.status + ').');
  return Buffer.from(xhr.response);
}
function bytes(file) {return file.bytes ??= fetchBytes(file.route);}
function status(file, directory = false, bigint = false) {
  const identity = file.identity || {dev:'0',ino:'0',size:0,mtimeNs:'0',ctimeNs:'0'};
  const number=bigint?BigInt:Number;
  return {...identity,dev:number(identity.dev),ino:number(identity.ino),size:number(identity.size),
    mtimeNs:BigInt(identity.mtimeNs),ctimeNs:BigInt(identity.ctimeNs),
    mtimeMs:Number(identity.mtimeNs)/1e6,ctimeMs:Number(identity.ctimeNs)/1e6,
    isDirectory:()=>directory,isFile:()=>!directory};
}
export const constants = {O_RDONLY:0,O_NONBLOCK:0,O_NOFOLLOW:0};
export function openSync(path,flags) {
  if(flags==='wx'){
    if(files.has(path))throw Error('Memory file already exists.');
    files.set(path,{bytes:Buffer.alloc(0),identity:{dev:'0',ino:'0',size:0,mtimeNs:'0',ctimeNs:'0'},output:true});
  }
  const file=files.get(physical(path));if(!file)throw absent(path);
  const fd=nextFd++;descriptors.set(fd,{...file,...flags==='wx'?{target:path}:{}});return fd;
}
export function closeSync(fd) {descriptors.delete(fd);}
export function fstatSync(fd,options) {const file=descriptors.get(fd);if(!file)throw Error('Closed memory-volume descriptor.');return status(file,false,options?.bigint===true);}
export function readSync(fd, target, offset, length, position) {
  const file=descriptors.get(fd);if(!file)throw Error('Closed memory-volume descriptor.');
  const data=bytes(file).subarray(position,position+length);target.set(data,offset);return data.length;
}
export function readFileSync(path, encoding) {
  const file=files.get(path), data=file?bytes(file):allowedAssets.has(path)?fetchBytes(path):null;
  if(!data)throw absent(path);return encoding?data.toString(encoding):data;
}
export function statSync(path) {path=physical(path);if(directories.has(path))return status({},true);const file=files.get(path);if(!file)throw absent(path);return status(file);}
export function realpathSync(path) {statSync(path);return physical(path);}
export function readdirSync(path,options) {
  const entries=directories.get(physical(path));if(!entries)throw absent(path);
  return entries.map(entry=>options?.withFileTypes?{name:entry.name,isDirectory:()=>entry.kind==='directory',isFile:()=>entry.kind==='file'}:typeof entry==='string'?entry:entry.name);
}
export function mkdirSync(path,options) {if(directories.has(path)){if(options?.recursive)return;throw Error('Memory directory already exists.');}directories.set(path,[]);}
export function writeFileSync(path, value, options) {
  if(typeof path==='number'){
    const descriptor=descriptors.get(path);if(!descriptor?.target)throw Error('Descriptor is not writable.');
    return writeFileSync(descriptor.target,value,options);
  }
  if(options?.flag==='wx'&&files.has(path))throw Error('Memory file already exists.');
  const data=Buffer.from(value);files.set(path,{bytes:data,identity:{dev:'0',ino:'0',size:data.length,mtimeNs:'0',ctimeNs:'0'},output:true});
}
export function unlinkSync(path) {if(!files.delete(path))throw absent(path);}
export function renameSync(source,target) {const file=files.get(source);if(!file)throw absent(source);files.set(target,file);files.delete(source);}
export function outputs() {return Object.fromEntries([...files].filter(([,file])=>file.output).map(([path,file])=>[path,file.bytes]));}
export function resources() {return {openDescriptors:descriptors.size,retainedReadBuffers:[...files.values()].filter(file=>!file.output&&file.bytes).length};}
export function basename(path) {return path.slice(path.lastIndexOf('/')+1);}
export function extname(path) {const name=basename(path),dot=name.lastIndexOf('.');return dot<=0?'':name.slice(dot);}
export function isAbsolute(path) {return path.startsWith('/')||(host.platform==='win32'&&/^[A-Za-z]:[\\/]|^\\\\/.test(path));}
export function join(...parts) {
  if(host.platform==='win32'&&(/^[A-Za-z]:[\\/]|^\\\\/.test(parts[0]||'')||parts[0]?.startsWith('/physical/'))){
    const text=parts.filter(Boolean).join('\\').replaceAll('/','\\');
    return (text.startsWith('\\\\')?'\\':'')+text.replace(/\\+/g,'\\').replace(/^\\physical\\/,'/physical/');
  }
  const text=parts.filter(Boolean).join('/'),absolute=text.startsWith('/'),stack=[];
  for(const part of text.split('/')){
    if(!part||part==='.')continue;
    if(part==='..'&&stack.length&&stack[stack.length-1]!=='..')stack.pop();
    else if(part!=='..'||!absolute)stack.push(part);
  }
  return (absolute?'/':'')+stack.join('/') || '.';
}
export const posix={join,isAbsolute,basename,extname};
export const win32={join(...parts){return join(...parts);}};
export function homedir() {return host.home;}
export function createHash(algorithm) {
  if(algorithm!=='sha256')throw Error('Unsupported Office digest.');const hash=sha256.create();
  return {update(value){hash.update(typeof value==='string'?new TextEncoder().encode(value):value);return this;},
    digest(encoding){const data=Buffer.from(hash.digest());return encoding?data.toString(encoding):data;}};
}
export function createRequire() {
  return loader=>{
    if(!allowedAssets.has(loader))throw Error('Unlisted Office module loader.');
    importScripts(loader);return globalThis.createLibreOfficeModule;
  };
}
