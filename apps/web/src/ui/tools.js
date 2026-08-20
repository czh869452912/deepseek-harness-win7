/**
 * Specialized Interactive Tool Views (`@deepseek-ai/dsh-client-ui-tool`)
 * Renders file diffs, terminal windows, search results, todo lists, and plan review cards.
 */

import { formatMarkdown, escapeHtml } from "./markdown.js";

export function renderToolCall(toolCall, onPlanAction) {
  const fn = toolCall.function || {};
  const name = fn.name || "unknown_tool";
  let rawArgs = fn.arguments || "{}";

  if (name === "exit_plan_mode") {
    try {
      const parsed = typeof rawArgs === "string" ? JSON.parse(rawArgs) : rawArgs;
      return renderPlanReviewCard(parsed.plan, onPlanAction);
    } catch (e) {
      return renderPlanReviewCard(rawArgs, onPlanAction);
    }
  }

  let prettyArgs = rawArgs;
  try {
    if (typeof rawArgs === "string") {
      prettyArgs = JSON.stringify(JSON.parse(rawArgs), null, 2);
    }
  } catch (e) {}

  let icon = "🔧";
  let titleExtra = "";

  if (name === "str_replace_editor") {
    icon = "📝";
    titleExtra = "文件编辑器";
  } else if (name === "pwsh" || name === "bash") {
    icon = "💻";
    titleExtra = "持久终端 Shell";
  } else if (name === "glob" || name === "grep") {
    icon = "🔍";
    titleExtra = "文件搜索";
  } else if (name === "todo_write") {
    icon = "📋";
    titleExtra = "任务清单";
  }

  return `
    <div class="tool-view-card">
      <div class="tool-view-header">
        <span class="tool-title">${icon} ${escapeHtml(name)} ${titleExtra ? `<span style="font-size:11px;color:var(--text-muted)">(${titleExtra})</span>` : ""}</span>
        <span class="tool-status-pill pill-success">RUNNING</span>
      </div>
      <div class="tool-view-body">${escapeHtml(prettyArgs)}</div>
    </div>
  `;
}

export function renderToolResult(resultData) {
  const name = resultData.name || "tool";
  const rawResult = resultData.result || "";

  let icon = "✓";
  if (name === "pwsh" || name === "bash") icon = "💻";
  else if (name === "str_replace_editor") icon = "📝";
  else if (name === "glob" || name === "grep") icon = "🔍";

  return `
    <div class="tool-view-card">
      <div class="tool-view-header">
        <span class="tool-title">${icon} 结果: ${escapeHtml(name)}</span>
        <span class="tool-status-pill pill-success">SUCCESS</span>
      </div>
      <div class="tool-view-body">${escapeHtml(String(rawResult))}</div>
    </div>
  `;
}

export function renderPlanReviewCard(planMarkdown, onPlanAction) {
  const formatted = formatMarkdown(planMarkdown || "");
  const cardId = "plan-card-" + Math.random().toString(36).slice(2, 8);

  // Expose global callback
  window[`approvePlan_${cardId}`] = () => {
    if (onPlanAction) onPlanAction("Approve");
  };
  window[`rejectPlan_${cardId}`] = () => {
    if (onPlanAction) onPlanAction("Keep planning");
  };

  return `
    <div class="plan-review-container">
      <div class="plan-header-title">
        <span>📋</span>
        <span>规划方案评审与审批 (Plan Review & Approval)</span>
      </div>
      <div class="plan-markdown-body">${formatted}</div>
      <div class="plan-button-row">
        <button class="btn-plan-approve" onclick="window['approvePlan_${cardId}']()">✓ 批准并执行方案 (Approve)</button>
        <button class="btn-plan-reject" onclick="window['rejectPlan_${cardId}']()">✎ 继续补充规划 (Keep planning)</button>
      </div>
    </div>
  `;
}
