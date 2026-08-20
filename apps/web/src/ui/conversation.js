/**
 * Conversation & Message Flow View (`@deepseek-ai/dsh-client-ui-conversation`)
 * Includes MessageIconActions (Copy, Clock, Branch) and TurnTail ProducedFiles.
 */

import { formatMarkdown, escapeHtml } from "./markdown.js";
import { renderToolCall, renderToolResult } from "./tools.js";
import { renderProducedFiles } from "./deliverables.js";

function getClockString() {
  const d = new Date();
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

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
    const clock = getClockString();
    row.innerHTML = `
      <div class="user-bubble">${escapeHtml(content)}</div>
      <div class="message-actions-row user-actions">
        <span class="message-clock">${clock}</span>
        <button type="button" class="btn-message-action" title="复制文本" onclick="navigator.clipboard.writeText(${JSON.stringify(content)})">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 4v12a2 2 0 002 2h8a2 2 0 002-2V7.242a2 2 0 00-.602-1.43L16.083 2.57A2 2 0 0014.685 2H10a2 2 0 00-2 2z"/><path d="M16 18v2a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h2"/></svg>
        </button>
      </div>
    `;
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
    const producedPaths = [];
    if (msg.tool_calls && Array.isArray(msg.tool_calls)) {
      msg.tool_calls.forEach((tc) => {
        const fn = tc.function || {};
        if (fn.name === "str_replace_editor") {
          try {
            const args = typeof fn.arguments === "string" ? JSON.parse(fn.arguments) : fn.arguments;
            if (args && args.path) producedPaths.push(args.path);
          } catch (e) {}
        }
        turn.innerHTML += renderToolCall(tc, this.onPlanAction);
      });
    }

    // 4. Produced deliverables chips
    if (producedPaths.length > 0) {
      turn.innerHTML += renderProducedFiles(producedPaths);
    }

    // 5. Message Actions Row
    const clock = getClockString();
    const copyText = msg.content || "";
    turn.innerHTML += `
      <div class="message-actions-row assistant-actions">
        <span class="message-clock">${clock}</span>
        <button type="button" class="btn-message-action" title="复制回复" onclick="navigator.clipboard.writeText(${JSON.stringify(copyText)})">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 4v12a2 2 0 002 2h8a2 2 0 002-2V7.242a2 2 0 00-.602-1.43L16.083 2.57A2 2 0 0014.685 2H10a2 2 0 00-2 2z"/><path d="M16 18v2a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h2"/></svg>
        </button>
      </div>
    `;

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
