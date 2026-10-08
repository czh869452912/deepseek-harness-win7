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
