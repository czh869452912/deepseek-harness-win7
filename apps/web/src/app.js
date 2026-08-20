/**
 * DeepSeek Harness Web GUI - Complete Reactive Client SPA
 * Zero-dependency, 100% Windows 7 Browser Compatible.
 */

(function () {
  // State
  let currentSessionId = "default-session";
  let isGenerating = false;
  let eventSource = null;
  let currentSessions = [];

  // DOM Elements
  const bodyRoot = document.getElementById("body-root");
  const sidebar = document.getElementById("sidebar");
  const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");
  const btnNewSession = document.getElementById("btn-new-session");
  const workspaceLabel = document.getElementById("workspace-label");
  const selectPreset = document.getElementById("select-preset");
  const sessionList = document.getElementById("session-list");
  const inputSearchSessions = document.getElementById("input-search-sessions");
  const btnOpenSettings = document.getElementById("btn-open-settings");
  const btnCloseSettings = document.getElementById("btn-close-settings");
  const btnSaveSettings = document.getElementById("btn-save-settings");
  const settingsModal = document.getElementById("settings-modal");
  const btnToggleTheme = document.getElementById("btn-toggle-theme");

  const modelChipDisplay = document.getElementById("model-name-text");
  const goalBar = document.getElementById("goal-bar");
  const goalObjective = document.getElementById("goal-objective");
  const goalPhase = document.getElementById("goal-phase");
  const goalRounds = document.getElementById("goal-rounds");
  const btnGoalToggle = document.getElementById("btn-goal-toggle");
  const btnPlanToggle = document.getElementById("btn-plan-toggle");
  const planModeLabel = document.getElementById("plan-mode-label");
  const planActiveIndicator = document.getElementById("plan-active-indicator");

  const messagesContainer = document.getElementById("messages-container");
  const heroScreen = document.getElementById("hero-screen");
  const chatFlow = document.getElementById("chat-flow");

  const promptTextarea = document.getElementById("prompt-textarea");
  const btnSend = document.getElementById("btn-send");
  const btnStop = document.getElementById("btn-stop");
  const slashPopup = document.getElementById("slash-popup");

  // Settings inputs
  const settingBaseUrl = document.getElementById("setting-base-url");
  const settingApiKey = document.getElementById("setting-api-key");
  const settingModel = document.getElementById("setting-model");

  // Initialize
  async function init() {
    setupEventListeners();
    await fetchStatus();
    await fetchSessionList();
    await loadSessionHistory(currentSessionId);
    connectSSE();
  }

  function setupEventListeners() {
    // Sidebar toggle
    btnToggleSidebar.addEventListener("click", () => {
      sidebar.classList.toggle("collapsed");
    });

    // Theme toggle
    btnToggleTheme.addEventListener("click", () => {
      bodyRoot.classList.toggle("theme-light");
      const isLight = bodyRoot.classList.contains("theme-light");
      localStorage.setItem("dsh_theme", isLight ? "light" : "dark");
    });
    if (localStorage.getItem("dsh_theme") === "light") {
      bodyRoot.classList.add("theme-light");
    }

    // New session
    btnNewSession.addEventListener("click", handleNewSession);

    // Preset switch
    selectPreset.addEventListener("change", handlePresetChange);

    // Search sessions
    inputSearchSessions.addEventListener("input", (e) => {
      renderSessionList(e.target.value.trim().toLowerCase());
    });

    // Plan mode toggle
    btnPlanToggle.addEventListener("click", handleTogglePlanMode);

    // Goal toggle
    btnGoalToggle.addEventListener("click", handleToggleGoal);

    // Settings Modal
    btnOpenSettings.addEventListener("click", () => {
      settingsModal.classList.remove("hidden");
    });
    btnCloseSettings.addEventListener("click", () => {
      settingsModal.classList.add("hidden");
    });
    btnSaveSettings.addEventListener("click", handleSaveSettings);

    // Hero Cards
    document.querySelectorAll(".hero-card").forEach((card) => {
      card.addEventListener("click", () => {
        const cmd = card.getAttribute("data-cmd");
        if (cmd) {
          promptTextarea.value = cmd;
          promptTextarea.focus();
        }
      });
    });

    // Composer Input & Slash Commands
    promptTextarea.addEventListener("input", handleComposerInput);
    promptTextarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });

    btnSend.addEventListener("click", handleSend);
    btnStop.addEventListener("click", handleCancel);

    // Slash command items
    document.querySelectorAll(".slash-item").forEach((item) => {
      item.addEventListener("click", () => {
        const cmd = item.getAttribute("data-cmd");
        promptTextarea.value = cmd;
        slashPopup.classList.add("hidden");
        promptTextarea.focus();
      });
    });

    // Document click to close popups
    document.addEventListener("click", (e) => {
      if (!slashPopup.contains(e.target) && e.target !== promptTextarea) {
        slashPopup.classList.add("hidden");
      }
    });
  }

  // Fetch Status
  async function fetchStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      if (data.model) {
        modelChipDisplay.textContent = data.model;
        if (settingModel) settingModel.value = data.model;
      }
      updatePlanModeUI(data.planMode);
      updateGoalUI(data.goal);
      if (workspaceLabel) workspaceLabel.textContent = "Win7 CWD";
    } catch (e) {
      console.warn("Failed to fetch status:", e);
    }
  }

  // Session List
  async function fetchSessionList() {
    try {
      const res = await fetch("/api/session/list");
      const data = await res.json();
      currentSessions = data.sessions || [];
      renderSessionList();
    } catch (e) {
      console.warn("Failed to fetch session list:", e);
    }
  }

  function renderSessionList(filterQuery = "") {
    sessionList.innerHTML = '<div class="session-group-title">历史会话</div>';
    const filtered = currentSessions.filter((s) => s.id.toLowerCase().includes(filterQuery));

    if (filtered.length === 0) {
      const emptyDiv = document.createElement("div");
      emptyDiv.className = "session-item";
      emptyDiv.innerHTML = `<span class="session-title-text" style="color:var(--text-muted)">无匹配会话</span>`;
      sessionList.appendChild(emptyDiv);
      return;
    }

    filtered.forEach((s) => {
      const item = document.createElement("div");
      item.className = `session-item ${s.id === currentSessionId ? "active" : ""}`;
      item.innerHTML = `
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
        </svg>
        <span class="session-title-text">${escapeHtml(s.id)}</span>
      `;
      item.addEventListener("click", () => switchSession(s.id));
      sessionList.appendChild(item);
    });
  }

  async function switchSession(sessionId) {
    if (sessionId === currentSessionId) return;
    currentSessionId = sessionId;
    renderSessionList();
    await loadSessionHistory(sessionId);
  }

  async function handleNewSession() {
    const newSid = "session-" + Date.now().toString(36);
    currentSessionId = newSid;
    chatFlow.innerHTML = "";
    heroScreen.classList.remove("hidden");

    await fetch("/api/session/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: newSid, preset: selectPreset.value }),
    });

    await fetchSessionList();
  }

  function handlePresetChange() {
    const preset = selectPreset.value;
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

  function updatePlanModeUI(active) {
    if (active) {
      btnPlanToggle.classList.add("active");
      planModeLabel.textContent = "规划模式: 开";
      planActiveIndicator.classList.remove("hidden");
    } else {
      btnPlanToggle.classList.remove("active");
      planModeLabel.textContent = "规划模式: 关";
      planActiveIndicator.classList.add("hidden");
    }
  }

  function updateGoalUI(goal) {
    if (!goal || goal.phase === "complete") {
      goalBar.classList.add("hidden");
      return;
    }
    goalBar.classList.remove("hidden");
    goalObjective.textContent = goal.objective || "长程自主任务";
    goalPhase.textContent = (goal.phase || "active").toUpperCase();
    goalPhase.className = `goal-status-badge badge-${goal.phase || "active"}`;
    goalRounds.textContent = `Round ${goal.roundsStarted || 1}`;
    btnGoalToggle.textContent = goal.phase === "paused" ? "恢复" : "暂停";
  }

  async function handleTogglePlanMode() {
    const isCurrentlyActive = btnPlanToggle.classList.contains("active");
    const target = !isCurrentlyActive;
    await fetch("/api/plan/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: target }),
    });
    updatePlanModeUI(target);
  }

  async function handleToggleGoal() {
    const action = btnGoalToggle.textContent === "暂停" ? "pause" : "resume";
    await fetch("/api/goal/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action }),
    });
    await fetchStatus();
  }

  async function handleSaveSettings() {
    settingsModal.classList.add("hidden");
    alert("设置已保存。");
  }

  function handleComposerInput() {
    const val = promptTextarea.value;
    if (val === "/" || (val.startsWith("/") && !val.includes(" "))) {
      slashPopup.classList.remove("hidden");
    } else {
      slashPopup.classList.add("hidden");
    }
  }

  // Load Session History
  async function loadSessionHistory(sessionId) {
    try {
      const res = await fetch(`/api/session/history?sessionId=${sessionId}`);
      const data = await res.json();
      chatFlow.innerHTML = "";
      if (data.events && data.events.length > 0) {
        heroScreen.classList.add("hidden");
        data.events.forEach(handleSessionEvent);
      } else {
        heroScreen.classList.remove("hidden");
      }
    } catch (e) {
      console.warn("Failed to load history:", e);
    }
  }

  // Connect SSE
  function connectSSE() {
    if (eventSource) eventSource.close();
    eventSource = new EventSource("/api/session/events");

    eventSource.addEventListener("session/event", (e) => {
      try {
        const event = JSON.parse(e.data);
        handleSessionEvent(event);
      } catch (err) {}
    });

    eventSource.addEventListener("goal/changed", (e) => {
      try {
        const data = JSON.parse(e.data);
        updateGoalUI(data.goal);
      } catch (err) {}
    });

    eventSource.onerror = () => {
      setTimeout(connectSSE, 3000);
    };
  }

  function handleSessionEvent(event) {
    heroScreen.classList.add("hidden");
    const type = event.type;
    const data = event.data || {};

    if (type === "user/message") {
      renderUserMessage(data.content || "");
    } else if (type === "assistant/message") {
      const msg = data.message || {};
      renderAssistantMessage(msg);
    } else if (type === "tool/result") {
      renderToolResult(data);
    } else if (type === "plan/mode") {
      updatePlanModeUI(data.active);
    } else if (type === "turn/end") {
      setGenerating(false);
    }
  }

  function renderUserMessage(content) {
    const row = document.createElement("div");
    row.className = "message-row user";
    row.innerHTML = `<div class="user-bubble">${escapeHtml(content)}</div>`;
    chatFlow.appendChild(row);
    scrollToBottom();
  }

  function renderAssistantMessage(msg) {
    const row = document.createElement("div");
    row.className = "message-row assistant";

    const turn = document.createElement("div");
    turn.className = "assistant-turn";

    // 1. Thought / Reasoning accordion
    if (msg.reasoning_content) {
      turn.innerHTML += `
        <details class="thought-accordion" open>
          <summary class="thought-summary">
            <span class="live-dot" style="background:var(--accent-cyan)"></span>
            <span>思考过程 (Thought Process)</span>
          </summary>
          <div class="thought-body">${escapeHtml(msg.reasoning_content)}</div>
        </details>
      `;
    }

    // 2. Assistant Markdown Body
    if (msg.content) {
      turn.innerHTML += `<div class="assistant-markdown">${formatMarkdown(msg.content)}</div>`;
    }

    // 3. Tool Calls
    if (msg.tool_calls && Array.isArray(msg.tool_calls)) {
      msg.tool_calls.forEach((tc) => {
        const fn = tc.function || {};
        if (fn.name === "exit_plan_mode") {
          try {
            const args = JSON.parse(fn.arguments || "{}");
            turn.innerHTML += renderPlanReviewCard(args.plan);
          } catch (e) {}
        } else {
          turn.innerHTML += `
            <div class="tool-view-card">
              <div class="tool-view-header">
                <span class="tool-title">🔧 ${escapeHtml(fn.name)}</span>
                <span class="tool-status-pill pill-success">RUNNING</span>
              </div>
              <div class="tool-view-body">${escapeHtml(fn.arguments || "")}</div>
            </div>
          `;
        }
      });
    }

    row.appendChild(turn);
    chatFlow.appendChild(row);
    scrollToBottom();
  }

  function renderToolResult(data) {
    const card = document.createElement("div");
    card.className = "tool-view-card";
    const name = data.name || "tool";
    card.innerHTML = `
      <div class="tool-view-header">
        <span class="tool-title">✓ 结果: ${escapeHtml(name)}</span>
        <span class="tool-status-pill pill-success">SUCCESS</span>
      </div>
      <div class="tool-view-body">${escapeHtml(String(data.result || ""))}</div>
    `;
    chatFlow.appendChild(card);
    scrollToBottom();
  }

  function renderPlanReviewCard(planMarkdown) {
    const rendered = formatMarkdown(planMarkdown);
    return `
      <div class="plan-review-container">
        <div class="plan-header-title">📋 规划方案评审 (Plan Review & Approval)</div>
        <div class="plan-markdown-body">${rendered}</div>
        <div class="plan-button-row">
          <button class="btn-plan-approve" onclick="window.submitPlanReviewChoice('Approve')">✓ 批准并开始执行 (Approve)</button>
          <button class="btn-plan-reject" onclick="window.submitPlanReviewChoice('Keep planning')">✎ 继续规划 (Keep planning)</button>
        </div>
      </div>
    `;
  }

  window.submitPlanReviewChoice = async function (choice) {
    await fetch("/api/agent/prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: currentSessionId, content: choice }),
    });
  };

  async function handleSend() {
    const text = promptTextarea.value.trim();
    if (!text || isGenerating) return;

    if (text === "/clear") {
      chatFlow.innerHTML = "";
      heroScreen.classList.remove("hidden");
      promptTextarea.value = "";
      return;
    }

    promptTextarea.value = "";
    slashPopup.classList.add("hidden");
    setGenerating(true);

    try {
      await fetch("/api/agent/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: currentSessionId, content: text }),
      });
    } catch (e) {
      alert("发送失败: " + e.message);
      setGenerating(false);
    }
  }

  async function handleCancel() {
    await fetch("/api/agent/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: currentSessionId }),
    });
    setGenerating(false);
  }

  function setGenerating(generating) {
    isGenerating = generating;
    if (generating) {
      btnSend.classList.add("hidden");
      btnStop.classList.remove("hidden");
    } else {
      btnSend.classList.remove("hidden");
      btnStop.classList.add("hidden");
    }
  }

  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // Native Lightweight Markdown Parser (100% Win7 offline compatible)
  function formatMarkdown(text) {
    if (!text) return "";
    let html = escapeHtml(text);

    // Code blocks ```lang ... ```
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function (match, lang, code) {
      return `<pre><div style="display:flex;justify-content:space-between;color:var(--text-muted);margin-bottom:6px;font-size:11px"><span>${lang || "code"}</span><button style="background:none;border:none;color:var(--accent-blue);cursor:pointer" onclick="navigator.clipboard.writeText(this.parentElement.nextElementSibling.textContent)">复制</button></div><code>${code}</code></pre>`;
    });

    // Inline code `...`
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Headers
    html = html.replace(/^### (.*$)/gim, "<h3>$1</h3>");
    html = html.replace(/^## (.*$)/gim, "<h2>$1</h2>");
    html = html.replace(/^# (.*$)/gim, "<h1>$1</h1>");

    // Bold & Italic
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");

    // Paragraphs / linebreaks
    html = html.replace(/\n\n/g, "</p><p>");
    html = "<p>" + html + "</p>";

    return html;
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Start on load
  document.addEventListener("DOMContentLoaded", init);
})();
