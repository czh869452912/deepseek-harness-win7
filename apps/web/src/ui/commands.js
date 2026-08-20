/**
 * Slash Command Suggestions Controller (`@deepseek-ai/dsh-client-ui-commands`)
 */

export class CommandsView {
  constructor({ textarea, popup, onSelectCommand }) {
    this.textarea = textarea;
    this.popup = popup;
    this.onSelectCommand = onSelectCommand;

    this._bindEvents();
  }

  _bindEvents() {
    this.textarea.addEventListener("input", () => {
      const val = this.textarea.value;
      if (val === "/" || (val.startsWith("/") && !val.includes(" "))) {
        this.popup.classList.remove("hidden");
      } else {
        this.popup.classList.add("hidden");
      }
    });

    this.popup.querySelectorAll(".slash-item").forEach((item) => {
      item.addEventListener("click", () => {
        const cmd = item.getAttribute("data-cmd");
        if (this.onSelectCommand) this.onSelectCommand(cmd);
        this.popup.classList.add("hidden");
      });
    });

    document.addEventListener("click", (e) => {
      if (!this.popup.contains(e.target) && e.target !== this.textarea) {
        this.popup.classList.add("hidden");
      }
    });
  }

  hide() {
    this.popup.classList.add("hidden");
  }
}
