/**
 * Conversation & Message Flow View (`@deepseek-ai/dsh-client-ui-conversation`)
 * 1:1 Implementation of Live Token Streaming, ThinkingTail rolling preview,
 * Fork session actions, and Context Disclosure rows.
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
  constructor({ containerId = "messages-container", flowId = "chat-flow", heroId = "hero-screen", onPlanAction, onForkSession }) {
    this.container = document.getElementById(containerId);
    this.flow = document.getElementById(flowId);
    this.hero = document.getElementById(heroId);
    this.onPlanAction = onPlanAction;
    this.onForkSession = onForkSession;

    // In-flight streaming state
    this.currentStreamingTurn = null;
    this.currentStreamingRow = null;
    this.partialAccumulator = {
      reasoning: "",
      content: "",
      toolCalls: [],
    };
    this.rafScheduled = false;
  }

  clear() {
    this.flow.innerHTML = "";
    this.hero.classList.remove("hidden");
    this.currentStreamingRow = null;
    this.currentStreamingTurn = null;
  }

  renderEvents(events) {
    this.flow.innerHTML = "";
    this.currentStreamingRow = null;
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
      this.finishCurrentStream();
      this.appendUserMessage(data.content || "");
    } else if (type === "assistant/message") {
      this.finishCurrentStream();
      const msg = data.message || {};
      this.appendAssistantMessage(msg, data.timing);
    } else if (type === "tool/result") {
      this.appendToolResult(data);
    } else if (type === "turn/end") {
      this.finishCurrentStream();
    }
  }

  /**
   * Handle real-time incoming token/chunk delta from LLM streaming
   */
  handleStreamChunk(chunkData) {
    this.hero.classList.add("hidden");
    if (!this.currentStreamingRow) {
      this._createStreamingRow();
    }

    const deltaType = chunkData.delta_type;
    if (deltaType === "reasoning" && chunkData.reasoning !== undefined) {
      this.partialAccumulator.reasoning = chunkData.reasoning;
    } else if (deltaType === "text" && chunkData.content !== undefined) {
      this.partialAccumulator.content = chunkData.content;
    } else if (deltaType === "tool_call" && chunkData.tool_calls) {
      this.partialAccumulator.toolCalls = chunkData.tool_calls;
    }

    this._scheduleFrameRender();
  }

  _createStreamingRow() {
    const row = document.createElement("div");
    row.className = "message-row assistant streaming-in-flight";

    const turn = document.createElement("div");
    turn.className = "assistant-turn";

    turn.innerHTML = `
      <details class="thought-accordion in-flight-thought hidden" open>
        <summary class="thought-summary">
          <span class="live-dot pulse-cyan"></span>
          <span class="thought-tail-preview">思考中...</span>
        </summary>
        <div class="thought-body"></div>
      </details>
      <div class="assistant-markdown"></div>
      <div class="streaming-tools-container"></div>
    `;

    row.appendChild(turn);
    this.flow.appendChild(row);
    this.currentStreamingRow = row;
    this.scrollToBottom();
  }

  _scheduleFrameRender() {
    if (this.rafScheduled) return;
    this.rafScheduled = true;

    requestAnimationFrame(() => {
      this.rafScheduled = false;
      if (!this.currentStreamingRow) return;

      const turn = this.currentStreamingRow.querySelector(".assistant-turn");
      const thoughtAccordion = turn.querySelector(".thought-accordion");
      const thoughtBody = turn.querySelector(".thought-body");
      const tailPreview = turn.querySelector(".thought-tail-preview");
      const markdownBody = turn.querySelector(".assistant-markdown");
      const toolsContainer = turn.querySelector(".streaming-tools-container");

      // 1. Thinking tail update
      if (this.partialAccumulator.reasoning) {
        thoughtAccordion.classList.remove("hidden");
        thoughtBody.textContent = this.partialAccumulator.reasoning;

        // Rolling tail line preview
        const lines = this.partialAccumulator.reasoning.trim().split("\n");
        const latestLine = lines[lines.length - 1] || "思考中...";
        tailPreview.textContent = `思考过程: ${latestLine.slice(0, 70)}`;
      }

      // 2. Text Markdown update
      if (this.partialAccumulator.content) {
        markdownBody.innerHTML = formatMarkdown(this.partialAccumulator.content);
      }

      // 3. Tool Calls update
      if (this.partialAccumulator.toolCalls.length > 0) {
        toolsContainer.innerHTML = this.partialAccumulator.toolCalls
          .map((tc) => renderToolCall(tc, this.onPlanAction))
          .join("");
      }

      this.scrollToBottom();
    });
  }

  finishCurrentStream() {
    if (this.currentStreamingRow) {
      this.currentStreamingRow.classList.remove("streaming-in-flight");
      const tailPreview = this.currentStreamingRow.querySelector(".thought-tail-preview");
      if (tailPreview) {
        tailPreview.textContent = "思考过程 (Thought Process)";
      }
      this.currentStreamingRow = null;
      this.partialAccumulator = { reasoning: "", content: "", toolCalls: [] };
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

  appendAssistantMessage(msg, timing = null) {
    const row = document.createElement("div");
    row.className = "message-row assistant";

    const turn = document.createElement("div");
    turn.className = "assistant-turn";

    // 1. Reasoning Accordion
    if (msg.reasoning_content) {
      turn.innerHTML += `
        <details class="thought-accordion">
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

    // 5. Message Actions Row with Fork Session
    const clock = getClockString();
    const copyText = msg.content || "";
    const ttftText = timing && timing.ttftMs ? ` · 首 token ${timing.ttftMs}ms` : "";

    turn.innerHTML += `
      <div class="message-actions-row assistant-actions">
        <span class="message-clock">${clock}${ttftText}</span>
        <button type="button" class="btn-message-action" title="复制回复" onclick="navigator.clipboard.writeText(${JSON.stringify(copyText)})">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 4v12a2 2 0 002 2h8a2 2 0 002-2V7.242a2 2 0 00-.602-1.43L16.083 2.57A2 2 0 0014.685 2H10a2 2 0 00-2 2z"/><path d="M16 18v2a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h2"/></svg>
        </button>
        <button type="button" class="btn-message-action" title="从此节点分支新会话 (Fork Session)" onclick="window._onForkFromHere()">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3v12M18 9a3 3 0 100-6 3 3 0 000 6zM6 21a3 3 0 100-6 3 3 0 000 6zM18 6a9 9 0 01-9 9"/></svg>
        </button>
      </div>
    `;

    row.appendChild(turn);
    this.flow.appendChild(row);
    this.scrollToBottom();

    window._onForkFromHere = () => {
      if (this.onForkSession) this.onForkSession();
    };
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
