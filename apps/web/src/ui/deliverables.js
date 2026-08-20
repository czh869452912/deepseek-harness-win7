/**
 * Produced Deliverables & Files Component (`@deepseek-ai/dsh-client-ui-deliverables`)
 * Renders the files modified/created in a turn as openable chips.
 */

import { escapeHtml } from "./markdown.js";

export function extractProducedFiles(events) {
  const paths = new Set();
  (events || []).forEach((e) => {
    if (e.type === "tool/result" || e.type === "assistant/message") {
      const msg = e.data && e.data.message;
      if (msg && msg.tool_calls) {
        msg.tool_calls.forEach((tc) => {
          const fn = tc.function || {};
          if (fn.name === "str_replace_editor") {
            try {
              const args = typeof fn.arguments === "string" ? JSON.parse(fn.arguments) : fn.arguments;
              if (args && args.path) paths.add(args.path);
            } catch (err) {}
          }
        });
      }
    }
  });
  return Array.from(paths);
}

export function renderProducedFiles(paths) {
  if (!paths || paths.length === 0) return "";
  const chipsHtml = paths.map((p) => {
    const filename = p.split(/[\\/]/).pop() || p;
    return `
      <span class="deliverable-chip" title="${escapeHtml(p)}" onclick="navigator.clipboard.writeText('${escapeHtml(p)}');alert('已复制文件路径: ${escapeHtml(p)}')">
        <span class="file-icon">📄</span>
        <span class="file-name">${escapeHtml(filename)}</span>
      </span>
    `;
  }).join("");

  return `
    <div class="deliverables-row">
      <span class="deliverables-label">产出产物:</span>
      <div class="deliverables-chips-list">${chipsHtml}</div>
    </div>
  `;
}
