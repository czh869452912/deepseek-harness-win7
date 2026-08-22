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


from dsh.cordis.plugin import Plugin


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
            raw_entries = loader.entries() if callable(loader.entries) else loader.entries
            for entry in raw_entries:
                options = getattr(entry, "options", {})
                if options.get("group"):
                    continue
                fiber = getattr(entry, "fiber", None)
                state_code = getattr(fiber, "state", None) if fiber else None
                phase = FIBER_PHASE_MAP.get(state_code) if (fiber is not None and state_code is not None) else None

                entry_id = getattr(entry, "id", options.get("id", getattr(entry, "name", "unknown")))
                module_name = options.get("name") or getattr(entry, "name", entry_id)

                entries.append({
                    "entryId": entry_id,
                    "moduleName": module_name,
                    "enabled": not getattr(entry, "disabled", False),
                    "fiberPhase": phase,
                })
        else:
            # Fallback if loader service is not attached
            registry = getattr(self.ctx, "registry", None)
            if registry and hasattr(registry, "list_fibers"):
                for fiber in registry.list_fibers():
                    plugin_inst = getattr(fiber, "plugin", None)
                    pid = getattr(plugin_inst, "id", getattr(fiber, "name", str(fiber)))
                    pname = getattr(plugin_inst, "name", pid)
                    state_code = getattr(fiber, "state", 2)
                    phase = FIBER_PHASE_MAP.get(state_code, "active")
                    entries.append({
                        "entryId": pid,
                        "moduleName": pname,
                        "enabled": True,
                        "fiberPhase": phase,
                    })

        return {"entries": entries}


class PluginInventoryPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-host-plugin-inventory`: Exposes Cordis plugin inventory gateway.
    """

    id = "plugin-inventory"
    name = "@deepseek-ai/dsh-host-plugin-inventory"
    inject = []

    def apply(self, ctx: Any) -> None:
        gateway = PluginInventoryGateway(ctx)
        ctx.set_service("plugin_inventory", gateway)
        ctx.set_service("pluginInventory", gateway)

