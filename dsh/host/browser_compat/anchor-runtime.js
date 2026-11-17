/* Host-owned adapter for dynamic React portals in browsers without CSS anchors.
 * Vendor rules are generated beside original styles; Source bundles stay intact.
 */
(function () {
  if (typeof document === 'undefined' || typeof CSS === 'undefined' ||
      CSS.supports('anchor-name: --dsh-native') || window.__dshAnchorCompatibility) return;
  const prototype = CSSStyleDeclaration.prototype;
  const set = prototype.setProperty, get = prototype.getPropertyValue;
  const remove = prototype.removeProperty, priority = prototype.getPropertyPriority;
  const names = {'anchor-name': '--dsh-compat-anchor-name', 'position-anchor': '--dsh-compat-position-anchor'};
  let frame = 0, running = false, pending = false, last = '', generation = 0;
  const ids = new WeakMap(); let nextId = 0;
  const identity = node => {if (!ids.has(node)) ids.set(node, ++nextId); return ids.get(node);};
  const state = {refreshes: 0, active: false, error: null, targets: 0, observers: 0};
  const alignment = document.createElement('style');
  alignment.setAttribute('data-dsh-anchor-alignment', '');
  alignment.textContent = `
    [data-dsh-anchor-compat~="end-x"]{margin-left:auto!important;margin-right:0!important}
    [data-dsh-anchor-compat~="start-x"]{margin-left:0!important;margin-right:0!important}
    [data-dsh-anchor-compat~="center-x"]{margin-left:auto!important;margin-right:auto!important}
    [data-dsh-anchor-compat~="end-y"]{margin-top:auto!important;margin-bottom:0!important}
    [data-dsh-anchor-compat~="start-y"]{margin-top:0!important;margin-bottom:0!important}
    [data-dsh-anchor-compat~="center-y"]{margin-top:auto!important;margin-bottom:auto!important}`;
  (document.head || document.documentElement).append(alignment);
  Object.defineProperty(window, '__dshAnchorCompatibility', {value: state});
  function schedule() {
    pending = true;
    if (!running && !frame) frame = requestAnimationFrame(refresh);
  }
  prototype.setProperty = function (key, value, importance) {
    if (Object.hasOwn(names, key)) {set.call(this, names[key], value, importance); schedule(); return;}
    return set.call(this, key, value, importance);
  };
  prototype.getPropertyValue = function (key) {return get.call(this, names[key] || key);};
  prototype.getPropertyPriority = function (key) {return priority.call(this, names[key] || key);};
  prototype.removeProperty = function (key) {
    if (Object.hasOwn(names, key)) {const value = remove.call(this, names[key]); schedule(); return value;}
    return remove.call(this, key);
  };
  for (const [camel, key] of [['anchorName', 'anchor-name'], ['positionAnchor', 'position-anchor']]) {
    Object.defineProperty(prototype, camel, {configurable: true, enumerable: true,
      get() {return get.call(this, names[key]);},
      set(value) {this.setProperty(key, value);}});
  }
  function signature() {
    const styles = Array.from(document.querySelectorAll('style:not([data-generated-by-polyfill]):not([data-dsh-color-mix-fallback]),link[rel="stylesheet"]'));
    const anchors = Array.from(document.querySelectorAll('[style]')).filter(node =>
      /(?:--dsh-compat-(?:anchor-name|position-anchor)|--dsh-menu-anchor)\s*:/.test(node.getAttribute('style')));
    return styles.map(node => identity(node) + ':' + (node.href || node.textContent)).join('|') + '\n' +
      anchors.map(node => identity(node) + ':' + node.className + ':' + get.call(node.style, names['anchor-name']) +
        ':' + get.call(node.style, names['position-anchor']) + ':' + get.call(node.style, '--dsh-menu-anchor')).join('|');
  }
  async function refresh() {
    frame = 0; pending = false;
    const value = signature(); if (value === last) return;
    last = value; running = true; const turn = ++generation;
    try {
      dshAnchorVendor.reset();
      const target = document.querySelector('[style*="--dsh-compat-position-anchor"],[style*="--dsh-menu-anchor"]');
      if (target) await dshAnchorVendor.apply({positionAreaContainingBlock: false});
      if (turn === generation) {
        state.refreshes++; state.active = !!target; state.error = null;
        state.targets = dshAnchorVendor.targets.size; state.observers = dshAnchorVendor.observers();
      }
    } catch (error) {
      state.error = String(error); console.error('Host CSS anchor compatibility failed', error);
    } finally {running = false; if (pending) schedule();}
  }
  const observer = new MutationObserver(() => {
    for (const target of dshAnchorVendor.targets) dshAnchorVendor.align(target);
    schedule();
  });
  observer.observe(document, {subtree: true, childList: true, characterData: true,
    attributes: true, attributeFilter: ['style', 'class', 'href', 'rel', 'data-anchor-polyfill']});
  document.addEventListener('load', event => {if (event.target instanceof HTMLLinkElement) schedule();}, true);
  window.addEventListener('pagehide', () => {
    observer.disconnect(); cancelAnimationFrame(frame); generation++; dshAnchorVendor.reset();
    frame = 0; last = ''; state.active = false; state.targets = 0; state.observers = 0;
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) {
      observer.observe(document, {subtree:true,childList:true,characterData:true,attributes:true,
        attributeFilter:['style','class','href','rel','data-anchor-polyfill']});schedule();
    }
  });
  schedule();
})();
