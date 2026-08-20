/**
 * Session Execution Stats Line (`@deepseek-ai/dsh-client-ui-conversation/StatsLine`)
 * Renders live statistics strip right above the composer.
 */

export function formatDuration(ms) {
  const s = ms / 1000;
  if (s < 60) return `${Math.round(s * 10) / 10}s`;
  const whole = Math.round(s);
  return `${Math.floor(whole / 60)}m${whole % 60}s`;
}

export function formatTokens(n) {
  if (n < 1000) return String(n);
  if (n < 1000000) return `${Math.round((n / 1000) * 10) / 10}K`;
  return `${Math.round((n / 1000000) * 10) / 10}M`;
}

export class StatsLineView {
  constructor({ containerId = "stats-line-dock" }) {
    this.container = document.getElementById(containerId);
    this.stats = {
      turns: 0,
      steps: 0,
      llmMs: 0,
      toolMs: 0,
      inputTokens: 0,
      outputTokens: 0,
    };
  }

  updateFromEvents(events) {
    if (!events || !this.container) return;
    let turns = 0;
    let steps = 0;
    let toolCalls = 0;

    events.forEach((e) => {
      if (e.type === "user/message") turns++;
      if (e.type === "assistant/message") steps++;
      if (e.type === "tool/result") toolCalls++;
    });

    this.stats.turns = turns;
    this.stats.steps = steps;
    this.stats.toolMs = toolCalls * 250; // estimate
    this.render();
  }

  render() {
    if (!this.container || this.stats.steps === 0) {
      if (this.container) this.container.classList.add("hidden");
      return;
    }

    this.container.classList.remove("hidden");
    const groups = [
      `轮次: ${this.stats.turns} · 步骤: ${this.stats.steps}`,
    ];

    if (this.stats.toolMs > 0) {
      groups.push(`工具调用: ${formatDuration(this.stats.toolMs)}`);
    }

    this.container.innerHTML = `
      <div class="stats-line-bar">
        ${groups.map((g, i) => `<span>${g}</span>${i < groups.length - 1 ? '<span class="stats-sep">|</span>' : ""}`).join("")}
      </div>
    `;
  }
}
