/**
 * Goal Bar Controller (`@deepseek-ai/dsh-client-ui-goal`)
 */

export class GoalBarView {
  constructor({ onToggleGoal }) {
    this.onToggleGoal = onToggleGoal;
    this.goalBar = document.getElementById("goal-bar");
    this.goalObjective = document.getElementById("goal-objective");
    this.goalPhase = document.getElementById("goal-phase");
    this.goalRounds = document.getElementById("goal-rounds");
    this.btnToggle = document.getElementById("btn-goal-toggle");

    this.currentGoal = null;
    this._bindEvents();
  }

  _bindEvents() {
    this.btnToggle.addEventListener("click", () => {
      if (this.onToggleGoal && this.currentGoal) {
        const action = this.currentGoal.phase === "paused" ? "resume" : "pause";
        this.onToggleGoal(action);
      }
    });
  }

  update(goal) {
    this.currentGoal = goal;
    if (!goal || goal.phase === "complete") {
      this.goalBar.classList.add("hidden");
      return;
    }

    this.goalBar.classList.remove("hidden");
    this.goalObjective.textContent = goal.objective || "长程自主任务";
    this.goalPhase.textContent = (goal.phase || "active").toUpperCase();
    this.goalPhase.className = `goal-status-badge badge-${goal.phase || "active"}`;
    this.goalRounds.textContent = `Round ${goal.roundsStarted || 1}`;
    this.btnToggle.textContent = goal.phase === "paused" ? "恢复" : "暂停";
  }
}
