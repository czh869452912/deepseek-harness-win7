/**
 * DeepSeek Harness Web GUI Client SPA
 */

(function () {
  let currentSessionId = "default-session";
  let isGenerating = false;
  let eventSource = null;

  // DOM Elements
  const chatStream = document.getElementById("chat-stream");
  const promptInput = document.getElementById("prompt-input");
  const btnSend = document.getElementById("btn-send");
  const btnCancel = document.getElementById("btn-cancel");
  const btnNewSession = document.getElementById("btn-new-session");
  const selectPreset = document.getElementById("select-preset");
  const modelBadge = document.getElementById("model-badge");
  const planModeBtn = document.getElementById("btn-plan-toggle");
  const planModeLabel = document.getElementById("plan-mode-label");
  const goalBar = document.getElementById("goal-bar");
  const goalObjective = document.getElementById("goal-objective");
  const goalPhase = document.getElementById("goal-phase");
  const btnGoalToggle = document.getElementById("btn-goal-toggle");
  const welcomeScreen = document.getElementById("welcome-screen");

  // Initialize
  async function init() {
    setupEventListeners();
    await fetchStatus();
    await loadSessionHistory();
    connectSSE();
  }

  function setupEventListeners() {
    btnSend.addEventListener("click", handleSend);
    promptInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });

    btnCancel.addEventListener("click", handleCancel);
    btnNewSession.addEventListener("click", handleNewSession);
    selectPreset.addEventListener("change", handlePresetChange);
    planModeBtn.addEventListener("click", handleTogglePlanMode);
    btnGoalToggle.addEventListener("click", handleToggleGoal);

    // Quick hint cards
    document.querySelectorAll(".hint-card").forEach((card) => {
      card.addEventListener("click", () => {
        const cmd = card.getAttribute("data-cmd");
        if (cmd) {
          promptInput.value = cmd;
          promptInput.focus();
        }
      });
    });
  }

  async function fetchStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      if (data.model) {
        modelBadge.textContent = data.model;
      }
      updatePlanModeUI(data.planMode);
      updateGoalUI(data.goal);
    } catch (e) {
      console.warn("Failed to fetch status:", e);
    }
  }

  function updatePlanModeUI(active) {
    if (active) {
      planModeBtn.classList.add("active");
      planModeLabel.textContent = "规划模式: 开";
    } else {
      planModeBtn.classList.remove("active");
      planModeLabel.textContent = "规划模式: 关";
    }
  }

  function updateGoalUI(goal) {
    if (!goal || goal.phase === "complete") {
      goalBar.classList.add("hidden");
      return;
    }
    goalBar.classList.remove("hidden");
    goalObjective.textContent = goal.objective || "长程任务";
    goalPhase.textContent = (goal.phase || "active").toUpperCase();
    btnGoalToggle.textContent = goal.phase === "paused" ? "恢复" : "暂停";
  }

  async function loadSessionHistory() {
    try {
      const res = await fetch(`/api/session/history?sessionId=${currentSessionId}`);
      const data = await res.json();
      if (data.events && data.events.length > 0) {
        if (welcomeScreen) welcomeScreen.classList.add("hidden");
        renderEvents(data.events);
      }
    } catch (e) {
      console.warn("Failed to load session history:", e);
    }
  }

  function connectSSE() {
    if (eventSource) {
      eventSource.close();
    }
    eventSource = new EventSource("/api/session/events");

    eventSource.addEventListener("session/event", (e) => {
      try {
        const event = JSON.parse(e.data);
        handleSessionEvent(event);
      } catch (err) {
        console.error("SSE parse error:", err);
      }
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
    if (welcomeScreen) welcomeScreen.classList.add("hidden");
    const type = event.type;
    const data = event.data || {};

    if (type === "user/message") {
      appendUserMessage(data.content || "");
    } else if (type === "assistant/message") {
      const msg = data.message || {};
      appendAssistantMessage(msg);
    } else if (type === "tool/result") {
      appendToolResult(data);
    } else if (type === "plan/mode") {
      updatePlanModeUI(data.active);
    } else if (type === "turn/end") {
      setGenerating(false);
    }
  }

  function renderEvents(events) {
    chatStream.innerHTML = "";
    events.forEach(handleSessionEvent);
  }

  function appendUserMessage(content) {
    const row = document.createElement("div");
    row.className = "message-row user";
    row.innerHTML = `<div class="message-bubble">${escapeHtml(content)}</div>`;
    chatStream.appendChild(row);
    scrollToBottom();
  }

  function appendAssistantMessage(msg) {
    const row = document.createElement("div");
    row.className = "message-row assistant";

    let html = "";
    if (msg.reasoning_content) {
      html += `<details class="thought-block"><summary>思考过程</summary><div class="thought-content">${escapeHtml(msg.reasoning_content)}</div></details>`;
    }

    if (msg.content) {
      const parsedContent = typeof marked !== "undefined" ? marked.parse(msg.content) : escapeHtml(msg.content);
      html += `<div class="message-bubble">${parsedContent}</div>`;
    }

    if (msg.tool_calls) {
      msg.tool_calls.forEach((tc) => {
        const fn = tc.function || {};
        if (fn.name === "exit_plan_mode") {
          try {
            const args = JSON.parse(fn.arguments || "{}");
            html += renderPlanReviewCard(args.plan);
          } catch (e) {}
        } else {
          html += `<div class="tool-card"><div class="tool-header"><span>🔧 工具调用: ${fn.name}</span></div><div class="tool-output">${escapeHtml(fn.arguments || "")}</div></div>`;
        }
      });
    }

    row.innerHTML = html;
    chatStream.appendChild(row);
    scrollToBottom();
  }

  function appendToolResult(data) {
    const card = document.createElement("div");
    card.className = "tool-card";
    card.innerHTML = `<div class="tool-header"><span>✓ 工具结果: ${data.name || "tool"}</span></div><div class="tool-output">${escapeHtml(String(data.result || ""))}</div>`;
    chatStream.appendChild(card);
    scrollToBottom();
  }

  function renderPlanReviewCard(planMarkdown) {
    const renderedPlan = typeof marked !== "undefined" ? marked.parse(planMarkdown) : escapeHtml(planMarkdown);
    return `
      <div class="plan-review-card">
        <div class="plan-review-title">📋 规划方案评审 (Plan Review)</div>
        <div class="plan-content">${renderedPlan}</div>
        <div class="plan-actions">
          <button class="btn-approve" onclick="window.submitPlanFeedback('Approve')">批准并开始执行 (Approve)</button>
          <button class="btn-keep-planning" onclick="window.submitPlanFeedback('Keep planning')">继续规划 (Keep planning)</button>
        </div>
      </div>
    `;
  }

  window.submitPlanFeedback = async function (choice) {
    await fetch("/api/agent/prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: currentSessionId, content: choice }),
    });
  };

  async function handleSend() {
    const text = promptInput.value.trim();
    if (!text || isGenerating) return;

    promptInput.value = "";
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

  async function handleNewSession() {
    const newSid = "session-" + Date.now().toString(36);
    currentSessionId = newSid;
    chatStream.innerHTML = "";
    if (welcomeScreen) welcomeScreen.classList.remove("hidden");
    await fetch("/api/session/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: newSid, preset: selectPreset.value }),
    });
  }

  async function handlePresetChange() {
    const preset = selectPreset.value;
    alert(`已切换预设至: ${preset} (对新会话生效)`);
  }

  async function handleTogglePlanMode() {
    const isCurrentlyActive = planModeBtn.classList.contains("active");
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

  function setGenerating(generating) {
    isGenerating = generating;
    if (generating) {
      btnSend.classList.add("hidden");
      btnCancel.classList.remove("hidden");
    } else {
      btnSend.classList.remove("hidden");
      btnCancel.classList.add("hidden");
    }
  }

  function scrollToBottom() {
    chatStream.scrollTop = chatStream.scrollHeight;
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // Run on DOM ready
  document.addEventListener("DOMContentLoaded", init);
})();
