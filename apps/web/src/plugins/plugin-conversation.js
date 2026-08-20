/**
 * Conversation Plugin (`@deepseek-ai/dsh-client-ui-conversation`).
 * 1:1 Implementation of Message Nodes, Live Token Streaming,
 * ReasoningRow, Tool Cards, and Conversation Slots.
 */

import { ConversationView } from "../ui/conversation.js";
import { formatMarkdown, escapeHtml } from "../ui/markdown.js";
import { ApiClient } from "../connection/api.js";

export function ConversationRoot(props) {
  const { renderSlot, ctx } = props;
  const layout = ctx ? ctx.get("layout") : null;
  const sessionsMgr = ctx ? ctx.get("sessions") : null;
  const currSession = sessionsMgr ? sessionsMgr.getCurrentSession() : null;

  const rootEl = document.createElement("div");
  rootEl.className = "conversation-container";

  // 1. Conversation Header (Model Selection, Preset, Details Toggle)
  const headerEl = document.createElement("header");
  headerEl.className = "conversation-header";
  headerEl.innerHTML = `
    <div class="header-left">
      <button class="btn-icon" id="btn-toggle-sidebar-hdr" title="折叠/展开侧边栏">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="3" y1="12" x2="21" y2="12"></line>
          <line x1="3" y1="6" x2="21" y2="6"></line>
          <line x1="3" y1="18" x2="21" y2="18"></line>
        </svg>
      </button>
      <div class="model-select-badge" id="btn-model-select">
        <span class="model-icon">🤖</span>
        <span class="model-name" id="current-model-label">deepseek-chat</span>
      </div>
      <span class="preset-pill" id="current-preset-label">Standard</span>
    </div>
    <div class="header-right">
      <button class="btn-header-action" id="btn-toggle-details" title="查看执行轨迹与指标">
        <span>⚡ 轨迹 (Trajectory)</span>
      </button>
    </div>
  `;

  // 2. Dock Area (Goal Bar / Plan Banner)
  const dockEl = document.createElement("div");
  dockEl.className = "conversation-dock";
  dockEl.id = "slot-outlet-dock";
  renderSlot("conversation.dock", { ctx }, dockEl);

  // 3. Message Body Flow
  const bodyEl = document.createElement("div");
  bodyEl.className = "conversation-body";
  bodyEl.id = "messages-container";
  bodyEl.innerHTML = `
    <div class="chat-flow" id="chat-flow"></div>
    <div class="hero-screen" id="hero-screen">
      <div class="hero-logo">🤖</div>
      <h2>DeepSeek Harness (Win7)</h2>
      <p>极简与创造并存的 Windows 7 原生 Cordis 智能体开发环境</p>
      <div class="hero-shortcuts">
        <div class="shortcut-chip"><span>⚡</span> <span>输入 / 唤起快捷指令</span></div>
        <div class="shortcut-chip"><span>📁</span> <span>输入 @ 关联工程文件</span></div>
        <div class="shortcut-chip"><span>📋</span> <span>支持 Plan 方案评审</span></div>
      </div>
    </div>
  `;

  // 4. Composer & Input Slot Area
  const composerEl = document.createElement("div");
  composerEl.className = "conversation-composer-wrap";
  composerEl.id = "slot-outlet-composer";
  renderSlot("conversation.composer", { ctx }, composerEl);

  rootEl.appendChild(headerEl);
  rootEl.appendChild(dockEl);
  rootEl.appendChild(bodyEl);
  rootEl.appendChild(composerEl);

  // Initialize ConversationView engine
  const convView = new ConversationView({
    containerId: "messages-container",
    flowId: "chat-flow",
    heroId: "hero-screen",
  });

  if (currSession) {
    convView.renderEvents(currSession.events || []);
  }

  // Bind Header actions
  headerEl.querySelector("#btn-toggle-sidebar-hdr").addEventListener("click", () => {
    if (layout) layout.toggleSidebar();
  });

  headerEl.querySelector("#btn-toggle-details").addEventListener("click", () => {
    if (layout) layout.toggleDetails();
  });

  return rootEl;
}

export class PluginConversation {
  static inject = ["slots", "sessions"];

  apply(ctx) {
    const slots = ctx.get("slots");
    slots.register({
      name: "conversation",
      children: {
        "conversation.header": { kind: "single", scope: "session-maybe" },
        "conversation.dock": { kind: "list", scope: "session-maybe" },
        "conversation.body": { kind: "single", scope: "session-maybe" },
        "conversation.composer": { kind: "chain", scope: "session-maybe" },
      },
      inject: () => ({ ctx }),
    }, ConversationRoot);
  }
}
