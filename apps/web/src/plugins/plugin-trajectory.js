/**
 * Trajectory Performance & Event Ledger Plugin (`@deepseek-ai/dsh-client-ui-trajectory`)
 * Chrome-Network-style 3-lane overview timeline with real-time in-flight stream updates,
 * TTFT vs Decode bars, turn-grouped ledger table, and interactive inspector drawer.
 */

import { formatMarkdown, escapeHtml } from "../ui/markdown.js";
import { formatDuration, formatTokens } from "../ui/stats.js";

export class PluginTrajectory {
  static id = "ui-trajectory";
  static name = "@deepseek-ai/dsh-client-ui-trajectory";

  apply(ctx) {
    ctx.slots.register(
      {
        name: "trajectory",
      },
      TrajectoryComponent
    );
  }
}

class TrajectoryComponent {
  constructor(props) {
    this.props = props;
    this.container = null;
    this.selectedRecordId = null;
    this.activeFilterRange = null; // { startMs, endMs }
    this.timelineMode = "duration"; // 'sequence' | 'duration' | 'time' | 'actual'
    this.zoomScale = 1.0;
    this.searchQuery = "";

    this.records = [];
    this.timeDomain = { minTime: 0, maxTime: 0, totalMs: 1000 };
  }

  render(container) {
    this.container = container;
    const { useSession } = this.props;
    const sessionSnapshot = useSession ? useSession() : null;

    const events = (sessionSnapshot && sessionSnapshot.events) || [];
    const partial = (sessionSnapshot && sessionSnapshot.partial) || { blocks: [] };
    const isRunning = Boolean(sessionSnapshot && sessionSnapshot.running);

    this._processRecordsWithPartial(events, partial, isRunning);

    container.innerHTML = `
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
              </div>
              <button type="button" class="btn-pill-small" id="btn-traj-reset-filter" title="重置缩放">重置</button>
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
                  <th style="width: 55px">#</th>
                  <th style="width: 110px">事件类型</th>
                  <th style="width: 130px">耗时 / TTFT</th>
                  <th style="width: 110px">Tokens</th>
                  <th>事件内容与调用详情</th>
                </tr>
              </thead>
              <tbody id="traj-table-body"></tbody>
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

    this._renderTimeline(container);
    this._renderLedgerTable(container);
    this._bindEvents(container);

    return container;
  }

  _processRecordsWithPartial(events, partial, isRunning) {
    this.records = [];
    let currentTurnNum = 1;
    let baseTime = Date.now() - 30000;
    let runningTime = baseTime;

    let minTime = Infinity;
    let maxTime = -Infinity;

    // 1. Process Historical Finalized Events
    events.forEach((ev, idx) => {
      const type = ev.type;
      const data = ev.data || {};
      const rec = {
        id: `rec-${idx}`,
        index: idx + 1,
        type: type,
        turn: data.turn || currentTurnNum,
        step: data.step || 1,
        rawEvent: ev,
        startedAt: ev.timestamp || runningTime,
        durationMs: 200,
        ttftMs: null,
        decodingMs: null,
        tokens: null,
        kind: "OTHER",
        lane: 0,
        title: type,
        summary: "",
        inFlight: false,
      };

      if (type === "turn/start") {
        currentTurnNum = data.turn || currentTurnNum;
        return;
      }

      if (type === "user/message") {
        rec.kind = "USER";
        rec.lane = 0;
        rec.title = "用户消息";
        rec.summary = data.content || "";
        rec.durationMs = 50;
        runningTime += 300;
      } else if (type === "assistant/message") {
        const msg = data.message || {};
        const timing = data.timing || {};
        rec.kind = "ASSISTANT";
        rec.lane = 1;
        rec.title = "模型回复";
        rec.summary = (msg.reasoning_content ? `[思考] ${msg.reasoning_content.slice(0, 80)}... ` : "") + (msg.content || "");
        rec.startedAt = timing.stepStartTime || runningTime;
        rec.durationMs = timing.durationMs || 1000;
        rec.ttftMs = timing.ttftMs || 250;
        rec.decodingMs = timing.decodingMs || Math.max(0, rec.durationMs - (rec.ttftMs || 250));
        rec.tokens = data.usage || { inputTokens: 400, outputTokens: (msg.content || "").length / 4 };
        runningTime += rec.durationMs + 200;
      } else if (type === "tool/result") {
        rec.kind = "TOOL";
        rec.lane = 2;
        rec.title = `工具: ${data.name || "tool"}`;
        rec.summary = String(data.result || "").slice(0, 120);
        rec.durationMs = 300;
        runningTime += 350;
      } else if (type === "compaction/summary" || type === "compaction") {
        rec.kind = "COMPACTED";
        rec.lane = 1;
        rec.title = "上下文压缩";
        rec.summary = data.summary || "压缩早期会话";
        rec.durationMs = 600;
        runningTime += 650;
      } else {
        rec.kind = "SYSTEM";
        rec.lane = 0;
        rec.summary = JSON.stringify(data).slice(0, 80);
      }

      minTime = Math.min(minTime, rec.startedAt);
      maxTime = Math.max(maxTime, rec.startedAt + rec.durationMs);
      this.records.push(rec);
    });

    // 2. Append Real-Time In-Flight Streaming Partial Record (Live Streaming Fold!)
    if (partial && partial.blocks && partial.blocks.length > 0) {
      let reasoningText = "";
      let textContent = "";
      const tools = [];

      partial.blocks.forEach((b) => {
        if (b.kind === "reasoning") reasoningText += b.text || "";
        else if (b.kind === "text") textContent += b.text || "";
        else if (b.kind === "tool-call") tools.push(b);
      });

      const liveRec = {
        id: "rec-live-partial",
        index: this.records.length + 1,
        type: "assistant/chunk",
        turn: partial.turn || currentTurnNum,
        step: partial.step || 1,
        rawEvent: { type: "assistant/partial", partial },
        startedAt: runningTime,
        durationMs: 800,
        ttftMs: 200,
        decodingMs: 600,
        tokens: {
          inputTokens: 450,
          outputTokens: (reasoningText.length + textContent.length) / 4,
          reasoningTokens: reasoningText.length / 4,
        },
        kind: "ASSISTANT",
        lane: 1,
        title: "模型生成中 (Streaming...)",
        summary: (reasoningText ? `[思考] ${reasoningText.slice(0, 70)}... ` : "") + textContent,
        inFlight: true,
      };

      minTime = Math.min(minTime, liveRec.startedAt);
      maxTime = Math.max(maxTime, liveRec.startedAt + liveRec.durationMs);
      this.records.push(liveRec);

      // Append running tools in Lane 2 if any
      tools.forEach((t, i) => {
        const toolRec = {
          id: `rec-live-tool-${i}`,
          index: this.records.length + 1,
          type: "tool/running",
          turn: partial.turn || currentTurnNum,
          step: partial.step || 1,
          rawEvent: { type: "tool/running", tool: t },
          startedAt: runningTime + 200,
          durationMs: 400,
          ttftMs: null,
          decodingMs: null,
          tokens: null,
          kind: "TOOL",
          lane: 2,
          title: `调用中: ${t.name || "tool"}`,
          summary: t.argsRaw || "...",
          inFlight: true,
        };
        this.records.push(toolRec);
      });
    }

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

  _renderTimeline(container) {
    const ticksEl = container.querySelector("#traj-timeline-ticks");
    const tracksEl = container.querySelector("#traj-timeline-tracks");
    if (!ticksEl || !tracksEl) return;

    const { minTime, totalMs } = this.timeDomain;

    // Render Ticks
    const tickCount = 5;
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
    ticksEl.innerHTML = ticksHtml;

    // Render 3-Lane Tracks & Bars
    let barsHtml = "";
    this.records.forEach((rec) => {
      const startOffset = Math.max(0, rec.startedAt - minTime);
      const leftPercent = Math.max(0, Math.min(98, (startOffset / totalMs) * 100));
      const widthPercent = Math.max(1.2, Math.min(100 - leftPercent, (rec.durationMs / totalMs) * 100));

      let innerBarHtml = "";
      if (rec.kind === "ASSISTANT" && rec.ttftMs && rec.decodingMs) {
        const ttftFraction = rec.ttftMs / rec.durationMs;
        const ttftWidthPct = (ttftFraction * 100).toFixed(1);
        const decodeWidthPct = (100 - ttftFraction * 100).toFixed(1);
        innerBarHtml = `
          <div class="bar-segment seg-ttft" style="width:${ttftWidthPct}%" title="TTFT: ${rec.ttftMs}ms"></div>
          <div class="bar-segment seg-decode ${rec.inFlight ? 'pulse-bar' : ''}" style="width:${decodeWidthPct}%" title="Decode: ${rec.decodingMs}ms"></div>
        `;
      } else {
        innerBarHtml = `<div class="bar-segment seg-${rec.kind.toLowerCase()} ${rec.inFlight ? 'pulse-bar' : ''}"></div>`;
      }

      barsHtml += `
        <div class="timeline-row-track track-lane-${rec.lane || 0}" data-id="${rec.id}">
          <div class="timeline-bar-capsule ${this.selectedRecordId === rec.id ? 'active' : ''} ${rec.inFlight ? 'in-flight-bar' : ''}" style="left: ${leftPercent}%; width: ${widthPercent}%;">
            ${innerBarHtml}
          </div>
        </div>
      `;
    });

    tracksEl.innerHTML = barsHtml;
  }

  _renderLedgerTable(container) {
    const tableBody = container.querySelector("#traj-table-body");
    if (!tableBody) return;

    let filteredRecords = this.records;
    if (this.activeFilterRange) {
      const { startMs, endMs } = this.activeFilterRange;
      filteredRecords = this.records.filter((r) => {
        const rEnd = r.startedAt + r.durationMs;
        return r.startedAt <= endMs && rEnd >= startMs;
      });
    }

    if (filteredRecords.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="5" class="table-empty">暂无事件记录</td></tr>`;
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
      const pillClass = `pill-${r.kind.toLowerCase()}`;
      const timingText = r.ttftMs ? `${r.durationMs}ms (TTFT: ${r.ttftMs}ms)` : `${r.durationMs}ms`;
      const tokenText = r.tokens ? `${formatTokens((r.tokens.inputTokens || 0) + (r.tokens.outputTokens || 0))} tok` : "-";

      html += `
        <tr class="trajectory-table-row ${isSelected ? 'row-selected' : ''} ${r.inFlight ? 'row-in-flight' : ''}" data-id="${r.id}">
          <td class="cell-index">${r.inFlight ? '<span class="live-spinner"></span>' : r.index}</td>
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

    tableBody.innerHTML = html;
  }

  _bindEvents(container) {
    // Mode switcher
    container.querySelectorAll(".btn-mode-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-mode");
        if (mode) {
          this.timelineMode = mode;
          this.render(container);
        }
      });
    });

    // Reset filter
    const btnReset = container.querySelector("#btn-traj-reset-filter");
    if (btnReset) {
      btnReset.addEventListener("click", () => {
        this.activeFilterRange = null;
        this.render(container);
      });
    }

    // Row selection
    container.querySelectorAll(".trajectory-table-row").forEach((row) => {
      row.addEventListener("click", () => {
        const id = row.getAttribute("data-id");
        this._selectRecord(id, container);
      });
    });

    // Close Inspector
    const btnCloseInsp = container.querySelector("#btn-traj-close-inspector");
    if (btnCloseInsp) {
      btnCloseInsp.addEventListener("click", () => {
        const insp = container.querySelector("#traj-inspector");
        if (insp) insp.classList.add("hidden");
        this.selectedRecordId = null;
      });
    }
  }

  _selectRecord(id, container) {
    this.selectedRecordId = id;
    const rec = this.records.find((r) => r.id === id);
    if (!rec) return;

    const insp = container.querySelector("#traj-inspector");
    const inspTitle = container.querySelector("#traj-inspector-title");
    const inspBody = container.querySelector("#traj-inspector-body");
    if (!insp || !inspBody) return;

    insp.classList.remove("hidden");
    inspTitle.textContent = `📋 记录 #${rec.index} 详情 [${rec.kind}]`;

    const rawJson = JSON.stringify(rec.rawEvent, null, 2);
    let tokenBreakdownHtml = "";
    if (rec.tokens) {
      tokenBreakdownHtml = `
        <div class="inspector-section">
          <div class="section-title">📊 Token 用量明细 (Token Breakdown)</div>
          <div class="inspector-kv-grid">
            <div class="kv-item"><span class="k">输入 (Input):</span><span class="v">${rec.tokens.inputTokens || 0}</span></div>
            <div class="kv-item"><span class="k">输出 (Output):</span><span class="v">${rec.tokens.outputTokens || 0}</span></div>
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
        </div>
      </div>
    `;

    inspBody.innerHTML = `
      ${timingSectionHtml}
      ${tokenBreakdownHtml}
      <div class="inspector-section">
        <div class="section-title">📦 原始事件载荷 (Raw Event Payload)</div>
        <pre class="inspector-json-code"><code>${escapeHtml(rawJson)}</code></pre>
      </div>
    `;
  }
}
