/**
 * DeepSeek Harness Client Session (`@deepseek-ai/dsh-client-runtime/sessions/session`)
 * Owns a session's event log window, streaming partial state, and observable snapshot.
 */

import { Notifier } from "./notifier.js";
import { PartialAccumulator, isVisibleAssistantChunk } from "./partial.js";

export class Session {
  constructor(sessionId, options = {}) {
    this.id = sessionId;
    this.options = options;
    this.events = [];
    this.views = [];
    this.openState = "cold"; // 'cold' | 'loading' | 'open' | 'error'
    this.running = false;

    this.notifier = new Notifier();
    this.partialAccumulator = new PartialAccumulator(1, 1);
  }

  subscribe(listener) {
    return this.notifier.subscribe(listener);
  }

  getSnapshot() {
    return {
      id: this.id,
      events: this.events,
      views: this.views,
      openState: this.openState,
      running: this.running,
      partial: this.partialAccumulator.toPartial(),
      hasEvents: this.events.length > 0,
    };
  }

  setHistory(events = []) {
    this.events = [...events];
    this.openState = "open";
    this.partialAccumulator.clear();
    this.notifier.markDirty();
  }

  setRunning(running) {
    if (this.running !== running) {
      this.running = running;
      if (!running) {
        this.partialAccumulator.clear();
      }
      this.notifier.markDirty();
    }
  }

  /**
   * Land an incoming live SessionEvent.
   */
  acceptLiveEvent(event, view = null) {
    if (!event) return;
    this.events.push(event);
    if (view) this.views.push(view);

    const type = event.type;
    if (type === "turn/end" || type === "assistant/message") {
      this.partialAccumulator.clear();
      if (type === "turn/end") {
        this.running = false;
      }
    } else if (type === "turn/start") {
      const data = event.data || {};
      this.partialAccumulator = new PartialAccumulator(data.turn || 1, 1);
      this.running = true;
    }

    this.notifier.markDirty();
  }

  /**
   * Fold an in-flight streaming chunk.
   */
  handleChunk(chunkData) {
    if (!chunkData) return;
    this.running = true;
    const changed = this.partialAccumulator.push(chunkData);
    if (changed) {
      this.notifier.markFrameDirty();
    }
  }

  /**
   * Handle routed MuxFrame envelope.
   */
  handleMuxEnvelope(rpcId, frame) {
    if (!frame) return;
    const type = frame.type;

    switch (type) {
      case "session/event":
        this.acceptLiveEvent(frame.event, frame.view);
        break;
      case "session/chunk":
      case "assistant/chunk":
        this.handleChunk(frame.data || frame.chunk || frame);
        break;
      case "agent/status":
        if (frame.status === "running") this.setRunning(true);
        else if (frame.status === "idle") this.setRunning(false);
        break;
      default:
        break;
    }
  }
}
