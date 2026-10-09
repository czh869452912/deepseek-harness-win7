/* Host capability adapter, loaded before the unchanged upstream application.
 * DOM: https://dom.spec.whatwg.org/#dom-abortsignal-any
 * ECMA-262: https://tc39.es/ecma262/#sec-promise.withresolvers
 * This event-based AbortSignal adapter cannot implement inaccessible native
 * abort algorithms (e.g. earlier stopImmediatePropagation listeners).
 */
(() => {
  'use strict';
  if (typeof Promise.withResolvers !== 'function') {
    const methods = {
      withResolvers() {
        let resolve, reject;
        const promise = new this((yes, no) => {
          if (resolve !== undefined || reject !== undefined) {
            throw new TypeError('Promise capability executor already invoked');
          }
          resolve = yes;
          reject = no;
        });
        if (typeof resolve !== 'function' || typeof reject !== 'function') {
          throw new TypeError('Promise capability requires callable resolvers');
        }
        return {promise, resolve, reject};
      }
    };
    Object.defineProperty(Promise, 'withResolvers', {
      value: methods.withResolvers, writable: true, configurable: true
    });
  }
  if (typeof AbortSignal.any !== 'function') {
    const aborted = Object.getOwnPropertyDescriptor(AbortSignal.prototype, 'aborted').get;
    const reason = Object.getOwnPropertyDescriptor(AbortSignal.prototype, 'reason').get;
    const add = EventTarget.prototype.addEventListener;
    const remove = EventTarget.prototype.removeEventListener;
    // The returned signal owns its controller without making source listeners
    // keep otherwise unreachable combined signals alive.
    const controllers = new WeakMap();
    const registry = new FinalizationRegistry(entries => {
      for (const [source, listener] of entries) remove.call(source, 'abort', listener);
    });
    const methods = {
      any(signals) {
        if (signals === null || (typeof signals !== 'object' && typeof signals !== 'function') ||
            typeof signals[Symbol.iterator] !== 'function') {
          throw new TypeError('AbortSignal.any requires a sequence of AbortSignals');
        }
        const sources = [];
        // Convert the entire sequence before selecting an already-aborted
        // source: a later invalid member must still throw.
        for (const source of signals) {
          aborted.call(source); // Native brand check also accepts other realms.
          sources.push(source);
        }
        const controller = new AbortController();
        for (const source of sources) {
          if (aborted.call(source)) {
            controller.abort(reason.call(source));
            return controller.signal;
          }
        }
        const weak = new WeakRef(controller);
        const entries = [];
        const cleanup = () => {
          for (const [source, listener] of entries) remove.call(source, 'abort', listener);
          entries.length = 0;
        };
        for (const source of new Set(sources)) {
          const listener = () => {
            // Ignore manually dispatched events on a non-aborted source.
            if (!aborted.call(source)) return;
            const target = weak.deref();
            cleanup();
            if (target) {
              registry.unregister(target);
              target.abort(reason.call(source));
            }
          };
          entries.push([source, listener]);
          add.call(source, 'abort', listener);
        }
        controllers.set(controller.signal, controller);
        registry.register(controller, entries, controller);
        return controller.signal;
      }
    };
    Object.defineProperty(AbortSignal, 'any', {
      value: methods.any, writable: true, configurable: true
    });
  }
})();

(() => {
if (typeof document === 'undefined' || typeof CSS === 'undefined' ||
    CSS.supports('color', 'color-mix(in srgb, red, blue)')) return;
/** Host fallback for the pinned bundled two-color sRGB expressions.
 * Original styles stay intact. Native color-mix documents and non-DOM realms
 * allocate no fallback state. The private owner reverses generated effects. */
function splitTop(value){
 let depth=0,start=0,rows=[];
 for(let index=0;index<value.length;index++){
  if(value[index]==='(')depth++;else if(value[index]===')')depth--;
  else if(value[index]===','&&depth===0){rows.push(value.slice(start,index).trim());start=index+1;}
  if(depth<0)throw new TypeError('Unbalanced color expression');
 }
 if(depth)throw new TypeError('Unbalanced color expression');
 rows.push(value.slice(start).trim());return rows;
}
function mix(value,variables,seen=new Set()){
 value=value.trim();
 if(!value){const error=new TypeError('Unset custom color');error.cssInvalid=true;throw error;}
 if(value.startsWith('var(')&&value.endsWith(')')){
  const parts=splitTop(value.slice(4,-1)),key=parts[0];
  if(seen.has(key))throw new TypeError('Cyclic custom color');
  const next=variables[key]?.trim()?variables[key]:parts[1];if(next===undefined){const error=new TypeError('Missing custom color '+key);error.cssInvalid=true;throw error;}
  return mix(next,variables,new Set([...seen,key]));
 }
 if(value.startsWith('color-mix(')&&value.endsWith(')')){
  const args=splitTop(value.slice(10,-1));if(args.length!==3||args[0]!=='in srgb')throw new TypeError('Only two sRGB colors supported by this host adapter');
  const entries=args.slice(1).map(part=>{const match=part.match(/\s+([0-9]+(?:\.[0-9]+)?)%$/);return {color:mix(match?part.slice(0,match.index):part,variables,seen),percent:match?Number(match[1])/100:null};});
  let [p,q]=entries.map(row=>row.percent);
  if(p===null&&q===null)p=q=.5;else if(p===null)p=1-q;else if(q===null)q=1-p;
  if(p<0||q<0||p>1||q>1||p+q<=0)throw new TypeError('Invalid mix percentage');
  const sum=p+q,multiplier=Math.min(sum,1);p/=sum;q/=sum;
  const [a,b]=entries.map(row=>row.color),alpha=a[3]*p+b[3]*q;
  return [...a.slice(0,3).map((component,index)=>alpha?(component*a[3]*p+b[index]*b[3]*q)/alpha:0),alpha*multiplier];
 }
 if(value==='transparent')return [0,0,0,0];
 if(/^#[0-9a-f]{3}$/i.test(value))return [...value.slice(1)].map(v=>parseInt(v+v,16)/255).concat(1);
 if(/^#[0-9a-f]{6}$/i.test(value))return [1,3,5].map(i=>parseInt(value.slice(i,i+2),16)/255).concat(1);
 const rgb=value.match(/^rgba?\(([^)]+)\)$/);if(rgb){const parts=rgb[1].split(',').map(Number);if(parts.length===3)parts.push(1);if(parts.length!==4||parts.some(v=>!Number.isFinite(v)))throw new TypeError('Invalid color');return [...parts.slice(0,3).map(v=>v/255),parts[3]];}
 throw new TypeError('Unobserved color syntax '+value);
}
function rgba(color){return `rgba(${color.slice(0,3).map(v=>(v*255).toFixed(8)).join(',')},${color[3].toFixed(8)})`;}

function installColorMix() {
  if (CSS.supports('color', 'color-mix(in srgb, red, blue)')) return {active: false, dispose() {}};
  let expressions = new Map(), active = new Map(), serial = 0, pending = false;
  const originals = new Map(), own = new WeakSet(), tokens = new Set();
  const saved = new WeakMap(), mediaListeners = new Map();
  let disposed = false, pendingFrame = 0, watchFrame = 0, mediaDirty = true;
  const written = new WeakMap(), properties = new WeakMap(), scopes = new Set(), errorKeys = new Set();
  const facts = {styles: 0, activeStyles: 0, expressions: 0, refreshes: 0, invalidScopes: 0, mediaScans: 0, maxRefreshMs: 0, visited: 0, disposed: false, errors: []};
  function transcribe(text) {
    let out = '', from = 0, index;
    while ((index = text.indexOf('color-mix(', from)) >= 0) {
      let end = index + 10, depth = 1;
      while (end < text.length && depth) {
        if (text[end] === '(') depth++;
        else if (text[end] === ')') depth--;
        end++;
      }
      if (depth) return text;
      const expression = text.slice(index, end);
      if (!active.has(expression)) active.set(expression, expressions.get(expression) ?? '--dsh-host-mix-' + serial++);
      for (const token of expression.match(/--[a-zA-Z0-9_-]+/g) || []) tokens.add(token);
      out += text.slice(from, index) + 'var(' + active.get(expression) + ')';
      from = end;
    }
    return out + text.slice(from);
  }
  function styles() {
    active = new Map(); tokens.clear();
    for (const [original, clone] of originals) {
      if (!original.isConnected || !original.textContent.includes('color-mix(')) {
        clone.remove(); originals.delete(original);
      }
    }
    for (const original of document.querySelectorAll('style')) {
      if (own.has(original)) continue;
      const text = original.textContent;
      if (!text.includes('color-mix(')) continue;
      const transformed = transcribe(text);
      let clone = originals.get(original);
      if (!clone) {
        clone = document.createElement('style'); own.add(clone);
        originals.set(original, clone); facts.styles++;
      }
      for (const attribute of ['media', 'type', 'title']) {
        const value = original.getAttribute(attribute);
        if (value === null) clone.removeAttribute(attribute);
        else if (clone.getAttribute(attribute) !== value) clone.setAttribute(attribute, value);
      }
      if (clone.nonce !== original.nonce) clone.nonce = original.nonce;
      if (clone.textContent !== transformed) clone.textContent = transformed;
      if (original.nextSibling !== clone) original.after(clone);
      if (clone.sheet && original.sheet) clone.sheet.disabled = original.sheet.disabled;
    }
    expressions = active;
    facts.expressions = expressions.size; facts.activeStyles = originals.size;
  }
  function release(element, name) {
    const values = saved.get(element), previous = values?.get(name);
    if (previous) {
      if (previous.value) element.style.setProperty(name, previous.value, previous.priority);
      else element.style.removeProperty(name);
      values.delete(name);
    }
  }
  function claim(element, name, color) {
    let values = saved.get(element);
    if (!values) {values = new Map(); saved.set(element, values);}
    if (!values.has(name)) values.set(name, {value: element.style.getPropertyValue(name), priority: element.style.getPropertyPriority(name)});
    if (element.style.getPropertyValue(name) !== color) element.style.setProperty(name, color);
  }
  function clear(element) {
    for (const name of properties.get(element) ?? []) release(element, name);
    properties.delete(element); scopes.delete(element);
  }
  function refresh() {
    pending = false; pendingFrame = 0;
    if (disposed) return;
    const started = performance.now();
    styles(); facts.refreshes++; syncMedia();
    if (!expressions.size) {for (const element of [...scopes]) clear(element); return;}
    for (const element of scopes) if (!element.isConnected) clear(element);
    const signatures = new Map(), memo = new Map(), activeNames = new Set(expressions.values());
    const snapshots = [];
    facts.visited = 0;
    // Read the full palette before writing generated properties. Interleaved
    // reads and writes otherwise force descendant style recalculation repeatedly.
    for (const element of document.querySelectorAll('*')) {
      facts.visited++;
      if (!element.style || element.tagName === 'STYLE' || element.tagName === 'SCRIPT') continue;
      const computed = getComputedStyle(element), values = {};
      for (const token of tokens) values[token] = computed.getPropertyValue(token).trim();
      snapshots.push({element, values});
    }
    for (const {element, values} of snapshots) {
      const signature = JSON.stringify(values), inherited = signatures.get(element.parentElement);
      signatures.set(element, signature);
      let colors = memo.get(signature);
      if (!colors) {
        colors = new Map();
        for (const [expression, name] of expressions) {
          try {colors.set(name, rgba(mix(expression, values)));}
          catch (error) {
            colors.set(name, null);
            if (error.cssInvalid) {facts.invalidScopes++; continue;}
            const key = expression + ':' + error.message;
            if (!errorKeys.has(key)) {
              errorKeys.add(key);
              if (facts.errors.length < 64) facts.errors.push({expression, message: error.message});
            }
          }
        }
        memo.set(signature, colors);
      }
      const previous = properties.get(element) ?? new Set(), owned = new Set();
      for (const name of previous) if (!activeNames.has(name)) release(element, name);
      for (const [name, color] of colors) {
        if (signature === inherited) {
          if (previous.has(name)) release(element, name);
        } else {
          claim(element, name, color ?? 'initial');
          owned.add(name);
        }
      }
      if (owned.size) {properties.set(element, owned); scopes.add(element);}
      else {properties.delete(element); scopes.delete(element);}
      written.set(element, element.getAttribute('style'));
    }
    facts.maxRefreshMs = Math.max(facts.maxRefreshMs, performance.now() - started);
  }
  function schedule() {if (!disposed && !pending) {pending = true; pendingFrame = requestAnimationFrame(refresh);}}
  function syncMedia() {
    if (!mediaDirty) return;
    mediaDirty = false; facts.mediaScans++;
    const queries = new Set(['(prefers-color-scheme: dark)', '(forced-colors: active)']);
    function rules(rows) {for (const rule of rows) {if (rule.media?.mediaText) queries.add(rule.media.mediaText); if (rule.cssRules) rules(rule.cssRules);}}
    for (const sheet of document.styleSheets) {try {if (sheet.media.mediaText) queries.add(sheet.media.mediaText); rules(sheet.cssRules);} catch {}}
    for (const [query, media] of mediaListeners) if (!queries.has(query)) {media.removeEventListener('change', schedule); mediaListeners.delete(query);}
    for (const query of queries) if (!mediaListeners.has(query)) {const media = matchMedia(query); media.addEventListener('change', schedule); mediaListeners.set(query, media);}
  }
  function watchDisabled() {
    if (disposed) return;
    for (const [original, clone] of originals) if (original.sheet && clone.sheet && original.sheet.disabled !== clone.sheet.disabled) {
      clone.sheet.disabled = original.sheet.disabled; schedule();
    }
    watchFrame = requestAnimationFrame(watchDisabled);
  }
  const observer = new MutationObserver(records => {
    if (records.some(record => !own.has(record.target) && (
        record.target.tagName === 'STYLE' || record.target.parentElement?.tagName === 'STYLE' ||
        (record.type === 'childList' && [...record.addedNodes, ...record.removedNodes].some(node => !own.has(node) &&
          (node.nodeType === 1 && (node.matches('style,link[rel="stylesheet"]') || node.querySelector('style,link[rel="stylesheet"]')))))))) mediaDirty = true;
    if (records.some(record => {
      if (own.has(record.target) || own.has(record.target.parentElement)) return false;
      if (record.type === 'attributes' && record.attributeName === 'style' && written.get(record.target) === record.target.getAttribute('style')) return false;
      if (record.type === 'childList' && [...record.addedNodes, ...record.removedNodes].every(node => own.has(node))) return false;
      return true;
    })) schedule();
  });
  observer.observe(document, {subtree: true, childList: true, characterData: true, attributes: true,
    attributeFilter: ['class', 'style', 'media', 'type', 'title', 'nonce', 'disabled', 'data-theme', 'data-dsw-theme', 'data-ds-dark-theme']});
  for (const event of ['pointerover', 'pointerout', 'focusin', 'focusout']) document.addEventListener(event, schedule, true);
  window.addEventListener('resize', schedule);
  for (const event of ['beforeprint', 'afterprint']) window.addEventListener(event, schedule);
  function dispose() {
    if (disposed) return;
    disposed = true; facts.disposed = true;
    observer.disconnect(); cancelAnimationFrame(pendingFrame); cancelAnimationFrame(watchFrame);
    for (const event of ['pointerover', 'pointerout', 'focusin', 'focusout']) document.removeEventListener(event, schedule, true);
    window.removeEventListener('resize', schedule);
    for (const event of ['beforeprint', 'afterprint']) window.removeEventListener(event, schedule);
    for (const media of mediaListeners.values()) media.removeEventListener('change', schedule);
    mediaListeners.clear();
    for (const clone of originals.values()) clone.remove(); originals.clear();
    for (const element of [...scopes]) clear(element);
    expressions.clear(); active.clear(); tokens.clear();
    facts.activeStyles = facts.expressions = 0;
  }
  schedule(); watchFrame = requestAnimationFrame(watchDisabled);
  return {active: true, facts, dispose};
}
const key = Symbol.for('deepseek-win7.host.color-mix');
window[key]?.dispose();
let current, listening = false;
function hidden() {current?.dispose();}
function shown(event) {if (event.persisted) manager.install();}
const manager = {install() {
    current?.dispose(); current = installColorMix();
    Object.defineProperty(window, key, {value: manager, configurable: true});
    if (!listening) {window.addEventListener('pagehide', hidden); window.addEventListener('pageshow', shown); listening = true;}
    return current;
  }, dispose() {
    current?.dispose(); window.removeEventListener('pagehide', hidden); window.removeEventListener('pageshow', shown); listening = false;
    if (window[key] === manager) delete window[key];
  }, get current() {return current;}};
manager.install();

})();
