/**
 * DeepSeek Harness Web GUI SPA Entrypoint (`apps/web/src/main.js`)
 * Modular Cordis Slot Plugin Architecture & Reactive Downlink Router.
 */

import { ClientContext } from "./runtime/context.js";
import { SlotRegistry } from "./slots/registry.js";
import { createSlotRenderer } from "./slots/renderer.js";
import { SessionManager } from "./runtime/manager.js";
import { ApiClient } from "./connection/api.js";
import { DownlinkStream } from "./connection/sse.js";

// Import Cordis Client Plugins
import { PluginLayout } from "./plugins/plugin-layout.js";
import { PluginSidebar } from "./plugins/plugin-sidebar.js";
import { PluginNav } from "./plugins/plugin-nav.js";
import { PluginConversation } from "./plugins/plugin-conversation.js";
import { PluginTrajectory } from "./plugins/plugin-trajectory.js";
import { PluginTools } from "./plugins/plugin-tools.js";
import { PluginComposer } from "./plugins/plugin-composer.js";
import { PluginSettings } from "./plugins/plugin-settings.js";

class WebApplication {
  constructor() {
    this.ctx = new ClientContext();
  }

  async start() {
    // 1. Mount Core Services on Context
    const slotRegistry = new SlotRegistry(this.ctx);
    this.ctx.set_service("slots", slotRegistry);

    const slotRenderer = createSlotRenderer(this.ctx, slotRegistry);
    slotRegistry.install(slotRenderer);

    const sessionManager = new SessionManager(this.ctx);
    this.ctx.set_service("sessions", sessionManager);

    // 2. Mount UI Plugins on Context
    this.ctx.plugin(PluginLayout);
    this.ctx.plugin(PluginSidebar);
    this.ctx.plugin(PluginNav);
    this.ctx.plugin(PluginConversation);
    this.ctx.plugin(PluginTrajectory);
    this.ctx.plugin(PluginTools);
    this.ctx.plugin(PluginComposer);
    this.ctx.plugin(PluginSettings);

    // 3. Connect Downlink Stream (SSE)
    const downlink = new DownlinkStream({
      onSessionEvent: (ev) => {
        sessionManager.getCurrentSession().acceptLiveEvent(ev);
      },
      onSessionChunk: (chunk) => {
        sessionManager.getCurrentSession().handleChunk(chunk.data || chunk);
      },
      onAssistantChunk: (chunk) => {
        sessionManager.getCurrentSession().handleChunk(chunk.data || chunk);
      },
      onAgentStatus: (status) => {
        if (status && status.status === "running") {
          sessionManager.getCurrentSession().setRunning(true);
        } else if (status && status.status === "idle") {
          sessionManager.getCurrentSession().setRunning(false);
        }
      },
    });
    downlink.connect();

    // 4. Initial Bootstrap Data Fetch
    try {
      const status = await ApiClient.getStatus();
      if (status.cwd) {
        this.ctx.set_service("cwd", status.cwd);
      }
      const sessionListRes = await ApiClient.getSessions();
      if (sessionListRes && sessionListRes.sessions) {
        sessionManager.setSessionList(sessionListRes.sessions);
      }
      const currentHistory = await ApiClient.getHistory(sessionManager.currentSessionId);
      if (currentHistory && currentHistory.events) {
        sessionManager.getCurrentSession().setHistory(currentHistory.events);
      }
    } catch (err) {
      console.warn("[App] Initial fetch failed:", err);
    }

    // 5. Mount Root Slot Hierarchy into DOM
    const rootEl = document.getElementById("app") || document.body;
    this.ctx.slots.renderSlot("root", {}, rootEl);

    // Global tab switcher bridge for slot updates
    window._dshSwitchTab = (tab) => {
      if (tab === "trajectory") {
        const trajOutlet = document.querySelector("#slot-outlet-trajectory");
        if (trajOutlet) {
          slotRenderer.renderSlot("trajectory", {}, trajOutlet);
        }
      } else if (tab === "chat") {
        const convOutlet = document.querySelector("#slot-outlet-conversation");
        if (convOutlet) {
          slotRenderer.renderSlot("conversation", {}, convOutlet);
        }
      }
    };

    // 6. Subscribe to session changes for reactive UI updates
    sessionManager.subscribe(() => {
      // Trigger update on conversation & trajectory slot outlets
      const convOutlet = document.querySelector("#slot-outlet-conversation");
      if (convOutlet && !convOutlet.classList.contains("hidden")) {
        slotRenderer.renderSlot("conversation", {}, convOutlet);
      }
      const trajOutlet = document.querySelector("#slot-outlet-trajectory");
      if (trajOutlet && !trajOutlet.classList.contains("hidden")) {
        slotRenderer.renderSlot("trajectory", {}, trajOutlet);
      }
      const composerOutlet = document.querySelector("#slot-outlet-composer");
      if (composerOutlet) {
        // Keep composer state in sync with running bit
        const btnSend = composerOutlet.querySelector("#btn-composer-send");
        const btnStop = composerOutlet.querySelector("#btn-composer-stop");
        const isRunning = sessionManager.getCurrentSession().running;
        if (btnSend && btnStop) {
          if (isRunning) {
            btnSend.classList.add("hidden");
            btnStop.classList.remove("hidden");
          } else {
            btnSend.classList.remove("hidden");
            btnStop.classList.add("hidden");
          }
        }
      }
    });
  }
}

// Start application when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  const app = new WebApplication();
  app.start();
});
