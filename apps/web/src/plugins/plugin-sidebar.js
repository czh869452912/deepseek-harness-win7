/**
 * Sidebar Plugin (`@deepseek-ai/dsh-client-ui-sidebar`)
 * Renders workspace chip, session search, session lists, new session actions,
 * and bottom settings / theme triggers into the 'sidebar' slot.
 */

import { escapeHtml } from "../ui/markdown.js";
import { ApiClient } from "../connection/api.js";

export class PluginSidebar {
  static id = "ui-sidebar";
  static name = "@deepseek-ai/dsh-client-ui-sidebar";

  apply(ctx) {
    ctx.slots.register(
      {
        name: "sidebar",
        inject: (injectCtx) => ({
          onNewSession: async () => {
            const sid = "session-" + Date.now().toString(36);
            await ApiClient.createSession(sid);
            const mgr = injectCtx.get("sessions");
            if (mgr) mgr.switchSession(sid);
          },
          onSelectSession: (sid) => {
            const mgr = injectCtx.get("sessions");
            if (mgr) mgr.switchSession(sid);
          },
          onToggleTheme: () => {
            const isLight = document.body.classList.contains("theme-light");
            document.body.className = isLight ? "theme-dark" : "theme-light";
            localStorage.setItem("dsh_theme", isLight ? "dark" : "light");
          },
        }),
      },
      SidebarComponent
    );
  }
}

class SidebarComponent {
  constructor(props) {
    this.props = props;
    this.searchQuery = "";
  }

  render(container) {
    const { sessionId, useSessions, onNewSession, onSelectSession, onToggleTheme } = this.props;
    const sessions = useSessions ? useSessions() : [];
    const cwd = (this.props.useWorkspaces && this.props.useWorkspaces().cwd) || "Win7 Workspace";

    container.innerHTML = `
      <div class="sidebar-top">
        <div class="brand">
          <svg class="fish-logo" viewBox="0 0 34 25" width="28" height="21" fill="none">
            <path d="M17 1C10 1 3 6 1 12.5C3 19 10 24 17 24C24 24 31 19 33 12.5C31 6 24 1 17 1Z" fill="#3B82F6" fill-opacity="0.2"/>
            <path d="M17 3C11 3 5 7.5 3 12.5C5 17.5 11 22 17 22C23 22 29 17.5 31 12.5C29 7.5 23 3 17 3Z" stroke="#60A5FA" stroke-width="2"/>
            <circle cx="10" cy="12.5" r="2.5" fill="#93C5FD"/>
            <path d="M19 8C22 10.5 22 14.5 19 17" stroke="#93C5FD" stroke-width="2" stroke-linecap="round"/>
          </svg>
          <span class="brand-title">DeepSeek Harness</span>
          <span class="preview-tag">Win7</span>
        </div>
        <button id="btn-sidebar-new-session" class="btn-new-chat" title="新建会话 (Ctrl+N)">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5v14M5 12h14"/>
          </svg>
          <span>新会话</span>
        </button>
      </div>

      <!-- Workspace Bar -->
      <div class="workspace-chip-container">
        <div class="workspace-chip" title="当前工作区目录">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
          </svg>
          <span class="workspace-name">${escapeHtml(cwd)}</span>
        </div>
      </div>

      <!-- Agent Preset Selector -->
      <div class="sidebar-preset-box">
        <div class="sidebar-label">运行预设 (Agent Preset)</div>
        <div class="preset-dropdown-wrap">
          <select id="sidebar-preset-select" class="preset-select">
            <option value="standard" selected>标准模式 (Standard)</option>
            <option value="minimal">极简模式 (Minimal)</option>
            <option value="creative">创造模式 (Creative)</option>
          </select>
        </div>
      </div>

      <!-- Search & Sessions List -->
      <div class="sidebar-history">
        <div class="history-search-box">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
          </svg>
          <input type="text" id="sidebar-session-search" placeholder="搜索历史会话..." value="${escapeHtml(this.searchQuery)}" />
        </div>

        <div class="history-list-scroll" id="sidebar-session-list-items"></div>
      </div>

      <!-- Footer Actions -->
      <div class="sidebar-bottom">
        <button id="btn-sidebar-open-settings" class="btn-sidebar-footer" title="设置">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>
          </svg>
          <span>设置</span>
        </button>
        <button id="btn-sidebar-toggle-theme" class="btn-sidebar-footer" title="切换深色/浅色主题">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>
          </svg>
        </button>
      </div>
    `;

    // Render session items
    const listEl = container.querySelector("#sidebar-session-list-items");
    const filtered = sessions.filter((s) =>
      s.id.toLowerCase().includes(this.searchQuery.toLowerCase())
    );

    if (filtered.length === 0) {
      listEl.innerHTML = `<div class="session-item"><span class="session-title-text" style="color:var(--text-muted)">无匹配会话</span></div>`;
    } else {
      listEl.innerHTML = filtered
        .map(
          (s) => `
          <div class="session-item ${s.id === sessionId ? "active" : ""}" data-id="${escapeHtml(s.id)}">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
            </svg>
            <span class="session-title-text">${escapeHtml(s.id)}</span>
          </div>
        `
        )
        .join("");

      listEl.querySelectorAll(".session-item").forEach((item) => {
        item.addEventListener("click", () => {
          const sid = item.getAttribute("data-id");
          if (sid && onSelectSession) onSelectSession(sid);
        });
      });
    }

    // Bind event listeners
    const btnNew = container.querySelector("#btn-sidebar-new-session");
    if (btnNew && onNewSession) btnNew.addEventListener("click", onNewSession);

    const inputSearch = container.querySelector("#sidebar-session-search");
    if (inputSearch) {
      inputSearch.addEventListener("input", (e) => {
        this.searchQuery = e.target.value;
        this.render(container);
      });
    }

    const btnTheme = container.querySelector("#btn-sidebar-toggle-theme");
    if (btnTheme && onToggleTheme) btnTheme.addEventListener("click", onToggleTheme);

    const btnSettings = container.querySelector("#btn-sidebar-open-settings");
    if (btnSettings) {
      btnSettings.addEventListener("click", () => {
        const modal = document.getElementById("settings-modal");
        if (modal) modal.classList.remove("hidden");
      });
    }

    return container;
  }
}
