/**
 * DeepSeek Harness SessionManager (`@deepseek-ai/dsh-client-runtime/sessions/manager`)
 * Multi-session lifecycle manager, active session switcher, and sessions projection source.
 */

import { Notifier } from "./notifier.js";
import { Session } from "./session.js";

export class SessionManager {
  constructor(ctx) {
    this.ctx = ctx;
    this.sessions = new Map();
    this.currentSessionId = "default-session";
    this.notifier = new Notifier();
    this.sessionSummaries = [];

    // Ensure default session exists
    this.sessionOf(this.currentSessionId);
  }

  subscribe(listener) {
    return this.notifier.subscribe(listener);
  }

  sessionOf(sessionId) {
    if (!this.sessions.has(sessionId)) {
      const session = new Session(sessionId);
      this.sessions.set(sessionId, session);
      // Relay individual session changes to manager subscribers
      session.subscribe(() => {
        if (session.id === this.currentSessionId) {
          this.notifier.markFrameDirty();
        }
      });
      this.notifier.markDirty();
    }
    return this.sessions.get(sessionId);
  }

  getCurrentSession() {
    return this.sessionOf(this.currentSessionId);
  }

  switchSession(sessionId) {
    if (this.currentSessionId === sessionId) return;
    this.currentSessionId = sessionId;
    this.sessionOf(sessionId); // Ensure created
    this.notifier.notifyNow();
  }

  setSessionList(list) {
    this.sessionSummaries = list || [];
    this.sessionSummaries.forEach((s) => {
      if (s.id && !this.sessions.has(s.id)) {
        this.sessionOf(s.id);
      }
    });
    this.notifier.markDirty();
  }

  getSessionsSnapshot() {
    if (this.sessionSummaries.length > 0) {
      return this.sessionSummaries;
    }
    return Array.from(this.sessions.keys()).map((id) => ({
      id,
      active: id === this.currentSessionId,
    }));
  }

  /**
   * Route incoming frame to target session.
   */
  routeFrame(frame) {
    if (!frame) return;
    const targetSid = frame.sessionId || this.currentSessionId;
    const session = this.sessionOf(targetSid);
    session.handleMuxEnvelope(frame.rpcId || "mux", frame);
  }
}
