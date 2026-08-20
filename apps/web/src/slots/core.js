/**
 * DeepSeek Harness SlotCore Engine (`@deepseek-ai/dsh-client-ui-slots/core`)
 * Pure slot registry core: slot declarations ledger, single/list/keyed/chain
 * contributions dispatch, load-time authorization validation, and cascading disposal.
 */

export class SlotCore {
  constructor() {
    // Declarations ledger: slotName -> { kind, scope, owner, children, declaringEntryId }
    this._declarations = new Map();
    // Contributions table: slotName -> StoredEntry[]
    this._contributions = new Map();
    // Listeners for slot mutations (for ui-renderer reactive updates)
    this._mutationListeners = new Set();
    // Listeners for declaration lifetime (for ctx.slots.inject)
    this._declarationListeners = new Map();
    // Monotonic epochs per slot declaration
    this._declarationEpochs = new Map();

    // Pre-seed 'root' slot: the shell's single root hole
    this._declarations.set("root", {
      name: "root",
      kind: "single",
      scope: "root",
      owner: {},
      declaringEntryId: "shell-seed",
    });
    this._declarationEpochs.set("root", 1);
  }

  onMutate(listener) {
    this._mutationListeners.add(listener);
    return () => this._mutationListeners.delete(listener);
  }

  _notifyMutate(slotName) {
    this._mutationListeners.forEach((fn) => {
      try {
        fn(slotName);
      } catch (e) {
        console.error("[SlotCore] Mutation listener error:", e);
      }
    });
  }

  _notifyDeclaration(slotName) {
    const listeners = this._declarationListeners.get(slotName);
    if (listeners) {
      listeners.forEach((fn) => {
        try {
          fn();
        } catch (e) {
          console.error("[SlotCore] Declaration listener error:", e);
        }
      });
    }
  }

  subscribeDeclaration(slotName, callback) {
    if (!this._declarationListeners.has(slotName)) {
      this._declarationListeners.set(slotName, new Set());
    }
    const set = this._declarationListeners.get(slotName);
    set.add(callback);
    return () => set.delete(callback);
  }

  declarationEpoch(slotName) {
    return this._declarationEpochs.get(slotName) || 0;
  }

  specOf(slotName) {
    return this._declarations.get(slotName);
  }

  specDynamic(slotName) {
    return this._declarations.get(slotName);
  }

  entriesOf(slotName) {
    return this._contributions.get(slotName) || [];
  }

  /**
   * Shadowing winners per cell for a slot:
   * - single: top entry
   * - list: all entries sorted by order
   * - keyed: map by entryKey
   * - chain: all entries with pure select() function
   */
  entriesOfSlot(slotName) {
    const all = this._contributions.get(slotName) || [];
    const spec = this._declarations.get(slotName);
    if (!spec) return [];

    if (spec.kind === "single") {
      return all.length > 0 ? [all[all.length - 1]] : [];
    }
    if (spec.kind === "list") {
      return [...all].sort((a, b) => (a.order || 0) - (b.order || 0));
    }
    if (spec.kind === "keyed") {
      const byKey = new Map();
      all.forEach((entry) => {
        if (entry.key) byKey.set(entry.key, entry);
      });
      return Array.from(byKey.values());
    }
    if (spec.kind === "chain") {
      return [...all].sort((a, b) => (a.priority || 0) - (b.priority || 0));
    }
    return all;
  }

  /**
   * Register a component into a declared slot.
   */
  register(options, component, context = null) {
    const {
      name,
      children = {},
      store = null,
      inject = null,
      key = null,
      order = 0,
      priority = 0,
      select = null,
      locale = null,
      id = `entry-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    } = options;

    if (!name) {
      throw new Error("Slot registration must specify a target slot 'name'.");
    }

    // 1. Validate that the target slot is declared
    const targetSpec = this._declarations.get(name);
    if (!targetSpec) {
      throw new Error(`Cannot register into undeclared slot '${name}'.`);
    }

    // 2. Validate chain slot select function
    if (targetSpec.kind === "chain" && typeof select !== "function") {
      throw new Error(`Chain slot registration into '${name}' requires a pure select(owner) function.`);
    }

    // 3. Validate and declare child slots
    const declaredChildNames = [];
    for (const [childName, childSpec] of Object.entries(children)) {
      if (this._declarations.has(childName)) {
        throw new Error(
          `Conflict: Child slot '${childName}' is already declared by entry '${this._declarations.get(childName).declaringEntryId}'.`
        );
      }
      this._declarations.set(childName, {
        name: childName,
        kind: childSpec.kind || "single",
        scope: childSpec.scope || targetSpec.scope || "root",
        owner: childSpec.owner || {},
        declaringEntryId: id,
      });
      this._declarationEpochs.set(childName, (this._declarationEpochs.get(childName) || 0) + 1);
      declaredChildNames.push(childName);
    }

    // 4. Stored Entry Record
    const storedEntry = {
      id,
      name,
      children,
      declaredChildNames,
      store,
      inject,
      key,
      order,
      priority,
      select,
      locale,
      component,
      context,
      targetScope: targetSpec.scope,
    };

    if (!this._contributions.has(name)) {
      this._contributions.set(name, []);
    }
    this._contributions.get(name).push(storedEntry);

    // Notify listeners
    this._notifyMutate(name);
    declaredChildNames.forEach((cn) => this._notifyDeclaration(cn));

    // 5. Return Reversible Disposer
    let disposed = false;
    return () => {
      if (disposed) return;
      disposed = true;

      // Remove contribution
      const list = this._contributions.get(name);
      if (list) {
        const idx = list.indexOf(storedEntry);
        if (idx !== -1) list.splice(idx, 1);
        if (list.length === 0) this._contributions.delete(name);
      }

      // Rollback child slot declarations and cascade contributions
      for (const childName of declaredChildNames) {
        this._declarations.delete(childName);
        this._declarationEpochs.set(childName, (this._declarationEpochs.get(childName) || 0) + 1);

        // Clear child contributions if any registered into this declared slot
        if (this._contributions.has(childName)) {
          this._contributions.delete(childName);
          this._notifyMutate(childName);
        }
        this._notifyDeclaration(childName);
      }

      this._notifyMutate(name);
    };
  }
}
