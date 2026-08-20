/**
 * DeepSeek Harness Notifier (`@deepseek-ai/dsh-client-runtime/sessions/notifier`)
 * Multi-cadence observable notification engine:
 * - notifyNow: immediate synchronous dispatch for user gestures
 * - markDirty: microtask-batched dispatch for structural updates
 * - markFrameDirty: 60fps RAF-batched dispatch for visible streaming chunks
 */

export class Notifier {
  constructor() {
    this._listeners = new Set();
    this._dirtyMicrotask = false;
    this._dirtyFrame = false;
  }

  subscribe(listener) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  /**
   * Immediate synchronous notification (direct echo of user gestures).
   */
  notifyNow() {
    this._dirtyMicrotask = false;
    this._dirtyFrame = false;
    this._dispatch();
  }

  /**
   * Microtask-batched notification (structural state changes, session open, new turns).
   */
  markDirty() {
    if (this._dirtyMicrotask) return;
    this._dirtyMicrotask = true;

    queueMicrotask(() => {
      if (!this._dirtyMicrotask) return;
      this._dirtyMicrotask = false;
      this._dispatch();
    });
  }

  /**
   * Animation-frame-batched notification (high-frequency token/reasoning/tool chunk streaming).
   */
  markFrameDirty() {
    if (this._dirtyFrame) return;
    this._dirtyFrame = true;

    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => {
        if (!this._dirtyFrame) return;
        this._dirtyFrame = false;
        this._dispatch();
      });
    } else {
      setTimeout(() => {
        if (!this._dirtyFrame) return;
        this._dirtyFrame = false;
        this._dispatch();
      }, 16);
    }
  }

  _dispatch() {
    this._listeners.forEach((fn) => {
      try {
        fn();
      } catch (err) {
        console.error("[Notifier] Listener dispatch error:", err);
      }
    });
  }
}
