/**
 * Subagent Directory & Navigation (`@deepseek-ai/dsh-client-ui-subagent`)
 * Displays child subagents hierarchy, status, token consumption, and allows opening child transcript.
 */

export class SubagentNavView {
  constructor({ containerId = "subagent-container", onOpenSubagent }) {
    this.container = document.getElementById(containerId);
    this.onOpenSubagent = onOpenSubagent;
    this.subagents = [];

    this._createUI();
    this._bindEvents();
  }

  _createUI() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="subagent-btn hidden" id="btn-subagent-tree" title="查看子智能体 (Subagents)">
        <span class="subagent-icon">🤖</span>
        <span class="subagent-text" id="subagent-count-text">子智能体</span>
      </div>

      <div class="subagent-popover hidden" id="subagent-popover">
        <div class="subagent-header">
          <span>🤖 子智能体谱系目录 (Subagents)</span>
          <button type="button" class="btn-icon-plain" id="btn-close-subagent">✕</button>
        </div>
        <div class="subagent-list" id="subagent-list-body">
          <div class="subagent-empty">暂无派生的子智能体</div>
        </div>
      </div>
    `;

    this.btnTree = document.getElementById("btn-subagent-tree");
    this.popover = document.getElementById("subagent-popover");
    this.countText = document.getElementById("subagent-count-text");
    this.listBody = document.getElementById("subagent-list-body");
    this.btnClose = document.getElementById("btn-close-subagent");
  }

  _bindEvents() {
    if (!this.btnTree || !this.popover) return;
    this.btnTree.addEventListener("click", (e) => {
      e.stopPropagation();
      this.popover.classList.toggle("hidden");
    });
    if (this.btnClose) {
      this.btnClose.addEventListener("click", () => this.popover.classList.add("hidden"));
    }
    document.addEventListener("click", (e) => {
      if (!this.popover.contains(e.target) && e.target !== this.btnTree) {
        this.popover.classList.add("hidden");
      }
    });
  }

  setSubagents(list) {
    this.subagents = list || [];
    this.render();
  }

  render() {
    if (!this.btnTree) return;
    if (this.subagents.length === 0) {
      this.btnTree.classList.add("hidden");
      this.popover.classList.add("hidden");
      return;
    }

    this.btnTree.classList.remove("hidden");
    this.countText.textContent = `${this.subagents.length} 个子智能体`;

    this.listBody.innerHTML = this.subagents.map((sa) => `
      <div class="subagent-item" onclick="window._onOpenSubagent('${sa.id}')">
        <div class="subagent-item-left">
          <span class="subagent-icon-small">🤖</span>
          <div>
            <div class="subagent-name">${sa.name || sa.id}</div>
            <div class="subagent-desc">${sa.role || 'Subagent Worker'}</div>
          </div>
        </div>
        <div class="subagent-item-right">
          <span class="subagent-status-pill pill-${sa.status || 'idle'}">${(sa.status || 'IDLE').toUpperCase()}</span>
        </div>
      </div>
    `).join("");

    window._onOpenSubagent = (id) => {
      if (this.onOpenSubagent) this.onOpenSubagent(id);
      this.popover.classList.add("hidden");
    };
  }
}
