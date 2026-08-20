/**
 * Settings Modal Plugin (`@deepseek-ai/dsh-client-ui-settings`)
 * Registers the multi-tab settings modal into the 'shell.overlay' list slot.
 */

import { ApiClient } from "../connection/api.js";
import { escapeHtml } from "../ui/markdown.js";

export class PluginSettings {
  static id = "ui-settings";
  static name = "@deepseek-ai/dsh-client-ui-settings";

  apply(ctx) {
    ctx.slots.register(
      {
        name: "shell.overlay",
        order: 10,
        inject: (injectCtx) => ({
          onSaveSettings: async (cfg) => {
            await ApiClient.saveSettings(cfg);
          },
        }),
      },
      SettingsOverlayComponent
    );
  }
}

class SettingsOverlayComponent {
  constructor(props) {
    this.props = props;
    this.activeTab = "models";
    this.settings = {
      baseUrl: "https://api.deepseek.com",
      apiKey: "",
      model: "deepseek-v4-flash",
    };
  }

  render(container) {
    const { onSaveSettings } = this.props;

    container.innerHTML = `
      <div class="modal-backdrop hidden" id="settings-modal-dialog">
        <div class="settings-dialog-card">
          <div class="settings-header">
            <div class="settings-title-group">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"/>
                <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>
              </svg>
              <h2>系统设置 (Settings)</h2>
            </div>
            <button type="button" class="btn-icon-plain" id="btn-settings-dialog-close">✕</button>
          </div>

          <div class="settings-tabs-nav">
            <button type="button" class="tab-settings-nav ${this.activeTab === "models" ? "active" : ""}" data-tab="models">🤖 模型与服务商 (Models)</button>
            <button type="button" class="tab-settings-nav ${this.activeTab === "plugins" ? "active" : ""}" data-tab="plugins">🔌 插件清单 (Plugins)</button>
            <button type="button" class="tab-settings-nav ${this.activeTab === "general" ? "active" : ""}" data-tab="general">⚙ 常规偏好 (General)</button>
          </div>

          <div class="settings-content-body">
            <!-- Models Tab -->
            <div class="settings-tab-pane ${this.activeTab === "models" ? "" : "hidden"}" id="tab-pane-models">
              <div class="form-group">
                <label>API 基础地址 (Base URL)</label>
                <input type="text" id="setting-input-base-url" value="${escapeHtml(this.settings.baseUrl)}" />
              </div>
              <div class="form-group">
                <label>API Key</label>
                <input type="password" id="setting-input-api-key" placeholder="sk-..." value="${escapeHtml(this.settings.apiKey)}" />
              </div>
              <div class="form-group">
                <label>默认模型 (Model Name)</label>
                <input type="text" id="setting-input-model" value="${escapeHtml(this.settings.model)}" />
              </div>
            </div>

            <!-- Plugins Tab -->
            <div class="settings-tab-pane ${this.activeTab === "plugins" ? "" : "hidden"}" id="tab-pane-plugins">
              <div class="plugin-inventory-list">
                <div class="plugin-item-card">
                  <div class="plugin-name">@deepseek-ai/dsh-client-ui-layout</div>
                  <span class="plugin-status-badge badge-active">ACTIVE</span>
                </div>
                <div class="plugin-item-card">
                  <div class="plugin-name">@deepseek-ai/dsh-client-ui-conversation</div>
                  <span class="plugin-status-badge badge-active">ACTIVE</span>
                </div>
                <div class="plugin-item-card">
                  <div class="plugin-name">@deepseek-ai/dsh-client-ui-trajectory</div>
                  <span class="plugin-status-badge badge-active">ACTIVE</span>
                </div>
                <div class="plugin-item-card">
                  <div class="plugin-name">@deepseek-ai/dsh-client-ui-tool</div>
                  <span class="plugin-status-badge badge-active">ACTIVE</span>
                </div>
                <div class="plugin-item-card">
                  <div class="plugin-name">@deepseek-ai/dsh-client-ui-sidebar</div>
                  <span class="plugin-status-badge badge-active">ACTIVE</span>
                </div>
              </div>
            </div>

            <!-- General Tab -->
            <div class="settings-tab-pane ${this.activeTab === "general" ? "" : "hidden"}" id="tab-pane-general">
              <div class="form-group">
                <label>发送按键行为</label>
                <select id="setting-enter-mode">
                  <option value="enter" selected>Enter 发送，Shift+Enter 换行</option>
                  <option value="ctrl-enter">Ctrl+Enter 发送，Enter 换行</option>
                </select>
              </div>
            </div>
          </div>

          <div class="settings-footer">
            <button type="button" class="btn-plain" id="btn-settings-cancel">取消</button>
            <button type="button" class="btn-primary" id="btn-settings-save">保存设置</button>
          </div>
        </div>
      </div>
    `;

    const dialog = container.querySelector("#settings-modal-dialog");
    const btnClose = container.querySelector("#btn-settings-dialog-close");
    const btnCancel = container.querySelector("#btn-settings-cancel");
    const btnSave = container.querySelector("#btn-settings-save");

    // Close logic
    const closeDialog = () => dialog.classList.add("hidden");
    btnClose.addEventListener("click", closeDialog);
    btnCancel.addEventListener("click", closeDialog);

    // Tab switching
    container.querySelectorAll(".tab-settings-nav").forEach((tabBtn) => {
      tabBtn.addEventListener("click", () => {
        const tab = tabBtn.getAttribute("data-tab");
        if (tab) {
          this.activeTab = tab;
          this.render(container);
          dialog.classList.remove("hidden");
        }
      });
    });

    // Save logic
    btnSave.addEventListener("click", async () => {
      const baseUrlInput = container.querySelector("#setting-input-base-url");
      const apiKeyInput = container.querySelector("#setting-input-api-key");
      const modelInput = container.querySelector("#setting-input-model");

      const newCfg = {
        baseUrl: baseUrlInput ? baseUrlInput.value.trim() : this.settings.baseUrl,
        apiKey: apiKeyInput ? apiKeyInput.value.trim() : this.settings.apiKey,
        model: modelInput ? modelInput.value.trim() : this.settings.model,
      };

      this.settings = newCfg;
      if (onSaveSettings) await onSaveSettings(newCfg);
      closeDialog();
    });

    // Expose global show helper for external triggers
    window._showSettingsModal = () => {
      dialog.classList.remove("hidden");
    };

    return container;
  }
}
