/**
 * Specialized Interactive Tool Views (`@deepseek-ai/dsh-client-ui-tool`)
 * 1:1 Implementation of Code Diff Viewer, Terminal Shell Card, Search Result Card, Todo Card.
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

  let parsedArgs = {};
  try {
    parsedArgs = typeof rawArgs === "string" ? JSON.parse(rawArgs) : rawArgs;
  } catch (e) {
    parsedArgs = { raw: rawArgs };
  }

  // 1. str_replace_editor Diff View Card
  if (name === "str_replace_editor") {
    return renderDiffEditorCard(parsedArgs, "RUNNING");
  }

  // 2. pwsh / bash Terminal Card
  if (name === "pwsh" || name === "bash") {
    return renderTerminalCard(name, parsedArgs.command || "", "", "RUNNING");
  }

  // 3. glob / grep Search Card
  if (name === "glob" || name === "grep") {
    return renderSearchCard(name, parsedArgs, "", "RUNNING");
  }

  // 4. todo_write Card
  if (name === "todo_write") {
    return renderTodoCard(parsedArgs.todos || [], "RUNNING");
  }

  // Generic Fallback
  let prettyArgs = rawArgs;
  try {
    if (typeof rawArgs === "string") prettyArgs = JSON.stringify(JSON.parse(rawArgs), null, 2);
  } catch (e) {}

  return `
    <div class="tool-view-card">
      <div class="tool-view-header">
        <span class="tool-title">🔧 ${escapeHtml(name)}</span>
        <span class="tool-status-pill pill-running">RUNNING</span>
      </div>
      <div class="tool-view-body">${escapeHtml(prettyArgs)}</div>
    </div>
  `;
}

export function renderToolResult(resultData) {
  const name = resultData.name || "tool";
  const rawResult = resultData.result || "";

  if (name === "pwsh" || name === "bash") {
    return renderTerminalCard(name, "", rawResult, "SUCCESS");
  }

  if (name === "glob" || name === "grep") {
    return renderSearchCard(name, {}, rawResult, "SUCCESS");
  }

  if (name === "str_replace_editor") {
    return `
      <div class="tool-view-card tool-editor-result">
        <div class="tool-view-header">
          <span class="tool-title">📝 编辑器执行结果: ${escapeHtml(name)}</span>
          <span class="tool-status-pill pill-success">SUCCESS</span>
        </div>
        <div class="tool-view-body">${escapeHtml(String(rawResult))}</div>
      </div>
    `;
  }

  let icon = "✓";
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

/**
 * Render Code Diff Card for str_replace_editor
 */
export function renderDiffEditorCard(args, status = "RUNNING") {
  const command = args.command || "str_replace";
  const path = args.path || "file";
  const oldStr = args.old_str || "";
  const newStr = args.new_str || "";

  let diffLinesHtml = "";
  if (oldStr || newStr) {
    const oldLines = oldStr.split("\n");
    const newLines = newStr.split("\n");

    oldLines.forEach((l, i) => {
      if (l.trim() || oldLines.length === 1) {
        diffLinesHtml += `
          <div class="diff-line diff-del">
            <span class="diff-sign">-</span>
            <span class="diff-code">${escapeHtml(l)}</span>
          </div>
        `;
      }
    });

    newLines.forEach((l, i) => {
      if (l.trim() || newLines.length === 1) {
        diffLinesHtml += `
          <div class="diff-line diff-add">
            <span class="diff-sign">+</span>
            <span class="diff-code">${escapeHtml(l)}</span>
          </div>
        `;
      }
    });
  } else if (args.file_text) {
    // create file
    diffLinesHtml = `
      <div class="diff-line diff-add">
        <span class="diff-sign">+</span>
        <span class="diff-code">${escapeHtml(args.file_text.slice(0, 300))}...</span>
      </div>
    `;
  }

  return `
    <div class="tool-view-card tool-card-diff">
      <div class="tool-view-header">
        <div class="tool-title-wrap">
          <span class="tool-icon">📝</span>
          <span class="tool-file-path">${escapeHtml(path)}</span>
          <span class="tool-command-badge">${escapeHtml(command)}</span>
        </div>
        <span class="tool-status-pill pill-${status.toLowerCase()}">${status}</span>
      </div>
      <div class="diff-viewer-body">
        ${diffLinesHtml || `<div class="diff-empty">${escapeHtml(JSON.stringify(args))}</div>`}
      </div>
    </div>
  `;
}

/**
 * Render Terminal Output Card for pwsh / bash
 */
export function renderTerminalCard(shellName, command, output, status = "RUNNING") {
  return `
    <div class="tool-view-card tool-card-terminal">
      <div class="terminal-header">
        <div class="terminal-dots">
          <span class="dot-red"></span>
          <span class="dot-yellow"></span>
          <span class="dot-green"></span>
        </div>
        <span class="terminal-title">💻 ${escapeHtml(shellName.toUpperCase())} Terminal</span>
        <span class="tool-status-pill pill-${status.toLowerCase()}">${status}</span>
      </div>
      <div class="terminal-body">
        ${command ? `<div class="terminal-cmd-line"><span class="terminal-prompt">$</span> <code>${escapeHtml(command)}</code></div>` : ""}
        ${output ? `<pre class="terminal-output"><code>${escapeHtml(output)}</code></pre>` : ""}
      </div>
    </div>
  `;
}

/**
 * Render Search Result Card for glob / grep
 */
export function renderSearchCard(toolName, args, result, status = "RUNNING") {
  const pattern = args.pattern || args.query || "";
  const path = args.path || ".";

  return `
    <div class="tool-view-card tool-card-search">
      <div class="tool-view-header">
        <span class="tool-title">🔍 ${escapeHtml(toolName.toUpperCase())}: <code>${escapeHtml(pattern || path)}</code></span>
        <span class="tool-status-pill pill-${status.toLowerCase()}">${status}</span>
      </div>
      <div class="tool-view-body">
        ${result ? `<pre class="search-result-pre"><code>${escapeHtml(String(result))}</code></pre>` : `<span class="text-muted">正在检索文件库...</span>`}
      </div>
    </div>
  `;
}

/**
 * Render Todo Checklist Card for todo_write
 */
export function renderTodoCard(todos, status = "RUNNING") {
  let itemsHtml = "";
  if (Array.isArray(todos)) {
    itemsHtml = todos.map((t) => {
      const isDone = t.status === "completed";
      const isProgress = t.status === "in_progress";
      const icon = isDone ? "☑" : isProgress ? "⏳" : "☐";
      return `
        <div class="todo-item-row ${t.status || 'pending'}">
          <span class="todo-icon">${icon}</span>
          <span class="todo-title ${isDone ? 'todo-done' : ''}">${escapeHtml(t.title || t.content || '')}</span>
          <span class="todo-status-badge badge-${t.status || 'pending'}">${(t.status || 'pending').toUpperCase()}</span>
        </div>
      `;
    }).join("");
  }

  return `
    <div class="tool-view-card tool-card-todo">
      <div class="tool-view-header">
        <span class="tool-title">📋 任务清单 (Todo Plan)</span>
        <span class="tool-status-pill pill-${status.toLowerCase()}">${status}</span>
      </div>
      <div class="todo-list-body">
        ${itemsHtml || '<div class="text-muted">无任务项</div>'}
      </div>
    </div>
  `;
}

/**
 * Render Plan Review & Approval Card
 */
export function renderPlanReviewCard(planMarkdown, onPlanAction) {
  const formatted = formatMarkdown(planMarkdown || "");
  const cardId = "plan-card-" + Math.random().toString(36).slice(2, 8);

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
