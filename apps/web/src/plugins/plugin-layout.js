/**
 * Layout Frame Plugin (`@deepseek-ai/dsh-client-ui-layout`)
 * Declares the application root layout frame, sidebar, conversation, trajectory,
 * header nav, composer, and shell overlay slots.
 */

import { defineStore } from "../slots/store.js";

export function createLayoutStore() {
  return defineStore({
    init: () => ({
      sidebarCollapsed: false,
      activeTab: "chat", // 'chat' | 'trajectory'
      theme: localStorage.getItem("dsh_theme") || "dark",
      settingsOpen: false,
    }),
    actions: {
      toggleSidebar: (draft) => {
        draft.sidebarCollapsed = !draft.sidebarCollapsed;
      },
      setActiveTab: (draft, tab) => {
        draft.activeTab = tab;
      },
      toggleTheme: (draft) => {
        draft.theme = draft.theme === "light" ? "dark" : "light";
        localStorage.setItem("dsh_theme", draft.theme);
      },
      setSettingsOpen: (draft, open) => {
        draft.settingsOpen = Boolean(open);
      },
    },
  });
}

export class PluginLayout {
  static id = "ui-layout";
  static name = "@deepseek-ai/dsh-client-ui-layout";

  apply(ctx) {
    const layoutStore = createLayoutStore();

    ctx.slots.register(
      {
        name: "root",
        children: {
          sidebar: { kind: "single", scope: "root" },
          "header.nav": { kind: "single", scope: "root" },
          conversation: { kind: "single", scope: "session" },
          trajectory: { kind: "single", scope: "session" },
          composer: { kind: "single", scope: "session" },
          "shell.overlay": { kind: "list", scope: "root" },
        },
        store: layoutStore,
        inject: (injectCtx, { actions }) => ({
          onToggleSidebar: () => actions.toggleSidebar(),
          onSwitchTab: (tab) => actions.setActiveTab(tab),
          onToggleTheme: () => actions.toggleTheme(),
          onOpenSettings: () => actions.setSettingsOpen(true),
          onCloseSettings: () => actions.setSettingsOpen(false),
        }),
      },
      AppFrame
    );
  }
}

class AppFrame {
  constructor(props) {
    this.props = props;
  }

  render(container) {
    const { useStore, renderSlot } = this.props;
    const state = useStore();

    container.className = `app-layout ${state.sidebarCollapsed ? "sidebar-collapsed" : ""}`;
    container.innerHTML = `
      <!-- Left Sidebar Slot Outlet -->
      <aside class="sidebar ${state.sidebarCollapsed ? "collapsed" : ""}" id="slot-outlet-sidebar"></aside>

      <!-- Main Viewport -->
      <main class="main-viewport">
        <!-- Top Nav Slot Outlet -->
        <header class="top-nav-bar" id="slot-outlet-nav"></header>

        <!-- Viewport Slots (Chat & Trajectory) -->
        <div class="view-content-area" style="flex:1; display:flex; flex-direction:column; overflow:hidden; position:relative;">
          <section class="messages-container ${state.activeTab === "chat" ? "" : "hidden"}" id="slot-outlet-conversation"></section>
          <section class="trajectory-container ${state.activeTab === "trajectory" ? "" : "hidden"}" id="slot-outlet-trajectory"></section>
        </div>

        <!-- Bottom Composer Slot Outlet -->
        <footer class="composer-shell" id="slot-outlet-composer"></footer>
      </main>

      <!-- Shell Overlay Slot Outlet (Modals, Popovers) -->
      <div id="slot-outlet-overlay"></div>
    `;

    // Apply theme
    document.body.className = state.theme === "light" ? "theme-light" : "theme-dark";

    // Render child slots into their designated outlets
    const sidebarEl = container.querySelector("#slot-outlet-sidebar");
    const navEl = container.querySelector("#slot-outlet-nav");
    const convEl = container.querySelector("#slot-outlet-conversation");
    const trajEl = container.querySelector("#slot-outlet-trajectory");
    const composerEl = container.querySelector("#slot-outlet-composer");
    const overlayEl = container.querySelector("#slot-outlet-overlay");

    renderSlot("sidebar", {}, sidebarEl);
    renderSlot("header.nav", {}, navEl);
    renderSlot("conversation", {}, convEl);
    renderSlot("trajectory", {}, trajEl);
    renderSlot("composer", {}, composerEl);
    renderSlot("shell.overlay", {}, overlayEl);

    return container;
  }
}
