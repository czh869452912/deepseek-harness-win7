/**
 * Cordis in Browser Runtime (`@deepseek-ai/cordis`).
 * 1:1 Browser implementation of Cordis Context, Services, Fiber Lifecycle,
 * Reversible Effects, and Asynchronous Dependency Injection.
 */

export class Fiber {
  constructor(ctx, plugin, options = {}) {
    this.ctx = ctx;
    this.plugin = plugin;
    this.options = options;
    this.state = "pending"; // pending | active | failed | disposed
    this.disposers = [];
    this.inject = {};
    if (plugin && plugin.inject) {
      const injectList = Array.isArray(plugin.inject) ? plugin.inject : [plugin.inject];
      injectList.forEach((s) => {
        this.inject[s] = true;
      });
    }
  }

  async activate() {
    if (this.state === "active" || this.state === "disposed") return;
    try {
      if (typeof this.plugin === "function") {
        if (this.plugin.prototype && this.plugin.prototype.apply) {
          const instance = new this.plugin(this.options);
          const res = instance.apply(this.ctx);
          if (res && typeof res.then === "function") await res;
        } else {
          const res = this.plugin(this.ctx, this.options);
          if (res && typeof res.then === "function") await res;
        }
      } else if (this.plugin && typeof this.plugin.apply === "function") {
        const res = this.plugin.apply(this.ctx, this.options);
        if (res && typeof res.then === "function") await res;
      }
      this.state = "active";
      this.ctx.emit("internal/status", { entry: { options: this.options, fiber: this } });
    } catch (err) {
      this.state = "failed";
      console.error(`[Cordis] Plugin activation failed for ${this.options.name || "plugin"}:`, err);
      this.ctx.emit("internal/status", { entry: { options: this.options, fiber: this } });
      throw err;
    }
  }

  async dispose() {
    this.state = "disposed";
    for (const d of this.disposers.reverse()) {
      try {
        const res = d();
        if (res && typeof res.then === "function") await res;
      } catch (err) {
        console.warn("[Cordis] Error during fiber disposer:", err);
      }
    }
    this.disposers = [];
  }
}

export class Context {
  constructor(parent = null) {
    this.parent = parent;
    this._services = parent ? new Map(parent._services) : new Map();
    this._events = new Map();
    this._fibers = [];
    this._waiters = []; // List of { services: string[], callback: Function }
    this.fiber = new Fiber(this, null, { name: "root" });

    // Self-register context
    this.set_service("ctx", this);
  }

  get(name) {
    return this._services.get(name);
  }

  set_service(name, instance) {
    this._services.set(name, instance);
    this[name] = instance;
    this.emit("internal/service", name);
    this._checkWaiters();
  }

  provide(name, instance) {
    this.set_service(name, instance);
    return () => {
      if (this._services.get(name) === instance) {
        this._services.delete(name);
        delete this[name];
      }
    };
  }

  get reflect() {
    return {
      provide: (name, instance) => this.provide(name, instance),
    };
  }

  effect(fn, desc = "") {
    let disposer = null;
    try {
      disposer = fn();
    } catch (e) {
      console.error(`[Cordis] Effect execution failed (${desc}):`, e);
    }
    if (typeof disposer === "function") {
      this.fiber.disposers.push(disposer);
      return disposer;
    }
    return () => {};
  }

  on(event, handler) {
    if (!this._events.has(event)) {
      this._events.set(event, new Set());
    }
    const handlers = this._events.get(event);
    handlers.add(handler);
    const disposer = () => {
      handlers.delete(handler);
    };
    this.fiber.disposers.push(disposer);
    return disposer;
  }

  emit(event, ...args) {
    const handlers = this._events.get(event);
    if (handlers) {
      handlers.forEach((h) => {
        try {
          h(...args);
        } catch (err) {
          console.error(`[Cordis] Event listener error (${event}):`, err);
        }
      });
    }
    if (this.parent) {
      this.parent.emit(event, ...args);
    }
  }

  async serial(event, ...args) {
    const handlers = this._events.get(event);
    if (handlers) {
      for (const h of Array.from(handlers)) {
        await h(...args);
      }
    }
  }

  async parallel(event, ...args) {
    const handlers = this._events.get(event);
    if (handlers) {
      await Promise.all(Array.from(handlers).map((h) => h(...args)));
    }
  }

  async waterfall(event, initialData, ...extra) {
    let curr = initialData;
    const handlers = this._events.get(event);
    if (handlers) {
      for (const h of Array.from(handlers)) {
        curr = await h(curr, ...extra);
      }
    }
    return curr;
  }

  inject(services, callback) {
    const serviceList = Array.isArray(services) ? services : [services];
    return new Promise((resolve, reject) => {
      const check = () => {
        const missing = serviceList.filter((s) => !this._services.has(s));
        if (missing.length === 0) {
          try {
            const res = callback ? callback(this) : this;
            resolve(res);
            return true;
          } catch (e) {
            reject(e);
            return true;
          }
        }
        return false;
      };

      if (!check()) {
        this._waiters.push({ services: serviceList, check, resolve, reject });
      }
    });
  }

  _checkWaiters() {
    this._waiters = this._waiters.filter((w) => !w.check());
  }

  async plugin(pluginClassOrObj, options = {}) {
    const subCtx = new Context(this);
    const fiber = new Fiber(subCtx, pluginClassOrObj, options);
    subCtx.fiber = fiber;
    this._fibers.push(fiber);

    // Check inject before activating
    const injectList = Object.keys(fiber.inject);
    if (injectList.length > 0) {
      await this.inject(injectList, async () => {
        await fiber.activate();
      });
    } else {
      await fiber.activate();
    }
    return fiber;
  }
}

export class CordisLoaderPlugin {
  static inject = [];

  constructor() {
    this.entriesMap = new Map();
    this.internal = null; // ClientModuleSystem instance
  }

  apply(ctx) {
    ctx.loader = this;
    ctx.set_service("loader", this);
  }

  async create(options) {
    const name = options.name;
    const id = name;
    const entryObj = {
      id,
      options,
      fiber: undefined,
    };
    this.entriesMap.set(id, entryObj);

    // Dynamic import via internal ClientModuleSystem
    if (this.internal) {
      try {
        const mod = await this.internal.import(name);
        const pluginTarget = mod && mod.default ? mod.default : mod;
        const fiber = await this.ctx.plugin(pluginTarget, options);
        entryObj.fiber = fiber;
      } catch (err) {
        console.error(`[CordisLoader] Failed to import/mount entry "${name}":`, err);
      }
    }
    return id;
  }

  resolve(id) {
    return this.entriesMap.get(id) || { options: { name: id }, fiber: undefined };
  }

  entries() {
    return Array.from(this.entriesMap.values());
  }

  async await() {
    // Wait until all pending fibers settle
    const fibers = Array.from(this.entriesMap.values())
      .map((e) => e.fiber)
      .filter(Boolean);
    await Promise.all(
      fibers.map((f) => {
        if (f.state === "active") return Promise.resolve();
        return new Promise((res) => {
          const off = this.ctx.on("internal/status", (payload) => {
            if (payload.entry && payload.entry.fiber === f) {
              if (f.state === "active" || f.state === "failed") {
                off();
                res();
              }
            }
          });
        });
      })
    );
  }
}
