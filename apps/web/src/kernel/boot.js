/**
 * Web Boot Kernel (`@deepseek-ai/dsh-client-web/src/boot`).
 * Initializes ClientModuleSystem, in-browser Cordis Context & Loader,
 * displays boot progress, and hands over mount point to uiRenderer.
 */

import { Context, CordisLoaderPlugin } from "./cordis.js";
import { ClientModuleSystem } from "../modules/system.js";
import { getStaticModules } from "./seed.js";

export class BootPage {
  constructor(container) {
    this.container = container;
    this.total = 0;
    this.loaded = 0;
    this.states = new Map();
    this.render();
  }

  setTotal(total) {
    this.total = total;
    this.render();
  }

  setState(name, state) {
    this.states.set(name, state);
    if (state === "active") {
      this.loaded = Array.from(this.states.values()).filter((s) => s === "active").length;
    }
    this.render();
  }

  fail(message) {
    this.container.innerHTML = `
      <div class="boot-screen boot-failed">
        <div class="boot-card">
          <div class="boot-logo">⚠️</div>
          <h2>DeepSeek Harness 启动失败</h2>
          <pre class="boot-error-log">${escapeHtml(message)}</pre>
          <button class="btn-primary" onclick="window.location.reload()">重试 (Reload)</button>
        </div>
      </div>
    `;
  }

  render() {
    const percent = this.total > 0 ? Math.round((this.loaded / this.total) * 100) : 0;
    let itemsHtml = "";
    for (const [pkgName, state] of this.states.entries()) {
      const icon = state === "active" ? "✓" : state === "failed" ? "✕" : "⏳";
      itemsHtml += `
        <div class="boot-plugin-item ${state}">
          <span class="boot-plugin-icon">${icon}</span>
          <span class="boot-plugin-name">${escapeHtml(pkgName)}</span>
          <span class="boot-plugin-state">${state.toUpperCase()}</span>
        </div>
      `;
    }

    this.container.innerHTML = `
      <div class="boot-screen">
        <div class="boot-card">
          <div class="boot-logo-spinner"></div>
          <h2>DeepSeek Harness (Win7)</h2>
          <div class="boot-progress-bar-wrap">
            <div class="boot-progress-bar" style="width: ${percent}%"></div>
          </div>
          <div class="boot-status-text">正在挂载 Cordis 浏览器插件内核 (${this.loaded}/${this.total || 0})...</div>
          <div class="boot-plugins-list">${itemsHtml}</div>
        </div>
      </div>
    `;
  }

  dispose() {
    // Clear boot page
  }
}

function escapeHtml(str) {
  if (typeof str !== "string") return String(str);
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export class AppWebEntry {
  constructor(container) {
    this.container = container;
    this.page = new BootPage(container);
    this.ctx = null;
    this.modules = null;
    this.manifest = null;
  }

  async run() {
    try {
      const win = globalThis;
      const bootManifest = win.__DSH_BOOT__ || {
        rev: "0",
        entries: [],
        plugins: [],
      };

      this.modules = new ClientModuleSystem({
        manifest: bootManifest,
        staticModules: getStaticModules(),
        registrationTarget: win.__ModuleLoader__,
      });
      this.manifest = this.modules.manifest;

      const ctx = new Context();
      this.ctx = ctx;

      // Mount core services onto browser context
      ctx.set_service("client_modules", this.modules);
      ctx.set_service("clientModules", this.modules);

      await this.runPluginBoot(ctx);
      await this.mountApp(ctx);
    } catch (err) {
      console.error("[AppWebEntry] Boot failure:", err);
      this.page.fail(err instanceof Error ? err.message : String(err));
    }
  }

  async runPluginBoot(ctx) {
    await ctx.plugin(CordisLoaderPlugin);
    const loader = ctx.loader;
    loader.internal = this.modules;

    const rows = (this.manifest.plugins || this.manifest.entries || []).map((r) => r.id);
    this.page.setTotal(rows.length);

    ctx.on("internal/status", (payload) => {
      const entry = payload.entry;
      if (entry && entry.options && entry.fiber) {
        this.page.setState(entry.options.name, entry.fiber.state);
      }
    });

    await Promise.all(
      rows.map(async (name) => {
        this.page.setState(name, "loading");
        const id = await loader.create({ name });
        const res = loader.resolve(id);
        if (res && res.fiber) {
          this.page.setState(name, res.fiber.state);
        }
      })
    );

    await loader.await();
  }

  async mountApp(ctx) {
    // Await uiRenderer
    await ctx.inject(["uiRenderer"], (scope) => {
      this.page.dispose();
      scope.uiRenderer.mount(this.container);
    });
  }

  async dispose() {
    if (this.ctx && this.ctx.fiber) {
      await this.ctx.fiber.dispose();
    }
    this.page.dispose();
  }
}
