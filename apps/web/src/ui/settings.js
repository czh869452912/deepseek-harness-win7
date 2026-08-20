/**
 * Settings & Model Configuration Modal (`@deepseek-ai/dsh-client-ui-settings`)
 */

export class SettingsView {
  constructor({ modal, baseUrlInput, apiKeyInput, modelInput, onSave }) {
    this.modal = modal;
    this.baseUrlInput = baseUrlInput;
    this.apiKeyInput = apiKeyInput;
    this.modelInput = modelInput;
    this.onSave = onSave;

    this.btnClose = document.getElementById("btn-close-settings");
    this.btnSave = document.getElementById("btn-save-settings");

    this._bindEvents();
  }

  _bindEvents() {
    this.btnClose.addEventListener("click", () => this.hide());
    this.btnSave.addEventListener("click", () => {
      const config = {
        baseUrl: this.baseUrlInput.value.trim(),
        apiKey: this.apiKeyInput.value.trim(),
        model: this.modelInput.value.trim(),
      };
      if (this.onSave) this.onSave(config);
      this.hide();
    });
  }

  show(initial = {}) {
    if (initial.baseUrl) this.baseUrlInput.value = initial.baseUrl;
    if (initial.apiKey) this.apiKeyInput.value = initial.apiKey;
    if (initial.model) this.modelInput.value = initial.model;
    this.modal.classList.remove("hidden");
  }

  hide() {
    this.modal.classList.add("hidden");
  }
}
