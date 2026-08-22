"""
SQLite storage backend for the storage hub.
Aligned 1:1 with official `@deepseek-ai/dsh-storage-sqlite`.
"""

import json
import os
import sqlite3
from typing import Any, Callable, Dict, Optional
from dsh.storage.backend import UNIT_NAME_RE, KvFacet, KvUnit, KvUnitDescriptor, StorageBackend
from dsh.storage.error import StorageError

STORAGE_SQLITE_SCHEMA_VERSION = 1


def record_table_name(unit: str, table: str) -> str:
    return f"u_{unit}_{table}"


recordTableName = record_table_name


class SqliteKvUnit(KvUnit):
    """The SQLite KvUnit implementation."""

    def __init__(
        self,
        db: sqlite3.Connection,
        descriptor: KvUnitDescriptor,
        on_close: Callable[[], None],
    ):
        self.db = db
        self.descriptor = descriptor
        self._on_close = on_close
        self.closed = False

    async def load_all(self) -> Dict[str, Any]:
        if self.closed:
            raise StorageError("closed", f"kv unit '{self.descriptor.name}' is closed")
        tables_res: Dict[str, Dict[str, Any]] = {}
        for tbl in self.descriptor.tables:
            phys = record_table_name(self.descriptor.name, tbl)
            cursor = self.db.execute(f'SELECT key, value FROM "{phys}"')
            recs: Dict[str, Any] = {}
            for key, val_text in cursor.fetchall():
                try:
                    recs[key] = json.loads(val_text)
                except Exception as e:
                    raise StorageError(
                        "malformed-medium",
                        f"kv unit '{self.descriptor.name}' holds unparsable JSON at table '{tbl}' key '{key}'",
                        cause=e,
                    )
            tables_res[tbl] = recs

        global_val = None
        if self.descriptor.has_global:
            cursor = self.db.execute("SELECT value FROM unit_globals WHERE unit = ?", (self.descriptor.name,))
            row = cursor.fetchone()
            if row is not None:
                try:
                    global_val = json.loads(row[0])
                except Exception as e:
                    raise StorageError(
                        "malformed-medium",
                        f"kv unit '{self.descriptor.name}' holds unparsable JSON at global slot",
                        cause=e,
                    )

        return {"tables": tables_res, "global": global_val}

    async def put_record(self, table: str, key: str, value: Any) -> None:
        if self.closed:
            raise StorageError("closed", f"kv unit '{self.descriptor.name}' is closed")
        if table not in self.descriptor.tables:
            raise ValueError(f"kv unit '{self.descriptor.name}' declared no table '{table}'")
        phys = record_table_name(self.descriptor.name, table)
        val_text = json.dumps(value)
        self.db.execute(
            f'INSERT INTO "{phys}" (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (key, val_text),
        )
        self.db.commit()

    async def delete_record(self, table: str, key: str) -> None:
        if self.closed:
            raise StorageError("closed", f"kv unit '{self.descriptor.name}' is closed")
        if table not in self.descriptor.tables:
            raise ValueError(f"kv unit '{self.descriptor.name}' declared no table '{table}'")
        phys = record_table_name(self.descriptor.name, table)
        self.db.execute(f'DELETE FROM "{phys}" WHERE key = ?', (key,))
        self.db.commit()

    async def set_global(self, value: Any) -> None:
        if self.closed:
            raise StorageError("closed", f"kv unit '{self.descriptor.name}' is closed")
        if not self.descriptor.has_global:
            raise ValueError(f"kv unit '{self.descriptor.name}' declared no global slot")
        val_text = json.dumps(value)
        self.db.execute(
            "INSERT INTO unit_globals (unit, value) VALUES (?, ?) ON CONFLICT(unit) DO UPDATE SET value = excluded.value",
            (self.descriptor.name, val_text),
        )
        self.db.commit()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._on_close()


class SqliteStorageBackend(StorageBackend):
    """The SQLite StorageBackend."""

    def __init__(self, config: Dict[str, Any]):
        path = config.get("path", ":memory:")
        journal_mode = str(config.get("journal_mode", config.get("journalMode", "wal"))).upper()
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            try:
                self.db.execute(f"PRAGMA journal_mode = {journal_mode}")
            except Exception:
                pass
        cursor = self.db.execute("PRAGMA user_version")
        row = cursor.fetchone()
        on_disk = row[0] if row else 0
        if on_disk != 0 and on_disk != STORAGE_SQLITE_SCHEMA_VERSION:
            raise StorageError(
                "version-mismatch",
                f'storage database at "{path}" has schema version {on_disk}, incompatible with this build ({STORAGE_SQLITE_SCHEMA_VERSION})',
            )
        self.db.execute("CREATE TABLE IF NOT EXISTS units (name TEXT PRIMARY KEY, version INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS unit_globals (unit TEXT PRIMARY KEY REFERENCES units(name), value TEXT NOT NULL)")
        if on_disk == 0:
            self.db.execute(f"PRAGMA user_version = {STORAGE_SQLITE_SCHEMA_VERSION}")
        self.db.commit()

        self._units: Dict[str, SqliteKvUnit] = {}
        self.closed = False
        self.kv = self._KvFacetImpl(self)

    class _KvFacetImpl(KvFacet):
        def __init__(self, outer: "SqliteStorageBackend"):
            self.outer = outer

        async def open(self, descriptor: KvUnitDescriptor) -> KvUnit:
            if self.outer.closed:
                raise StorageError("closed", "sqlite storage backend is closed")
            if not UNIT_NAME_RE.match(descriptor.name):
                raise ValueError(f"kv unit name '{descriptor.name}' violates {UNIT_NAME_RE.pattern}")
            for tbl in descriptor.tables:
                if not UNIT_NAME_RE.match(tbl):
                    raise ValueError(f"kv table name '{tbl}' in unit '{descriptor.name}' violates {UNIT_NAME_RE.pattern}")
            if descriptor.name in self.outer._units:
                raise ValueError(f"kv unit '{descriptor.name}' is already open (double-open is a caller bug)")

            cursor = self.outer.db.execute("SELECT version FROM units WHERE name = ?", (descriptor.name,))
            row = cursor.fetchone()
            if row is None:
                self.outer.db.execute("INSERT INTO units (name, version) VALUES (?, ?)", (descriptor.name, descriptor.version))
                self.outer.db.commit()
            elif row[0] != descriptor.version:
                raise StorageError(
                    "version-mismatch",
                    f"kv unit '{descriptor.name}' is stamped version {row[0]} on the medium, incompatible with descriptor version {descriptor.version}",
                )

            for tbl in descriptor.tables:
                phys = record_table_name(descriptor.name, tbl)
                self.outer.db.execute(f'CREATE TABLE IF NOT EXISTS "{phys}" (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self.outer.db.commit()

            def on_close():
                self.outer._units.pop(descriptor.name, None)

            unit = SqliteKvUnit(self.outer.db, descriptor, on_close)
            self.outer._units[descriptor.name] = unit
            return unit

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for unit in list(self._units.values()):
            await unit.close()
        self.db.close()
