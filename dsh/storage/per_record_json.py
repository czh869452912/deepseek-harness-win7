"""Version-stamped per-record JSON medium; live memory belongs to the domain."""
import asyncio
import json
import os
import re
import datetime

from dsh.storage.backend import KvUnit
from dsh.storage.error import StorageError
from dsh.storage.storage_json import write_atomic
from dsh.cordis.errors import AggregateError

_MISSING = object()
_KEY = re.compile(r"^[a-zA-Z0-9_-]+$")


async def rename_document(source,target):
    await asyncio.get_running_loop().run_in_executor(None,os.replace,source,target)


async def remove_document(path):
    try:await asyncio.get_running_loop().run_in_executor(None,os.remove,path)
    except FileNotFoundError:pass


async def fsync_directory(path):
    if os.name=='nt':return
    def sync():
        fd=os.open(path,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    await asyncio.get_running_loop().run_in_executor(None,sync)


class PerRecordJsonUnit(KvUnit):
    def __init__(self, descriptor, root, on_close):
        self.descriptor, self.root, self.on_close = descriptor, root, on_close
        self.directory = os.path.join(root, descriptor.name)
        self.closed = False
        self.unusable = None
        self.in_flight = set()
        self.closing = None

    def _assert_open(self):
        if self.closed:
            raise StorageError("closed", "unit '{}' is closed".format(self.descriptor.name))
        if self.unusable is not None:raise self.unusable

    async def _tracked(self,operation):
        task=asyncio.create_task(operation);self.in_flight.add(task)
        def settled(future):
            self.in_flight.discard(future)
            if not future.cancelled():future.exception()
        task.add_done_callback(settled)
        return await asyncio.shield(task)

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
            if isinstance(document, dict) and type(document.get("version")) in (int,float) and document["version"] in [self.descriptor.version] + self.descriptor.compatible_versions:
                return document.get("record", _MISSING)
        except (OSError, ValueError):
            pass
        return _MISSING

    async def backup_record(self, table, key):
        path = self._path(table, key)
        moved = path + '.bak.' + datetime.datetime.now().strftime('%Y%m%d%H%M')
        await self._tracked(rename_document(path,moved))
        return moved

    async def backupRecord(self,table,key):return await self.backup_record(table,key)

    async def load_all(self):
        self._assert_open()
        state = {"tables": {table: {} for table in self.descriptor.tables}, "global": None}
        has_documents = False
        for table in self.descriptor.tables:
            directory = os.path.join(self.directory, table)
            if not os.path.isdir(directory):
                continue
            has_documents = True
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
            if not isinstance(legacy, dict) or not isinstance(legacy.get("unit"), dict) or legacy["unit"].get("name") != self.descriptor.name or type(legacy['unit'].get('version')) not in (int,float) or legacy['unit'].get('version') not in [self.descriptor.version] + self.descriptor.compatible_versions:
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
        # The domain serializes callers, including bounded Windows replace
        # retries and close, above this medium.
        await write_atomic(path, json.dumps({"version": self.descriptor.version, "record": value},
                                          ensure_ascii=False, indent=2, allow_nan=False) + "\n")

    async def put_record(self, table, key, value):
        await self._tracked(self._write(self._path(table, key), value))

    async def delete_record(self, table, key):
        await self.delete_records(table,[key])

    async def delete_records(self,table,keys):
        self._assert_open()
        if table not in self.descriptor.tables:raise ValueError('undeclared table: '+table)
        unique=list(dict.fromkeys(keys));paths=[self._path(table,key) for key in unique]
        await self._tracked(self._remove_documents(os.path.join(self.directory,table),paths))

    async def _remove_documents(self,directory,paths):
        staged=[]
        try:
            for path in paths:
                moved=path+'.deleting'
                try:await rename_document(path,moved)
                except FileNotFoundError:continue
                staged.append((path,moved))
            if staged:await fsync_directory(directory)
        except BaseException as error:
            failures=[]
            for path,moved in staged:
                try:await rename_document(moved,path)
                except BaseException as restore_error:failures.append(restore_error)
            if staged:
                try:await fsync_directory(directory)
                except BaseException as restore_error:failures.append(restore_error)
            if not failures:raise
            self.unusable=StorageError('unknown-state',"unit '{}' could not restore a failed batch delete; its state is unknown".format(self.descriptor.name),cause=AggregateError([error]+failures,'batch delete failed and restoration failed'))
            raise self.unusable from error
        await asyncio.gather(*(remove_document(moved) for _,moved in staged),return_exceptions=True)

    async def set_global(self, value):
        self._assert_open()
        if not self.descriptor.has_global:
            raise ValueError("unit does not declare a global slot")
        await self._tracked(self._write(os.path.join(self.directory, "global.json"), value))

    async def close(self):
        if self.closing is None:
            self.closed=True
            async def drain():
                await asyncio.gather(*list(self.in_flight),return_exceptions=True)
                self.on_close()
            self.closing=asyncio.create_task(drain())
        await asyncio.shield(self.closing)
