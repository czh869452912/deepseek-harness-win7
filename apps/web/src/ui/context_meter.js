/**
 * Context Meter Component (`@deepseek-ai/dsh-client-ui-conversation/ContextMeter`)
 * 14px SVG circular progress ring showing context window usage,
 * and expandable breakdown popover detailing System prompt, Tools, and Messages.
 */

import { formatTokens } from "./stats.js";

export class ContextMeterView {
  constructor({ containerId = "context-meter-container" }) {
    this.container = document.getElementById(containerId);
    this.capacity = 128000;
    this.usedTokens = 0;
    this.breakdown = {
      systemTokens: 1200,
      toolsTokens: 1800,
      messagesTokens: 0,
    };
    this.isOpen = false;

    this._createUI();
    this._bindEvents();
  }

  _createUI() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="context-meter-wrapper">
        <div class="context-meter-ring-btn" id="btn-context-ring" title="查看上下文窗口占用情况">
          <svg class="ring-svg" width="16" height="16" viewBox="0 0 36 36">
            <path class="ring-bg"
              d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            />
            <path class="ring-fill" id="context-ring-fill"
              stroke-dasharray="0, 100"
              d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            />
          </svg>
          <span class="ring-pct-text" id="context-pct-text">0%</span>
        </div>

        <div class="context-popover hidden" id="context-popover">
          <div class="popover-title">
            <span>🧠 上下文窗口容量 (Context)</span>
            <span class="popover-pct" id="popover-pct-label">0% 已用</span>
          </div>

          <div class="context-bar-track">
            <div class="bar-seg seg-sys" id="bar-seg-sys" style="width: 0%" title="系统提示词"></div>
            <div class="bar-seg seg-tools" id="bar-seg-tools" style="width: 0%" title="工具定义"></div>
            <div class="bar-seg seg-msgs" id="bar-seg-msgs" style="width: 0%" title="对话历史"></div>
          </div>

          <div class="context-stats-grid">
            <div class="stat-row">
              <span class="dot dot-sys"></span>
              <span class="label">系统提示词 (System):</span>
              <span class="val" id="val-sys">~1.2K</span>
            </div>
            <div class="stat-row">
              <span class="dot dot-tools"></span>
              <span class="label">工具定义 (Tools):</span>
              <span class="val" id="val-tools">~1.8K</span>
            </div>
            <div class="stat-row">
              <span class="dot dot-msgs"></span>
              <span class="label">对话历史 (Messages):</span>
              <span class="val" id="val-msgs">0</span>
            </div>
            <div class="stat-divider"></div>
            <div class="stat-row total-row">
              <span>总计已用:</span>
              <span class="val-total" id="val-total">~3.0K / 128K</span>
            </div>
          </div>
        </div>
      </div>
    `;

    this.ringFill = document.getElementById("context-ring-fill");
    this.pctText = document.getElementById("context-pct-text");
    this.popover = document.getElementById("context-popover");
    this.btnRing = document.getElementById("btn-context-ring");
  }

  _bindEvents() {
    if (!this.btnRing || !this.popover) return;
    this.btnRing.addEventListener("click", (e) => {
      e.stopPropagation();
      this.popover.classList.toggle("hidden");
    });

    document.addEventListener("click", (e) => {
      if (!this.popover.contains(e.target) && e.target !== this.btnRing) {
        this.popover.classList.add("hidden");
      }
    });
  }

  updateFromEvents(events) {
    let msgChars = 0;
    (events || []).forEach((e) => {
      if (e.type === "user/message") {
        msgChars += (e.data && e.data.content ? e.data.content.length : 0);
      } else if (e.type === "assistant/message") {
        const msg = e.data && e.data.message;
        if (msg) {
          msgChars += (msg.content ? msg.content.length : 0);
          msgChars += (msg.reasoning_content ? msg.reasoning_content.length : 0);
        }
      }
    });

    this.breakdown.messagesTokens = Math.round(msgChars / 3.8);
    this.usedTokens = this.breakdown.systemTokens + this.breakdown.toolsTokens + this.breakdown.messagesTokens;
    this.render();
  }

  render() {
    if (!this.ringFill) return;
    const pct = Math.min(100, Math.round((this.usedTokens / this.capacity) * 100));
    this.ringFill.setAttribute("stroke-dasharray", `${pct}, 100`);
    if (pct > 85) {
      this.ringFill.style.stroke = "var(--accent-red)";
    } else if (pct > 65) {
      this.ringFill.style.stroke = "var(--accent-amber)";
    } else {
      this.ringFill.style.stroke = "var(--accent-blue)";
    }

    if (this.pctText) this.pctText.textContent = `${pct}%`;

    const popoverPct = document.getElementById("popover-pct-label");
    if (popoverPct) popoverPct.textContent = `${pct}% 已用`;

    const sysPct = ((this.breakdown.systemTokens / this.capacity) * 100).toFixed(1);
    const toolsPct = ((this.breakdown.toolsTokens / this.capacity) * 100).toFixed(1);
    const msgsPct = ((this.breakdown.messagesTokens / this.capacity) * 100).toFixed(1);

    const segSys = document.getElementById("bar-seg-sys");
    const segTools = document.getElementById("bar-seg-tools");
    const segMsgs = document.getElementById("bar-seg-msgs");
    if (segSys) segSys.style.width = `${Math.max(1, sysPct)}%`;
    if (segTools) segTools.style.width = `${Math.max(1, toolsPct)}%`;
    if (segMsgs) segMsgs.style.width = `${Math.max(0, msgsPct)}%`;

    const valSys = document.getElementById("val-sys");
    const valTools = document.getElementById("val-tools");
    const valMsgs = document.getElementById("val-msgs");
    const valTotal = document.getElementById("val-total");

    if (valSys) valSys.textContent = `~${formatTokens(this.breakdown.systemTokens)}`;
    if (valTools) valTools.textContent = `~${formatTokens(this.breakdown.toolsTokens)}`;
    if (valMsgs) valMsgs.textContent = `~${formatTokens(this.breakdown.messagesTokens)}`;
    if (valTotal) valTotal.textContent = `~${formatTokens(this.usedTokens)} / ${formatTokens(this.capacity)}`;
  }
}
