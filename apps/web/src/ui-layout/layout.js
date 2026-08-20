/**
 * App Layout Plugin (`@deepseek-ai/dsh-client-ui-layout`).
 * 1:1 Implementation of 3-column AppFrame, Panel Controllers, and Layout Slots.
 */

export class LayoutController {
  constructor() {
    this.sidebarCollapsed = false;
    this.detailsOpen = false;
    this.listeners = new Set();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify() {
    for (const l of Array.from(this.listeners)) l();
  }

  toggleSidebar() {
    this.sidebarCollapsed = !this.sidebarCollapsed;
    this.notify();
  }

  toggleDetails() {
    this.detailsOpen = !this.detailsOpen;
    this.notify();
  }

  openDetails() {
    this.detailsOpen = true;
    this.notify();
  }

  closeDetails() {
    this.detailsOpen = false;
    this.notify();
  }
}

export function AppFrame(props) {
  const { renderSlot, layout } = props;
  const isCollapsed = layout ? layout.sidebarCollapsed : false;
  const isDetailsOpen = layout ? layout.detailsOpen : false;

  const frameEl = document.createElement("div");
  frameEl.className = "app-layout-frame";

  // 1. Sidebar Column
  const sidebarCol = document.createElement("aside");
  sidebarCol.className = `layout-col-sidebar ${isCollapsed ? "collapsed" : ""}`;
  sidebarCol.id = "slot-outlet-sidebar";
  renderSlot("sidebar", { collapsed: isCollapsed, width: isCollapsed ? 60 : 260 }, sidebarCol);

  // 2. Main Conversation Column
  const convCol = document.createElement("main");
  convCol.className = "layout-col-conversation";
  convCol.id = "slot-outlet-conversation";
  renderSlot("conversation", {}, convCol);

  // 3. Details Column (Trajectory / Diagnostics)
  const detailsCol = document.createElement("aside");
  detailsCol.className = `layout-col-details ${isDetailsOpen ? "open" : "hidden"}`;
  detailsCol.id = "slot-outlet-details";
  if (isDetailsOpen) {
    renderSlot("details", {}, detailsCol);
  }

  // 4. Shell Floating Overlay Layer
  const overlayLayer = document.createElement("div");
  overlayLayer.className = "layout-layer-overlay";
  overlayLayer.id = "slot-outlet-overlay";
  renderSlot("shell.overlay", {}, overlayLayer);

  frameEl.appendChild(sidebarCol);
  frameEl.appendChild(convCol);
  frameEl.appendChild(detailsCol);
  frameEl.appendChild(overlayLayer);

  return frameEl;
}

export class UiLayoutPlugin {
  static inject = ["slots"];

  apply(ctx) {
    const layout = new LayoutController();
    ctx.set_service("layout", layout);

    const slots = ctx.get("slots");
    slots.register({
      name: "root",
      children: {
        "sidebar": { kind: "single", scope: "root" },
        "conversation": { kind: "single", scope: "session-maybe" },
        "details": { kind: "single", scope: "session" },
        "shell.overlay": { kind: "list", scope: "root" },
      },
      inject: () => ({ layout }),
    }, AppFrame);

    layout.subscribe(() => {
      // Re-render root on layout state change
      const rootContainer = document.getElementById("app") || document.body;
      slots.renderSlot("root", {}, rootContainer);
    });
  }
}
