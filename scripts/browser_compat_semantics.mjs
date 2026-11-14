/** Independent realms exercise the adapter; this is not a Chromium 108 lane. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {browserCompatibilityInput} from './browser_compat_input.mjs';
const {script:code}=await browserCompatibilityInput(fileURLToPath(new URL('../dsh/host/browser_compat/',import.meta.url)));
const nativeAny = Object.getOwnPropertyDescriptor(AbortSignal, 'any');
let observations = 0;
try {
  delete AbortSignal.any;
  const realm = vm.createContext({AbortSignal, AbortController, EventTarget, Event});
  vm.runInContext('delete globalThis.Iterator; delete Array.prototype.toSorted;', realm);
  vm.runInContext(code, realm);
  observations += await vm.runInContext(`(async () => {
    let count = 0;
    function check(value) { count++; if (!value) throw new Error('capability assertion failed'); }
    function throws(call) { let caught = false; try {call();} catch (e) {caught = e.name === 'TypeError';} check(caught); }
    check(typeof Iterator === 'function');
    throws(() => Iterator()); throws(() => new Iterator());
    const iteratorPrototype = Object.getPrototypeOf(Object.getPrototypeOf([][Symbol.iterator]()));
    check(Iterator.prototype === iteratorPrototype);
    check([][Symbol.iterator]() instanceof Iterator);
    check(new Set()[Symbol.iterator]() instanceof Iterator);
    check((function*(){})() instanceof Iterator);
    check(!Object.getOwnPropertyDescriptor(globalThis, 'Iterator').enumerable);
    check(!Object.getOwnPropertyDescriptor(Iterator, 'prototype').writable);
    class Items extends Iterator { next(){return {done:true};} }
    const items = new Items(); check(items[Symbol.iterator]() === items);
    check(Items.prototype.constructor === Items);
    items.constructor = 'own'; check(items.constructor === 'own');
    items[Symbol.toStringTag] = 'Own'; check(Object.prototype.toString.call(items) === '[object Own]');
    throws(() => {Iterator.prototype.constructor = null;});
    const installedIterator = Iterator;
    const groups = [{id:'other',index:0},{id:'official',index:1},{id:'other',index:2}];
    const sorted = groups.toSorted((a,b)=>(a.id==='official'?0:1)-(b.id==='official'?0:1));
    check(sorted !== groups && sorted.map(v=>v.index).join(',') === '1,0,2');
    check(groups.map(v=>v.index).join(',') === '0,1,2');
    check(Object.keys([,1].toSorted()).join(',') === '0,1');
    check([,1].toSorted()[1] === undefined);
    check(Array.prototype.toSorted.call({0:'b',1:'a',length:2}).join(',') === 'a,b');
    throws(() => [].toSorted(null));
    throws(() => Array.prototype.toSorted.call(null));
    class CustomArray extends Array {static get [Symbol.species]() {throw new Error('species must not be used');}}
    check(new CustomArray(2,1).toSorted().constructor === Array);
    check(!Object.getOwnPropertyDescriptor(Array.prototype,'toSorted').enumerable);
    const installedSorted = Array.prototype.toSorted;
    const any = AbortSignal.any;
    check(any.length === 1);
    throws(() => any()); throws(() => any(null)); throws(() => any(''));
    throws(() => any([{}])); throws(() => any([new AbortController().signal, null]));
    check(!any([]).aborted);
    const a = new AbortController(), b = new AbortController();
    const why = {identity: 'reason'};
    a.abort(why); b.abort('second');
    check(any([a.signal, b.signal]).reason === why);
    throws(() => any([a.signal, {}]));
    const c = new AbortController(), d = new AbortController();
    const combined = any([c.signal, c.signal, d.signal]);
    let events = 0; combined.addEventListener('abort', () => events++);
    c.signal.dispatchEvent(new Event('abort')); check(!combined.aborted);
    c.abort(why); d.abort('late'); check(events === 1 && combined.reason === why);
    const e = new AbortController(), f = new AbortController();
    const first = any([e.signal]), last = any([first, f.signal]);
    e.abort(why); check(last.reason === why);
    const g = new AbortController();
    const reentrant = any([g.signal]);
    reentrant.addEventListener('abort', () => g.abort('reentered'));
    g.abort(why); check(reentrant.reason === why);
    const withResolvers = Promise.withResolvers;
    check(withResolvers.length === 0);
    check(!Object.getOwnPropertyDescriptor(Promise, 'withResolvers').enumerable);
    const deferred = Promise.withResolvers();
    check(Object.keys(deferred).join(',') === 'promise,resolve,reject');
    deferred.resolve(42); deferred.reject('late'); check(await deferred.promise === 42);
    const rejected = Promise.withResolvers(); rejected.reject(why);
    check(await rejected.promise.catch(value => value) === why);
    class Child extends Promise {};
    const child = Child.withResolvers(); check(child.promise instanceof Child);
    child.resolve('child'); check(await child.promise === 'child');
    throws(() => withResolvers.call({}));
    throws(() => new withResolvers());
    throws(() => withResolvers.call(class {constructor(executor) {executor(0, 0);}}));
    throws(() => withResolvers.call(class {constructor(executor) {executor(()=>{}, ()=>{}); executor(()=>{}, ()=>{});}}));
    class Custom {constructor(executor) {executor(()=>{}, ()=>{});}}
    check(withResolvers.call(Custom).promise instanceof Custom);
    const installed = Promise.withResolvers;
    ${code}
    check(Promise.withResolvers === installed && AbortSignal.any === any && Iterator === installedIterator);
    check(Array.prototype.toSorted === installedSorted);
    return count;
  })()`, realm);
} finally {
  if (nativeAny) Object.defineProperty(AbortSignal, 'any', nativeAny);
  else delete AbortSignal.any;
}
const nativeRealm = vm.createContext({AbortSignal, AbortController, EventTarget, Event,structuredClone});
vm.runInContext('Promise.withResolvers = function sentinel() {}; globalThis.saved = Promise.withResolvers; globalThis.Iterator = function ExistingIterator() {}; globalThis.savedIterator = Iterator;', nativeRealm);
vm.runInContext(code, nativeRealm);
assert.equal(vm.runInContext('Promise.withResolvers === saved', nativeRealm), true);
assert.equal(vm.runInContext('Iterator === savedIterator', nativeRealm), true);
assert.equal(AbortSignal.any, nativeAny?.value);
observations+=await vm.runInContext(`(async()=>{
  let count=0;const check=value=>{count++;if(!value)throw new Error('PDF capability assertion failed');};
  const reason={identity:'reject'};let called=false;
  const value=Promise.try((a,b)=>{called=true;return a+b;},2,3);
  check(called);check(await value===5);
  check(await Promise.try(()=>{throw reason;}).catch(error=>error)===reason);
  check(await Promise.try(1).catch(error=>error instanceof TypeError));
  class Child extends Promise{};check(Child.try(()=>7) instanceof Child);
  check(await Promise.try(()=>Promise.resolve('adopted'))==='adopted');
  check(!Object.getOwnPropertyDescriptor(Promise,'try').enumerable);
  check(Math.sumPrecise([1e20,1,-1e20])===1);
  check(Object.is(Math.sumPrecise([]),-0));check(Object.is(Math.sumPrecise([-0,-0]),-0));
  check(Number.isNaN(Math.sumPrecise([Infinity,-Infinity])));
  let bad=false;try{Math.sumPrecise([1,'2']);}catch(error){bad=error instanceof TypeError;}check(bad);
  check([...Uint8Array.fromBase64('YWJj')].join(',')==='97,98,99');
  check([...Uint8Array.fromBase64(' -_8= ',{alphabet:'base64url'})].join(',')==='251,255');
  check([...Uint8Array.fromBase64('YQ')].join(',')==='97');
  check(new Uint8Array([0,15,255]).toHex()==='000fff');
  check(new Uint8Array([251,255]).toBase64({alphabet:'base64url'})==='-_8=');
  const map=new Map([['existing',undefined]]);let calls=0;
  check(map.getOrInsertComputed('existing',()=>{calls++;return 9;})===undefined&&calls===0);
  check(map.getOrInsertComputed('new',key=>{calls++;return key;})==='new'&&calls===1);
  check(map.get('new')==='new'&&map.getOrInsert('new','replacement')==='new');
  check(map.getOrInsert('added',3)===3&&map.get('added')===3);
  const set=new Set([1,2,3]);check([...set.intersection(new Set([3,4]))].join(',')==='3');
  const buffer=new ArrayBuffer(3);new Uint8Array(buffer).set([1,2,3]);
  const moved=buffer.transferToFixedLength(5);
  check(buffer.byteLength===0&&moved.byteLength===5&&[...new Uint8Array(moved)].join(',')==='1,2,3,0,0');
  bad=false;try{Uint8Array.fromBase64('YQ',{lastChunkHandling:'strict'});}catch(error){bad=error instanceof SyntaxError;}check(bad);
  bad=false;try{Uint8Array.fromBase64('!');}catch(error){bad=error instanceof SyntaxError;}check(bad);
  bad=false;try{Uint8Array.fromBase64(123);}catch(error){bad=error instanceof TypeError;}check(bad);
  const installed=[Promise.try,Math.sumPrecise,Uint8Array.fromBase64];
  ${code}
  check(Promise.try===installed[0]&&Math.sumPrecise===installed[1]&&Uint8Array.fromBase64===installed[2]);
  return count;
})()`,nativeRealm);
class OldResponse extends Response{};class OldBlob extends Blob{};class OldBodyRequest extends Request{};
for(const Constructor of [OldResponse,OldBlob,OldBodyRequest])Object.defineProperty(Constructor.prototype,'bytes',{value:undefined,writable:true,configurable:true});
const bodyRealm=vm.createContext({Response:OldResponse,Request:OldBodyRequest,Blob:OldBlob,URL,URLSearchParams,AbortSignal,AbortController,EventTarget,Event,structuredClone});
vm.runInContext(code,bodyRealm);
observations+=await vm.runInContext(`(async()=>{
  let count=0;const check=value=>{count++;if(!value)throw new Error('Body bytes assertion failed');};
  const response=new Response('abc');const bytes=await response.bytes();
  check(bytes instanceof Uint8Array&&[...bytes].join(',')==='97,98,99');check(response.bodyUsed);
  check(await response.bytes().then(()=>false,error=>error.name==='TypeError'));
  check(await Response.prototype.bytes.call({}).then(()=>false,error=>error.name==='TypeError'));
  check([...await new Blob(['abc']).bytes()].join(',')==='97,98,99');
  check([...await new Request('https://example.com',{method:'POST',body:'x'}).bytes()].join(',')==='120');
  const locked=new Response('x');locked.body.getReader();check(await locked.bytes().then(()=>false,error=>error.name==='TypeError'));
  check(!Object.getOwnPropertyDescriptor(Response.prototype,'bytes').enumerable);
  const installed=Response.prototype.bytes;${code}
  check(Response.prototype.bytes===installed);return count;
})()`,bodyRealm);
const correctRealm = vm.createContext({URL,URLSearchParams,AbortSignal,AbortController,EventTarget,Event});
vm.runInContext('globalThis.savedURL = URL; globalThis.savedParams = URLSearchParams;',correctRealm);
vm.runInContext(code,correctRealm);
assert.equal(vm.runInContext('URL === savedURL && URLSearchParams === savedParams',correctRealm),true);

// Simulate only the independently observed old Chromium URL defect. All URL
// results below are produced by the actual pinned fallback, not a fake parser.
class OldURL extends URL { get hostname(){return this.protocol==='dsh-resource:'?'':super.hostname;} }
class OldRequest extends Request {}
const urlRealm=vm.createContext({URL:OldURL,URLSearchParams,Headers,Request:OldRequest,AbortController,AbortSignal,EventTarget,Event,
  fetch:async(input,init)=>({input,init}),Blob});
vm.runInContext(code,urlRealm);
observations+=await vm.runInContext(`(async()=>{
  let count=0;const check=value=>{count++;if(!value)throw new Error('URL fallback assertion failed');};
  const url=new URL('dsh-resource://file/session/id/name%20%23.txt?x=1&x=2#part');
  check(url.hostname==='file'&&url.host==='file'&&url.protocol==='dsh-resource:');
  check(url.pathname==='/session/id/name%20%23.txt'&&url.origin==='null');
  check(url.searchParams instanceof URLSearchParams&&url.searchParams.getAll('x').join(',')==='1,2');
  url.searchParams.set('x','a b');check(url.search==='?x=a+b');
  check(String(url)===url.href&&url.toJSON()===url.href);
  const relative=new URL('../next?q=ok',url);check(relative.href==='dsh-resource://file/session/next?q=ok');
  const opaque=new URL('data:text/plain,hello');check(opaque.hostname===''&&opaque.pathname==='text/plain,hello');
  check(new URL('https://EXAMPLE.com:443/a/../b').href==='https://example.com/b');
  check(new URL('file:///C:/space%20file').pathname==='/C:/space%20file');
  check(new URL('dsh-resource://File/x').hostname==='File');
  check(new URL('dsh-resource://file:123/x').port==='123');
  check(URL.canParse('x','https://example.com')&&!URL.canParse('http://['));
  check(URL.parse('bad')===null&&URL.parse('/x','https://example.com').pathname==='/x');
  let bad=false;try{new URL('dsh-resource://[invalid]/x')}catch(e){bad=e.name==='TypeError'}check(bad);
  const params=new URLSearchParams('x=1&x=2');params.delete('x','2');check(params.toString()==='x=1');
  const request=new Request('https://example.com',{method:'POST',body:params});
  check(request.headers.get('content-type')==='application/x-www-form-urlencoded;charset=UTF-8');
  check(await request.text()==='x=1');
  const controller=new AbortController();
  const response=await fetch('https://example.com',{method:'POST',body:params,signal:controller.signal});
  check(response.init.body==='x=1'&&response.init.headers.get('content-type')==='application/x-www-form-urlencoded;charset=UTF-8');
  check(response.init.signal===controller.signal);
  const explicit=await fetch('https://example.com',{body:params,headers:{'content-type':'application/custom'}});
  check(explicit.init.headers.get('content-type')==='application/custom');
  const blob=URL.createObjectURL(new Blob(['abc']));check(blob.startsWith('blob:'));URL.revokeObjectURL(blob);
  const installed=URL;
  ${code}
  check(URL===installed);
  return count;
})()`,urlRealm);
console.log(JSON.stringify({passed: true, observations, scope: 'simulated absent APIs, isolated VM realms; not browser/Win7 certification'}));
