/**
 * Slot DOM Renderer Engine (`@deepseek-ai/dsh-client-ui-slots/renderer`).
 * 1:1 Rendering of Slot entries, recursive children slots, and chain selector matching.
 */

export function createSlotRenderer(ctx, registry) {
  const activeMounts = new Map(); // container -> { name, props, cleanup }

  function renderSlot(name, ownerProps = {}, container = null) {
    const entries = registry.entriesOfSlot(name);
    const elements = [];

    for (const entry of entries) {
      const childProps = {
        ...ownerProps,
        ...(entry.options.key ? { key: entry.options.key } : {}),
        renderSlot: (childName, childOwnerProps = {}, childContainer = null) => {
          return renderSlot(childName, childOwnerProps, childContainer);
        },
        renderSlotChain: (childName, childOwnerProps = {}, opts = {}) => {
          return renderSlotChain(childName, childOwnerProps, opts);
        },
      };

      // Handle inject face
      if (typeof entry.inject === "function") {
        try {
          const injected = entry.inject(childProps);
          Object.assign(childProps, injected);
        } catch (err) {
          console.warn(`[SlotRenderer] Inject failed for ${name}:`, err);
        }
      }

      if (typeof entry.component === "function") {
        try {
          const res = entry.component(childProps);
          if (res instanceof HTMLElement) {
            elements.push(res);
          } else if (typeof res === "string") {
            const temp = document.createElement("div");
            temp.innerHTML = res.trim();
            while (temp.firstChild) {
              elements.push(temp.firstChild);
            }
          }
        } catch (err) {
          console.error(`[SlotRenderer] Error rendering component in slot "${name}":`, err);
        }
      }
    }

    if (container instanceof HTMLElement) {
      container.innerHTML = "";
      for (const el of elements) {
        container.appendChild(el);
      }
    }

    return elements;
  }

  function renderSlotChain(name, ownerProps = {}, opts = {}) {
    const entries = registry.entriesOfSlot(name);
    for (const entry of entries) {
      if (typeof entry.select === "function") {
        try {
          const matched = entry.select(ownerProps);
          if (matched !== null && matched !== undefined) {
            const childProps = {
              ...ownerProps,
              matched,
              renderSlot: (cName, cProps = {}, cContainer = null) => renderSlot(cName, cProps, cContainer),
              renderSlotChain: (cName, cProps = {}, cOpts = {}) => renderSlotChain(cName, cProps, cOpts),
            };
            if (typeof entry.component === "function") {
              return entry.component(childProps);
            }
          }
        } catch (err) {
          console.warn(`[SlotRenderer] Chain selector error in ${name}:`, err);
        }
      }
    }
    return opts.fallback || null;
  }

  return {
    renderSlot,
    renderSlotChain,
  };
}
