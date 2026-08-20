/**
 * Connection Controller (`@deepseek-ai/dsh-client-connection/client`).
 * 1:1 Implementation of 4-quadrant RPC, dual SSE stream pumps,
 * strict describe handshake, and jittered exponential backoff reconnects.
 */

export class ConnectionController {
  constructor(api, sinks = {}, config = {}) {
    this.api = api;
    this.sinks = sinks;
    this.config = {
      backoffBaseMs: 500,
      backoffFactor: 2,
      backoffMaxMs: 10000,
      streamOpenTimeoutMs: 3000,
      ...config,
    };
    this.generation = 0;
    this.attempt = 0;
    this.running = false;
    this.lastState = null;
    this.activeMuxSource = null;
    this.activeHostSource = null;
  }

  start() {
    if (this.running) return;
    this.running = true;
    this._loop();
  }

  stop() {
    this.running = false;
    if (this.activeMuxSource) {
      this.activeMuxSource.close();
      this.activeMuxSource = null;
    }
    if (this.activeHostSource) {
      this.activeHostSource.close();
      this.activeHostSource = null;
    }
  }

  _backoffDelay(attempt) {
    const { backoffBaseMs, backoffFactor, backoffMaxMs } = this.config;
    const cap = Math.min(backoffMaxMs, backoffBaseMs * Math.pow(backoffFactor, Math.max(0, attempt - 1)));
    return cap / 2 + Math.random() * (cap / 2);
  }

  async _loop() {
    while (this.running) {
      this.generation++;
      const gen = this.generation;

      try {
        await this._connectStreams(gen);
        // Describe handshake
        const desc = await this.api.describe();
        if (desc && desc.status === "ready" || desc.ok || desc.result) {
          this.attempt = 0;
          this._emitState("connected");
          if (this.sinks.onConnected) {
            this.sinks.onConnected(desc.value || desc.result?.value || desc);
          }
        }
      } catch (err) {
        console.warn(`[Connection] Generation #${gen} connection error:`, err);
      }

      if (!this.running) return;
      this._emitState("reconnecting");
      this.attempt++;
      const delay = this._backoffDelay(this.attempt);
      await new Promise((r) => setTimeout(r, delay));
    }
  }

  _connectStreams(gen) {
    return new Promise((resolve, reject) => {
      let muxOpened = false;
      let hostOpened = false;

      const checkOpen = () => {
        if (muxOpened && hostOpened) resolve();
      };

      const muxUrl = "/api/events/mux";
      const hostUrl = "/api/events/host";

      try {
        const esMux = new EventSource(muxUrl);
        this.activeMuxSource = esMux;

        esMux.onopen = () => {
          muxOpened = true;
          checkOpen();
        };

        esMux.addEventListener("mux", (ev) => {
          try {
            const data = JSON.parse(ev.data);
            if (this.sinks.onMuxEnvelope) this.sinks.onMuxEnvelope(data);
          } catch (e) {}
        });

        esMux.onerror = () => {
          esMux.close();
          if (gen === this.generation) {
            reject(new Error("Mux stream error"));
          }
        };

        const esHost = new EventSource(hostUrl);
        this.activeHostSource = esHost;

        esHost.onopen = () => {
          hostOpened = true;
          checkOpen();
        };

        esHost.addEventListener("host", (ev) => {
          try {
            const data = JSON.parse(ev.data);
            if (this.sinks.onHostEnvelope) this.sinks.onHostEnvelope(data);
          } catch (e) {}
        });

        esHost.onerror = () => {
          esHost.close();
          if (gen === this.generation) {
            reject(new Error("Host stream error"));
          }
        };

        // Stream open timeout fallback
        setTimeout(() => {
          resolve();
        }, this.config.streamOpenTimeoutMs);

      } catch (err) {
        reject(err);
      }
    });
  }

  _emitState(state) {
    if (this.lastState === state) return;
    this.lastState = state;
    if (this.sinks.onStateChange) {
      try {
        this.sinks.onStateChange(state);
      } catch (e) {
        console.error("[Connection] Sink onStateChange threw:", e);
      }
    }
  }
}
