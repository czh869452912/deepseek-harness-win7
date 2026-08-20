/**
 * Core Slot System (`@deepseek-ai/dsh-client-ui-slots`).
 * 1:1 Implementation of SlotCore, SlotKind (single, list, keyed, chain),
 * Cell Shadowing, Monotonic Epochs, and SlotOutlet dispatch.
 */

export function resolveSlotLabel(label) {
  return typeof label === "function" ? label() : label;
}

export class SlotCore {
  constructor() {
    this.records = new Map();
    this.mutateListeners = new Set();
    this.dirty = new Set();
    this.flushScheduled = false;
    this.abdicated = new WeakSet();
    this.entryErrorListeners = new Set();

    // Built-in root slot
    const root = this._record("root");
    root.spec = { kind: "single", scope: "root" };
    root.declaredBy = "(built-in)";
    root.declarationEpoch = 1;
  }

  _record(key) {
    if (!this.records.has(key)) {
      this.records.set(key, {
        spec: undefined,
        declaredBy: undefined,
        parent: undefined,
        declarationEpoch: 0,
        entries: [],
        version: 0,
        listeners: new Set(),
        declarationListeners: new Set(),
      });
    }
    return this.records.get(key);
  }

  register(options, component) {
    const name = options.name;
    const rec = this._record(name);
    if (!rec.spec) {
      // Auto-declare if root or child
      rec.spec = { kind: options.kind || "single", scope: options.scope || "root" };
    }

    const priority = options.priority ?? 0;
    const entry = {
      component,
      options: {
        key: options.key,
        id: options.id,
        order: options.order,
        label: options.label,
        priority,
      },
      select: options.select,
      inject: options.inject,
      children: options.children,
      store: options.store,
      locale: options.locale,
      registrant: options.registrant,
    };

    // Register child slot declarations
    const childDisposers = [];
    if (options.children) {
      for (const [childKey, childSpec] of Object.entries(options.children)) {
        const childRec = this._record(childKey);
        childRec.spec = childSpec;
        childRec.declaredBy = name;
        childRec.parent = name;
        childRec.declarationEpoch += 1;
        childDisposers.push(() => {
          childRec.spec = undefined;
          childRec.entries = [];
          childRec.version += 1;
          this._notify(childKey);
        });
      }
    }

    rec.entries = [...rec.entries, entry];
    rec.version += 1;
    this._notify(name);

    let disposed = false;
    return () => {
      if (disposed) return;
      disposed = true;
      rec.entries = rec.entries.filter((e) => e !== entry);
      rec.version += 1;
      this._notify(name);
      for (const cd of childDisposers) cd();
    };
  }

  entriesOfSlot(name) {
    const rec = this.records.get(name);
    if (!rec || !rec.spec) return [];
    const kind = rec.spec.kind;
    const liveEntries = rec.entries.filter((e) => !this.abdicated.has(e));

    if (kind === "single") {
      if (liveEntries.length === 0) return [];
      // Lowest priority renders
      const sorted = [...liveEntries].sort((a, b) => (a.options.priority ?? 0) - (b.options.priority ?? 0));
      return [sorted[0]];
    }

    if (kind === "list") {
      const byId = new Map();
      for (const e of liveEntries) {
        const id = e.options.id || "item";
        if (!byId.has(id) || (e.options.priority ?? 0) < (byId.get(id).options.priority ?? 0)) {
          byId.set(id, e);
        }
      }
      return Array.from(byId.values()).sort((a, b) => (a.options.order ?? 0) - (b.options.order ?? 0));
    }

    if (kind === "keyed") {
      const byKey = new Map();
      for (const e of liveEntries) {
        const k = e.options.key;
        if (!byKey.has(k) || (e.options.priority ?? 0) < (byKey.get(k).options.priority ?? 0)) {
          byKey.set(k, e);
        }
      }
      return Array.from(byKey.values());
    }

    if (kind === "chain") {
      return [...liveEntries].sort((a, b) => (a.options.priority ?? 0) - (b.options.priority ?? 0));
    }

    return liveEntries;
  }

  subscribe(name, listener) {
    const rec = this._record(name);
    rec.listeners.add(listener);
    return () => rec.listeners.delete(listener);
  }

  _notify(name) {
    const rec = this.records.get(name);
    if (rec) {
      for (const l of Array.from(rec.listeners)) {
        try {
          l();
        } catch (e) {
          console.warn("[SlotCore] Listener threw:", e);
        }
      }
    }
    for (const ml of Array.from(this.mutateListeners)) {
      try {
        ml(name);
      } catch (e) {}
    }
  }

  onMutate(listener) {
    this.mutateListeners.add(listener);
    return () => this.mutateListeners.delete(listener);
  }
}

export class SlotRegistry {
  constructor(ctx) {
    this.ctx = ctx;
    this.core = new SlotCore();
    this.renderer = null;
  }

  install(renderer) {
    this.renderer = renderer;
  }

  register(options, component) {
    const disposer = this.core.register(options, component);
    if (this.ctx && typeof this.ctx.effect === "function") {
      this.ctx.effect(() => disposer, `slot registration: ${options.name}`);
    }
    return disposer;
  }

  entriesOfSlot(name) {
    return this.core.entriesOfSlot(name);
  }

  subscribe(name, listener) {
    return this.core.subscribe(name, listener);
  }

  renderSlot(name, ownerProps = {}, container = null) {
    if (this.renderer) {
      return this.renderer.renderSlot(name, ownerProps, container);
    }
    return null;
  }

  renderSlotChain(name, ownerProps = {}, opts = {}) {
    if (this.renderer) {
      return this.renderer.renderSlotChain(name, ownerProps, opts);
    }
    return null;
  }
}
