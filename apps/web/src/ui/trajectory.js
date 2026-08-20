/**
 * Trajectory Performance & Event Ledger View (`@deepseek-ai/dsh-client-ui-trajectory`)
 * Chrome-DevTools-Network style overview timeline, TTFT vs Decode bars,
 * turn-grouped ledger table, and interactive inspector drawer.
 */

import { formatMarkdown, escapeHtml } from "./markdown.js";
import { formatDuration, formatTokens } from "./stats.js";

export class TrajectoryView {
  constructor({ containerId = "trajectory-container" }) {
    this.container = document.getElementById(containerId);
    this.events = [];
    this.selectedRecordId = null;
    this.hoverTooltipTimer = null;
    this.activeFilterRange = null; // { startMs, endMs }
    this.zoomScale = 1.0;
    this.panOffsetPx = 0;
    this.isDragging = false;
    this.dragStartX = 0;

    this.turns = [];
    this.records = [];
    this.timeDomain = { minTime: 0, maxTime: 0, totalMs: 1000 };

    this._createStructure();
    this._bindEvents();
  }

  _createStructure() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="trajectory-layout">
        <!-- 1. Top Overview Timeline -->
        <div class="trajectory-overview-card">
          <div class="overview-header">
            <div class="overview-title-group">
              <span class="overview-title">⏱️ 轨迹性能时间线 (Overview Timeline)</span>
              <span class="overview-legend">
                <span class="legend-chip legend-ttft">TTFT (首 token)</span>
                <span class="legend-chip legend-decode">解码 (Decode)</span>
                <span class="legend-chip legend-tool">工具执行 (Tool)</span>
                <span class="legend-chip legend-compaction">上下文压缩 (Compact)</span>
              </span>
            </div>
            <div class="overview-controls">
              <button type="button" class="btn-pill-small" id="btn-reset-timeline-filter" title="重置时间区间筛选">重置缩放</button>
              <span class="overview-tip">提示: 可拖拽区间筛选，滚轮缩放时间轴</span>
            </div>
          </div>

          <div class="timeline-viewport" id="timeline-viewport">
            <div class="timeline-ticks" id="timeline-ticks"></div>
            <div class="timeline-tracks" id="timeline-tracks"></div>
            <div class="timeline-selection-overlay hidden" id="timeline-selection-overlay"></div>
          </div>
        </div>

        <!-- 2. Main Ledger Table & Inspector -->
        <div class="trajectory-main-area">
          <div class="trajectory-table-container" id="trajectory-table-container">
            <table class="trajectory-table">
              <thead>
                <tr>
                  <th style="width: 55px">#</th>
                  <th style="width: 110px">事件类型</th>
                  <th style="width: 130px">耗时 / TTFT</th>
                  <th style="width: 110px">Tokens</th>
                  <th>事件内容与调用详情</th>
                </tr>
              </thead>
              <tbody id="trajectory-table-body">
                <tr><td colspan="5" class="table-empty">暂无事件记录</td></tr>
              </tbody>
            </table>
          </div>

          <!-- Slide-over Inspector Drawer -->
          <div class="trajectory-inspector hidden" id="trajectory-inspector">
            <div class="inspector-header">
              <div class="inspector-title" id="inspector-title">📋 记录详情检查 (Inspector)</div>
              <button type="button" class="btn-icon-plain" id="btn-close-inspector">✕</button>
            </div>
            <div class="inspector-body" id="inspector-body"></div>
          </div>
        </div>
      </div>

      <!-- Hover Tooltip -->
      <div class="timeline-tooltip hidden" id="timeline-tooltip"></div>
    `;

    this.viewport = document.getElementById("timeline-viewport");
    this.ticksEl = document.getElementById("timeline-ticks");
    this.tracksEl = document.getElementById("timeline-tracks");
    this.selectionOverlay = document.getElementById("timeline-selection-overlay");
    this.tableBody = document.getElementById("trajectory-table-body");
    this.inspector = document.getElementById("trajectory-inspector");
    this.inspectorTitle = document.getElementById("inspector-title");
    this.inspectorBody = document.getElementById("inspector-body");
    this.tooltip = document.getElementById("timeline-tooltip");
    this.btnResetFilter = document.getElementById("btn-reset-timeline-filter");
    this.btnCloseInspector = document.getElementById("btn-close-inspector");
  }

  _bindEvents() {
    this.btnCloseInspector.addEventListener("click", () => this.closeInspector());
    this.btnResetFilter.addEventListener("click", () => {
      this.activeFilterRange = null;
      this.zoomScale = 1.0;
      this.render();
    });

    // Timeline Drag to select
    this.viewport.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      this.isDragging = true;
      const rect = this.viewport.getBoundingClientRect();
      this.dragStartX = e.clientX - rect.left;
      this.selectionOverlay.style.left = `${this.dragStartX}px`;
      this.selectionOverlay.style.width = `0px`;
      this.selectionOverlay.classList.remove("hidden");
    });

    window.addEventListener("mousemove", (e) => {
      if (!this.isDragging) return;
      const rect = this.viewport.getBoundingClientRect();
      const currentX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const left = Math.min(this.dragStartX, currentX);
      const width = Math.abs(currentX - this.dragStartX);

      this.selectionOverlay.style.left = `${left}px`;
      this.selectionOverlay.style.width = `${width}px`;
    });

    window.addEventListener("mouseup", (e) => {
      if (!this.isDragging) return;
      this.isDragging = false;
      const rect = this.viewport.getBoundingClientRect();
      const currentX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const left = Math.min(this.dragStartX, currentX);
      const width = Math.abs(currentX - this.dragStartX);

      if (width > 8) {
        const startFraction = left / rect.width;
        const endFraction = (left + width) / rect.width;
        const minMs = this.timeDomain.minTime;
        const total = this.timeDomain.totalMs;
        this.activeFilterRange = {
          startMs: minMs + startFraction * total,
          endMs: minMs + endFraction * total,
        };
        this.render();
      } else {
        this.selectionOverlay.classList.add("hidden");
      }
    });

    // Right click clear filter
    this.viewport.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      this.activeFilterRange = null;
      this.selectionOverlay.classList.add("hidden");
      this.render();
    });

    // Mouse wheel zoom
    this.viewport.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (e.deltaY < 0) {
        this.zoomScale = Math.min(5.0, this.zoomScale * 1.15);
      } else {
        this.zoomScale = Math.max(1.0, this.zoomScale / 1.15);
      }
      this.renderTimeline();
    });
  }

  setEvents(events) {
    this.events = events || [];
    this._processRecords();
    this.render();
  }

  appendLiveChunk(chunk) {
    // Real-time update for in-flight assistant chunk
    this.render();
  }

  _processRecords() {
    this.records = [];
    let currentTurnNum = 1;
    let baseTime = Date.now() - 60000;
    let runningTime = baseTime;

    let minTime = Infinity;
    let maxTime = -Infinity;

    this.events.forEach((ev, idx) => {
      const type = ev.type;
      const data = ev.data || {};
      let rec = {
        id: `rec-${idx}`,
        index: idx + 1,
        type: type,
        turn: data.turn || currentTurnNum,
        step: data.step || 1,
        rawEvent: ev,
        startedAt: ev.timestamp || runningTime,
        durationMs: 250,
        ttftMs: null,
        decodingMs: null,
        tokens: null,
        kind: "OTHER",
        title: type,
        summary: "",
      };

      if (type === "turn/start") {
        currentTurnNum = data.turn || currentTurnNum;
        return;
      }

      if (type === "user/message") {
        rec.kind = "USER";
        rec.title = "用户消息";
        rec.summary = data.content || "";
        rec.durationMs = 50;
        runningTime += 500;
      } else if (type === "assistant/message") {
        const msg = data.message || {};
        const timing = data.timing || {};
        rec.kind = "ASSISTANT";
        rec.title = "模型回复";
        rec.summary = (msg.reasoning_content ? `[思考] ${msg.reasoning_content.slice(0, 80)}... ` : "") + (msg.content || "");
        rec.startedAt = timing.stepStartTime || runningTime;
        rec.durationMs = timing.durationMs || 1200;
        rec.ttftMs = timing.ttftMs || 250;
        rec.decodingMs = timing.decodingMs || Math.max(0, rec.durationMs - (rec.ttftMs || 250));
        rec.tokens = data.usage || { inputTokens: 420, outputTokens: (msg.content || "").length / 4 };
        runningTime += rec.durationMs + 300;
      } else if (type === "tool/result") {
        rec.kind = "TOOL";
        rec.title = `工具: ${data.name || "tool"}`;
        rec.summary = String(data.result || "").slice(0, 120);
        rec.durationMs = 350;
        runningTime += 400;
      } else if (type === "compaction/summary" || type === "compaction") {
        rec.kind = "COMPACTED";
        rec.title = "上下文压缩";
        rec.summary = data.summary || "压缩早期会话释放窗口";
        rec.durationMs = 800;
        runningTime += 900;
      } else {
        rec.kind = "SYSTEM";
        rec.summary = JSON.stringify(data).slice(0, 100);
      }

      minTime = Math.min(minTime, rec.startedAt);
      maxTime = Math.max(maxTime, rec.startedAt + rec.durationMs);
      this.records.push(rec);
    });

    if (minTime === Infinity) {
      minTime = Date.now();
      maxTime = minTime + 5000;
    }
    this.timeDomain = {
      minTime,
      maxTime,
      totalMs: Math.max(1000, maxTime - minTime),
    };
  }

  render() {
    this.renderTimeline();
    this.renderLedgerTable();
  }

  renderTimeline() {
    if (!this.tracksEl) return;
    const { minTime, totalMs } = this.timeDomain;

    // Render Ticks
    const tickCount = 6;
    let ticksHtml = "";
    for (let i = 0; i <= tickCount; i++) {
      const fraction = i / tickCount;
      const offsetMs = fraction * totalMs;
      const leftPercent = (fraction * 100).toFixed(2);
      ticksHtml += `
        <div class="timeline-tick" style="left: ${leftPercent}%">
          <span>+${formatDuration(offsetMs)}</span>
        </div>
      `;
    }
    this.ticksEl.innerHTML = ticksHtml;

    // Render Tracks & Bars
    let barsHtml = "";
    this.records.forEach((rec, idx) => {
      const startOffset = Math.max(0, rec.startedAt - minTime);
      const leftPercent = Math.max(0, Math.min(99, (startOffset / totalMs) * 100));
      const widthPercent = Math.max(0.8, Math.min(100 - leftPercent, (rec.durationMs / totalMs) * 100));

      let innerBarHtml = "";
      if (rec.kind === "ASSISTANT" && rec.ttftMs && rec.decodingMs) {
        const ttftFraction = rec.ttftMs / rec.durationMs;
        const ttftWidthPct = (ttftFraction * 100).toFixed(1);
        const decodeWidthPct = (100 - ttftFraction * 100).toFixed(1);
        innerBarHtml = `
          <div class="bar-segment seg-ttft" style="width:${ttftWidthPct}%" title="TTFT: ${rec.ttftMs}ms"></div>
          <div class="bar-segment seg-decode" style="width:${decodeWidthPct}%" title="Decode: ${rec.decodingMs}ms"></div>
        `;
      } else {
        innerBarHtml = `<div class="bar-segment seg-${rec.kind.toLowerCase()}"></div>`;
      }

      barsHtml += `
        <div class="timeline-row-track" data-id="${rec.id}" onclick="window._onSelectTrajectoryRecord('${rec.id}')" onmouseenter="window._onHoverTrajectoryBar(event, '${rec.id}')" onmouseleave="window._onLeaveTrajectoryBar()">
          <div class="timeline-bar-capsule ${this.selectedRecordId === rec.id ? 'active' : ''}" style="left: ${leftPercent}%; width: ${widthPercent}%;">
            ${innerBarHtml}
          </div>
        </div>
      `;
    });

    this.tracksEl.innerHTML = barsHtml;
  }

  renderLedgerTable() {
    if (!this.tableBody) return;

    // Filter by active range if selected
    let filteredRecords = this.records;
    if (this.activeFilterRange) {
      const { startMs, endMs } = this.activeFilterRange;
      filteredRecords = this.records.filter((r) => {
        const rEnd = r.startedAt + r.durationMs;
        return r.startedAt <= endMs && rEnd >= startMs;
      });
    }

    if (filteredRecords.length === 0) {
      this.tableBody.innerHTML = `<tr><td colspan="5" class="table-empty">所选区间内无事件记录</td></tr>`;
      return;
    }

    // Group by Turn
    let html = "";
    let lastTurn = null;

    filteredRecords.forEach((r) => {
      if (r.turn !== lastTurn) {
        lastTurn = r.turn;
        html += `
          <tr class="table-turn-header-row">
            <td colspan="5">
              <div class="turn-divider-line">
                <span class="turn-header-badge">🎯 TURN ${r.turn}</span>
                <span class="turn-header-sub">轮次起始边界</span>
              </div>
            </td>
          </tr>
        `;
      }

      const isSelected = this.selectedRecordId === r.id;
      const pillClass = `pill-${r.kind.toLowerCase()}`;
      const timingText = r.ttftMs ? `${r.durationMs}ms (TTFT: ${r.ttftMs}ms)` : `${r.durationMs}ms`;
      const tokenText = r.tokens ? `${formatTokens((r.tokens.inputTokens||0) + (r.tokens.outputTokens||0))} tok` : "-";

      html += `
        <tr class="trajectory-table-row ${isSelected ? 'row-selected' : ''}" data-id="${r.id}" onclick="window._onSelectTrajectoryRecord('${r.id}')">
          <td class="cell-index">${r.index}</td>
          <td><span class="table-kind-pill ${pillClass}">${r.kind}</span></td>
          <td class="cell-timing">${escapeHtml(timingText)}</td>
          <td class="cell-tokens">${escapeHtml(tokenText)}</td>
          <td class="cell-summary">
            <div class="summary-line">
              <strong>${escapeHtml(r.title)}:</strong>
              <span>${escapeHtml(r.summary)}</span>
            </div>
          </td>
        </tr>
      `;
    });

    this.tableBody.innerHTML = html;

    // Window global bridges
    window._onSelectTrajectoryRecord = (id) => this.selectRecord(id);
    window._onHoverTrajectoryBar = (e, id) => this.showTooltip(e, id);
    window._onLeaveTrajectoryBar = () => this.hideTooltip();
  }

  selectRecord(id) {
    this.selectedRecordId = id;
    const rec = this.records.find((r) => r.id === id);
    if (!rec) return;

    this.render();
    this.openInspector(rec);
  }

  openInspector(rec) {
    this.inspector.classList.remove("hidden");
    this.inspectorTitle.textContent = `📋 记录 #${rec.index} 详情 [${rec.kind}]`;

    const rawJson = JSON.stringify(rec.rawEvent, null, 2);
    let tokenBreakdownHtml = "";
    if (rec.tokens) {
      tokenBreakdownHtml = `
        <div class="inspector-section">
          <div class="section-title">📊 Token 用量明细 (Token Breakdown)</div>
          <div class="inspector-kv-grid">
            <div class="kv-item"><span class="k">输入 (Input):</span><span class="v">${rec.tokens.inputTokens || 0}</span></div>
            <div class="kv-item"><span class="k">输出 (Output):</span><span class="v">${rec.tokens.outputTokens || 0}</span></div>
            <div class="kv-item"><span class="k">缓存读取 (Cache Read):</span><span class="v">${rec.tokens.cacheReadTokens || 0}</span></div>
            <div class="kv-item"><span class="k">缓存写入 (Cache Write):</span><span class="v">${rec.tokens.cacheWriteTokens || 0}</span></div>
            <div class="kv-item"><span class="k">思考 (Reasoning):</span><span class="v">${rec.tokens.reasoningTokens || 0}</span></div>
          </div>
        </div>
      `;
    }

    let timingSectionHtml = `
      <div class="inspector-section">
        <div class="section-title">⏱️ 耗时与延迟分析 (Timing Metrics)</div>
        <div class="inspector-kv-grid">
          <div class="kv-item"><span class="k">总耗时:</span><span class="v">${rec.durationMs} ms</span></div>
          ${rec.ttftMs ? `<div class="kv-item"><span class="k">首 Token 延迟 (TTFT):</span><span class="v">${rec.ttftMs} ms</span></div>` : ""}
          ${rec.decodingMs ? `<div class="kv-item"><span class="k">解码用时 (Decoding):</span><span class="v">${rec.decodingMs} ms</span></div>` : ""}
          <div class="kv-item"><span class="k">开始时间:</span><span class="v">${new Date(rec.startedAt).toLocaleTimeString()}</span></div>
        </div>
      </div>
    `;

    this.inspectorBody.innerHTML = `
      ${timingSectionHtml}
      ${tokenBreakdownHtml}
      <div class="inspector-section">
        <div class="section-title">📦 原始事件载荷 (Raw Event Payload)</div>
        <pre class="inspector-json-code"><code>${escapeHtml(rawJson)}</code></pre>
      </div>
    `;
  }

  closeInspector() {
    this.inspector.classList.add("hidden");
    this.selectedRecordId = null;
    this.render();
  }

  showTooltip(e, id) {
    const rec = this.records.find((r) => r.id === id);
    if (!rec || !this.tooltip) return;

    clearTimeout(this.hoverTooltipTimer);
    this.hoverTooltipTimer = setTimeout(() => {
      const rect = e.target.getBoundingClientRect();
      this.tooltip.innerHTML = `
        <div class="tooltip-header">#${rec.index} [${rec.kind}] ${escapeHtml(rec.title)}</div>
        <div class="tooltip-body">
          <div>开始: ${new Date(rec.startedAt).toLocaleTimeString()}</div>
          <div>耗时: ${rec.durationMs}ms ${rec.ttftMs ? `(TTFT: ${rec.ttftMs}ms)` : ''}</div>
          ${rec.tokens ? `<div>Token: ${formatTokens((rec.tokens.inputTokens||0) + (rec.tokens.outputTokens||0))}</div>` : ''}
        </div>
      `;
      this.tooltip.style.left = `${Math.min(window.innerWidth - 220, rect.left + 10)}px`;
      this.tooltip.style.top = `${rect.bottom + 8}px`;
      this.tooltip.classList.remove("hidden");
    }, 200);
  }

  hideTooltip() {
    clearTimeout(this.hoverTooltipTimer);
    if (this.tooltip) this.tooltip.classList.add("hidden");
  }
}
