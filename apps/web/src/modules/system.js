/**
 * ClientModuleSystem (`@deepseek-ai/dsh-client-modules/client`).
 * 1:1 In-Browser lazy CJS module system, dependency injector, and stylesheet scope manager.
 */

export function stripClientSuffix(id) {
  if (typeof id !== "string") return id;
  return id.replace(/\/client$/, "");
}

function defaultLoadBundle(url) {
  return new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.async = true;
    el.src = url;
    el.addEventListener("load", () => {
      el.remove();
      resolve();
    }, { once: true });
    el.addEventListener("error", () => {
      el.remove();
      reject(new Error(`client-modules: bundle script ${url} failed to load`));
    }, { once: true });
    document.head.append(el);
  });
}

function claimStyles(id) {
  if (typeof document === "undefined") return [];
  for (const el of document.querySelectorAll("style:not([data-plugin])")) {
    el.setAttribute("data-plugin", id);
  }
  const owned = [];
  for (const el of document.querySelectorAll(`style[data-plugin="${id}"]`)) {
    owned.push(el.getAttribute("data-plugin-css") || id);
  }
  return owned;
}

export class ClientModuleSystem {
  constructor(options = {}) {
    this.version = "client";
    this.manifest = options.manifest || { rev: "0", entries: [], modules: [], plugins: [] };
    this.seed = new Map(Object.entries(options.staticModules || {}));
    this.loadBundle = options.loadBundle || defaultLoadBundle;
    this.loadCache = new Map();
    this.factories = new Map();
    this.bootstrapIds = new Set();
    this.pendingArrival = new Map();
    this.materializing = new Set();
    this.graphRows = new Map();

    const modulesList = this.manifest.modules || this.manifest.entries || this.manifest.plugins || [];
    for (const row of modulesList) {
      this.graphRows.set(row.id, row);
    }

    const target = options.registrationTarget || window.__ModuleLoader__ || { mode: "queue", pendingQueue: [] };
    const pending = (target.pendingQueue || []).splice(0);
    target.mode = "live";
    target.load = (reg) => {
      this.register(reg);
    };
    for (const reg of pending) {
      target.load(reg);
    }
  }

  register(registration) {
    if (!registration || !registration.id) return;
    const id = stripClientSuffix(registration.id);
    this.factories.set(id, registration.factory);
  }

  arrive(row) {
    const { id, url } = row;
    const pending = this.pendingArrival.get(id);
    if (pending !== undefined) return pending;
    if (this.loadCache.has(id) || this.factories.has(id)) return Promise.resolve();

    const task = this.loadBundle(url).then(() => {
      if (!this.factories.has(id)) {
        console.warn(`[ClientModuleSystem] Bundle ${url} loaded without registering "${id}" via __ModuleLoader__.load`);
      }
    }).finally(() => {
      this.pendingArrival.delete(id);
    });
    this.pendingArrival.set(id, task);
    return task;
  }

  async arriveGraphRow(row, open = []) {
    const next = [...open, row.id];
    const externals = row.external || [];
    for (const request of externals) {
      const id = stripClientSuffix(request);
      if (this.seed.has(request) || this.loadCache.has(id)) continue;
      const dependency = this.graphRows.get(id);
      if (dependency !== undefined) {
        await this.arriveGraphRow(dependency, next);
      }
    }
    await this.arrive(row);
  }

  materialize(id) {
    const existing = this.loadCache.get(id);
    if (existing !== undefined) return existing;
    const registered = this.factories.get(id);
    if (registered === undefined) {
      throw new Error(`client-modules: no registered factory for "${id}"`);
    }
    if (this.materializing.has(id)) {
      throw new Error(`client-modules: require cycle through "${id}"`);
    }
    this.materializing.add(id);
    try {
      const edges = new Set();
      const exports = registered(this.makeRequire(edges));
      const record = { id, exports, styles: claimStyles(id), edges };
      this.loadCache.set(id, record);
      return record;
    } finally {
      this.materializing.delete(id);
    }
  }

  makeRequire(edges) {
    return (spec) => {
      edges.add(spec);
      if (this.seed.has(spec)) return this.seed.get(spec);
      const id = stripClientSuffix(spec);
      const record = this.loadCache.get(id);
      if (record !== undefined) return record.exports;
      if (this.factories.has(id)) return this.materialize(id).exports;
      throw new Error(`client-modules: require("${spec}") missed module table`);
    };
  }

  async import(specifier) {
    if (this.seed.has(specifier)) return this.seed.get(specifier);
    const id = stripClientSuffix(specifier);
    const existing = this.loadCache.get(id);
    if (existing !== undefined) return existing.exports;

    const row = this.graphRows.get(id);
    if (row !== undefined) {
      await this.arriveGraphRow(row);
    } else if (!this.factories.has(id)) {
      throw new Error(`client-modules: cannot resolve "${specifier}"`);
    }
    return this.materialize(id).exports;
  }

  async prefetch(id) {
    const normalized = stripClientSuffix(id);
    if (this.loadCache.has(normalized)) return;
    const row = this.graphRows.get(normalized);
    if (row === undefined) return;
    await this.arriveGraphRow(row);
  }

  invalidate(id) {
    const normalized = stripClientSuffix(id);
    this.factories.delete(normalized);
    this.loadCache.delete(normalized);
  }
}
