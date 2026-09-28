"""Version-stamped per-record JSON medium; live memory belongs to the domain."""
import json
import os
import re

from dsh.storage.backend import KvUnit
from dsh.storage.error import StorageError
from dsh.storage.storage_json import write_atomic

_MISSING = object()
_KEY = re.compile(r"^[a-zA-Z0-9_-]+$")


class PerRecordJsonUnit(KvUnit):
    def __init__(self, descriptor, root, on_close):
        self.descriptor, self.root, self.on_close = descriptor, root, on_close
        self.directory = os.path.join(root, descriptor.name)
        self.closed = False

    def _assert_open(self):
        if self.closed:
            raise StorageError("closed", "unit '{}' is closed".format(self.descriptor.name))

    def _path(self, table, key):
        self._assert_open()
        if table not in self.descriptor.tables:
            raise ValueError("undeclared table: " + table)
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError("per-record key is not path-safe")
        # Windows device stems are legal upstream keys but cannot name files.
        # Reject them explicitly instead of writing a device or hanging.
        if os.name == "nt" and re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])", key):
            raise ValueError("per-record key names a Windows device")
        return os.path.join(self.directory, table, key + ".json")

    def _read(self, path):
        try:
            with open(path, encoding="utf-8") as stream:
                document = json.load(stream)
            if isinstance(document, dict) and type(document.get("version")) is int and document["version"] == self.descriptor.version:
                return document.get("record", _MISSING)
        except (OSError, ValueError):
            pass
        return _MISSING

    async def load_all(self):
        self._assert_open()
        state = {"tables": {table: {} for table in self.descriptor.tables}, "global": None}
        has_documents = False
        for table in self.descriptor.tables:
            directory = os.path.join(self.directory, table)
            if not os.path.isdir(directory):
                continue
            for filename in os.listdir(directory):
                if not filename.endswith(".json"):
                    continue
                has_documents = True
                key = filename[:-5]
                if not _KEY.fullmatch(key):
                    continue
                value = self._read(os.path.join(directory, filename))
                if value is not _MISSING:
                    state["tables"][table][key] = value
        global_path = os.path.join(self.directory, "global.json")
        if self.descriptor.has_global and os.path.lexists(global_path):
            has_documents = True
            value = self._read(global_path)
            if value is not _MISSING:
                state["global"] = value
        if not has_documents:
            try:
                with open(os.path.join(self.root, self.descriptor.name + ".json"), encoding="utf-8") as stream:
                    legacy = json.load(stream)
            except (FileNotFoundError, ValueError):
                return state
            if not isinstance(legacy, dict) or not isinstance(legacy.get("unit"), dict) or legacy["unit"].get("name") != self.descriptor.name:
                return state
            tables = legacy.get("tables")
            if not isinstance(tables, dict):
                return state
            for table, records in tables.items():
                if table not in state["tables"] or not isinstance(records, dict):
                    continue
                for key, value in records.items():
                    await self.put_record(table, key, value)
                    state["tables"][table][key] = value
        return state

    async def _write(self, path, value):
        # No await yields during the atomic filesystem operation: close cannot
        # overtake a write, and the domain serializes all callers above us.
        await write_atomic(path, json.dumps({"version": self.descriptor.version, "record": value},
                                          ensure_ascii=False, indent=2, allow_nan=False) + "\n")

    async def put_record(self, table, key, value):
        await self._write(self._path(table, key), value)

    async def delete_record(self, table, key):
        path = self._path(table, key)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    async def set_global(self, value):
        self._assert_open()
        if not self.descriptor.has_global:
            raise ValueError("unit does not declare a global slot")
        await self._write(os.path.join(self.directory, "global.json"), value)

    async def close(self):
        if not self.closed:
            self.closed = True
            self.on_close()
