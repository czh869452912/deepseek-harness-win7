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

  async setModel(model) {
    const res = await fetch("/api/model/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    });
    return await res.json();
  },

  async describeSettings() {
    const res = await fetch("/api/settings/describe");
    return await res.json();
  },

  async saveSettings(config) {
    const res = await fetch("/api/settings/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    return await res.json();
  },

  async discoverModels(baseUrl, apiKey) {
    const res = await fetch("/api/models/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ baseUrl, apiKey }),
    });
    return await res.json();
  },

  async getWorkspaceFiles() {
    const res = await fetch("/api/workspace/files");
    return await res.json();
  },

  async setPermission(preset) {
    const res = await fetch("/api/permission/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preset }),
    });
    return await res.json();
  },

  async getJobs() {
    const res = await fetch("/api/jobs/list");
    return await res.json();
  },

  async forkSession(sourceSessionId, cutoffIndex = null) {
    const res = await fetch("/api/session/fork", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sourceSessionId, cutoffIndex }),
    });
    return await res.json();
  },
};
