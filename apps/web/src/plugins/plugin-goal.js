/**
 * Goal Tracker Plugin (`@deepseek-ai/dsh-client-ui-goal`).
 * 1:1 Implementation of Goal Bar, CAS Optimistic Locking, and Multi-turn Goal Lifecycle.
 */

import { escapeHtml } from "../ui/markdown.js";

export function GoalBarView(props) {
  const { goal, onAction } = props;
  if (!goal || !goal.objective) return document.createElement("div");

  const isPaused = goal.status === "paused";
  const isComplete = goal.status === "completed";

  const rootEl = document.createElement("div");
  rootEl.className = "goal-bar-container";
  rootEl.innerHTML = `
    <div class="goal-bar-inner ${goal.status || 'active'}">
      <div class="goal-left">
        <span class="goal-icon">🎯</span>
        <span class="goal-objective">${escapeHtml(goal.objective)}</span>
        <span class="goal-status-badge badge-${goal.status || 'active'}">${(goal.status || 'active').toUpperCase()}</span>
      </div>
      <div class="goal-actions">
        ${!isComplete ? `
          <button class="btn-goal-act" id="btn-goal-toggle">${isPaused ? "▶ 继续" : "⏸ 暂停"}</button>
          <button class="btn-goal-act" id="btn-goal-complete">✓ 完成</button>
        ` : `
          <button class="btn-goal-act" id="btn-goal-clear">✕ 清除</button>
        `}
      </div>
    </div>
  `;

  const btnToggle = rootEl.querySelector("#btn-goal-toggle");
  const btnComplete = rootEl.querySelector("#btn-goal-complete");
  const btnClear = rootEl.querySelector("#btn-goal-clear");

  if (btnToggle) {
    btnToggle.addEventListener("click", () => {
      if (onAction) onAction(isPaused ? "resume" : "pause");
    });
  }
  if (btnComplete) {
    btnComplete.addEventListener("click", () => {
      if (onAction) onAction("complete");
    });
  }
  if (btnClear) {
    btnClear.addEventListener("click", () => {
      if (onAction) onAction("clear");
    });
  }

  return rootEl;
}

export class PluginGoal {
  static inject = ["slots", "sessions"];

  apply(ctx) {
    const slots = ctx.get("slots");
    let currentGoal = null;

    async function sendGoalAction(action) {
      if (!currentGoal) return;
      try {
        await fetch(`/api/goals/${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ref: { id: currentGoal.id, revision: currentGoal.revision },
          }),
        });
      } catch (e) {
        console.error("[Goal] Action error:", e);
      }
    }

    slots.register({
      name: "conversation.dock",
      id: "goal-bar",
      inject: () => ({
        goal: currentGoal,
        onAction: sendGoalAction,
      }),
    }, (props) => GoalBarView(props));

    // Listen to projection events
    ctx.on("goal/changed", (data) => {
      currentGoal = data.goal || data;
      const dockOutlet = document.getElementById("slot-outlet-dock");
      if (dockOutlet) {
        slots.renderSlot("conversation.dock", {}, dockOutlet);
      }
    });
  }
}
