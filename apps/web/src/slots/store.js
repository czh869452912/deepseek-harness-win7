/**
 * DeepSeek Harness Client Store Engine (`@deepseek-ai/dsh-client-ui-slots/store`)
 * Framework-neutral snapshot store engine: defineStore, draft-action transforms,
 * subscribe/getSnapshot observable pattern, and scope-isolated persistence.
 */

export function defineStore(spec) {
  const { init, persist, actions = {} } = spec;

  return {
    spec,
    create(scopeKey) {
      const storageKey = persist ? (scopeKey ? `${persist}.${scopeKey}` : persist) : null;

      let state = (() => {
        if (storageKey) {
          try {
            const saved = localStorage.getItem(storageKey);
            if (saved) return JSON.parse(saved);
          } catch (e) {}
        }
        return typeof init === "function" ? init() : { ...init };
      })();

      const listeners = new Set();

      function getSnapshot() {
        return state;
      }

      function subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      }

      function notify() {
        if (storageKey) {
          try {
            localStorage.setItem(storageKey, JSON.stringify(state));
          } catch (e) {}
        }
        listeners.forEach((fn) => {
          try {
            fn(state);
          } catch (err) {
            console.error("[Store] listener error:", err);
          }
        });
      }

      function clearPersisted() {
        if (storageKey) {
          try {
            localStorage.removeItem(storageKey);
          } catch (e) {}
        }
      }

      // Bake action methods
      const bakedActions = {};
      for (const [actionName, actionFn] of Object.entries(actions)) {
        bakedActions[actionName] = (...params) => {
          const draft = Array.isArray(state) ? [...state] : { ...state };
          const result = actionFn(draft, ...params);
          state = result !== undefined ? result : draft;
          notify();
        };
      }

      return {
        getSnapshot,
        subscribe,
        clearPersisted,
        actions: bakedActions,
      };
    },
  };
}
