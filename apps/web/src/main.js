/**
 * DeepSeek Harness Web GUI SPA Entrypoint (`apps/web/src/main.js`)
 * Modular, reactive frontend architecture 1:1 aligned with DeepSeek Harness.
 */

import { ApiClient } from "./connection/api.js";
import { DownlinkStream } from "./connection/sse.js";
import { SidebarView } from "./ui/sidebar.js";
import { ConversationView } from "./ui/conversation.js";
import { GoalBarView } from "./ui/goal.js";
import { PlanModeView } from "./ui/plan.js";
import { CommandsView } from "./ui/commands.js";
import { SettingsView } from "./ui/settings.js";

class App {
  constructor() {
    this.currentSessionId = "default-session";
    this.isGenerating = false;

    // DOM Elements
    this.bodyRoot = document.getElementById("body-root");
    this.modelChipDisplay = document.getElementById("model-name-text");
    this.promptTextarea = document.getElementById("prompt-textarea");
    this.btnSend = document.getElementById("btn-send");
    this.btnStop = document.getElementById("btn-stop");
    this.slashPopup = document.getElementById("slash-popup");

    // Initialize UI Components
    this.sidebar = new SidebarView({
      onSelectSession: (sid) => this.switchSession(sid),
      onNewSession: () => this.createNewSession(),
      onPresetChange: (preset) => this.switchPreset(preset),
      onToggleTheme: () => this.toggleTheme(),
      onOpenSettings: () => this.settings.show({ model: this.modelChipDisplay.textContent }),
    });

    this.conversation = new ConversationView({
      onPlanAction: (choice) => this.sendPrompt(choice),
    });

    this.goalBar = new GoalBarView({
      onToggleGoal: (action) => this.handleGoalToggle(action),
    });

    this.planMode = new PlanModeView({
      onTogglePlanMode: (target) => this.handlePlanToggle(target),
    });

    this.commands = new CommandsView({
      textarea: this.promptTextarea,
      popup: this.slashPopup,
      onSelectCommand: (cmd) => {
        this.promptTextarea.value = cmd;
        this.promptTextarea.focus();
      },
    });

    this.settings = new SettingsView({
      modal: document.getElementById("settings-modal"),
      baseUrlInput: document.getElementById("setting-base-url"),
      apiKeyInput: document.getElementById("setting-api-key"),
      modelInput: document.getElementById("setting-model"),
      onSave: (cfg) => {
        if (cfg.model) this.modelChipDisplay.textContent = cfg.model;
      },
    });

    // Initialize Downlink SSE Stream
    this.downlink = new DownlinkStream({
      onSessionEvent: (e) => this.handleSessionEvent(e),
      onGoalChanged: (goal) => this.goalBar.update(goal),
      onAgentStatus: (status) => {},
    });

    this._bindComposer();
  }

  async start() {
    this._restoreTheme();
    await this.refreshStatus();
    await this.refreshSessions();
    await this.loadCurrentSession();
    this.downlink.connect();
  }

  _bindComposer() {
    this.btnSend.addEventListener("click", () => this.handleSend());
    this.btnStop.addEventListener("click", () => this.handleStop());

    this.promptTextarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.handleSend();
      }
    });
  }

  _restoreTheme() {
    if (localStorage.getItem("dsh_theme") === "light") {
      this.bodyRoot.classList.add("theme-light");
    }
  }

  toggleTheme() {
    this.bodyRoot.classList.toggle("theme-light");
    const isLight = this.bodyRoot.classList.contains("theme-light");
    localStorage.setItem("dsh_theme", isLight ? "light" : "dark");
  }

  async refreshStatus() {
    try {
      const status = await ApiClient.getStatus();
      if (status.model) {
        this.modelChipDisplay.textContent = status.model;
      }
      this.planMode.update(status.planMode);
      this.goalBar.update(status.goal);
      this.sidebar.setWorkspace("Win7 Workspace");
    } catch (e) {
      console.warn("Status refresh failed:", e);
    }
  }

  async refreshSessions() {
    try {
      const res = await ApiClient.getSessions();
      this.sidebar.setSessions(res.sessions || [], this.currentSessionId);
    } catch (e) {
      console.warn("Session fetch failed:", e);
    }
  }

  async loadCurrentSession() {
    try {
      const res = await ApiClient.getHistory(this.currentSessionId);
      this.conversation.renderEvents(res.events || []);
    } catch (e) {
      console.warn("History load failed:", e);
    }
  }

  async switchSession(sessionId) {
    if (sessionId === this.currentSessionId) return;
    this.currentSessionId = sessionId;
    this.sidebar.setActive(sessionId);
    await this.loadCurrentSession();
  }

  async createNewSession() {
    const newSid = "session-" + Date.now().toString(36);
    this.currentSessionId = newSid;
    this.conversation.clear();
    await ApiClient.createSession(newSid);
    await this.refreshSessions();
  }

  switchPreset(preset) {
    const toast = document.createElement("div");
    toast.className = "plan-banner-chip";
    toast.style.position = "fixed";
    toast.style.top = "60px";
    toast.style.right = "20px";
    toast.style.zIndex = "1000";
    toast.textContent = `已切换预设为: ${preset}`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2500);
  }

  async handlePlanToggle(target) {
    await ApiClient.setPlanMode(target);
    this.planMode.update(target);
  }

  async handleGoalToggle(action) {
    const res = await ApiClient.goalAction(action);
    if (res.goal) {
      this.goalBar.update(res.goal);
    }
  }

  async handleSend() {
    const text = this.promptTextarea.value.trim();
    if (!text || this.isGenerating) return;

    if (text === "/clear") {
      this.conversation.clear();
      this.promptTextarea.value = "";
      return;
    }

    this.promptTextarea.value = "";
    this.commands.hide();
    this.setGenerating(true);

    try {
      await ApiClient.prompt(this.currentSessionId, text);
    } catch (e) {
      alert("发送失败: " + e.message);
      this.setGenerating(false);
    }
  }

  async sendPrompt(text) {
    this.setGenerating(true);
    try {
      await ApiClient.prompt(this.currentSessionId, text);
    } catch (e) {
      this.setGenerating(false);
    }
  }

  async handleStop() {
    await ApiClient.cancel(this.currentSessionId);
    this.setGenerating(false);
  }

  handleSessionEvent(event) {
    this.conversation.appendEvent(event);
    if (event.type === "plan/mode") {
      this.planMode.update(event.data && event.data.active);
    } else if (event.type === "turn/end") {
      this.setGenerating(false);
    }
  }

  setGenerating(generating) {
    this.isGenerating = generating;
    if (generating) {
      this.btnSend.classList.add("hidden");
      this.btnStop.classList.remove("hidden");
    } else {
      this.btnSend.classList.remove("hidden");
      this.btnStop.classList.add("hidden");
    }
  }
}

// Start application on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  const app = new App();
  app.start();
});
