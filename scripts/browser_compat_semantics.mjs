/** Independent realms exercise the adapter; this is not a Chromium 108 lane. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const code = readFileSync(new URL('../dsh/host/browser_compat/compat.js', import.meta.url), 'utf8');
const nativeAny = Object.getOwnPropertyDescriptor(AbortSignal, 'any');
let observations = 0;
try {
  delete AbortSignal.any;
  const realm = vm.createContext({AbortSignal, AbortController, EventTarget, Event});
  vm.runInContext(code, realm);
  await vm.runInContext(`(async () => {
    function check(value) { if (!value) throw new Error('capability assertion failed'); }
    function throws(call) { let caught = false; try {call();} catch (e) {caught = e.name === 'TypeError';} check(caught); }
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
    check(Promise.withResolvers === installed && AbortSignal.any === any);
  })()`, realm);
  observations += 29;
} finally {
  if (nativeAny) Object.defineProperty(AbortSignal, 'any', nativeAny);
  else delete AbortSignal.any;
}
const nativeRealm = vm.createContext({AbortSignal, AbortController, EventTarget, Event});
vm.runInContext('Promise.withResolvers = function sentinel() {}; globalThis.saved = Promise.withResolvers;', nativeRealm);
vm.runInContext(code, nativeRealm);
assert.equal(vm.runInContext('Promise.withResolvers === saved', nativeRealm), true);
assert.equal(AbortSignal.any, nativeAny?.value);
console.log(JSON.stringify({passed: true, observations, scope: 'simulated absent APIs, isolated VM realms; not browser/Win7 certification'}));
