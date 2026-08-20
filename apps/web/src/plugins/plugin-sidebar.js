/**
 * Sidebar & Workspace Plugin (`@deepseek-ai/dsh-client-ui-sidebar` & `@deepseek-ai/dsh-client-ui-workspace`).
 * 1:1 Workspace Tree, Sessions Navigation, Blank Session Reuse, and Archive Actions.
 */

import { escapeHtml } from "../ui/markdown.js";
import { ApiClient } from "../connection/api.js";

export function SidebarRoot(props) {
  const { renderSlot, collapsed, ctx } = props;
  const sessionsMgr = ctx ? ctx.get("sessions") : null;
  const currentSessionId = sessionsMgr ? sessionsMgr.currentSessionId : "default-session";
  const sessionList = sessionsMgr ? sessionsMgr.sessionList : [];

  const rootEl = document.createElement("div");
  rootEl.className = `sidebar-container ${collapsed ? "collapsed" : ""}`;

  // 1. Sidebar Header & Workspace
  const headerEl = document.createElement("div");
  headerEl.className = "sidebar-header";
  headerEl.innerHTML = `
    <div class="workspace-badge" id="btn-workspace-select" title="当前工作区">
      <span class="workspace-icon">📁</span>
      <span class="workspace-name" id="workspace-label">加载中...</span>
    </div>
    <button class="btn-icon" id="btn-new-session" title="新建会话 (New Session)">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="12" y1="5" x2="12" y2="19"></line>
        <line x1="5" y1="12" x2="19" y2="12"></line>
      </svg>
    </button>
  `;

  // 2. Search & Sessions Area
  const searchEl = document.createElement("div");
  searchEl.className = "sidebar-search-wrap";
  searchEl.innerHTML = `
    <input type="text" class="sidebar-search-input" id="input-search-sessions" placeholder="搜索会话 (Search)...">
  `;

  const listEl = document.createElement("div");
  listEl.className = "sidebar-sessions-list";
  listEl.id = "session-list-outlet";

  function renderList(query = "") {
    listEl.innerHTML = '<div class="session-group-title">历史会话</div>';
    const filtered = sessionList.filter((s) => s.id.toLowerCase().includes(query.toLowerCase()));

    if (filtered.length === 0) {
      const empty = document.createElement("div");
      empty.className = "session-item empty";
      empty.innerHTML = `<span class="text-muted">无匹配会话</span>`;
      listEl.appendChild(empty);
      return;
    }

    filtered.forEach((s) => {
      const isActive = s.id === currentSessionId;
      const item = document.createElement("div");
      item.className = `session-item ${isActive ? "active" : ""}`;
      item.innerHTML = `
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
        </svg>
        <span class="session-title-text">${escapeHtml(s.title || s.id)}</span>
      `;
      item.addEventListener("click", () => {
        if (sessionsMgr) sessionsMgr.selectSession(s.id);
      });
      listEl.appendChild(item);
    });
  }

  renderList();

  // 3. Sidebar Footer (Settings / Theme)
  const footerEl = document.createElement("div");
  footerEl.className = "sidebar-footer";
  footerEl.innerHTML = `
    <button class="btn-sidebar-footer" id="btn-toggle-theme" title="切换深色/浅色主题">
      <span>🌓</span>
      <span class="btn-label">主题</span>
    </button>
    <button class="btn-sidebar-footer" id="btn-open-settings" title="打开系统设置">
      <span>⚙️</span>
      <span class="btn-label">设置</span>
    </button>
  `;

  // Bind Events
  headerEl.querySelector("#btn-new-session").addEventListener("click", () => {
    if (sessionsMgr) sessionsMgr.createNewSession();
  });

  searchEl.querySelector("#input-search-sessions").addEventListener("input", (e) => {
    renderList(e.target.value.trim());
  });

  footerEl.querySelector("#btn-toggle-theme").addEventListener("click", () => {
    const isDark = document.body.classList.contains("theme-dark");
    document.body.classList.toggle("theme-dark", !isDark);
    document.body.classList.toggle("theme-light", isDark);
  });

  footerEl.querySelector("#btn-open-settings").addEventListener("click", () => {
    const modal = document.getElementById("modal-settings");
    if (modal) modal.classList.remove("hidden");
  });

  rootEl.appendChild(headerEl);
  rootEl.appendChild(searchEl);
  rootEl.appendChild(listEl);
  rootEl.appendChild(footerEl);

  // Fetch workspace path
  ApiClient.getStatus().then((st) => {
    const wsLabel = headerEl.querySelector("#workspace-label");
    if (wsLabel && st.cwd) {
      wsLabel.textContent = st.cwd.split(/[\\/]/).pop() || st.cwd;
      wsLabel.title = st.cwd;
    }
  }).catch(() => {});

  return rootEl;
}

export class PluginSidebar {
  static inject = ["slots", "sessions"];

  apply(ctx) {
    const slots = ctx.get("slots");
    slots.register({
      name: "sidebar",
      inject: () => ({ ctx }),
    }, SidebarRoot);

    const sessionsMgr = ctx.get("sessions");
    if (sessionsMgr) {
      sessionsMgr.subscribe(() => {
        const outlet = document.getElementById("slot-outlet-sidebar");
        if (outlet) {
          slots.renderSlot("sidebar", { ctx }, outlet);
        }
      });
    }
  }
}
