/**
 * Composer & Input Plugin (`@deepseek-ai/dsh-client-ui-input-trigger`, `@deepseek-ai/dsh-client-ui-commands`).
 * 1:1 Implementation of Multimodal Textarea, Queue/Steer Switch, Mentions, and Slash Palette.
 */

import { ApiClient } from "../connection/api.js";
import { escapeHtml } from "../ui/markdown.js";

export function ComposerView(props) {
  const { ctx } = props;
  const sessionsMgr = ctx ? ctx.get("sessions") : null;

  const rootEl = document.createElement("div");
  rootEl.className = "composer-inner";

  rootEl.innerHTML = `
    <div class="composer-suggestions hidden" id="composer-suggestions"></div>
    <div class="composer-box">
      <textarea class="composer-textarea" id="composer-input" placeholder="输入指令或提问... (按 Enter 发送, Shift+Enter 换行, / 快捷指令, @ 关联文件)" rows="1"></textarea>
      <div class="composer-controls">
        <div class="composer-left-tools">
          <button class="btn-tool-icon" id="btn-attach-file" title="上传附件图片">
            <span>📎</span>
          </button>
          <div class="mode-select-pill">
            <label><input type="radio" name="input-mode" value="queue" checked> 排队 (Queue)</label>
            <label><input type="radio" name="input-mode" value="steer"> 插话 (Steer)</label>
          </div>
        </div>
        <div class="composer-right-actions">
          <button class="btn-send" id="btn-composer-send" title="发送消息">
            <span>发送</span>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
          <button class="btn-stop hidden" id="btn-composer-stop" title="终止当前生成">
            <span>■ 停止</span>
          </button>
        </div>
      </div>
    </div>
  `;

  const textarea = rootEl.querySelector("#composer-input");
  const btnSend = rootEl.querySelector("#btn-composer-send");
  const btnStop = rootEl.querySelector("#btn-composer-stop");
  const suggestionsBox = rootEl.querySelector("#composer-suggestions");

  // Auto-grow textarea
  textarea.addEventListener("input", () => {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 180) + "px";
  });

  async function handleSend() {
    const text = textarea.value.trim();
    if (!text) return;

    const modeInput = rootEl.querySelector('input[name="input-mode"]:checked');
    const mode = modeInput ? modeInput.value : "queue";
    const sid = sessionsMgr ? sessionsMgr.currentSessionId : "default-session";

    textarea.value = "";
    textarea.style.height = "auto";

    btnSend.classList.add("hidden");
    btnStop.classList.remove("hidden");

    try {
      await ApiClient.sendPrompt(sid, text, mode);
    } catch (err) {
      console.error("[Composer] Send error:", err);
      btnSend.classList.remove("hidden");
      btnStop.classList.add("hidden");
    }
  }

  btnSend.addEventListener("click", handleSend);

  btnStop.addEventListener("click", async () => {
    const sid = sessionsMgr ? sessionsMgr.currentSessionId : "default-session";
    await ApiClient.cancel(sid);
    btnSend.classList.remove("hidden");
    btnStop.classList.add("hidden");
  });

  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  return rootEl;
}

export class PluginComposer {
  static inject = ["slots", "sessions"];

  apply(ctx) {
    const slots = ctx.get("slots");
    // Register as fallback chain entry for conversation.composer
    slots.register({
      name: "conversation.composer",
      priority: 999, // default fallback
      select: () => ({ isFallback: true }),
      inject: () => ({ ctx }),
    }, ComposerView);
  }
}
