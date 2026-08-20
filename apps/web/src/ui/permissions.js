/**
 * Permission Preset Selector & Risk Modal (`@deepseek-ai/dsh-client-ui-permission-presets`)
 * Allows switching between Read-only, Workspace-write, and Full-access (with risk confirmation).
 */

export const PERMISSION_PRESETS = [
  { id: "read-only", label: "🛡️ 只读模式 (Read-only)", desc: "只能查看与搜索文件，禁止任何编辑与执行" },
  { id: "workspace-write", label: "📁 工作区读写 (Workspace)", desc: "允许在当前工作区内创建、修改代码与运行命令" },
  { id: "danger-full-access", label: "⚠️ 完整系统权限 (Full Access)", desc: "拥有无限制的系统调用与全局文件访问权限" },
];

export class PermissionSelectView {
  constructor({ containerId = "permission-select-container", modalId = "permission-modal", onSelectPermission }) {
    this.container = document.getElementById(containerId);
    this.modal = document.getElementById(modalId);
    this.onSelectPermission = onSelectPermission;
    this.currentPreset = "workspace-write";
    this.pendingPreset = null;
    this.isOpen = false;

    this._createUI();
    this._bindEvents();
  }

  _createUI() {
    if (this.container) {
      this.container.innerHTML = `
        <div class="permission-chip-button" id="btn-permission-chip" title="切换当前会话访问权限">
          <span class="permission-icon">📁</span>
          <span id="permission-label-text">Workspace</span>
          <span class="dropdown-arrow">▾</span>
        </div>
        <div class="permission-menu hidden" id="permission-menu">
          ${PERMISSION_PRESETS.map((p) => `
            <div class="permission-menu-item ${p.id === this.currentPreset ? 'active' : ''}" data-id="${p.id}">
              <div class="p-item-title">${p.label}</div>
              <div class="p-item-desc">${p.desc}</div>
            </div>
          `).join("")}
        </div>
      `;
    }

    if (!this.modal) {
      const modalEl = document.createElement("div");
      modalEl.id = "permission-modal";
      modalEl.className = "modal-backdrop hidden";
      modalEl.innerHTML = `
        <div class="modal-dialog risk-modal">
          <div class="modal-header risk-header">
            <div class="modal-title">⚠️ 完整系统权限确认 (Risk Confirmation)</div>
            <button type="button" class="btn-icon-plain" id="btn-close-risk-modal">✕</button>
          </div>
          <div class="modal-body">
            <p class="risk-warning-text">
              您正在切换到 <strong>Full Access (完整权限)</strong> 模式。<br>
              智能体将能够直接执行任意 Shell 命令、访问工作区外的系统敏感目录，存在潜在的文件覆盖或系统变更风险。
            </p>
            <label class="risk-checkbox-label">
              <input type="checkbox" id="chk-risk-agree">
              <span>我已知晓并自愿承担由 Agent 执行产生的一切风险</span>
            </label>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn-secondary" id="btn-cancel-risk">取消</button>
            <button type="button" class="btn-danger" id="btn-confirm-risk" disabled>确认启用完整权限</button>
          </div>
        </div>
      `;
      document.body.appendChild(modalEl);
      this.modal = modalEl;
    }
  }

  _bindEvents() {
    const chipBtn = document.getElementById("btn-permission-chip");
    const menu = document.getElementById("permission-menu");
    if (!chipBtn || !menu) return;

    chipBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.classList.toggle("hidden");
    });

    menu.querySelectorAll(".permission-menu-item").forEach((item) => {
      item.addEventListener("click", () => {
        const id = item.getAttribute("data-id");
        menu.classList.add("hidden");
        this.requestSetPermission(id);
      });
    });

    document.addEventListener("click", (e) => {
      if (!menu.contains(e.target) && e.target !== chipBtn) {
        menu.classList.add("hidden");
      }
    });

    // Risk Modal events
    const chkAgree = document.getElementById("chk-risk-agree");
    const btnConfirm = document.getElementById("btn-confirm-risk");
    const btnCancel = document.getElementById("btn-cancel-risk");
    const btnClose = document.getElementById("btn-close-risk-modal");

    if (chkAgree && btnConfirm) {
      chkAgree.addEventListener("change", () => {
        btnConfirm.disabled = !chkAgree.checked;
      });

      btnConfirm.addEventListener("click", () => {
        this.applyPermission("danger-full-access");
        this.modal.classList.add("hidden");
      });
    }

    if (btnCancel) {
      btnCancel.addEventListener("click", () => {
        this.modal.classList.add("hidden");
      });
    }
    if (btnClose) {
      btnClose.addEventListener("click", () => {
        this.modal.classList.add("hidden");
      });
    }
  }

  requestSetPermission(presetId) {
    if (presetId === "danger-full-access") {
      const chkAgree = document.getElementById("chk-risk-agree");
      const btnConfirm = document.getElementById("btn-confirm-risk");
      if (chkAgree) chkAgree.checked = false;
      if (btnConfirm) btnConfirm.disabled = true;
      this.modal.classList.remove("hidden");
      return;
    }
    this.applyPermission(presetId);
  }

  applyPermission(presetId) {
    this.currentPreset = presetId;
    const labelEl = document.getElementById("permission-label-text");
    const iconEl = this.container ? this.container.querySelector(".permission-icon") : null;

    if (presetId === "read-only") {
      if (labelEl) labelEl.textContent = "Read-only";
      if (iconEl) iconEl.textContent = "🛡️";
    } else if (presetId === "danger-full-access") {
      if (labelEl) labelEl.textContent = "Full Access";
      if (iconEl) iconEl.textContent = "⚠️";
    } else {
      if (labelEl) labelEl.textContent = "Workspace";
      if (iconEl) iconEl.textContent = "📁";
    }

    const menu = document.getElementById("permission-menu");
    if (menu) {
      menu.querySelectorAll(".permission-menu-item").forEach((item) => {
        item.classList.toggle("active", item.getAttribute("data-id") === presetId);
      });
    }

    if (this.onSelectPermission) this.onSelectPermission(presetId);
  }
}
