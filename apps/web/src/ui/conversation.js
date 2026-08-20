/**
 * Conversation & Message Flow View (`@deepseek-ai/dsh-client-ui-conversation`)
 */

import { formatMarkdown, escapeHtml } from "./markdown.js";
import { renderToolCall, renderToolResult } from "./tools.js";

export class ConversationView {
  constructor({ containerId = "messages-container", flowId = "chat-flow", heroId = "hero-screen", onPlanAction }) {
    this.container = document.getElementById(containerId);
    this.flow = document.getElementById(flowId);
    this.hero = document.getElementById(heroId);
    this.onPlanAction = onPlanAction;
  }

  clear() {
    this.flow.innerHTML = "";
    this.hero.classList.remove("hidden");
  }

  renderEvents(events) {
    this.flow.innerHTML = "";
    if (events && events.length > 0) {
      this.hero.classList.add("hidden");
      events.forEach((e) => this.appendEvent(e));
    } else {
      this.hero.classList.remove("hidden");
    }
  }

  appendEvent(event) {
    this.hero.classList.add("hidden");
    const type = event.type;
    const data = event.data || {};

    if (type === "user/message") {
      this.appendUserMessage(data.content || "");
    } else if (type === "assistant/message") {
      const msg = data.message || {};
      this.appendAssistantMessage(msg);
    } else if (type === "tool/result") {
      this.appendToolResult(data);
    }
  }

  appendUserMessage(content) {
    const row = document.createElement("div");
    row.className = "message-row user";
    row.innerHTML = `<div class="user-bubble">${escapeHtml(content)}</div>`;
    this.flow.appendChild(row);
    this.scrollToBottom();
  }

  appendAssistantMessage(msg) {
    const row = document.createElement("div");
    row.className = "message-row assistant";

    const turn = document.createElement("div");
    turn.className = "assistant-turn";

    // 1. Reasoning Accordion
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
        turn.innerHTML += renderToolCall(tc, this.onPlanAction);
      });
    }

    row.appendChild(turn);
    this.flow.appendChild(row);
    this.scrollToBottom();
  }

  appendToolResult(data) {
    const cardHtml = renderToolResult(data);
    const wrap = document.createElement("div");
    wrap.innerHTML = cardHtml;
    this.flow.appendChild(wrap.firstElementChild);
    this.scrollToBottom();
  }

  scrollToBottom() {
    this.container.scrollTop = this.container.scrollHeight;
  }
}
