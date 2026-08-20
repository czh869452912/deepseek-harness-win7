/**
 * Header Navigation & Status Bar Plugin (`@deepseek-ai/dsh-client-ui-nav`)
 * Renders view tabs, goal bar, plan toggle, jobs pill, and model chip into 'header.nav'.
 */

import { ApiClient } from "../connection/api.js";

export class PluginNav {
  static id = "ui-nav";
  static name = "@deepseek-ai/dsh-client-ui-nav";

  apply(ctx) {
    ctx.slots.register(
      {
        name: "header.nav",
        inject: (injectCtx) => ({
          onTogglePlanMode: async (target) => {
            await ApiClient.setPlanMode(target);
          },
          onToggleGoal: async (action) => {
            await ApiClient.goalAction(action);
          },
        }),
      },
      NavComponent
    );
  }
}

class NavComponent {
  constructor(props) {
    this.props = props;
    this.status = {
      model: "deepseek-v4-flash",
      planMode: false,
      goal: null,
    };
  }

  render(container) {
    const { onTogglePlanMode, onToggleGoal } = this.props;

    container.innerHTML = `
      <div class="nav-left">
        <button id="btn-header-toggle-sidebar" class="btn-icon-plain" title="折叠/展开侧边栏">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12h18M3 6h18M3 18h18"/>
          </svg>
        </button>

        <!-- View Tabs Switcher (Chat vs Trajectory) -->
        <div class="view-tabs-group">
          <button type="button" class="tab-view-btn active" id="tab-btn-chat">
            <span>💬 对话</span>
          </button>
          <button type="button" class="tab-view-btn" id="tab-btn-trajectory">
            <span>📊 轨迹时间线</span>
          </button>
        </div>

        <!-- Goal Banner (when active) -->
        <div id="header-goal-bar" class="goal-bar-pill ${this.status.goal && this.status.goal.phase !== "complete" ? "" : "hidden"}">
          <div class="goal-tag">🎯 GOAL</div>
          <span class="goal-title-text">${(this.status.goal && this.status.goal.objective) || "长程任务"}</span>
          <span class="goal-status-badge badge-${(this.status.goal && this.status.goal.phase) || "active"}">${((this.status.goal && this.status.goal.phase) || "ACTIVE").toUpperCase()}</span>
          <button id="btn-header-goal-toggle" class="btn-pill-small">${(this.status.goal && this.status.goal.phase === "paused") ? "恢复" : "暂停"}</button>
        </div>
      </div>

      <div class="nav-right">
        <!-- Background Jobs Container -->
        <div id="header-jobs-container"></div>

        <!-- Plan Mode Switch Button -->
        <button id="btn-header-plan-toggle" class="btn-plan-pill ${this.status.planMode ? "active" : ""}" title="切换规划模式 (/plan)">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>
          </svg>
          <span>规划模式: ${this.status.planMode ? "开" : "关"}</span>
        </button>

        <!-- Current Model Chip -->
        <div class="model-chip" id="header-model-chip">
          <span class="live-dot"></span>
          <span id="header-model-name">${this.status.model}</span>
        </div>
      </div>
    `;

    // View tab switching
    const tabChat = container.querySelector("#tab-btn-chat");
    const tabTraj = container.querySelector("#tab-btn-trajectory");
    const convOutlet = document.querySelector("#slot-outlet-conversation");
    const trajOutlet = document.querySelector("#slot-outlet-trajectory");

    tabChat.addEventListener("click", () => {
      tabChat.classList.add("active");
      tabTraj.classList.remove("active");
      if (convOutlet) convOutlet.classList.remove("hidden");
      if (trajOutlet) trajOutlet.classList.add("hidden");
      if (typeof window._dshSwitchTab === "function") {
        window._dshSwitchTab("chat");
      }
    });

    tabTraj.addEventListener("click", () => {
      tabTraj.classList.add("active");
      tabChat.classList.remove("active");
      if (convOutlet) convOutlet.classList.add("hidden");
      if (trajOutlet) trajOutlet.classList.remove("hidden");
      if (typeof window._dshSwitchTab === "function") {
        window._dshSwitchTab("trajectory");
      }
    });

    // Plan Mode Toggle
    const btnPlan = container.querySelector("#btn-header-plan-toggle");
    btnPlan.addEventListener("click", async () => {
      this.status.planMode = !this.status.planMode;
      if (onTogglePlanMode) await onTogglePlanMode(this.status.planMode);
      this.render(container);
    });

    // Sidebar Toggle
    const btnSidebar = container.querySelector("#btn-header-toggle-sidebar");
    btnSidebar.addEventListener("click", () => {
      const sidebar = document.querySelector("#slot-outlet-sidebar");
      if (sidebar) sidebar.classList.toggle("collapsed");
    });

    return container;
  }
}
