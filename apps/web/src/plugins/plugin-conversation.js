/**
 * Conversation & Message Flow Plugin (`@deepseek-ai/dsh-client-ui-conversation`)
 * Renders conversation message tree, streaming in-flight response, thinking tail,
 * deliverables, and delegates tool calls to 'tool.call.view'.
 */

import { formatMarkdown, escapeHtml } from "../ui/markdown.js";
import { renderProducedFiles } from "../ui/deliverables.js";
import { ApiClient } from "../connection/api.js";

export class PluginConversation {
  static id = "ui-conversation";
  static name = "@deepseek-ai/dsh-client-ui-conversation";

  apply(ctx) {
    ctx.slots.register(
      {
        name: "conversation",
        children: {
          "tool.call.view": { kind: "keyed", scope: "session" },
        },
        inject: (injectCtx, { sessionId }) => ({
          onForkSession: async () => {
            const newSid = "fork-" + Date.now().toString(36);
            await ApiClient.forkSession(sessionId);
            const mgr = injectCtx.get("sessions");
            if (mgr) mgr.switchSession(newSid);
          },
          onSendPrompt: async (text) => {
            await ApiClient.prompt(sessionId, text);
          },
        }),
      },
      ConversationComponent
    );
  }
}

class ConversationComponent {
  constructor(props) {
    this.props = props;
    this.container = null;
    this.lastRenderedSessionId = null;
  }

  render(container) {
    this.container = container;
    const { useSession, renderSlot, onForkSession, onSendPrompt } = this.props;
    const sessionSnapshot = useSession ? useSession() : null;

    const events = (sessionSnapshot && sessionSnapshot.events) || [];
    const partial = (sessionSnapshot && sessionSnapshot.partial) || { blocks: [] };
    const isRunning = Boolean(sessionSnapshot && sessionSnapshot.running);

    if (events.length === 0 && (!partial.blocks || partial.blocks.length === 0)) {
      container.innerHTML = `
        <div class="hero-screen">
          <div class="hero-glow-bg"></div>
          <div class="hero-content">
            <div class="hero-brand">
              <svg class="hero-fish" viewBox="0 0 34 25" width="46" height="34" fill="none">
                <path d="M17 1C10 1 3 6 1 12.5C3 19 10 24 17 24C24 24 31 19 33 12.5C31 6 24 1 17 1Z" fill="#3B82F6" fill-opacity="0.3"/>
                <path d="M17 3C11 3 5 7.5 3 12.5C5 17.5 11 22 17 22C23 22 29 17.5 31 12.5C29 7.5 23 3 17 3Z" stroke="#3B82F6" stroke-width="2"/>
                <circle cx="10" cy="12.5" r="3" fill="#60A5FA"/>
                <path d="M19 8C22 10.5 22 14.5 19 17" stroke="#60A5FA" stroke-width="2" stroke-linecap="round"/>
              </svg>
              <h1 class="hero-title">DeepSeek Harness</h1>
              <span class="hero-badge">Portable Win7</span>
            </div>
            <p class="hero-subtitle">全功能 Windows 7 原生智能体环境，内置流式代码编辑、终端、规划与轨迹分析。</p>

            <div class="hero-cards-grid">
              <div class="hero-card" data-cmd="/plan 帮我检查代码并设计重构方案">
                <div class="hero-card-icon">📋</div>
                <div class="hero-card-text">
                  <strong>/plan 规划模式</strong>
                  <span>进入只读探索，输出决策完备的 Markdown 设计方案</span>
                </div>
              </div>
              <div class="hero-card" data-cmd="/goal 运行完整测试套件并修复所有异常">
                <div class="hero-card-icon">🎯</div>
                <div class="hero-card-text">
                  <strong>/goal 自主长任务</strong>
                  <span>开启多轮自治循环，直至完成目标</span>
                </div>
              </div>
              <div class="hero-card" data-cmd="阅读并分析当前项目的核心架构">
                <div class="hero-card-icon">🔍</div>
                <div class="hero-card-text">
                  <strong>代码库调研</strong>
                  <span>使用 glob、grep 与 str_replace_editor 检视代码</span>
                </div>
              </div>
              <div class="hero-card" data-cmd="/compact">
                <div class="hero-card-icon">⚡</div>
                <div class="hero-card-text">
                  <strong>/compact 上下文压缩</strong>
                  <span>智能总结早期会话，释放上下文窗口</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      `;

      container.querySelectorAll(".hero-card").forEach((c) => {
        c.addEventListener("click", () => {
          const cmd = c.getAttribute("data-cmd");
          const input = document.getElementById("composer-prompt-input");
          if (input && cmd) {
            input.value = cmd;
            input.focus();
          }
        });
      });

      return container;
    }

    // Build chat flow
    let flowHtml = '<div class="chat-flow">';

    // 1. Render Historical / Finalized Events
    events.forEach((ev) => {
      const type = ev.type;
      const data = ev.data || {};

      if (type === "user/message") {
        flowHtml += `
          <div class="message-row user">
            <div class="user-bubble">${escapeHtml(data.content || "")}</div>
          </div>
        `;
      } else if (type === "assistant/message") {
        const msg = data.message || {};
        flowHtml += '<div class="message-row assistant"><div class="assistant-turn">';

        // Reasoning
        if (msg.reasoning_content) {
          flowHtml += `
            <details class="thought-accordion">
              <summary class="thought-summary">
                <span class="live-dot" style="background:var(--accent-cyan)"></span>
                <span>思考过程 (Thought Process)</span>
              </summary>
              <div class="thought-body">${escapeHtml(msg.reasoning_content)}</div>
            </details>
          `;
        }

        // Markdown
        if (msg.content) {
          flowHtml += `<div class="assistant-markdown">${formatMarkdown(msg.content)}</div>`;
        }

        // Tool calls placeholders
        const producedPaths = [];
        if (msg.tool_calls && Array.isArray(msg.tool_calls)) {
          msg.tool_calls.forEach((tc, i) => {
            const fn = tc.function || {};
            if (fn.name === "str_replace_editor") {
              try {
                const args = typeof fn.arguments === "string" ? JSON.parse(fn.arguments) : fn.arguments;
                if (args && args.path) producedPaths.push(args.path);
              } catch (e) {}
            }
            flowHtml += `<div class="tool-call-outlet-placeholder" data-tool-index="${i}" data-tool-name="${escapeHtml(fn.name || "")}" data-tool-args="${escapeHtml(fn.arguments || "{}")}"></div>`;
          });
        }

        // Deliverables
        if (producedPaths.length > 0) {
          flowHtml += renderProducedFiles(producedPaths);
        }

        // Fork session action
        flowHtml += `
          <div class="message-actions-row assistant-actions">
            <button type="button" class="btn-message-action btn-fork-action" title="从此节点分支新会话">
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3v12M18 9a3 3 0 100-6 3 3 0 000 6zM6 21a3 3 0 100-6 3 3 0 000 6zM18 6a9 9 0 01-9 9"/></svg>
            </button>
          </div>
        `;

        flowHtml += "</div></div>";
      } else if (type === "tool/result") {
        flowHtml += `
          <div class="tool-view-card">
            <div class="tool-view-header">
              <span class="tool-title">✓ 结果: ${escapeHtml(data.name || "tool")}</span>
              <span class="tool-status-pill pill-success">SUCCESS</span>
            </div>
            <div class="tool-view-body">${escapeHtml(String(data.result || ""))}</div>
          </div>
        `;
      }
    });

    // 2. Render In-flight Live Streaming Partial Assistant Block
    if (partial && partial.blocks && partial.blocks.length > 0) {
      let reasoningText = "";
      let markdownText = "";
      const toolBlocks = [];

      partial.blocks.forEach((b) => {
        if (b.kind === "reasoning") reasoningText += b.text || "";
        else if (b.kind === "text") markdownText += b.text || "";
        else if (b.kind === "tool-call") toolBlocks.push(b);
      });

      flowHtml += '<div class="message-row assistant streaming-in-flight"><div class="assistant-turn">';

      if (reasoningText) {
        const lines = reasoningText.trim().split("\n");
        const latestLine = lines[lines.length - 1] || "思考中...";
        flowHtml += `
          <details class="thought-accordion in-flight-thought" open>
            <summary class="thought-summary">
              <span class="live-dot pulse-cyan"></span>
              <span class="thought-tail-preview">思考中: ${escapeHtml(latestLine.slice(0, 70))}</span>
            </summary>
            <div class="thought-body">${escapeHtml(reasoningText)}</div>
          </details>
        `;
      }

      if (markdownText) {
        flowHtml += `<div class="assistant-markdown">${formatMarkdown(markdownText)}</div>`;
      }

      toolBlocks.forEach((tc, i) => {
        flowHtml += `<div class="tool-call-outlet-placeholder" data-tool-index="${i}" data-tool-name="${escapeHtml(tc.name || "")}" data-tool-args="${escapeHtml(tc.argsRaw || "{}")}"></div>`;
      });

      flowHtml += "</div></div>";
    }

    flowHtml += "</div>";
    container.innerHTML = flowHtml;

    // Render keyed tool call outlets
    container.querySelectorAll(".tool-call-outlet-placeholder").forEach((holder) => {
      const toolName = holder.getAttribute("data-tool-name");
      const toolArgs = holder.getAttribute("data-tool-args");
      renderSlot(
        "tool.call.view",
        {
          name: toolName,
          arguments: toolArgs,
          status: isRunning ? "RUNNING" : "SUCCESS",
          onPlanAction: onSendPrompt,
        },
        holder,
        { entryKey: toolName }
      );
    });

    // Bind Fork Session actions
    container.querySelectorAll(".btn-fork-action").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (onForkSession) onForkSession();
      });
    });

    // Auto-scroll to bottom
    container.scrollTop = container.scrollHeight;

    return container;
  }
}
