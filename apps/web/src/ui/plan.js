/**
 * Plan Mode UI Component (`@deepseek-ai/dsh-client-ui-plan`)
 */

export class PlanModeView {
  constructor({ onTogglePlanMode }) {
    this.onTogglePlanMode = onTogglePlanMode;
    this.btnToggle = document.getElementById("btn-plan-toggle");
    this.label = document.getElementById("plan-mode-label");
    this.banner = document.getElementById("plan-active-indicator");

    this.isActive = false;
    this._bindEvents();
  }

  _bindEvents() {
    this.btnToggle.addEventListener("click", () => {
      const target = !this.isActive;
      if (this.onTogglePlanMode) this.onTogglePlanMode(target);
    });
  }

  update(active) {
    this.isActive = Boolean(active);
    if (this.isActive) {
      this.btnToggle.classList.add("active");
      this.label.textContent = "规划模式: 开";
      this.banner.classList.remove("hidden");
    } else {
      this.btnToggle.classList.remove("active");
      this.label.textContent = "规划模式: 关";
      this.banner.classList.add("hidden");
    }
  }
}
