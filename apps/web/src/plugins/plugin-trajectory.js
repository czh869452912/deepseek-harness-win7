/**
 * Trajectory & Telemetry Plugin (`@deepseek-ai/dsh-client-ui-trajectory`).
 * 1:1 Implementation of Execution Timeline, Step Breakdown, Token Metrics, and Timing Stats.
 */

import { escapeHtml } from "../ui/markdown.js";

export function TrajectoryDetailsView(props) {
  const { ctx } = props;
  const sessionsMgr = ctx ? ctx.get("sessions") : null;
  const currSession = sessionsMgr ? sessionsMgr.getCurrentSession() : null;
  const events = currSession ? currSession.events : [];

  const rootEl = document.createElement("div");
  rootEl.className = "trajectory-details-container";

  let totalPromptTokens = 0;
  let totalCompTokens = 0;
  let toolCallsCount = 0;
  const steps = [];

  events.forEach((ev, idx) => {
    const type = ev.type;
    const data = ev.data || {};
    if (type === "turn/start") {
      steps.push({ title: `轮次 #${data.turn || idx + 1}`, duration: data.durationMs || 0, type: "turn" });
    } else if (type === "tool/call") {
      toolCallsCount++;
      steps.push({ title: `工具: ${data.name || 'tool'}`, type: "tool" });
    } else if (type === "token/meter" || (data && data.tokens)) {
      const tok = data.tokens || data;
      totalPromptTokens += (tok.prompt_tokens || 0);
      totalCompTokens += (tok.completion_tokens || 0);
    }
  });

  let stepsHtml = "";
  steps.forEach((s) => {
    const icon = s.type === "tool" ? "🔧" : "⚡";
    stepsHtml += `
      <div class="trajectory-step-item ${s.type}">
        <span class="step-icon">${icon}</span>
        <span class="step-title">${escapeHtml(s.title)}</span>
      </div>
    `;
  });

  rootEl.innerHTML = `
    <div class="trajectory-header">
      <span class="traj-title">⚡ 运行时指标与轨迹 (Trajectory)</span>
      <button class="btn-icon-plain" id="btn-close-details" title="关闭">✕</button>
    </div>
    <div class="trajectory-metrics-cards">
      <div class="metric-card">
        <div class="metric-val">${totalPromptTokens + totalCompTokens || 0}</div>
        <div class="metric-lbl">总 Token 消耗</div>
      </div>
      <div class="metric-card">
        <div class="metric-val">${toolCallsCount}</div>
        <div class="metric-lbl">工具调用次数</div>
      </div>
      <div class="metric-card">
        <div class="metric-val">${steps.length}</div>
        <div class="metric-lbl">步骤数 (Steps)</div>
      </div>
    </div>
    <div class="trajectory-timeline">
      <div class="timeline-title">执行时间线</div>
      <div class="timeline-list">${stepsHtml || '<div class="text-muted">暂无步骤数据</div>'}</div>
    </div>
  `;

  const btnClose = rootEl.querySelector("#btn-close-details");
  if (btnClose) {
    btnClose.addEventListener("click", () => {
      const layout = ctx ? ctx.get("layout") : null;
      if (layout) layout.closeDetails();
    });
  }

  return rootEl;
}

export class PluginTrajectory {
  static inject = ["slots", "sessions"];

  apply(ctx) {
    const slots = ctx.get("slots");
    slots.register({
      name: "details",
      inject: () => ({ ctx }),
    }, TrajectoryDetailsView);
  }
}
