/**
 * UI Renderer Plugin (`@deepseek-ai/dsh-client-ui-renderer`).
 * 1:1 Mounts root slot into DOM container and drives reactive slot re-renders.
 */

import { SlotRegistry } from "../ui-slots/core.js";

export class UiRendererService {
  constructor(ctx) {
    this.ctx = ctx;
    this.container = null;
  }

  mount(container) {
    this.container = container;
    const slots = this.ctx.get("slots");
    if (!slots) {
      throw new Error("ui-renderer: slots service unavailable");
    }

    // Initial render of root slot
    this.render();

    // Subscribe to root mutations
    slots.core.subscribe("root", () => {
      this.render();
    });
  }

  render() {
    if (!this.container) return;
    const slots = this.ctx.get("slots");
    if (slots) {
      slots.renderSlot("root", {}, this.container);
    }
  }
}

export class UiRendererPlugin {
  static inject = ["slots"];

  apply(ctx) {
    const service = new UiRendererService(ctx);
    ctx.set_service("uiRenderer", service);
    ctx.set_service("ui_renderer", service);
  }
}
