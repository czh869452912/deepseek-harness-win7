"""
In-memory settings provider fixture: the smallest real subclass of the Service
Definition, used by the base-class behavior suite in place of a file- or
network-backed provider.
1:1 with reference packages/settings/settings/tests/memory.ts.
"""

import asyncio
import copy
from typing import Any, Dict, List, Optional

from dsh.settings.provider import SettingsProvider


class MemorySettings(SettingsProvider):
    """In-memory provider exposing the protected provider hooks to tests."""

    def __init__(self, ctx: Optional[Any] = None, options: Optional[Dict[str, Any]] = None):
        super().__init__(ctx)
        option_map = options or {}
        # Raw document the provider "storage" currently holds.
        self.doc: Dict[str, Any] = copy.deepcopy(option_map.get("doc") or {})
        # Every _persist_section() call observed, in order.
        self.persisted: List[Dict[str, Any]] = []
        # When false, update() must reject before reaching persist().
        self.writableFlag: bool = option_map.get("writable", True)
        # Artificial persist latency so tests can interleave concurrent updates.
        self.persistDelayMs: int = option_map.get("persistDelayMs", 0)

    @property
    def writable(self) -> bool:
        return self.writableFlag

    def load(self) -> Dict[str, Any]:
        return copy.deepcopy(self.doc)

    async def _persist_section(self, ns: str, section: Dict[str, Any]) -> None:
        if self.persistDelayMs > 0:
            await asyncio.sleep(self.persistDelayMs / 1000.0)
        self.persisted.append({"ns": ns, "section": copy.deepcopy(section)})
        self.doc[ns] = copy.deepcopy(section)

    def push_external(self, doc: Dict[str, Any]) -> None:
        """Simulate an external storage change reaching the provider."""
        # In place, not rebound: the fixture is exercised through derived
        # service objects, where an attribute assignment would shadow `doc` on
        # the derived object and leave every other reader on the previous one.
        detached = copy.deepcopy(doc)
        self.doc.clear()
        self.doc.update(detached)
        self.publish(copy.deepcopy(doc))
