/**
 * Background Jobs View (`@deepseek-ai/dsh-client-ui-jobs`)
 * Renders active background tasks in the session header with live running timers.
 */

import { formatDuration } from "./stats.js";

export class JobsView {
  constructor({ containerId = "jobs-container" }) {
    this.container = document.getElementById(containerId);
    this.jobs = [];
    this.timer = null;

    this._createUI();
    this._bindEvents();
    this._startClock();
  }

  _createUI() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="jobs-pill-btn hidden" id="btn-jobs-pill" title="查看后台正在运行的任务">
        <span class="jobs-icon">⚙️</span>
        <span class="jobs-count" id="jobs-count-text">0 运行中</span>
      </div>

      <div class="jobs-popover hidden" id="jobs-popover">
        <div class="jobs-popover-header">
          <span>⚙️ 后台任务清单 (Background Jobs)</span>
          <button type="button" class="btn-icon-plain" id="btn-close-jobs">✕</button>
        </div>
        <div class="jobs-list" id="jobs-list-body">
          <div class="job-empty">暂无后台任务</div>
        </div>
      </div>
    `;

    this.btnPill = document.getElementById("btn-jobs-pill");
    this.popover = document.getElementById("jobs-popover");
    this.countText = document.getElementById("jobs-count-text");
    this.listBody = document.getElementById("jobs-list-body");
    this.btnClose = document.getElementById("btn-close-jobs");
  }

  _bindEvents() {
    if (!this.btnPill || !this.popover) return;
    this.btnPill.addEventListener("click", (e) => {
      e.stopPropagation();
      this.popover.classList.toggle("hidden");
    });
    if (this.btnClose) {
      this.btnClose.addEventListener("click", () => this.popover.classList.add("hidden"));
    }
    document.addEventListener("click", (e) => {
      if (!this.popover.contains(e.target) && e.target !== this.btnPill) {
        this.popover.classList.add("hidden");
      }
    });
  }

  _startClock() {
    this.timer = setInterval(() => {
      if (this.jobs.length > 0 && !this.popover.classList.contains("hidden")) {
        this.renderList();
      }
    }, 1000);
  }

  setJobs(jobs) {
    this.jobs = jobs || [];
    this.render();
  }

  render() {
    if (!this.btnPill) return;
    const running = this.jobs.filter((j) => j.status === "running");
    if (this.jobs.length === 0) {
      this.btnPill.classList.add("hidden");
      this.popover.classList.add("hidden");
      return;
    }

    this.btnPill.classList.remove("hidden");
    this.countText.textContent = `${running.length} 运行中`;
    this.renderList();
  }

  renderList() {
    if (!this.listBody) return;
    if (this.jobs.length === 0) {
      this.listBody.innerHTML = `<div class="job-empty">暂无后台任务</div>`;
      return;
    }

    const now = Date.now();
    this.listBody.innerHTML = this.jobs.map((j) => {
      const elapsedMs = j.startedAt ? Math.max(0, now - j.startedAt) : 0;
      return `
        <div class="job-item">
          <div class="job-item-header">
            <span class="job-kind-badge">${j.kind || 'task'}</span>
            <span class="job-label">${j.label || j.id}</span>
            <span class="job-status-pill pill-${j.status}">${j.status.toUpperCase()}</span>
          </div>
          <div class="job-item-footer">
            <span class="job-elapsed">已运行: ${formatDuration(elapsedMs)}</span>
          </div>
        </div>
      `;
    }).join("");
  }
}
