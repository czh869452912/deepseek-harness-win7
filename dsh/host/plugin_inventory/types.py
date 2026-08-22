"""
Plugin Inventory Type Definitions (`@deepseek-ai/dsh-host-plugin-inventory/types`).
Aligned 1:1 with reference `src/types.ts`.
"""

from typing import Any, Dict, List, Optional


class PluginInventoryItem:
    """Descriptor for host or client plugins in system inventory."""

    def __init__(self, plugin_id: str, name: str, surface: str, active: bool = True, description: str = ""):
        self.plugin_id = plugin_id
        self.name = name
        self.surface = surface  # 'host' or 'client'
        self.active = active
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.plugin_id,
            "name": self.name,
            "surface": self.surface,
            "active": self.active,
            "description": self.description,
        }
