/**
 * Composer Input Plugin (`@deepseek-ai/dsh-client-ui-composer`)
 * Renders prompt textarea, slash command autocomplete, plan active banner,
 * interactive question takeover, and send/stop actions into 'composer' slot.
 */

import { ApiClient } from "../connection/api.js";
import { CommandsView } from "../ui/commands.js";

export class PluginComposer {
  static id = "ui-composer";
  static name = "@deepseek-ai/dsh-client-ui-composer";

  apply(ctx) {
    ctx.slots.register(
      {
        name: "composer",
        inject: (injectCtx, { sessionId }) => ({
          onSend: async (text) => {
            await ApiClient.prompt(sessionId, text);
          },
          onCancel: async () => {
            await ApiClient.cancel(sessionId);
          },
        }),
      },
      ComposerComponent
    );
  }
}

class ComposerComponent {
  constructor(props) {
    this.props = props;
    this.commands = null;
  }

  render(container) {
    const { useSession, onSend, onCancel } = this.props;
    const sessionSnapshot = useSession ? useSession() : null;
    const isRunning = Boolean(sessionSnapshot && sessionSnapshot.running);

    container.innerHTML = `
      <!-- Interactive Question Flow Container (Takeover) -->
      <div id="composer-question-container" class="question-composer-container hidden"></div>

      <!-- Slash Popover -->
      <div class="slash-popup hidden" id="composer-slash-popup"></div>

      <!-- Main Input Card -->
      <div class="composer-card">
        <div class="composer-header">
          <div id="composer-plan-indicator" class="plan-banner-chip hidden">
            <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
            <span>规划模式已激活 (只读探索，不修改文件)</span>
          </div>
        </div>

        <textarea
          id="composer-prompt-input"
          class="composer-input"
          placeholder="输入需求或指令，支持 / 指令与 @ 引用，按 Enter 发送，Shift+Enter 换行..."
          rows="2"
        ></textarea>

        <div class="composer-footer">
          <div class="composer-left-actions">
            <span class="shortcut-tip">提示: 输入 <code>/</code> 唤出指令，<code>@</code> 引用文件</span>
          </div>
          <div class="composer-right-actions">
            <button id="btn-composer-stop" class="btn-action-stop ${isRunning ? "" : "hidden"}" title="停止生成">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2"/>
              </svg>
              <span>停止</span>
            </button>
            <button id="btn-composer-send" class="btn-action-send ${isRunning ? "hidden" : ""}" title="发送 (Enter)">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
          </div>
        </div>
      </div>
    `;

    const textarea = container.querySelector("#composer-prompt-input");
    const btnSend = container.querySelector("#btn-composer-send");
    const btnStop = container.querySelector("#btn-composer-stop");
    const slashPopup = container.querySelector("#composer-slash-popup");

    // Initialize Slash Commands Helper
    this.commands = new CommandsView({
      textarea,
      popup: slashPopup,
      onSelectCommand: (cmd) => {
        textarea.value = cmd;
        textarea.focus();
      },
    });

    const handleSendAction = () => {
      const text = textarea.value.trim();
      if (!text || isRunning) return;
      textarea.value = "";
      this.commands.hide();
      if (onSend) onSend(text);
    };

    btnSend.addEventListener("click", handleSendAction);
    btnStop.addEventListener("click", () => {
      if (onCancel) onCancel();
    });

    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSendAction();
      }
    });

    return container;
  }
}
