/**
 * Multi-Tab Settings Modal (`@deepseek-ai/dsh-client-ui-settings` / `ui-settings-models` / `ui-settings-plugins`)
 * 3-Tab Settings: General Preferences (Queue vs Steer), Models (with Discover Models probe), and Plugin Inventory.
 */

import { ApiClient } from "../connection/api.js";
import { escapeHtml } from "./markdown.js";

export class SettingsView {
  constructor({ modal, onSave }) {
    this.modal = modal;
    this.onSave = onSave;
    this.currentTab = "models"; // 'general' | 'models' | 'plugins'
    this.settingsData = null;

    this._createUI();
    this._bindEvents();
  }

  _createUI() {
    if (!this.modal) return;
    this.modal.innerHTML = `
      <div class="modal-dialog settings-dialog-wide">
        <div class="modal-header">
          <div class="modal-title">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>
            </svg>
            <span>系统设置 (Settings)</span>
          </div>
          <button id="btn-close-settings" class="btn-icon-plain">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- Tab Bar Navigation -->
        <div class="settings-tabs-bar">
          <button type="button" class="tab-item active" data-tab="models">🤖 模型提供方 (Models)</button>
          <button type="button" class="tab-item" data-tab="general">⚙️ 通用与按键 (General)</button>
          <button type="button" class="tab-item" data-tab="plugins">🧩 插件清单 (Plugins)</button>
        </div>

        <div class="modal-body settings-tab-content">
          <!-- 1. Models Tab -->
          <div class="tab-pane active" id="pane-models">
            <div class="settings-group">
              <label class="setting-label">API Base URL (端点地址)</label>
              <div class="input-with-btn">
                <input type="text" id="setting-base-url" class="setting-input" placeholder="https://api.deepseek.com/v1" />
                <button type="button" class="btn-secondary btn-discover" id="btn-discover-models">🔍 获取可用模型</button>
              </div>
              <span class="setting-hint">支持 OpenAI 兼容 API 格式</span>
            </div>

            <div class="settings-group">
              <label class="setting-label">API Key (认证凭据)</label>
              <input type="password" id="setting-api-key" class="setting-input" placeholder="sk-..." />
              <span class="setting-hint">保存在 ~/.dsh/.credentials.yaml 或环境变量中</span>
            </div>

            <div class="settings-group">
              <label class="setting-label">模型名称 (Model ID)</label>
              <input type="text" id="setting-model" class="setting-input" placeholder="deepseek-v4-flash" />
            </div>

            <div class="settings-group">
              <label class="setting-label">上下文窗口容量 (Context Window)</label>
              <input type="text" id="setting-context-window" class="setting-input" placeholder="128K (128000)" value="128K" />
            </div>
          </div>

          <!-- 2. General Tab -->
          <div class="tab-pane hidden" id="pane-general">
            <div class="settings-group">
              <label class="setting-label">繁忙时 Enter 行为 (Busy Enter Preference)</label>
              <select id="setting-busy-enter" class="preset-select">
                <option value="queue" selected>Queue (排队发送为下一轮次)</option>
                <option value="steer">Steer (直接插入当前正在运行的轮次)</option>
              </select>
              <span class="setting-hint">当智能体正在运行时按 Enter 的分发策略</span>
            </div>

            <div class="settings-group">
              <label class="setting-label">运行平台环境 (Environment Snapshot)</label>
              <div class="env-info-box">
                <div>平台: Windows 7 SP1+ (Win32)</div>
                <div>架构: Cordis Plugin Architecture</div>
                <div>运行时: Python 3.8.10 (Portable Embedded)</div>
              </div>
            </div>
          </div>

          <!-- 3. Plugins Tab -->
          <div class="tab-pane hidden" id="pane-plugins">
            <div class="plugin-inventory-list" id="plugin-inventory-list">
              <div class="plugin-card-item">
                <div class="plugin-card-title">💻 Shell Executor (pwsh/bash)</div>
                <div class="plugin-card-desc">Windows 7 原生 PowerShell / Cmd 持久交互终端</div>
                <span class="tool-status-pill pill-success">ACTIVE</span>
              </div>
              <div class="plugin-card-item">
                <div class="plugin-card-title">⚡ Agent Loop & Step Driver</div>
                <div class="plugin-card-desc">异步消息驱动与工具分发循环核心</div>
                <span class="tool-status-pill pill-success">ACTIVE</span>
              </div>
              <div class="plugin-card-item">
                <div class="plugin-card-title">📦 Context Compaction Engine</div>
                <div class="plugin-card-desc">上下文智能压缩、裁剪与早期轮次摘要</div>
                <span class="tool-status-pill pill-success">ACTIVE</span>
              </div>
              <div class="plugin-card-item">
                <div class="plugin-card-title">🔍 Filesystem Search (glob/grep)</div>
                <div class="plugin-card-desc">代码库快速检索与正规表达式搜索</div>
                <span class="tool-status-pill pill-success">ACTIVE</span>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button id="btn-save-settings" class="btn-primary">保存配置</button>
        </div>
      </div>
    `;

    this.baseUrlInput = document.getElementById("setting-base-url");
    this.apiKeyInput = document.getElementById("setting-api-key");
    this.modelInput = document.getElementById("setting-model");
    this.contextWindowInput = document.getElementById("setting-context-window");
    this.busyEnterSelect = document.getElementById("setting-busy-enter");
    this.btnDiscover = document.getElementById("btn-discover-models");
    this.btnClose = document.getElementById("btn-close-settings");
    this.btnSave = document.getElementById("btn-save-settings");
  }

  _bindEvents() {
    this.btnClose.addEventListener("click", () => this.hide());

    // Tab switching
    this.modal.querySelectorAll(".tab-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.getAttribute("data-tab");
        this.switchTab(tab);
      });
    });

    // Discover models button
    if (this.btnDiscover) {
      this.btnDiscover.addEventListener("click", async () => {
        const baseUrl = this.baseUrlInput.value.trim();
        const apiKey = this.apiKeyInput.value.trim();
        this.btnDiscover.textContent = "🔍 正在扫描...";
        try {
          const res = await ApiClient.discoverModels(baseUrl, apiKey);
          if (res.models && res.models.length > 0) {
            const chosen = prompt(`扫描到可用模型列表:\n${res.models.join("\n")}\n\n请输入要使用的模型名称:`, res.models[0]);
            if (chosen) {
              this.modelInput.value = chosen;
            }
          } else {
            alert("未扫描到模型列表: " + (res.error || "请检查端点和 Key"));
          }
        } catch (e) {
          alert("扫描失败: " + e.message);
        } finally {
          this.btnDiscover.textContent = "🔍 获取可用模型";
        }
      });
    }

    // Save button
    this.btnSave.addEventListener("click", () => {
      const config = {
        baseUrl: this.baseUrlInput.value.trim(),
        apiKey: this.apiKeyInput.value.trim(),
        model: this.modelInput.value.trim(),
        general: {
          busyEnter: this.busyEnterSelect.value,
        },
      };
      if (this.onSave) this.onSave(config);
      this.hide();
    });
  }

  switchTab(tabId) {
    this.currentTab = tabId;
    this.modal.querySelectorAll(".tab-item").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-tab") === tabId);
    });
    this.modal.querySelectorAll(".tab-pane").forEach((pane) => {
      pane.classList.toggle("hidden", pane.id !== `pane-${tabId}`);
      pane.classList.toggle("active", pane.id === `pane-${tabId}`);
    });
  }

  async show(initial = {}) {
    try {
      const desc = await ApiClient.describeSettings();
      if (desc.llm) {
        if (desc.llm.baseUrl) this.baseUrlInput.value = desc.llm.baseUrl;
        if (desc.llm.model) this.modelInput.value = desc.llm.model;
      }
      if (desc.general && desc.general.busyEnter) {
        this.busyEnterSelect.value = desc.general.busyEnter;
      }
    } catch (e) {}

    if (initial.baseUrl) this.baseUrlInput.value = initial.baseUrl;
    if (initial.apiKey) this.apiKeyInput.value = initial.apiKey;
    if (initial.model) this.modelInput.value = initial.model;

    this.modal.classList.remove("hidden");
  }

  hide() {
    this.modal.classList.add("hidden");
  }
}
