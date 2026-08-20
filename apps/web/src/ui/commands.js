/**
 * Input Triggers & Mention Pipeline (`@deepseek-ai/dsh-client-ui-input-trigger` / `ui-reference`)
 * Supports `/` slash commands and `@` references (@file, @session, @skill) with dynamic keyboard selection.
 */

import { escapeHtml } from "./markdown.js";
import { ApiClient } from "../connection/api.js";

export const SLASH_COMMANDS = [
  { trigger: "/", cmd: "/plan ", label: "/plan", desc: "切换或进入规划模式 (只读探索与方案评审)" },
  { trigger: "/", cmd: "/goal ", label: "/goal", desc: "设定并启动自主长任务目标循环" },
  { trigger: "/", cmd: "/compact", label: "/compact", desc: "压缩并总结早期会话步骤释放窗口" },
  { trigger: "/", cmd: "/clear", label: "/clear", desc: "清空当前会话界面显示" },
  { trigger: "/", cmd: "/permission workspace-write", label: "/permission", desc: "配置会话执行权限 (read-only/workspace/danger-full-access)" },
];

export class CommandsView {
  constructor({ textarea, popup, onSelectCommand }) {
    this.textarea = textarea;
    this.popup = popup;
    this.onSelectCommand = onSelectCommand;

    this.workspaceFiles = [];
    this.activeTrigger = null; // '/' or '@'
    this.selectedIndex = 0;
    this.currentCandidates = [];

    this._bindEvents();
    this._preloadFiles();
  }

  async _preloadFiles() {
    try {
      const res = await ApiClient.getWorkspaceFiles();
      this.workspaceFiles = res.files || [];
    } catch (e) {
      this.workspaceFiles = [];
    }
  }

  _bindEvents() {
    this.textarea.addEventListener("input", () => this.handleInput());
    this.textarea.addEventListener("keydown", (e) => this.handleKeyDown(e));

    document.addEventListener("click", (e) => {
      if (!this.popup.contains(e.target) && e.target !== this.textarea) {
        this.hide();
      }
    });
  }

  async handleInput() {
    const text = this.textarea.value;
    const cursorPos = this.textarea.selectionStart || text.length;
    const textBeforeCursor = text.slice(0, cursorPos);

    const slashMatch = textBeforeCursor.match(/(?:^|\s)\/([a-zA-Z0-9_-]*)$/);
    const atMatch = textBeforeCursor.match(/(?:^|\s)@([a-zA-Z0-9_.\-\/]*)$/);

    if (slashMatch) {
      this.activeTrigger = "/";
      const query = slashMatch[1].toLowerCase();
      this.currentCandidates = SLASH_COMMANDS.filter((c) =>
        c.label.toLowerCase().includes(query) || c.desc.toLowerCase().includes(query)
      );
      this.selectedIndex = 0;
      this.render();
    } else if (atMatch) {
      this.activeTrigger = "@";
      const query = atMatch[1].toLowerCase();
      if (this.workspaceFiles.length === 0) {
        await this._preloadFiles();
      }

      const fileCandidates = this.workspaceFiles
        .filter((f) => f.path.toLowerCase().includes(query) || f.name.toLowerCase().includes(query))
        .slice(0, 10)
        .map((f) => ({
          trigger: "@",
          cmd: `@${f.path} `,
          label: `@${f.path}`,
          desc: `工作区文件 (${f.ext || 'file'})`,
          icon: "📄",
        }));

      this.currentCandidates = fileCandidates;
      this.selectedIndex = 0;
      this.render();
    } else {
      this.hide();
    }
  }

  handleKeyDown(e) {
    if (this.popup.classList.contains("hidden") || this.currentCandidates.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      this.selectedIndex = (this.selectedIndex + 1) % this.currentCandidates.length;
      this.renderHighlight();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      this.selectedIndex = (this.selectedIndex - 1 + this.currentCandidates.length) % this.currentCandidates.length;
      this.renderHighlight();
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      const chosen = this.currentCandidates[this.selectedIndex];
      if (chosen) {
        this.applyCandidate(chosen);
      }
    } else if (e.key === "Escape") {
      this.hide();
    }
  }

  applyCandidate(item) {
    const text = this.textarea.value;
    const cursorPos = this.textarea.selectionStart || text.length;
    const textBeforeCursor = text.slice(0, cursorPos);
    const textAfterCursor = text.slice(cursorPos);

    let prefix = "";
    if (this.activeTrigger === "/") {
      prefix = textBeforeCursor.replace(/(?:^|\s)\/[a-zA-Z0-9_-]*$/, "");
    } else if (this.activeTrigger === "@") {
      prefix = textBeforeCursor.replace(/(?:^|\s)@[a-zA-Z0-9_.\-\/]*$/, "");
    }

    const newText = (prefix ? prefix + " " : "") + item.cmd + textAfterCursor;
    this.textarea.value = newText;
    this.hide();
    this.textarea.focus();
  }

  render() {
    if (this.currentCandidates.length === 0) {
      this.hide();
      return;
    }

    this.popup.classList.remove("hidden");
    this.popup.innerHTML = this.currentCandidates.map((c, i) => `
      <div class="slash-item ${i === this.selectedIndex ? 'active' : ''}" data-idx="${i}">
        <span class="slash-icon">${c.icon || (c.trigger === '/' ? '⚡' : '📌')}</span>
        <span class="slash-cmd">${escapeHtml(c.label)}</span>
        <span class="slash-desc">${escapeHtml(c.desc)}</span>
      </div>
    `).join("");

    this.popup.querySelectorAll(".slash-item").forEach((el) => {
      el.addEventListener("click", () => {
        const idx = parseInt(el.getAttribute("data-idx"), 10);
        const item = this.currentCandidates[idx];
        if (item) this.applyCandidate(item);
      });
    });
  }

  renderHighlight() {
    this.popup.querySelectorAll(".slash-item").forEach((el, i) => {
      el.classList.toggle("active", i === this.selectedIndex);
    });
  }

  hide() {
    this.popup.classList.add("hidden");
    this.activeTrigger = null;
    this.currentCandidates = [];
  }
}
