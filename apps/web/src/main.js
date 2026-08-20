/**
 * DeepSeek Harness Web GUI SPA Entrypoint (`apps/web/src/main.js`).
 * Cordis in Browser Microkernel, Modular Slot Architecture, and Dual-stream Router.
 */

import { AppWebEntry } from "./kernel/boot.js";
import { SlotRegistry } from "./ui-slots/core.js";
import { createSlotRenderer } from "./ui-slots/renderer.js";
import { UiRendererPlugin } from "./ui-renderer/renderer.js";
import { SessionManager } from "./runtime/manager.js";
import { ApiClient } from "./connection/api.js";
import { ConnectionController } from "./connection/controller.js";

// Core UI Plugins
import { UiLayoutPlugin } from "./ui-layout/layout.js";
import { PluginSidebar } from "./plugins/plugin-sidebar.js";
import { PluginConversation } from "./plugins/plugin-conversation.js";
import { PluginComposer } from "./plugins/plugin-composer.js";
import { PluginUserQuestions } from "./plugins/plugin-user-questions.js";
import { PluginPermissions } from "./plugins/plugin-permissions.js";
import { PluginGoal } from "./plugins/plugin-goal.js";
import { PluginTrajectory } from "./plugins/plugin-trajectory.js";
import { PluginSettings } from "./plugins/plugin-settings.js";

class WebApplication {
  constructor(container) {
    this.container = container;
    this.boot = new AppWebEntry(container);
  }

  async start() {
    // 1. Run Boot Kernel (instantiates Cordis Context & loads dynamic manifests)
    await this.boot.run();
    const ctx = this.boot.ctx;
    if (!ctx) return;

    // 2. Mount Base Slot & Renderer Services
    const slotRegistry = new SlotRegistry(ctx);
    ctx.set_service("slots", slotRegistry);

    const slotRenderer = createSlotRenderer(ctx, slotRegistry);
    slotRegistry.install(slotRenderer);

    const sessionManager = new SessionManager(ctx);
    ctx.set_service("sessions", sessionManager);

    // 3. Mount UI Plugins onto Browser Context
    await ctx.plugin(UiRendererPlugin);
    await ctx.plugin(UiLayoutPlugin);
    await ctx.plugin(PluginSidebar);
    await ctx.plugin(PluginConversation);
    await ctx.plugin(PluginComposer);
    await ctx.plugin(PluginUserQuestions);
    await ctx.plugin(PluginPermissions);
    await ctx.plugin(PluginGoal);
    await ctx.plugin(PluginTrajectory);
    await ctx.plugin(PluginSettings);

    // 4. Start Dual Streams Connection Controller (events.mux + events.host)
    const connection = new ConnectionController(
      {
        describe: () => ApiClient.getStatus(),
      },
      {
        onMuxEnvelope: (frame) => {
          if (frame.type === "session/event") {
            const sid = frame.sessionId || sessionManager.currentSessionId;
            sessionManager.getSession(sid).acceptLiveEvent(frame.event);
          } else if (frame.type === "session/subscribed") {
            // Reconcile sequence
          } else if (frame.type === "question/requested" || frame.type === "question/resolved") {
            ctx.emit(frame.type, frame);
          } else if (frame.type === "approval/requested" || frame.type === "approval/resolved") {
            ctx.emit(frame.type, frame);
          } else if (frame.type === "session/projection") {
            if (frame.key === "goal") {
              ctx.emit("goal/changed", frame.value);
            }
          }
        },
        onHostEnvelope: (frame) => {
          if (frame.type === "host/session-status") {
            sessionManager.getSession(frame.sessionId).setRunning(frame.running);
          } else if (frame.type === "host/session-added") {
            ApiClient.getSessions().then((res) => {
              if (res && res.sessions) sessionManager.setSessionList(res.sessions);
            }).catch(() => {});
          }
        },
        onConnected: () => {
          console.log("[Connection] Connected to DeepSeek Harness Host successfully.");
        },
      }
    );
    connection.start();

    // 5. Initial Data Fetch
    try {
      const status = await ApiClient.getStatus();
      if (status && status.cwd) {
        ctx.set_service("cwd", status.cwd);
      }
      const sessionListRes = await ApiClient.getSessions();
      if (sessionListRes && (sessionListRes.sessions || sessionListRes.items)) {
        sessionManager.setSessionList(sessionListRes.sessions || sessionListRes.items);
      }
      const currentHistory = await ApiClient.getHistory(sessionManager.currentSessionId);
      if (currentHistory && currentHistory.events) {
        sessionManager.getCurrentSession().setHistory(currentHistory.events);
      }
    } catch (err) {
      console.warn("[App] Initial fetch failed:", err);
    }

    // 6. Mount Application Root
    ctx.uiRenderer.mount(this.container);
  }
}

// Start application when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("app") || document.getElementById("root") || document.body;
  const app = new WebApplication(root);
  app.start();
});
