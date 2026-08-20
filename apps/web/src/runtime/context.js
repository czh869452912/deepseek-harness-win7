/**
 * DeepSeek Harness Client Cordis Context (`@deepseek-ai/dsh-client-runtime/context`)
 * Browser-side Cordis Dependency Injection & Event Hub container.
 */

export class ClientContext {
  constructor(parent = null) {
    this.parent = parent;
    this.services = new Map();
    this.eventListeners = new Map();
    this.disposers = [];
    this.plugins = [];
  }

  set_service(name, instance) {
    this.services.set(name, instance);
    this[name] = instance;
    return instance;
  }

  get(name) {
    if (this.services.has(name)) {
      return this.services.get(name);
    }
    if (this.parent) {
      return this.parent.get(name);
    }
    return undefined;
  }

  has(name) {
    return this.services.has(name) || (this.parent ? this.parent.has(name) : false);
  }

  on(eventName, handler) {
    if (!this.eventListeners.has(eventName)) {
      this.eventListeners.set(eventName, new Set());
    }
    const set = this.eventListeners.get(eventName);
    set.add(handler);
    return () => set.delete(handler);
  }

  emit(eventName, ...args) {
    const set = this.eventListeners.get(eventName);
    if (set) {
      set.forEach((fn) => {
        try {
          fn(...args);
        } catch (e) {
          console.error(`[ClientContext] Error in event listener '${eventName}':`, e);
        }
      });
    }
    if (this.parent) {
      this.parent.emit(eventName, ...args);
    }
  }

  effect(fn) {
    try {
      const res = fn();
      if (typeof res === "function") {
        this.disposers.push(res);
        return res;
      }
    } catch (e) {
      console.error("[ClientContext] Error running effect:", e);
    }
    return () => {};
  }

  plugin(PluginDef, config = {}) {
    try {
      let instance = null;
      if (typeof PluginDef === "function") {
        if (PluginDef.prototype && PluginDef.prototype.apply) {
          instance = new PluginDef(config);
          instance.apply(this);
        } else {
          // Function plugin
          instance = PluginDef(this, config);
        }
      } else if (PluginDef && typeof PluginDef.apply === "function") {
        instance = PluginDef;
        instance.apply(this);
      }
      this.plugins.push(instance);
      return instance;
    } catch (e) {
      console.error("[ClientContext] Error applying plugin:", e);
      throw e;
    }
  }

  extend() {
    return new ClientContext(this);
  }

  dispose() {
    for (let i = this.disposers.length - 1; i >= 0; i--) {
      try {
        this.disposers[i]();
      } catch (e) {}
    }
    this.disposers = [];
    this.eventListeners.clear();
    this.services.clear();
  }
}
