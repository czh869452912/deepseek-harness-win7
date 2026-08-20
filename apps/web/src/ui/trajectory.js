/**
 * Trajectory Performance & Event Ledger View (`@deepseek-ai/dsh-client-ui-trajectory`)
 * 1:1 Reference-Aligned 3-Lane Overview Timeline, In-Flight Token Streaming,
 * TTFT vs Decode dual-color split bars, turn-grouped ledger table, and interactive inspector.
 */

import { formatMarkdown, escapeHtml } from "./markdown.js";
import { formatDuration, formatTokens } from "./stats.js";
import {
  deriveTrajectoryTimeline,
  trajectoryTimelineFocusIndexes,
  formatTimelineOffset,
} from "../runtime/trajectory_timeline.js";

export class TrajectoryView {
  constructor({ containerId = "trajectory-container", onSelectRecord = null } = {}) {
    this.container = typeof containerId === "string" ? document.getElementById(containerId) : containerId;
    this.onSelectRecord = onSelectRecord;

    this.turns = [];
    this.selectedRecordId = null;
    this.hoverTooltipTimer = null;
    this.activeFilterRange = null; // { start, end }
    this.timelineMode = "duration"; // 'sequence' | 'duration' | 'time' | 'actual'
    this.zoomScale = 1.0;
    this.isDragging = false;
    this.dragStartX = 0;

    this.timelineModel = null;
    this.records = [];

    this._mounted = false;
    if (this.container) {
      this._createStructure();
      this._bindEvents();
      this._mounted = true;
    }
  }

  mount(container) {
    this.container = container;
    this._createStructure();
    this._bindEvents();
    this._mounted = true;
    this.render();
    return this.container;
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
              <div class="mode-select-group">
                <button type="button" class="btn-mode-pill ${this.timelineMode === "duration" ? "active" : ""}" data-mode="duration">耗时视图</button>
                <button type="button" class="btn-mode-pill ${this.timelineMode === "sequence" ? "active" : ""}" data-mode="sequence">序列视图</button>
                <button type="button" class="btn-mode-pill ${this.timelineMode === "time" ? "active" : ""}" data-mode="time">绝对时间</button>
                <button type="button" class="btn-mode-pill ${this.timelineMode === "actual" ? "active" : ""}" data-mode="actual">真实时间</button>
              </div>
              <button type="button" class="btn-pill-small" id="btn-traj-reset-filter" title="重置缩放与筛选">重置</button>
            </div>
          </div>

          <div class="timeline-viewport" id="traj-timeline-viewport">
            <div class="timeline-ticks" id="traj-timeline-ticks"></div>
            <div class="timeline-tracks" id="traj-timeline-tracks"></div>
            <div class="timeline-selection-overlay hidden" id="traj-timeline-overlay"></div>
          </div>
        </div>

        <!-- 2. Main Ledger Table & Inspector -->
        <div class="trajectory-main-area">
          <div class="trajectory-table-container">
            <table class="trajectory-table">
              <thead>
                <tr>
                  <th style="width: 60px">#</th>
                  <th style="width: 110px">事件类型</th>
                  <th style="width: 140px">耗时 / TTFT</th>
                  <th style="width: 110px">Tokens</th>
                  <th>事件内容与调用详情</th>
                </tr>
              </thead>
              <tbody id="traj-table-body">
                <tr><td colspan="5" class="table-empty">暂无事件记录</td></tr>
              </tbody>
            </table>
          </div>

          <!-- Slide-over Inspector Drawer -->
          <div class="trajectory-inspector hidden" id="traj-inspector">
            <div class="inspector-header">
              <div class="inspector-title" id="traj-inspector-title">📋 记录详情 (Inspector)</div>
              <button type="button" class="btn-icon-plain" id="btn-traj-close-inspector">✕</button>
            </div>
            <div class="inspector-body" id="traj-inspector-body"></div>
          </div>
        </div>
      </div>

      <!-- Hover Tooltip -->
      <div class="timeline-tooltip hidden" id="traj-timeline-tooltip"></div>
    `;

    this.viewport = this.container.querySelector("#traj-timeline-viewport");
    this.ticksEl = this.container.querySelector("#traj-timeline-ticks");
    this.tracksEl = this.container.querySelector("#traj-timeline-tracks");
    this.selectionOverlay = this.container.querySelector("#traj-timeline-overlay");
    this.tableBody = this.container.querySelector("#traj-table-body");
    this.inspector = this.container.querySelector("#traj-inspector");
    this.inspectorTitle = this.container.querySelector("#traj-inspector-title");
    this.inspectorBody = this.container.querySelector("#traj-inspector-body");
    this.tooltip = this.container.querySelector("#traj-timeline-tooltip");
    this.btnResetFilter = this.container.querySelector("#btn-traj-reset-filter");
    this.btnCloseInspector = this.container.querySelector("#btn-traj-close-inspector");
  }

  _bindEvents() {
    if (!this.container) return;

    // Mode Switcher Buttons
    this.container.querySelectorAll(".btn-mode-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-mode");
        if (mode && mode !== this.timelineMode) {
          this.timelineMode = mode;
          this.container.querySelectorAll(".btn-mode-pill").forEach((b) => {
            b.classList.toggle("active", b.getAttribute("data-mode") === mode);
          });
          this.render();
        }
      });
    });

    // Reset Button
    if (this.btnResetFilter) {
      this.btnResetFilter.addEventListener("click", () => {
        this.activeFilterRange = null;
        this.zoomScale = 1.0;
        if (this.selectionOverlay) this.selectionOverlay.classList.add("hidden");
        this.render();
      });
    }

    // Close Inspector
    if (this.btnCloseInspector) {
      this.btnCloseInspector.addEventListener("click", () => {
        this.closeInspector();
      });
    }

    // Timeline Drag to filter interval
    if (this.viewport) {
      this.viewport.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        this.isDragging = true;
        const rect = this.viewport.getBoundingClientRect();
        this.dragStartX = e.clientX - rect.left;
        if (this.selectionOverlay) {
          this.selectionOverlay.style.left = `${this.dragStartX}px`;
          this.selectionOverlay.style.width = `0px`;
          this.selectionOverlay.classList.remove("hidden");
        }
      });

      window.addEventListener("mousemove", (e) => {
        if (!this.isDragging || !this.viewport || !this.selectionOverlay) return;
        const rect = this.viewport.getBoundingClientRect();
        const currentX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
        const left = Math.min(this.dragStartX, currentX);
        const width = Math.abs(currentX - this.dragStartX);

        this.selectionOverlay.style.left = `${left}px`;
        this.selectionOverlay.style.width = `${width}px`;
      });

      window.addEventListener("mouseup", (e) => {
        if (!this.isDragging || !this.viewport) return;
        this.isDragging = false;
        const rect = this.viewport.getBoundingClientRect();
        const currentX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
        const left = Math.min(this.dragStartX, currentX);
        const width = Math.abs(currentX - this.dragStartX);

        if (width > 8 && this.timelineModel) {
          const startFraction = left / rect.width;
          const endFraction = (left + width) / rect.width;
          const minTime = this.timelineModel.start;
          const total = this.timelineModel.total || 1000;
          this.activeFilterRange = {
            start: minTime + startFraction * total,
            end: minTime + endFraction * total,
          };
          this.render();
        } else if (this.selectionOverlay) {
          this.selectionOverlay.classList.add("hidden");
        }
      });

      // Right click clear filter
      this.viewport.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        this.activeFilterRange = null;
        if (this.selectionOverlay) this.selectionOverlay.classList.add("hidden");
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
        this._renderTimeline();
      });
    }
  }

  updateLayout(turns = []) {
    this.turns = turns || [];
    this.render();
  }

  render() {
    if (!this._mounted) return;
    this.timelineModel = deriveTrajectoryTimeline(this.turns, this.timelineMode);
    this._extractRecords();
    this._renderTimeline();
    this._renderLedgerTable();
  }

  _extractRecords() {
    this.records = [];
    for (const turn of this.turns) {
      for (const group of turn.groups || []) {
        for (const cell of group.cells || []) {
          this.records.push(cell);
        }
      }
    }
  }

  _renderTimeline() {
    if (!this.ticksEl || !this.tracksEl) return;

    if (!this.timelineModel || !this.timelineModel.spans || this.timelineModel.spans.length === 0) {
      this.ticksEl.innerHTML = `<div class="timeline-tick" style="left:0%"><span>+0ms</span></div>`;
      this.tracksEl.innerHTML = `<div class="timeline-empty-hint">等待会话事件...</div>`;
      return;
    }

    const { start: minTime, total: totalDomain, spans, turnBoundaries } = this.timelineModel;
    const total = Math.max(1, totalDomain);

    // 1. Render Ticks
    const tickCount = 6;
    let ticksHtml = "";
    for (let i = 0; i <= tickCount; i++) {
      const fraction = i / tickCount;
      const offsetMs = fraction * total;
      const leftPercent = (fraction * 100).toFixed(2);
      const label = this.timelineMode === "sequence"
        ? `Step ${Math.round(fraction * total)}`
        : `+${formatTimelineOffset(offsetMs)}`;

      ticksHtml += `
        <div class="timeline-tick" style="left: ${leftPercent}%">
          <span>${label}</span>
        </div>
      `;
    }
    this.ticksEl.innerHTML = ticksHtml;

    // 2. Render 3-Lane Tracks & Bars
    let barsHtml = "";

    // Render turn boundary vertical divider lines
    if (turnBoundaries && turnBoundaries.length > 0) {
      turnBoundaries.forEach((tb) => {
        const turnOffset = Math.max(0, tb.time - minTime);
        const turnLeft = Math.max(0, Math.min(99.5, (turnOffset / total) * 100));
        barsHtml += `
          <div class="timeline-turn-marker" style="left: ${turnLeft}%" title="Turn ${tb.turn}">
            <span class="marker-badge">T${tb.turn}</span>
          </div>
        `;
      });
    }

    spans.forEach((span) => {
      const startOffset = Math.max(0, span.start - minTime);
      const leftPercent = Math.max(0, Math.min(98.5, (startOffset / total) * 100));
      const spanDuration = Math.max(1, span.end - span.start);
      const widthPercent = Math.max(1.0, Math.min(100 - leftPercent, (spanDuration / total) * 100));

      let innerBarHtml = "";
      const isSelected = this.selectedRecordId === span.cell.id;
      const inFlightClass = span.inFlight ? "pulse-bar" : "";

      if (span.kind === "message" && span.ttftMs && span.decodingMs && span.durationMs) {
        const ttftFraction = Math.max(0.05, Math.min(0.95, span.ttftMs / span.durationMs));
        const ttftWidthPct = (ttftFraction * 100).toFixed(1);
        const decodeWidthPct = (100 - ttftFraction * 100).toFixed(1);

        innerBarHtml = `
          <div class="bar-segment seg-ttft" style="width:${ttftWidthPct}%" title="TTFT: ${span.ttftMs}ms"></div>
          <div class="bar-segment seg-decode ${inFlightClass}" style="width:${decodeWidthPct}%" title="Decode: ${span.decodingMs}ms"></div>
        `;
      } else {
        const kindKey = (span.kind || "message").toLowerCase();
        innerBarHtml = `<div class="bar-segment seg-${kindKey} ${inFlightClass}"></div>`;
      }

      barsHtml += `
        <div class="timeline-row-track track-lane-${span.lane || 0}" data-id="${span.cell.id}">
          <div class="timeline-bar-capsule ${isSelected ? "active" : ""} ${span.inFlight ? "in-flight-bar" : ""}" style="left: ${leftPercent}%; width: ${widthPercent}%;">
            ${innerBarHtml}
          </div>
        </div>
      `;
    });

    this.tracksEl.innerHTML = barsHtml;

    // Attach timeline click & hover listeners
    this.tracksEl.querySelectorAll(".timeline-row-track").forEach((track) => {
      const id = track.getAttribute("data-id");
      track.addEventListener("click", () => this.selectRecord(id));
      track.addEventListener("mouseenter", (e) => this.showTooltip(e, id));
      track.addEventListener("mouseleave", () => this.hideTooltip());
    });
  }

  _renderLedgerTable() {
    if (!this.tableBody) return;

    let filteredRecords = this.records;
    if (this.activeFilterRange) {
      const { start, end } = this.activeFilterRange;
      filteredRecords = this.records.filter((r) => {
        const rStart = r.startedAt || 0;
        const rEnd = rStart + (r.durationMs || 100);
        return rStart <= end && rEnd >= start;
      });
    }

    if (filteredRecords.length === 0) {
      this.tableBody.innerHTML = `<tr><td colspan="5" class="table-empty">所选区间内无事件记录</td></tr>`;
      return;
    }

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
      const kindKey = (r.kind || "other").toLowerCase();
      const pillClass = `pill-${kindKey}`;

      let timingText = `${r.durationMs || 0}ms`;
      if (r.ttftMs) {
        timingText = `${r.durationMs}ms (TTFT: ${r.ttftMs}ms)`;
      }

      let tokenText = "-";
      if (r.tokens) {
        const totalTok = (r.tokens.inputTokens || 0) + (r.tokens.outputTokens || 0);
        tokenText = totalTok > 0 ? `${formatTokens(totalTok)} tok` : "-";
      }

      const indexDisplay = r.inFlight
        ? `<span class="live-spinner" title="Streaming..."></span>`
        : r.index;

      html += `
        <tr class="trajectory-table-row ${isSelected ? "row-selected" : ""} ${r.inFlight ? "row-in-flight" : ""}" data-id="${r.id}">
          <td class="cell-index">${indexDisplay}</td>
          <td><span class="table-kind-pill ${pillClass}">${r.kind.toUpperCase()}</span></td>
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

    // Attach row click listeners
    this.tableBody.querySelectorAll(".trajectory-table-row").forEach((row) => {
      const id = row.getAttribute("data-id");
      row.addEventListener("click", () => this.selectRecord(id));
    });
  }

  selectRecord(id) {
    this.selectedRecordId = id;
    const rec = this.records.find((r) => r.id === id);
    if (!rec) return;

    // Highlight row and bar in-place without rebuilding DOM
    if (this.tableBody) {
      this.tableBody.querySelectorAll(".trajectory-table-row").forEach((row) => {
        row.classList.toggle("row-selected", row.getAttribute("data-id") === id);
      });
    }
    if (this.tracksEl) {
      this.tracksEl.querySelectorAll(".timeline-row-track").forEach((track) => {
        const bar = track.querySelector(".timeline-bar-capsule");
        if (bar) bar.classList.toggle("active", track.getAttribute("data-id") === id);
      });
    }

    this.openInspector(rec);
    if (this.onSelectRecord) this.onSelectRecord(rec);
  }

  openInspector(rec) {
    if (!this.inspector || !this.inspectorBody || !this.inspectorTitle) return;

    this.inspector.classList.remove("hidden");
    this.inspectorTitle.textContent = `📋 记录 #${rec.index} 详情 [${(rec.kind || "").toUpperCase()}]`;

    const rawEvent = rec.rawNode || rec;
    const rawJson = JSON.stringify(rawEvent, null, 2);

    let tokenBreakdownHtml = "";
    if (rec.tokens) {
      tokenBreakdownHtml = `
        <div class="inspector-section">
          <div class="section-title">📊 Token 用量明细 (Token Breakdown)</div>
          <div class="inspector-kv-grid">
            <div class="kv-item"><span class="k">输入 (Input):</span><span class="v">${rec.tokens.inputTokens || 0}</span></div>
            <div class="kv-item"><span class="k">输出 (Output):</span><span class="v">${rec.tokens.outputTokens || 0}</span></div>
            <div class="kv-item"><span class="k">思考 (Reasoning):</span><span class="v">${rec.tokens.reasoningTokens || 0}</span></div>
            <div class="kv-item"><span class="k">缓存读取 (Cache Read):</span><span class="v">${rec.tokens.cacheReadTokens || 0}</span></div>
            <div class="kv-item"><span class="k">缓存写入 (Cache Write):</span><span class="v">${rec.tokens.cacheWriteTokens || 0}</span></div>
          </div>
        </div>
      `;
    }

    let timingSectionHtml = `
      <div class="inspector-section">
        <div class="section-title">⏱️ 耗时与延迟分析 (Timing Metrics)</div>
        <div class="inspector-kv-grid">
          <div class="kv-item"><span class="k">总耗时:</span><span class="v">${rec.durationMs || 0} ms</span></div>
          ${rec.ttftMs ? `<div class="kv-item"><span class="k">首 Token 延迟 (TTFT):</span><span class="v">${rec.ttftMs} ms</span></div>` : ""}
          ${rec.decodingMs ? `<div class="kv-item"><span class="k">解码用时 (Decoding):</span><span class="v">${rec.decodingMs} ms</span></div>` : ""}
          <div class="kv-item"><span class="k">开始时间:</span><span class="v">${new Date(rec.startedAt || Date.now()).toLocaleTimeString()}</span></div>
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
    if (this.inspector) this.inspector.classList.add("hidden");
    this.selectedRecordId = null;
    if (this.tableBody) {
      this.tableBody.querySelectorAll(".trajectory-table-row").forEach((row) => {
        row.classList.remove("row-selected");
      });
    }
    if (this.tracksEl) {
      this.tracksEl.querySelectorAll(".timeline-row-track .timeline-bar-capsule").forEach((bar) => {
        bar.classList.remove("active");
      });
    }
  }

  showTooltip(e, id) {
    const rec = this.records.find((r) => r.id === id);
    if (!rec || !this.tooltip) return;

    clearTimeout(this.hoverTooltipTimer);
    this.hoverTooltipTimer = setTimeout(() => {
      const rect = e.target.getBoundingClientRect();
      this.tooltip.innerHTML = `
        <div class="tooltip-header">#${rec.index} [${(rec.kind || "").toUpperCase()}] ${escapeHtml(rec.title)}</div>
        <div class="tooltip-body">
          <div>开始: ${new Date(rec.startedAt || Date.now()).toLocaleTimeString()}</div>
          <div>耗时: ${rec.durationMs || 0}ms ${rec.ttftMs ? `(TTFT: ${rec.ttftMs}ms)` : ""}</div>
          ${rec.tokens ? `<div>Token: ${formatTokens((rec.tokens.inputTokens || 0) + (rec.tokens.outputTokens || 0))}</div>` : ""}
        </div>
      `;
      this.tooltip.style.left = `${Math.min(window.innerWidth - 240, rect.left + 10)}px`;
      this.tooltip.style.top = `${rect.bottom + 8}px`;
      this.tooltip.classList.remove("hidden");
    }, 150);
  }

  hideTooltip() {
    clearTimeout(this.hoverTooltipTimer);
    if (this.tooltip) this.tooltip.classList.add("hidden");
  }
}
