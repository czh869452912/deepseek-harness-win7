"""
Runtime of one open domain and the DomainFacility.
Aligned 1:1 with official `@deepseek-ai/dsh-storage-domain/src/domain` and `src/index`.
"""

import asyncio
import json
import os
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.file_lock import FileLock
from dsh.storage.backend import KvUnit, StorageBackend
from dsh.storage.domain_error import DomainError
from dsh.storage.domain_events import DomainChanged
from dsh.storage.domain_spec import DomainSpec, descriptor_of


class DomainGlobal:
    """Handle on a domain's global singleton."""

    def __init__(self, get_fn: Callable[[], Any], set_fn: Callable[[Any], Any]):
        self._get_fn = get_fn
        self._set_fn = set_fn

    def get(self) -> Any:
        return self._get_fn()

    async def set(self, value: Any) -> None:
        await self._set_fn(value)


class KvTable:
    """Handle on one declared table."""

    def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError

    def entries(self) -> List[Tuple[str, Any]]:
        raise NotImplementedError

    def items(self) -> List[Tuple[str, Any]]:
        return self.entries()

    def keys(self) -> List[str]:
        raise NotImplementedError

    @property
    def size(self) -> int:
        raise NotImplementedError

    def __len__(self) -> int:
        return self.size

    async def put(self, key: str, value: Any) -> None:
        raise NotImplementedError

    async def delete(self, key: str) -> bool:
        raise NotImplementedError

    async def update(self, key: str, fn: Callable[[Any], Any]) -> Any:
        raise NotImplementedError


class KvTableImpl(KvTable):
    """In-memory record map bound to domain write chain."""

    def __init__(self, host: Any, table_name: str, records: Dict[str, Any]):
        self._host = host
        self._table_name = table_name
        self._records = records

    def get(self, key: str) -> Optional[Any]:
        self._host.assert_readable()
        return self._records.get(key)

    def entries(self) -> List[Tuple[str, Any]]:
        self._host.assert_readable()
        return list(self._records.items())

    def keys(self) -> List[str]:
        self._host.assert_readable()
        return list(self._records.keys())

    @property
    def size(self) -> int:
        self._host.assert_readable()
        return len(self._records)

    async def put(self, key: str, value: Any) -> None:
        async def _job():
            await self._host.unit.put_record(self._table_name, key, value)
            self._records[key] = value
            self._host.emit_changed(DomainChanged(self._host.domain_name, self._table_name, key, "put", value))

        await self._host.enqueue(_job)

    async def delete(self, key: str) -> bool:
        res_box = [False]

        async def _job():
            if key not in self._records:
                res_box[0] = False
                return
            await self._host.unit.delete_record(self._table_name, key)
            del self._records[key]
            res_box[0] = True
            self._host.emit_changed(DomainChanged(self._host.domain_name, self._table_name, key, "deleted"))

        await self._host.enqueue(_job)
        return res_box[0]

    async def update(self, key: str, fn: Callable[[Any], Any]) -> Any:
        res_box = [None]

        async def _job():
            if key not in self._records:
                raise DomainError(
                    "missing-key",
                    f"domain '{self._host.domain_name}' table '{self._table_name}' has no record '{key}' to update",
                )
            next_val = fn(self._records[key])
            await self._host.unit.put_record(self._table_name, key, next_val)
            self._records[key] = next_val
            res_box[0] = next_val
            self._host.emit_changed(DomainChanged(self._host.domain_name, self._table_name, key, "put", next_val))

        await self._host.enqueue(_job)
        return res_box[0]


class DomainImpl:
    """Single domain implementation behind Domain interface."""

    def __init__(
        self,
        ctx: Any,
        spec: DomainSpec,
        unit: KvUnit,
        records: Dict[str, Dict[str, Any]],
        global_value: Any,
        on_closed: Callable[[], None],
    ):
        self.ctx = ctx
        self.name = spec.name
        self.unit = unit
        self.domain_name = spec.name
        self._on_closed = on_closed
        self._tables: Dict[str, KvTableImpl] = {}
        self._global_value = global_value
        self._global_handle: Optional[DomainGlobal] = None

        self._operation_tail: Optional[asyncio.Future] = None
        self._disposing = False
        self._closed = False

        for tbl_name, recs in records.items():
            self._tables[tbl_name] = KvTableImpl(self, tbl_name, recs)

        if spec.global_spec is not None or getattr(spec, "global_", None) is not None:
            self._global_handle = DomainGlobal(
                get_fn=self._get_global,
                set_fn=self._set_global,
            )

    def assert_readable(self) -> None:
        if self._closed:
            raise DomainError("closed", f"domain '{self.name}' is closed")

    def _get_global(self) -> Any:
        self.assert_readable()
        return self._global_value

    async def _set_global(self, value: Any) -> None:
        async def _job():
            await self.unit.set_global(value)
            self._global_value = value
            self.emit_changed(DomainChanged(self.name, "", "", "put", value))

        await self.enqueue(_job)

    @property
    def global_handle(self) -> DomainGlobal:
        if self._global_handle is None:
            raise ValueError(f"domain '{self.name}' declares no global")
        return self._global_handle

    @property
    def global_(self) -> DomainGlobal:
        return self.global_handle

    def table(self, name: str) -> KvTableImpl:
        tbl = self._tables.get(name)
        if tbl is None:
            raise ValueError(f"domain '{self.name}' declares no table '{name}'")
        return tbl

    def emit_changed(self, change: DomainChanged) -> None:
        if self.ctx and hasattr(self.ctx, "emit"):
            try:
                self.ctx.emit("domain/changed", change)
            except Exception as e:
                if hasattr(self.ctx, "logger"):
                    self.ctx.logger.warn(f"domain '{self.name}': domain/changed listener failed: {e}")

    async def enqueue(self, job: Callable[[], Any]) -> Any:
        if self._disposing:
            raise DomainError("closed", f"domain '{self.name}' is closed")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        fut = loop.create_future()
        prev_tail = self._operation_tail

        async def runner():
            if prev_tail:
                try:
                    await prev_tail
                except Exception:
                    pass
            try:
                res = await job()
                if not fut.done():
                    fut.set_result(res)
            except Exception as ex:
                if not fut.done():
                    fut.set_exception(ex)

        task = asyncio.create_task(runner())
        self._operation_tail = task
        return await fut

    async def close(self) -> None:
        if self._closed:
            return
        self._disposing = True
        if self._operation_tail:
            try:
                await self._operation_tail
            except Exception:
                pass
        await self.unit.close()
        self._closed = True
        if self._on_closed:
            self._on_closed()


class DomainUnit:
    """A named schema-validated KV unit backed by a JSON file."""

    def __init__(self, name: str, root_dir: str):
        self.name = name
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)
        self.file_path = os.path.join(self.root_dir, f"{name}.json")
        self.lock_path = self.file_path + ".lock"
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            os.makedirs(self.root_dir, exist_ok=True)
            if os.path.exists(self.file_path):
                lock = FileLock(self.lock_path, timeout=10)
                try:
                    with lock:
                        with open(self.file_path, "r", encoding="utf-8") as f:
                            text = f.read()
                            self._data = json.loads(text) if text.strip() else {}
                except Exception:
                    self._data = {}
            else:
                self._data = {}

    def _save(self) -> None:
        with self._lock:
            os.makedirs(self.root_dir, exist_ok=True)
            lock = FileLock(self.lock_path, timeout=10)
            with lock:
                temp_fd, temp_path = tempfile.mkstemp(dir=self.root_dir, prefix=f"{self.name}_", suffix=".tmp")
                try:
                    with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                        json.dump(self._data, f, ensure_ascii=False, indent=2)
                        f.write("\n")
                    os.replace(temp_path, self.file_path)
                finally:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> bool:
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False

    def list_keys(self) -> List[str]:
        return list(self._data.keys())

    def entries(self) -> Dict[str, Any]:
        return dict(self._data)

    def clear(self) -> None:
        self._data.clear()
        self._save()


class DomainFacility:
    """The mounted domain facility."""

    def __init__(self, ctx: Any, config: Optional[Dict[str, Any]] = None, root_dir: Optional[str] = None):
        self.ctx = ctx
        self.config = config or {"backend": "json", "routes": {}}
        self.root_dir = root_dir or os.path.join(resolve_dsh_home(), "storages")
        self._domains: Dict[str, DomainImpl] = {}
        self._reserved: Set[str] = set()
        self._simple_units: Dict[str, DomainUnit] = {}

    async def open(self, spec: DomainSpec) -> DomainImpl:
        if spec.name in self._reserved:
            raise DomainError("already-open", f"domain '{spec.name}' is already open")
        self._reserved.add(spec.name)

        try:
            routes = self.config.get("routes", {})
            backend_name = routes.get(spec.name, self.config.get("backend", "json"))
            storage_hub = self.ctx.get("storage") if self.ctx and hasattr(self.ctx, "get") else None
            if not storage_hub or not hasattr(storage_hub, "backend"):
                from dsh.storage.storage_json import JsonStorageBackend
                backend: StorageBackend = JsonStorageBackend(self.root_dir)
            else:
                backend = storage_hub.backend.get(backend_name)

            if not backend.kv:
                raise DomainError("facet-unsupported", f"backend '{backend_name}' routed for domain '{spec.name}' has no kv facet")

            desc = descriptor_of(spec)
            unit = await backend.kv.open(desc)

            try:
                snapshot = await unit.load_all()
                tables_records: Dict[str, Dict[str, Any]] = {}
                for tbl_name, tbl_spec in spec.tables.items():
                    recs: Dict[str, Any] = {}
                    raw_map = snapshot["tables"].get(tbl_name, {})
                    for k, raw in raw_map.items():
                        try:
                            recs[k] = tbl_spec.value_schema.parse(raw)
                        except Exception as e:
                            raise DomainError(
                                "invalid-record",
                                f"domain '{spec.name}': stored record '{k}' in table '{tbl_name}' does not match its schema",
                                detail={"table": tbl_name, "key": k},
                                cause=e,
                            )
                    tables_records[tbl_name] = recs

                global_val = None
                if spec.global_spec is not None:
                    raw_g = snapshot.get("global")
                    if raw_g is None:
                        global_val = spec.global_spec.initial
                    else:
                        try:
                            global_val = spec.global_spec.schema.parse(raw_g)
                        except Exception as e:
                            raise DomainError(
                                "invalid-record",
                                f"domain '{spec.name}': stored global does not match its schema",
                                detail={"table": "", "key": ""},
                                cause=e,
                            )

                def on_closed():
                    self._domains.pop(spec.name, None)
                    self._reserved.discard(spec.name)

                domain = DomainImpl(self.ctx, spec, unit, tables_records, global_val, on_closed)
                self._domains[spec.name] = domain
                return domain
            except Exception as e:
                await unit.close()
                raise e
        except Exception as e:
            self._reserved.discard(spec.name)
            raise e

    def get(self, name: str) -> Optional[DomainImpl]:
        return self._domains.get(name)

    async def close_all(self) -> None:
        for domain in list(self._domains.values()):
            await domain.close()

    def __call__(self, name_or_spec: Any) -> Any:
        if isinstance(name_or_spec, str):
            if name_or_spec not in self._simple_units:
                self._simple_units[name_or_spec] = DomainUnit(name_or_spec, self.root_dir)
            return self._simple_units[name_or_spec]
        elif isinstance(name_or_spec, DomainSpec):
            return self.open(name_or_spec)
        raise ValueError(f"invalid argument to domain: {name_or_spec}")
