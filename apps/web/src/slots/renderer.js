/**
 * DeepSeek Harness DOM SlotRenderer (`@deepseek-ai/dsh-client-ui-renderer`)
 * Mounts the declared Slot hierarchy into the DOM with 4-share Props composition:
 * PropsRuntime, PropsRenderSlots, PropsStore, and InjectFace.
 */

export class DOMSlotRenderer {
  constructor(ctx, slotRegistry) {
    this.ctx = ctx;
    this.registry = slotRegistry;
    this.core = slotRegistry.core;
    this.rootContainer = null;
    this._mountedOutlets = new Map(); // outletId -> OutletInstance

    // Subscribe to slot structure mutations
    this.core.onMutate((slotName) => {
      this._updateOutletsForSlot(slotName);
    });
  }

  renderRoot(ownerProps = {}, container = null) {
    this.rootContainer = container || document.getElementById("app") || document.body;
    return this.renderSlot("root", ownerProps, this.rootContainer);
  }

  /**
   * Render a slot into a parent DOM container.
   */
  renderSlot(slotName, ownerProps = {}, targetContainer = null, opts = {}) {
    const spec = this.core.specOf(slotName);
    if (!spec) {
      if (opts.fallback) {
        if (typeof opts.fallback === "string") {
          targetContainer.innerHTML = opts.fallback;
        } else if (opts.fallback instanceof Node) {
          targetContainer.innerHTML = "";
          targetContainer.appendChild(opts.fallback);
        }
      }
      return;
    }

    const entries = this.core.entriesOfSlot(slotName);
    if (!targetContainer) {
      targetContainer = document.createElement("div");
      targetContainer.className = `slot-outlet slot-${slotName.replace(/\./g, "-")}`;
    }

    const outletId = `outlet-${slotName}-${Math.random().toString(36).slice(2, 7)}`;
    const outlet = {
      id: outletId,
      slotName,
      spec,
      ownerProps,
      container: targetContainer,
      opts,
      mountedComponents: [],
    };

    this._mountedOutlets.set(outletId, outlet);
    this._mountOutlet(outlet, entries);

    return targetContainer;
  }

  /**
   * Render a chain slot with select-based takeover.
   */
  renderSlotChain(slotName, ownerProps = {}, opts = {}, targetContainer = null) {
    return this.renderSlot(slotName, ownerProps, targetContainer, {
      ...opts,
      isChain: true,
    });
  }

  _mountOutlet(outlet, entries) {
    const { slotName, spec, ownerProps, container, opts } = outlet;
    container.innerHTML = "";
    outlet.mountedComponents = [];

    if (entries.length === 0) {
      if (opts && opts.fallback) {
        if (typeof opts.fallback === "string") container.innerHTML = opts.fallback;
        else if (opts.fallback instanceof Node) container.appendChild(opts.fallback);
      }
      return;
    }

    // 1. Single Slot
    if (spec.kind === "single") {
      const winner = entries[0];
      if (winner) {
        this._renderEntryInto(winner, ownerProps, container, outlet);
      }
      return;
    }

    // 2. List Slot
    if (spec.kind === "list") {
      entries.forEach((entry) => {
        const itemWrapper = document.createElement("div");
        itemWrapper.className = `slot-list-item item-${entry.id}`;
        container.appendChild(itemWrapper);
        this._renderEntryInto(entry, ownerProps, itemWrapper, outlet);
      });
      return;
    }

    // 3. Keyed Slot
    if (spec.kind === "keyed") {
      const targetKey = opts.entryKey;
      const match = entries.find((e) => e.key === targetKey) || entries[0];
      if (match) {
        this._renderEntryInto(match, ownerProps, container, outlet);
      }
      return;
    }

    // 4. Chain Slot
    if (spec.kind === "chain") {
      let matchedEntry = null;
      let matchedData = null;

      for (const entry of entries) {
        if (typeof entry.select === "function") {
          const matchResult = entry.select(ownerProps);
          if (matchResult !== null && matchResult !== undefined) {
            matchedEntry = entry;
            matchedData = matchResult;
            break;
          }
        }
      }

      if (matchedEntry) {
        this._renderEntryInto(
          matchedEntry,
          { ...ownerProps, matched: matchedData },
          container,
          outlet
        );
      } else if (opts && opts.fallback) {
        if (typeof opts.fallback === "string") container.innerHTML = opts.fallback;
        else if (opts.fallback instanceof Node) container.appendChild(opts.fallback);
      }
    }
  }

  _renderEntryInto(entry, ownerProps, container, outlet) {
    const Component = entry.component;
    if (!Component) return;

    // 1. Resolve Session Context
    const sessionMgr = this.ctx ? this.ctx.get("sessions") : null;
    const currentSession = sessionMgr && typeof sessionMgr.getCurrentSession === "function"
      ? sessionMgr.getCurrentSession()
      : null;
    const sessionId = currentSession ? currentSession.id : "default-session";

    // 2. Resolve Store Props Share
    let storeProps = {};
    if (entry.store) {
      const storeInst = this.registry.getStoreInstance(
        entry.store,
        entry.targetScope || "root",
        sessionId
      );
      if (storeInst) {
        storeProps = {
          useStore: (selector = (s) => s) => selector(storeInst.getSnapshot()),
          actions: storeInst.actions,
        };
      }
    }

    // 3. Resolve Injected Business Props Share
    let injectProps = {};
    if (typeof entry.inject === "function") {
      try {
        const rawInject = entry.inject(this.ctx, {
          sessionId,
          actions: storeProps.actions || {},
          owner: ownerProps,
        }) || {};

        // Bind any bare observable hooks into use<HookName>
        const boundHooks = {};
        if (rawInject.hooks && typeof rawInject.hooks === "object") {
          for (const [hookName, obs] of Object.entries(rawInject.hooks)) {
            const capitalized = hookName.charAt(0).toUpperCase() + hookName.slice(1);
            boundHooks[`use${capitalized}`] = (sel = (v) => v) =>
              obs && typeof obs.getSnapshot === "function" ? sel(obs.getSnapshot()) : undefined;
          }
        }

        injectProps = {
          ...rawInject,
          ...boundHooks,
        };
      } catch (err) {
        console.error(`[SlotRenderer] Inject failed for entry '${entry.id}':`, err);
      }
    }

    // 4. Resolve PropsRenderSlots Share
    const renderSlotsShare = {
      renderSlot: (childName, childOwner = {}, customContainer = null) => {
        return this.renderSlot(childName, childOwner, customContainer);
      },
      renderSlotChain: (childName, childOwner = {}, opts = {}, customContainer = null) => {
        return this.renderSlotChain(childName, childOwner, opts, customContainer);
      },
    };

    // 5. Resolve PropsRuntime Share
    const runtimeShare = {
      sessionId,
      useSession: (selector = (s) => s) =>
        currentSession && typeof currentSession.getSnapshot === "function"
          ? selector(currentSession.getSnapshot())
          : null,
      useSessions: (selector = (s) => s) =>
        sessionMgr && typeof sessionMgr.getSessionsSnapshot === "function"
          ? selector(sessionMgr.getSessionsSnapshot())
          : [],
      useWorkspaces: () => ({ cwd: (this.ctx && this.ctx.get("cwd")) || "" }),
    };

    // 6. Compose 4-Share Props
    const composedProps = {
      ...runtimeShare,
      ...ownerProps,
      ...renderSlotsShare,
      ...storeProps,
      ...injectProps,
    };

    // 7. Mount Component
    try {
      if (typeof Component === "function") {
        if (Component.prototype && Component.prototype.render) {
          // Class-based component
          const instance = new Component(composedProps);
          const node = instance.render(container);
          if (node instanceof Node && !container.contains(node)) {
            container.appendChild(node);
          }
          outlet.mountedComponents.push(instance);
        } else {
          // Function component returning DOM Element or HTML string
          const output = Component(composedProps);
          if (output instanceof Node) {
            container.appendChild(output);
          } else if (typeof output === "string") {
            container.innerHTML = output;
          }
        }
      }
    } catch (renderError) {
      console.error(`[SlotRenderer] Component render error for entry '${entry.id}':`, renderError);
      container.innerHTML = `<div class="slot-error-boundary">⚠ 组件渲染错误: ${renderError.message}</div>`;
    }
  }

  _updateOutletsForSlot(slotName) {
    this._mountedOutlets.forEach((outlet) => {
      if (outlet.slotName === slotName) {
        const entries = this.core.entriesOfSlot(slotName);
        this._mountOutlet(outlet, entries);
      }
    });
  }
}

export function createSlotRenderer(ctx, slotRegistry) {
  return new DOMSlotRenderer(ctx, slotRegistry);
}
