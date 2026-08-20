/**
 * Connection & Web API Client (`@deepseek-ai/dsh-client-connection`)
 * Handles unary RPC calls to the backend /api endpoints.
 */

export const ApiClient = {
  async getStatus() {
    const res = await fetch("/api/status");
    return await res.json();
  },

  async getPresets() {
    const res = await fetch("/api/presets/list");
    return await res.json();
  },

  async getSessions() {
    const res = await fetch("/api/session/list");
    return await res.json();
  },

  async createSession(sessionId, preset = "standard") {
    const res = await fetch("/api/session/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId, preset }),
    });
    return await res.json();
  },

  async getHistory(sessionId) {
    const res = await fetch(`/api/session/history?sessionId=${encodeURIComponent(sessionId)}`);
    return await res.json();
  },

  async prompt(sessionId, content) {
    const res = await fetch("/api/agent/prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId, content }),
    });
    return await res.json();
  },

  async cancel(sessionId) {
    const res = await fetch("/api/agent/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId }),
    });
    return await res.json();
  },

  async setPlanMode(active) {
    const res = await fetch("/api/plan/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active }),
    });
    return await res.json();
  },

  async goalAction(action, objective = null) {
    const res = await fetch("/api/goal/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, objective }),
    });
    return await res.json();
  },
};
