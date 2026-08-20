/**
 * Model Selection Menu (`@deepseek-ai/dsh-client-ui-model-selection`)
 */

import { escapeHtml } from "./markdown.js";

export const AVAILABLE_MODELS = [
  { id: "deepseek-v4-flash", name: "DeepSeek-V4 Flash", desc: "极速响应，代码与规划兼顾", default: true },
  { id: "deepseek-chat", name: "DeepSeek-V3", desc: "通用对话与全栈推理", default: false },
  { id: "deepseek-reasoner", name: "DeepSeek-R1", desc: "深度思考与长链推理", default: false },
];

export class ModelSelectView {
  constructor({ trigger, onSelectModel }) {
    this.trigger = trigger;
    this.onSelectModel = onSelectModel;
    this.currentModel = "deepseek-v4-flash";
    this.isOpen = false;

    this._createMenu();
    this._bindEvents();
  }

  _createMenu() {
    this.menu = document.createElement("div");
    this.menu.className = "model-dropdown-menu hidden";
    this.menu.innerHTML = `
      <div class="model-menu-title">选择模型 (Select Model)</div>
      <div class="model-options-list">
        ${AVAILABLE_MODELS.map((m) => `
          <button type="button" class="model-option-item ${m.id === this.currentModel ? "selected" : ""}" data-model="${m.id}">
            <div class="model-option-main">
              <span class="model-option-name">${escapeHtml(m.name)}</span>
              <span class="model-option-desc">${escapeHtml(m.desc)}</span>
            </div>
            ${m.id === this.currentModel ? '<span class="model-check">✓</span>' : ""}
          </button>
        `).join("")}
      </div>
    `;
    document.body.appendChild(this.menu);
  }

  _bindEvents() {
    this.trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      this.toggle();
    });

    this.menu.querySelectorAll(".model-option-item").forEach((item) => {
      item.addEventListener("click", () => {
        const modelId = item.getAttribute("data-model");
        this.setModel(modelId);
        this.close();
        if (this.onSelectModel) this.onSelectModel(modelId);
      });
    });

    document.addEventListener("click", (e) => {
      if (!this.menu.contains(e.target) && e.target !== this.trigger) {
        this.close();
      }
    });
  }

  setModel(modelId) {
    this.currentModel = modelId;
    this.trigger.querySelector("#model-name-text").textContent = modelId;
    this.menu.querySelectorAll(".model-option-item").forEach((item) => {
      const isThis = item.getAttribute("data-model") === modelId;
      item.className = `model-option-item ${isThis ? "selected" : ""}`;
      const check = item.querySelector(".model-check");
      if (isThis && !check) {
        const checkSpan = document.createElement("span");
        checkSpan.className = "model-check";
        checkSpan.textContent = "✓";
        item.appendChild(checkSpan);
      } else if (!isThis && check) {
        check.remove();
      }
    });
  }

  toggle() {
    if (this.isOpen) this.close();
    else this.open();
  }

  open() {
    const rect = this.trigger.getBoundingClientRect();
    this.menu.style.top = `${rect.bottom + 6}px`;
    this.menu.style.right = `${window.innerWidth - rect.right}px`;
    this.menu.classList.remove("hidden");
    this.isOpen = true;
  }

  close() {
    this.menu.classList.add("hidden");
    this.isOpen = false;
  }
}
