/**
 * Tool Views Plugin (`@deepseek-ai/dsh-client-ui-tool`)
 * Registers specialized interactive cards into the keyed 'tool.call.view' slot.
 */

import {
  renderDiffEditorCard,
  renderTerminalCard,
  renderSearchCard,
  renderTodoCard,
  renderPlanReviewCard,
} from "../ui/tools.js";
import { escapeHtml } from "../ui/markdown.js";

export class PluginTools {
  static id = "ui-tool";
  static name = "@deepseek-ai/dsh-client-ui-tool";

  apply(ctx) {
    // 1. str_replace_editor Diff View
    ctx.slots.register(
      {
        name: "tool.call.view",
        key: "str_replace_editor",
      },
      (props) => {
        let args = {};
        try {
          args = typeof props.arguments === "string" ? JSON.parse(props.arguments) : props.arguments || {};
        } catch (e) {
          args = { raw: props.arguments };
        }
        return renderDiffEditorCard(args, props.status || "RUNNING");
      }
    );

    // 2. pwsh Terminal Card
    ctx.slots.register(
      {
        name: "tool.call.view",
        key: "pwsh",
      },
      (props) => {
        let args = {};
        try {
          args = typeof props.arguments === "string" ? JSON.parse(props.arguments) : props.arguments || {};
        } catch (e) {
          args = { command: props.arguments };
        }
        return renderTerminalCard("PWSH", args.command || "", props.output || "", props.status || "RUNNING");
      }
    );

    // 3. bash Terminal Card
    ctx.slots.register(
      {
        name: "tool.call.view",
        key: "bash",
      },
      (props) => {
        let args = {};
        try {
          args = typeof props.arguments === "string" ? JSON.parse(props.arguments) : props.arguments || {};
        } catch (e) {
          args = { command: props.arguments };
        }
        return renderTerminalCard("BASH", args.command || "", props.output || "", props.status || "RUNNING");
      }
    );

    // 4. glob / grep Search Cards
    ctx.slots.register(
      {
        name: "tool.call.view",
        key: "glob",
      },
      (props) => {
        let args = {};
        try {
          args = typeof props.arguments === "string" ? JSON.parse(props.arguments) : props.arguments || {};
        } catch (e) {
          args = { pattern: props.arguments };
        }
        return renderSearchCard("GLOB", args, props.output || "", props.status || "RUNNING");
      }
    );

    ctx.slots.register(
      {
        name: "tool.call.view",
        key: "grep",
      },
      (props) => {
        let args = {};
        try {
          args = typeof props.arguments === "string" ? JSON.parse(props.arguments) : props.arguments || {};
        } catch (e) {
          args = { query: props.arguments };
        }
        return renderSearchCard("GREP", args, props.output || "", props.status || "RUNNING");
      }
    );

    // 5. todo_write Card
    ctx.slots.register(
      {
        name: "tool.call.view",
        key: "todo_write",
      },
      (props) => {
        let args = {};
        try {
          args = typeof props.arguments === "string" ? JSON.parse(props.arguments) : props.arguments || {};
        } catch (e) {
          args = { todos: [] };
        }
        return renderTodoCard(args.todos || [], props.status || "RUNNING");
      }
    );

    // 6. exit_plan_mode Approval Card
    ctx.slots.register(
      {
        name: "tool.call.view",
        key: "exit_plan_mode",
      },
      (props) => {
        let planText = "";
        try {
          const parsed = typeof props.arguments === "string" ? JSON.parse(props.arguments) : props.arguments || {};
          planText = parsed.plan || props.arguments || "";
        } catch (e) {
          planText = props.arguments || "";
        }
        return renderPlanReviewCard(planText, props.onPlanAction);
      }
    );

    // 7. Generic Fallback Tool Card
    ctx.slots.register(
      {
        name: "tool.call.view",
        order: 100, // lowest priority fallback
      },
      (props) => {
        const name = props.name || "tool";
        let prettyArgs = props.arguments || "";
        try {
          if (typeof prettyArgs === "string") prettyArgs = JSON.stringify(JSON.parse(prettyArgs), null, 2);
        } catch (e) {}

        return `
          <div class="tool-view-card">
            <div class="tool-view-header">
              <span class="tool-title">🔧 ${escapeHtml(name)}</span>
              <span class="tool-status-pill pill-${(props.status || "running").toLowerCase()}">${props.status || "RUNNING"}</span>
            </div>
            <div class="tool-view-body">${escapeHtml(prettyArgs)}</div>
          </div>
        `;
      }
    );
  }
}
