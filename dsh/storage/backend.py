"""
Backend-facing vocabulary of the storage hub.
Aligned 1:1 with official `@deepseek-ai/dsh-storage/src/backend`.
"""

import re
from typing import Any, Dict, List, Optional

UNIT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class KvUnitDescriptor:
    """Static identity and shape of one KV unit."""

    def __init__(self, name: str, version: int, tables: List[str], has_global: bool = False):
        self.name = name
        self.version = version
        self.tables = tables
        self.has_global = has_global
        self.hasGlobal = has_global


class KvUnit:
    """One opened unit."""

    async def load_all(self) -> Dict[str, Any]:
        raise NotImplementedError

    async def loadAll(self) -> Dict[str, Any]:
        return await self.load_all()

    async def put_record(self, table: str, key: str, value: Any) -> None:
        raise NotImplementedError

    async def putRecord(self, table: str, key: str, value: Any) -> None:
        await self.put_record(table, key, value)

    async def delete_record(self, table: str, key: str) -> None:
        raise NotImplementedError

    async def deleteRecord(self, table: str, key: str) -> None:
        await self.delete_record(table, key)

    async def set_global(self, value: Any) -> None:
        raise NotImplementedError

    async def setGlobal(self, value: Any) -> None:
        await self.set_global(value)

    async def close(self) -> None:
        raise NotImplementedError


class KvFacet:
    """The key-value data shape facet."""

    async def open(self, descriptor: KvUnitDescriptor) -> KvUnit:
        raise NotImplementedError


class StorageBackend:
    """One registered backend owning one storage medium."""

    kv: Optional[KvFacet] = None

    async def close(self) -> None:
        raise NotImplementedError
