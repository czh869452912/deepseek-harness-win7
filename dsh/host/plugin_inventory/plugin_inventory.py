"""
Plugin Inventory Gateway (`@deepseek-ai/dsh-host-plugin-inventory`).
Read-only projection of current Cordis Loader entries and Fiber states.
Aligned 1:1 with reference `plugin-inventory/src/index.ts`.
"""

from typing import Any, Dict, List, Optional

FIBER_PHASE_MAP = {
    0: "pending",
    1: "loading",
    2: "active",
    3: "failed",
    4: None,
    5: "unloading",
}


class PluginInventoryGateway:
    """
    Exposes Cordis Loader's current plugin entries and lifecycle states.
    Mounted on `ctx.plugin_inventory` or `ctx.pluginInventory`.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        ctx.set_service("plugin_inventory", self)
        ctx.set_service("pluginInventory", self)

    def list(self) -> Dict[str, Any]:
        """
        Read active entries from Cordis loader on every call.
        Returns entries in loader registration order.
        """
        entries: List[Dict[str, Any]] = []
        loader = getattr(self.ctx, "loader", None)
        if loader and hasattr(loader, "entries"):
            for entry in loader.entries():
                if getattr(entry, "is_group", False):
                    continue
                fiber = getattr(entry, "fiber", None)
                state_code = getattr(fiber, "state", None) if fiber else None
                phase = FIBER_PHASE_MAP.get(state_code) if state_code is not None else None

                entries.append({
                    "entryId": getattr(entry, "id", "unknown"),
                    "moduleName": getattr(entry, "name", "unknown"),
                    "enabled": not getattr(entry, "disabled", False),
                    "fiberPhase": phase,
                })
        else:
            # Fallback if loader service is not attached
            registry = getattr(self.ctx, "registry", {})
            if hasattr(registry, "values"):
                for plugin_inst in registry.values():
                    pid = getattr(plugin_inst, "id", str(plugin_inst))
                    pname = getattr(plugin_inst, "name", pid)
                    entries.append({
                        "entryId": pid,
                        "moduleName": pname,
                        "enabled": True,
                        "fiberPhase": "active",
                    })

        return {"entries": entries}
