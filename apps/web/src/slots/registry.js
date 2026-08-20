/**
 * DeepSeek Harness SlotRegistry Service (`@deepseek-ai/dsh-client-runtime/slots`)
 * Cordis Service layer of the slot system: wraps SlotCore, manages store instance
 * scopes (root vs per-session), declaration injection (ctx.slots.inject), and renderer installation.
 */

import { SlotCore } from "./core.js";

const ROOT_INSTANCE_KEY = "root";

export class SlotRegistry {
  constructor(ctx) {
    this.ctx = ctx;
    this._core = new SlotCore();
    this._renderer = null;

    // Store axis: storeHandle -> { scope, instances: Map<scopeKey, StoreInstance> }
    this._storeInstances = new Map();

    this._core.onMutate((slotName) => {
      if (this.ctx && typeof this.ctx.emit === "function") {
        this.ctx.emit("slots/changed", slotName);
      }
    });
  }

  /**
   * Primary slot registration API.
   */
  register(options, component) {
    let storeHandle = options.store;
    if (typeof storeHandle === "function") {
      // Execute factory once to get handle
      storeHandle = storeHandle();
    }

    const normalizedOpts = {
      ...options,
      store: storeHandle,
    };

    const disposer = this._core.register(normalizedOpts, component, this.ctx);

    if (this.ctx && typeof this.ctx.effect === "function") {
      this.ctx.effect(() => disposer);
    }

    return disposer;
  }

  /**
   * Observe declaration lifetime of a slot.
   * Runs callback whenever the slot is declared into existence; rolls back when collapsed.
   */
  inject(slotName, callback) {
    let activeDisposer = null;
    let activeEpoch = -1;

    const reconcile = () => {
      const isDeclared = Boolean(this._core.specDynamic(slotName));
      const epoch = this._core.declarationEpoch(slotName);

      if (isDeclared && activeEpoch !== epoch) {
        if (activeDisposer) {
          activeDisposer();
          activeDisposer = null;
        }
        activeEpoch = epoch;
        try {
          const res = callback();
          if (typeof res === "function") {
            activeDisposer = res;
          } else if (res && typeof res[Symbol.iterator] === "function") {
            const list = Array.from(res);
            activeDisposer = () => {
              for (let i = list.length - 1; i >= 0; i--) {
                if (typeof list[i] === "function") list[i]();
              }
            };
          }
        } catch (e) {
          console.error(`[SlotRegistry] inject('${slotName}') callback failed:`, e);
        }
      } else if (!isDeclared && activeDisposer) {
        activeDisposer();
        activeDisposer = null;
        activeEpoch = -1;
      }
    };

    const unsubscribe = this._core.subscribeDeclaration(slotName, reconcile);
    reconcile();

    const stop = () => {
      unsubscribe();
      if (activeDisposer) {
        activeDisposer();
        activeDisposer = null;
      }
    };

    if (this.ctx && typeof this.ctx.effect === "function") {
      this.ctx.effect(() => stop);
    }

    return stop;
  }

  /**
   * Install the active SlotRenderer host.
   */
  install(renderer) {
    if (this._renderer) {
      console.warn("[SlotRegistry] Overwriting installed slot renderer.");
    }
    this._renderer = renderer;
  }

  /**
   * Single ctx-level render entry point for 'root'.
   */
  renderSlot(name, ownerProps = {}, targetContainer = null) {
    if (name !== "root") {
      throw new Error(
        `ctx.slots.renderSlot only renders 'root' (got "${name}"). Child slots render through component props.`
      );
    }
    if (!this._renderer) {
      throw new Error("Slot renderer not installed. Call ctx.slots.install(renderer) first.");
    }
    return this._renderer.renderRoot(ownerProps, targetContainer);
  }

  /**
   * Get or instantiate a StoreInstance for a store handle under the given scope.
   */
  getStoreInstance(handle, scope = "root", sessionId = null) {
    if (!handle || typeof handle.create !== "function") return null;

    if (!this._storeInstances.has(handle)) {
      this._storeInstances.set(handle, {
        scope,
        instances: new Map(),
      });
    }

    const entry = this._storeInstances.get(handle);
    const instanceKey = scope === "session" && sessionId ? sessionId : ROOT_INSTANCE_KEY;

    if (!entry.instances.has(instanceKey)) {
      const instance = handle.create(instanceKey);
      entry.instances.set(instanceKey, instance);
    }

    return entry.instances.get(instanceKey);
  }

  /**
   * Clear session-scoped store instances when a session is closed or destroyed.
   */
  clearSessionStores(sessionId) {
    this._storeInstances.forEach((entry) => {
      if (entry.scope === "session" && entry.instances.has(sessionId)) {
        const inst = entry.instances.get(sessionId);
        if (inst && typeof inst.clearPersisted === "function") {
          inst.clearPersisted();
        }
        entry.instances.delete(sessionId);
      }
    });
  }

  get core() {
    return this._core;
  }
}
