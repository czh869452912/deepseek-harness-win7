/**
 * DeepSeek Harness Web GUI SPA Entrypoint (`apps/web/src/main.js`)
 * 1:1 Complete Component Assembly & Real-time Reactive Downlink Router.
 */

import { ApiClient } from "./connection/api.js";
import { DownlinkStream } from "./connection/sse.js";
import { SidebarView } from "./ui/sidebar.js";
import { ConversationView } from "./ui/conversation.js";
import { TrajectoryView } from "./ui/trajectory.js";
import { GoalBarView } from "./ui/goal.js";
import { PlanModeView } from "./ui/plan.js";
import { CommandsView } from "./ui/commands.js";
import { SettingsView } from "./ui/settings.js";
import { QuestionFlowView } from "./ui/questions.js";
import { StatsLineView } from "./ui/stats.js";
import { ModelSelectView } from "./ui/model_select.js";
import { PermissionSelectView } from "./ui/permissions.js";
import { ContextMeterView } from "./ui/context_meter.js";
import { JobsView } from "./ui/jobs.js";
import { SubagentNavView } from "./ui/subagent.js";

class App {
  constructor() {
    this.currentSessionId = "default-session";
    this.isGenerating = false;
    this.currentEvents = [];
    this.activeView = "chat"; // 'chat' | 'trajectory'

    // DOM Elements
    this.bodyRoot = document.getElementById("body-root");
    this.modelChipDisplay = document.getElementById("model-name-text");
    this.modelChipTrigger = document.getElementById("model-chip-display");
    this.promptTextarea = document.getElementById("prompt-textarea");
    this.btnSend = document.getElementById("btn-send");
    this.btnStop = document.getElementById("btn-stop");
    this.slashPopup = document.getElementById("slash-popup");
    this.messagesContainer = document.getElementById("messages-container");
    this.trajectoryContainer = document.getElementById("trajectory-container");
    this.tabBtnChat = document.getElementById("tab-btn-chat");
    this.tabBtnTrajectory = document.getElementById("tab-btn-trajectory");

    // Initialize UI Components
    this.modelSelect = new ModelSelectView({
      trigger: this.modelChipTrigger,
      onSelectModel: async (m) => {
        await ApiClient.setModel(m);
        this._showToast(`已切换当前模型为: ${m}`);
      },
    });

    this.sidebar = new SidebarView({
      onSelectSession: (sid) => this.switchSession(sid),
      onNewSession: () => this.createNewSession(),
      onPresetChange: (preset) => this.switchPreset(preset),
      onToggleTheme: () => this.toggleTheme(),
      onOpenSettings: () => this.settings.show({ model: this.modelChipDisplay.textContent }),
    });

    this.conversation = new ConversationView({
      onPlanAction: (choice) => this.sendPrompt(choice),
      onForkSession: () => this.forkCurrentSession(),
    });

    this.trajectory = new TrajectoryView({
      containerId: "trajectory-container",
    });

    this.permissions = new PermissionSelectView({
      containerId: "permission-select-container",
      onSelectPermission: async (p) => {
        await ApiClient.setPermission(p);
        this._showToast(`已切换会话权限为: ${p}`);
      },
    });

    this.contextMeter = new ContextMeterView({
      containerId: "context-meter-container",
    });

    this.jobs = new JobsView({
      containerId: "jobs-container",
    });

    this.subagent = new SubagentNavView({
      containerId: "subagent-container",
      onOpenSubagent: (id) => this.switchSession(id),
    });

    this.goalBar = new GoalBarView({
      onToggleGoal: (action) => this.handleGoalToggle(action),
    });

    this.planMode = new PlanModeView({
      onTogglePlanMode: (target) => this.handlePlanToggle(target),
    });

    this.questions = new QuestionFlowView({
      onAnswer: (answers) => this.sendPrompt(answers),
      onCancel: () => {},
    });

    this.statsLine = new StatsLineView({});

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
      onSave: async (cfg) => {
        await ApiClient.saveSettings(cfg);
        if (cfg.model) {
          this.modelChipDisplay.textContent = cfg.model;
          this.modelSelect.setModel(cfg.model);
        }
        this._showToast("系统设置已保存");
      },
    });

    // Downlink SSE Stream with live token streaming and chunk routing
    this.downlink = new DownlinkStream({
      onSessionEvent: (e) => this.handleSessionEvent(e),
      onSessionChunk: (chunk) => this.handleSessionChunk(chunk),
      onAssistantChunk: (chunk) => this.handleAssistantChunk(chunk),
      onGoalChanged: (goal) => this.goalBar.update(goal),
      onAgentStatus: (status) => this.handleAgentStatus(status),
    });

    this._bindComposer();
    this._bindViewTabs();
  }

  async start() {
    this._restoreTheme();
    await this.refreshStatus();
    await this.refreshSessions();
    await this.loadCurrentSession();
    await this.refreshJobs();
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

  _bindViewTabs() {
    if (this.tabBtnChat && this.tabBtnTrajectory) {
      this.tabBtnChat.addEventListener("click", () => this.switchView("chat"));
      this.tabBtnTrajectory.addEventListener("click", () => this.switchView("trajectory"));
    }
  }

  switchView(viewName) {
    this.activeView = viewName;
    if (viewName === "chat") {
      this.tabBtnChat.classList.add("active");
      this.tabBtnTrajectory.classList.remove("active");
      this.messagesContainer.classList.remove("hidden");
      this.trajectoryContainer.classList.add("hidden");
    } else {
      this.tabBtnTrajectory.classList.add("active");
      this.tabBtnChat.classList.remove("active");
      this.messagesContainer.classList.add("hidden");
      this.trajectoryContainer.classList.remove("hidden");
      this.trajectory.setEvents(this.currentEvents);
    }
  }

  _showToast(msg) {
    const toast = document.createElement("div");
    toast.className = "plan-banner-chip";
    toast.style.position = "fixed";
    toast.style.top = "60px";
    toast.style.right = "20px";
    toast.style.zIndex = "2000";
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2500);
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
      if (status.cwd) {
        this.sidebar.setWorkspace(status.cwd);
      }
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

  async refreshJobs() {
    try {
      const res = await ApiClient.getJobs();
      this.jobs.setJobs(res.jobs || []);
    } catch (e) {}
  }

  async loadCurrentSession() {
    try {
      const res = await ApiClient.getHistory(this.currentSessionId);
      this.currentEvents = res.events || [];
      this.conversation.renderEvents(this.currentEvents);
      this.trajectory.setEvents(this.currentEvents);
      this.statsLine.updateFromEvents(this.currentEvents);
      this.contextMeter.updateFromEvents(this.currentEvents);
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
    this.currentEvents = [];
    this.conversation.clear();
    this.trajectory.setEvents([]);
    this.questions.hide();
    this.statsLine.updateFromEvents([]);
    this.contextMeter.updateFromEvents([]);
    await ApiClient.createSession(newSid);
    await this.refreshSessions();
  }

  async forkCurrentSession() {
    const newSid = "fork-" + Date.now().toString(36);
    await ApiClient.forkSession(this.currentSessionId);
    this._showToast(`已成功创建分支会话`);
    await this.refreshSessions();
    await this.switchSession(newSid);
  }

  switchPreset(preset) {
    this._showToast(`已切换预设为: ${preset}`);
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
      this.questions.hide();
      this.promptTextarea.value = "";
      return;
    }

    this.promptTextarea.value = "";
    this.commands.hide();
    this.questions.hide();
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

  handleSessionChunk(chunk) {
    if (chunk && chunk.data) {
      this.conversation.handleStreamChunk(chunk.data);
      this.trajectory.appendLiveChunk(chunk.data);
    }
  }

  handleAssistantChunk(chunk) {
    if (chunk && chunk.data) {
      this.conversation.handleStreamChunk(chunk.data);
      this.trajectory.appendLiveChunk(chunk.data);
    }
  }

  handleSessionEvent(event) {
    this.currentEvents.push(event);
    this.conversation.appendEvent(event);
    this.trajectory.setEvents(this.currentEvents);
    this.statsLine.updateFromEvents(this.currentEvents);
    this.contextMeter.updateFromEvents(this.currentEvents);

    // Check ask_user_question tool calls
    if (event.type === "assistant/message") {
      const msg = event.data && event.data.message;
      if (msg && msg.tool_calls) {
        msg.tool_calls.forEach((tc) => {
          const fn = tc.function || {};
          if (fn.name === "ask_user_question" || fn.name === "ask_user") {
            try {
              const args = typeof fn.arguments === "string" ? JSON.parse(fn.arguments) : fn.arguments;
              const questions = args.questions || [{ question: args.question, options: args.options }];
              this.questions.showQuestions(questions);
            } catch (e) {}
          }
        });
      }
    }

    if (event.type === "plan/mode") {
      this.planMode.update(event.data && event.data.active);
    } else if (event.type === "turn/end") {
      this.setGenerating(false);
      this.loadCurrentSession();
      this.refreshJobs();
    }
  }

  handleAgentStatus(status) {
    if (status && status.status === "running") {
      this.setGenerating(true);
    } else if (status && status.status === "idle") {
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
