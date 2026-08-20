/**
 * Permission & Tool Approval Plugin (`@deepseek-ai/dsh-client-ui-permission-presets`).
 * 1:1 Implementation of Sensitive Tool Approval Prompt and POST /api/respond Confirmation Loop.
 */

import { escapeHtml } from "../ui/markdown.js";

export class PluginPermissions {
  static inject = ["slots", "sessions"];

  apply(ctx) {
    ctx.on("approval/requested", (payload) => {
      const { sessionId, rpcId, approvalId, toolName, reason } = payload;
      const chatFlow = document.getElementById("chat-flow");
      if (!chatFlow) return;

      const card = document.createElement("div");
      card.className = "approval-prompt-card";
      card.innerHTML = `
        <div class="approval-header">
          <span class="approval-icon">🛡️</span>
          <span class="approval-title">工具执行权限审批 (Permission Approval)</span>
        </div>
        <div class="approval-body">
          <p>智能体请求执行敏感工具: <code>${escapeHtml(toolName || "tool")}</code></p>
          ${reason ? `<div class="approval-reason">${escapeHtml(reason)}</div>` : ""}
        </div>
        <div class="approval-actions">
          <button class="btn-allow" id="btn-allow-once">✓ 允许单次 (Allowed Once)</button>
          <button class="btn-reject" id="btn-reject-approval">✕ 拒绝 (Reject)</button>
        </div>
      `;

      async function respond(outcome) {
        card.remove();
        try {
          await fetch("/api/respond", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              sessionId,
              rpcId,
              approvalId,
              outcome,
            }),
          });
        } catch (e) {
          console.error("[Approval] Error responding:", e);
        }
      }

      card.querySelector("#btn-allow-once").addEventListener("click", () => respond("allowed-once"));
      card.querySelector("#btn-reject-approval").addEventListener("click", () => respond("rejected"));

      chatFlow.appendChild(card);
      chatFlow.scrollTop = chatFlow.scrollHeight;
    });
  }
}
