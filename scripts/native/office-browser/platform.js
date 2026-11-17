/** Private POSIX memory-volume adapters for the unchanged SDK worker bodies. */
import {Buffer} from 'buffer';
import {sha256} from '@noble/hashes/sha256';

let files = new Map(), directories = new Map(), descriptors = new Map(), nextFd = 1;
let allowedAssets = new Set(), messages = [];
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
function status(file, directory = false) {
  const identity = file.identity || {dev:'0',ino:'0',size:0,mtimeNs:'0',ctimeNs:'0'};
  return {...identity,dev:BigInt(identity.dev),ino:BigInt(identity.ino),size:BigInt(identity.size),
    mtimeNs:BigInt(identity.mtimeNs),ctimeNs:BigInt(identity.ctimeNs),
    isDirectory:()=>directory,isFile:()=>!directory};
}
export const constants = {O_RDONLY:0,O_NONBLOCK:0,O_NOFOLLOW:0};
export function openSync(path) {const file=files.get(path);if(!file)throw absent(path);const fd=nextFd++;descriptors.set(fd,{...file});return fd;}
export function closeSync(fd) {descriptors.delete(fd);}
export function fstatSync(fd) {const file=descriptors.get(fd);if(!file)throw Error('Closed memory-volume descriptor.');return status(file);}
export function readSync(fd, target, offset, length, position) {
  const file=descriptors.get(fd);if(!file)throw Error('Closed memory-volume descriptor.');
  const data=bytes(file).subarray(position,position+length);target.set(data,offset);return data.length;
}
export function readFileSync(path, encoding) {
  const file=files.get(path), data=file?bytes(file):allowedAssets.has(path)?fetchBytes(path):null;
  if(!data)throw absent(path);return encoding?data.toString(encoding):data;
}
export function statSync(path) {if(directories.has(path))return status({},true);const file=files.get(path);if(!file)throw absent(path);return status(file);}
export function realpathSync(path) {statSync(path);return path;}
export function readdirSync(path) {if(!directories.has(path))throw absent(path);return [...directories.get(path)];}
export function mkdirSync(path) {if(directories.has(path))throw Error('Memory directory already exists.');directories.set(path,[]);}
export function writeFileSync(path, value, options) {
  if(options?.flag==='wx'&&files.has(path))throw Error('Memory file already exists.');
  const data=Buffer.from(value);files.set(path,{bytes:data,identity:{dev:'0',ino:'0',size:data.length,mtimeNs:'0',ctimeNs:'0'},output:true});
}
export function unlinkSync(path) {if(!files.delete(path))throw absent(path);}
export function renameSync(source,target) {const file=files.get(source);if(!file)throw absent(source);files.set(target,file);files.delete(source);}
export function outputs() {return Object.fromEntries([...files].filter(([,file])=>file.output).map(([path,file])=>[path,file.bytes]));}
export function resources() {return {openDescriptors:descriptors.size,retainedReadBuffers:[...files.values()].filter(file=>!file.output&&file.bytes).length};}
export function basename(path) {return path.slice(path.lastIndexOf('/')+1);}
export function extname(path) {const name=basename(path),dot=name.lastIndexOf('.');return dot<=0?'':name.slice(dot);}
export function isAbsolute(path) {return path.startsWith('/');}
export function join(...parts) {
  const text=parts.filter(Boolean).join('/'),absolute=text.startsWith('/'),stack=[];
  for(const part of text.split('/')){
    if(!part||part==='.')continue;
    if(part==='..'&&stack.length&&stack[stack.length-1]!=='..')stack.pop();
    else if(part!=='..'||!absolute)stack.push(part);
  }
  return (absolute?'/':'')+stack.join('/') || '.';
}
export const posix={join,isAbsolute,basename,extname};
// Windows/Office installation discovery belongs to the physical host. This
// browser volume deliberately accepts explicit POSIX roots only.
export const win32={join(){throw Error('Physical Windows discovery requires the host font provider.');}};
export function homedir() {return '/profile';}
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
