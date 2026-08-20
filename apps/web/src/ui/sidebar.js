/**
 * Sidebar & Session Management (`@deepseek-ai/dsh-client-ui-sidebar`)
 */

import { escapeHtml } from "./markdown.js";

export class SidebarView {
  constructor({ onSelectSession, onNewSession, onPresetChange, onToggleTheme, onOpenSettings }) {
    this.onSelectSession = onSelectSession;
    this.onNewSession = onNewSession;
    this.onPresetChange = onPresetChange;
    this.onToggleTheme = onToggleTheme;
    this.onOpenSettings = onOpenSettings;

    this.sidebar = document.getElementById("sidebar");
    this.btnToggle = document.getElementById("btn-toggle-sidebar");
    this.btnNewSession = document.getElementById("btn-new-session");
    this.selectPreset = document.getElementById("select-preset");
    this.sessionList = document.getElementById("session-list");
    this.inputSearch = document.getElementById("input-search-sessions");
    this.workspaceLabel = document.getElementById("workspace-label");
    this.btnTheme = document.getElementById("btn-toggle-theme");
    this.btnSettings = document.getElementById("btn-open-settings");

    this.sessions = [];
    this.activeSessionId = "default-session";

    this._bindEvents();
  }

  _bindEvents() {
    this.btnToggle.addEventListener("click", () => {
      this.sidebar.classList.toggle("collapsed");
    });

    this.btnNewSession.addEventListener("click", () => {
      if (this.onNewSession) this.onNewSession();
    });

    this.selectPreset.addEventListener("change", (e) => {
      if (this.onPresetChange) this.onPresetChange(e.target.value);
    });

    this.inputSearch.addEventListener("input", (e) => {
      this.render(e.target.value.trim().toLowerCase());
    });

    this.btnTheme.addEventListener("click", () => {
      if (this.onToggleTheme) this.onToggleTheme();
    });

    this.btnSettings.addEventListener("click", () => {
      if (this.onOpenSettings) this.onOpenSettings();
    });
  }

  setWorkspace(path) {
    if (this.workspaceLabel) {
      this.workspaceLabel.textContent = path || "CWD (Win7)";
    }
  }

  setSessions(sessions, activeId) {
    this.sessions = sessions || [];
    this.activeSessionId = activeId;
    this.render();
  }

  setActive(sessionId) {
    this.activeSessionId = sessionId;
    this.render();
  }

  render(filterQuery = "") {
    this.sessionList.innerHTML = '<div class="session-group-title">历史会话</div>';
    const filtered = this.sessions.filter((s) => s.id.toLowerCase().includes(filterQuery));

    if (filtered.length === 0) {
      const emptyDiv = document.createElement("div");
      emptyDiv.className = "session-item";
      emptyDiv.innerHTML = `<span class="session-title-text" style="color:var(--text-muted)">无匹配会话</span>`;
      this.sessionList.appendChild(emptyDiv);
      return;
    }

    filtered.forEach((s) => {
      const item = document.createElement("div");
      const isActive = s.id === this.activeSessionId;
      item.className = `session-item ${isActive ? "active" : ""}`;
      item.innerHTML = `
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
        </svg>
        <span class="session-title-text">${escapeHtml(s.id)}</span>
      `;
      item.addEventListener("click", () => {
        if (this.onSelectSession) this.onSelectSession(s.id);
      });
      this.sessionList.appendChild(item);
    });
  }
}
