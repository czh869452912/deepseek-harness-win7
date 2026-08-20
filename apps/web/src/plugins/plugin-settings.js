/**
 * Settings Plugin (`@deepseek-ai/dsh-client-ui-settings*`).
 * 1:1 Implementation of Multi-tab Settings Modal, Secret Redaction, and Provider Discovery.
 */

import { ApiClient } from "../connection/api.js";
import { escapeHtml } from "../ui/markdown.js";

export function SettingsModalView(props) {
  const { onClose, onSave } = props;

  const modalEl = document.createElement("div");
  modalEl.className = "modal-overlay";
  modalEl.id = "modal-settings-container";

  modalEl.innerHTML = `
    <div class="modal-card settings-modal">
      <div class="modal-header">
        <span class="modal-title">⚙️ 系统设置 (Settings)</span>
        <button class="btn-icon-plain" id="btn-close-settings">✕</button>
      </div>
      <div class="settings-body">
        <div class="settings-nav">
          <button class="settings-tab-btn active" data-tab="llm">模型与 API (LLM)</button>
          <button class="settings-tab-btn" data-tab="general">通用偏好 (General)</button>
          <button class="settings-tab-btn" data-tab="plugins">插件清单 (Plugins)</button>
        </div>
        <div class="settings-content">
          <!-- LLM Tab -->
          <div class="settings-pane active" id="pane-llm">
            <div class="form-group">
              <label>API 基础端点 (Base URL)</label>
              <input type="text" class="form-input" id="input-base-url" placeholder="https://api.deepseek.com/v1">
            </div>
            <div class="form-group">
              <label>API 密钥 (API Key - 写入脱敏保护)</label>
              <input type="password" class="form-input" id="input-api-key" placeholder="••••••••••••••••••••••••">
              <span class="form-help">密钥在服务端单向加密存储，不会下发至前端。</span>
            </div>
            <div class="form-group">
              <label>默认推理模型 (Model ID)</label>
              <input type="text" class="form-input" id="input-model-id" placeholder="deepseek-chat">
            </div>
          </div>

          <!-- General Tab -->
          <div class="settings-pane" id="pane-general">
            <div class="form-group">
              <label>界面语言 (Language)</label>
              <select class="form-input" id="select-locale">
                <option value="zh-CN">简体中文 (zh-CN)</option>
                <option value="en-US">English (en-US)</option>
              </select>
            </div>
            <div class="form-group">
              <label>主题模式 (Theme)</label>
              <select class="form-input" id="select-theme">
                <option value="dark">深色主题 (Dark Mode)</option>
                <option value="light">浅色主题 (Light Mode)</option>
              </select>
            </div>
          </div>

          <!-- Plugins Tab -->
          <div class="settings-pane" id="pane-plugins">
            <div class="plugins-inventory-list" id="plugins-inventory-outlet">
              <div class="text-muted">加载已挂载 Cordis 插件...</div>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn-plain" id="btn-cancel-settings">取消</button>
        <button class="btn-primary" id="btn-save-settings">保存配置 (Save)</button>
      </div>
    </div>
  `;

  // Tab switching
  const tabBtns = modalEl.querySelectorAll(".settings-tab-btn");
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tabId = btn.dataset.tab;
      modalEl.querySelectorAll(".settings-pane").forEach((p) => p.classList.remove("active"));
      const targetPane = modalEl.querySelector(`#pane-${tabId}`);
      if (targetPane) targetPane.classList.add("active");
    });
  });

  // Load current settings
  ApiClient.getSettings().then((desc) => {
    if (desc && desc.llm) {
      modalEl.querySelector("#input-base-url").value = desc.llm.baseUrl || "";
      modalEl.querySelector("#input-model-id").value = desc.llm.model || "";
      if (desc.llm.hasKey) {
        modalEl.querySelector("#input-api-key").placeholder = "已配置 (●●●●●●●●)";
      }
    }
    if (desc && desc.plugins) {
      const pOutlet = modalEl.querySelector("#plugins-inventory-outlet");
      let pHtml = "";
      desc.plugins.forEach((p) => {
        pHtml += `
          <div class="plugin-inventory-row">
            <span class="plugin-name">📦 ${escapeHtml(p.name || p.id)}</span>
            <span class="badge-active">ACTIVE</span>
          </div>
        `;
      });
      pOutlet.innerHTML = pHtml;
    }
  }).catch(() => {});

  modalEl.querySelector("#btn-close-settings").addEventListener("click", () => {
    modalEl.remove();
  });
  modalEl.querySelector("#btn-cancel-settings").addEventListener("click", () => {
    modalEl.remove();
  });

  modalEl.querySelector("#btn-save-settings").addEventListener("click", async () => {
    const baseUrl = modalEl.querySelector("#input-base-url").value.trim();
    const apiKey = modalEl.querySelector("#input-api-key").value.trim();
    const model = modalEl.querySelector("#input-model-id").value.trim();

    try {
      await ApiClient.saveSettings({
        baseUrl: baseUrl || undefined,
        apiKey: apiKey || undefined,
        model: model || undefined,
      });
      modalEl.remove();
    } catch (e) {
      console.error("[Settings] Save error:", e);
    }
  });

  return modalEl;
}

export class PluginSettings {
  static inject = ["slots"];

  apply(ctx) {
    // Global bridge to open settings
    window.openSettingsModal = () => {
      const existing = document.getElementById("modal-settings-container");
      if (existing) existing.remove();
      const modal = SettingsModalView({});
      document.body.appendChild(modal);
    };
  }
}
