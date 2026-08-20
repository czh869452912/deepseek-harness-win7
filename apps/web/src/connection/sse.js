/**
 * Downlink & Real-time Event Stream (`@deepseek-ai/dsh-client-connection/websocket-downlink`)
 * Connects to /api/session/events and dispatches events.
 */

export class DownlinkStream {
  constructor(listeners = {}) {
    this.listeners = listeners;
    this.eventSource = null;
    this.isConnected = false;
  }

  connect() {
    if (this.eventSource) {
      this.eventSource.close();
    }

    this.eventSource = new EventSource("/api/session/events");

    this.eventSource.onopen = () => {
      this.isConnected = true;
      if (this.listeners.onConnect) this.listeners.onConnect();
    };

    this.eventSource.addEventListener("session/event", (e) => {
      try {
        const event = JSON.parse(e.data);
        if (this.listeners.onSessionEvent) {
          this.listeners.onSessionEvent(event);
        }
      } catch (err) {
        console.error("[SSE] Failed to parse session event:", err);
      }
    });

    this.eventSource.addEventListener("goal/changed", (e) => {
      try {
        const data = JSON.parse(e.data);
        if (this.listeners.onGoalChanged) {
          this.listeners.onGoalChanged(data.goal);
        }
      } catch (err) {
        console.error("[SSE] Failed to parse goal event:", err);
      }
    });

    this.eventSource.addEventListener("session/chunk", (e) => {
      try {
        const chunk = JSON.parse(e.data);
        if (this.listeners.onSessionChunk) {
          this.listeners.onSessionChunk(chunk);
        }
      } catch (err) {
        console.error("[SSE] Failed to parse session chunk:", err);
      }
    });

    this.eventSource.addEventListener("assistant/chunk", (e) => {
      try {
        const chunk = JSON.parse(e.data);
        if (this.listeners.onAssistantChunk) {
          this.listeners.onAssistantChunk(chunk);
        }
      } catch (err) {
        console.error("[SSE] Failed to parse assistant chunk:", err);
      }
    });

    this.eventSource.addEventListener("agent/status", (e) => {
      try {
        const data = JSON.parse(e.data);
        if (this.listeners.onAgentStatus) {
          this.listeners.onAgentStatus(data);
        }
      } catch (err) {
        console.error("[SSE] Failed to parse agent status:", err);
      }
    });

    this.eventSource.onerror = () => {
      this.isConnected = false;
      if (this.listeners.onError) this.listeners.onError();
      setTimeout(() => this.connect(), 3000);
    };
  }

  disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}
