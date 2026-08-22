"""
JSON storage backend: one human-readable file per unit under a configured root.
Aligned 1:1 with official `@deepseek-ai/dsh-storage-json`.
"""

import json
import os
import uuid
from typing import Any, Callable, Dict, List, Optional
from dsh.storage.backend import UNIT_NAME_RE, KvFacet, KvUnit, KvUnitDescriptor, StorageBackend
from dsh.storage.error import StorageError


async def write_atomic(path: str, data: str) -> None:
    """Durably replace `path` with `data` atomically."""
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    tmp_path = os.path.join(dir_name, f".{uuid.uuid4()}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise e


def serialize(name: str, state: Dict[str, Any]) -> str:
    """Serialize unit state to JSON file content."""
    tables = {table: dict(records) for table, records in state["tables"].items()}
    document = {
        "unit": {"name": name, "version": state["version"]},
        "global": state["global"],
        "tables": tables,
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def parse(text: str, descriptor: KvUnitDescriptor) -> Dict[str, Any]:
    """Parse file content into unit state, validating shape and version."""
    try:
        doc = json.loads(text)
    except Exception as e:
        raise StorageError("malformed-medium", f"unit '{descriptor.name}': file is not valid JSON", cause=e)

    if not isinstance(doc, dict):
        raise StorageError("malformed-medium", f"unit '{descriptor.name}': file is not a JSON object")

    unit_info = doc.get("unit")
    if (
        not isinstance(unit_info, dict)
        or unit_info.get("name") != descriptor.name
        or not isinstance(unit_info.get("version"), int)
    ):
        raise StorageError("malformed-medium", f"unit '{descriptor.name}': missing or foreign unit header")

    version = unit_info["version"]
    if version != descriptor.version:
        raise StorageError("version-mismatch", f"unit '{descriptor.name}': stored version {version} != expected {descriptor.version}")

    tables_raw = doc.get("tables")
    if not isinstance(tables_raw, dict):
        raise StorageError("malformed-medium", f"unit '{descriptor.name}': tables is not an object")

    tables_state: Dict[str, Dict[str, Any]] = {}
    for table in descriptor.tables:
        records_raw = tables_raw.get(table)
        if records_raw is None:
            tables_state[table] = {}
        elif not isinstance(records_raw, dict):
            raise StorageError("malformed-medium", f"unit '{descriptor.name}': table '{table}' is not an object")
        else:
            tables_state[table] = dict(records_raw)

    return {
        "version": version,
        "global": doc.get("global"),
        "tables": tables_state,
    }


class JsonKvUnit(KvUnit):
    """One opened JSON KV unit."""

    def __init__(
        self,
        descriptor: KvUnitDescriptor,
        path: str,
        state: Dict[str, Any],
        on_close: Callable[[], None],
    ):
        self.descriptor = descriptor
        self.path = path
        self.state = state
        self._on_close = on_close
        self.closed = False

    async def load_all(self) -> Dict[str, Any]:
        if self.closed:
            raise StorageError("closed", f"unit '{self.descriptor.name}' is closed")
        tables_copy = {tbl: dict(recs) for tbl, recs in self.state["tables"].items()}
        return {"tables": tables_copy, "global": self.state["global"]}

    async def _publish(self) -> None:
        content = serialize(self.descriptor.name, self.state)
        await write_atomic(self.path, content)

    async def put_record(self, table: str, key: str, value: Any) -> None:
        if self.closed:
            raise StorageError("closed", f"unit '{self.descriptor.name}' is closed")
        if table not in self.state["tables"]:
            raise ValueError(f"unit '{self.descriptor.name}' does not declare table '{table}'")
        recs = self.state["tables"][table]
        had_key = key in recs
        prev = recs.get(key)
        recs[key] = value
        try:
            await self._publish()
        except Exception as e:
            if had_key:
                recs[key] = prev
            else:
                recs.pop(key, None)
            raise e

    async def delete_record(self, table: str, key: str) -> None:
        if self.closed:
            raise StorageError("closed", f"unit '{self.descriptor.name}' is closed")
        if table not in self.state["tables"]:
            raise ValueError(f"unit '{self.descriptor.name}' does not declare table '{table}'")
        recs = self.state["tables"][table]
        if key not in recs:
            return
        prev = recs[key]
        del recs[key]
        try:
            await self._publish()
        except Exception as e:
            recs[key] = prev
            raise e

    async def set_global(self, value: Any) -> None:
        if self.closed:
            raise StorageError("closed", f"unit '{self.descriptor.name}' is closed")
        if not self.descriptor.has_global:
            raise ValueError(f"unit '{self.descriptor.name}' does not declare a global slot")
        prev = self.state["global"]
        self.state["global"] = value
        try:
            await self._publish()
        except Exception as e:
            self.state["global"] = prev
            raise e

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._on_close()


class JsonStorageBackend(StorageBackend):
    """JSON storage backend."""

    def __init__(self, root: str):
        self.root = root
        self._open_units: Dict[str, KvUnit] = {}
        self.closed = False
        self.kv = self._KvFacetImpl(self)

    class _KvFacetImpl(KvFacet):
        def __init__(self, outer: "JsonStorageBackend"):
            self.outer = outer

        async def open(self, descriptor: KvUnitDescriptor) -> KvUnit:
            if self.outer.closed:
                raise StorageError("closed", "json backend is closed")
            if not UNIT_NAME_RE.match(descriptor.name):
                raise StorageError("malformed-medium", f"invalid unit name '{descriptor.name}'")
            for tbl in descriptor.tables:
                if not UNIT_NAME_RE.match(tbl):
                    raise StorageError("malformed-medium", f"invalid table name '{tbl}' in unit '{descriptor.name}'")
            if descriptor.name in self.outer._open_units:
                raise ValueError(f"unit '{descriptor.name}' is already open; a unit has exactly one live handle")

            os.makedirs(self.outer.root, exist_ok=True)
            unit_path = os.path.join(self.outer.root, f"{descriptor.name}.json")

            text: Optional[str] = None
            if os.path.exists(unit_path):
                with open(unit_path, "r", encoding="utf-8") as f:
                    text = f.read()

            if text is None:
                state = {
                    "version": descriptor.version,
                    "global": None,
                    "tables": {tbl: {} for tbl in descriptor.tables},
                }
            else:
                state = parse(text, descriptor)

            def on_close():
                self.outer._open_units.pop(descriptor.name, None)

            unit = JsonKvUnit(descriptor, unit_path, state, on_close)
            if self.outer.closed:
                await unit.close()
                raise StorageError("closed", "json backend is closed")
            self.outer._open_units[descriptor.name] = unit
            return unit

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for unit in list(self._open_units.values()):
            await unit.close()
