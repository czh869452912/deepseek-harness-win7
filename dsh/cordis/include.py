"""
File-backed include plugin matching reference/vendor/include/src/index.ts.
Provides EntryTree backed by YAML or JSON files with applyQueue serialization,
writeQueue atomic persistence with Win7 retry logic, and ConfigFileError.
"""

import asyncio
import copy
import inspect
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import yaml

from dsh.cordis.context import Context
from dsh.cordis.loader import EntryTree, EntryGroup, Entry, apply_entry_patches, sort_keys, js_constructor
from dsh.cordis.service import Service, ServiceSymbols


class ConfigFileError(Exception):
    """Error raised when reading, parsing, or validating a config file."""

    def __init__(self, stage: str, path: str, cause: Optional[Exception] = None):
        self.stage = stage
        self.path = path
        self.cause = cause
        msg = f"failed to {stage} config file {path}"
        if cause:
            msg += f": {cause}"
        super().__init__(msg)
        self.name = "ConfigFileError"


WRITE_RETRY_LIMIT = 10
WRITE_RETRY_DELAY_SEC = 0.05

SUPPORTED_EXTENSIONS = {".json", ".yaml", ".yml"}


class Include(EntryTree, Service):
    """
    Loader entry tree backed by a YAML or JSON file.
    Matching reference/vendor/include/src/index.ts.
    """

    inject = ["loader"]
    is_tree_carrier = True
    entry_group_key = True

    def __init__(self, ctx: Context, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.config: Dict[str, Any] = dict(cfg)
        Service.__init__(self, ctx, name="include", allow_replace=True)
        EntryTree.__init__(self, ctx)

        parent_tree = None
        fiber_entry = getattr(getattr(ctx, "fiber", None), "entry", None)
        if fiber_entry and getattr(fiber_entry, "parent", None):
            parent_tree = getattr(fiber_entry.parent, "tree", None)

        self.enable_logs = self.config.get("enableLogs", getattr(parent_tree, "enable_logs", False))
        raw_path = self.config.get("path", "")
        base_dir = self.ctx.base_url or os.getcwd()
        self.filename = os.path.abspath(os.path.join(base_dir, raw_path))

        ext = os.path.splitext(self.filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f'extension "{ext}" not supported')

        self.type = "application/yaml" if ext in (".yaml", ".yml") else "application/json"
        self.readonly = False
        self.content: Optional[str] = None
        self.data: Optional[List[Dict[str, Any]]] = None

        self.ctx.base_url = os.path.dirname(self.filename)

        self._apply_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self.pending_write: Optional[List[Dict[str, Any]]] = None
        self._write_task: Optional[asyncio.TimerHandle] = None

        async def _on_update(new_config: Any, *args: Any, **kwargs: Any) -> Any:
            next_fn = args[-1] if args and callable(args[-1]) else kwargs.get("next_fn")
            if isinstance(new_config, dict) and new_config.get("path") != self.config.get("path"):
                if next_fn and callable(next_fn):
                    res = next_fn()
                    if inspect.isawaitable(res):
                        return await res
                    return res
                return None

            async with self._apply_lock:
                if self.data is not None:
                    patches = new_config.get("patches") if isinstance(new_config, dict) else None
                    patched_data = self.apply_patches(self.data, patches)
                    res = self.root.update(patched_data)
                    if inspect.isawaitable(res):
                        await res
                    self.config = dict(new_config)
            # Short-circuit waterfall matching TS behavior
            return None

        ctx.on("internal/update", _on_update, global_listener=True)

    def apply_patches(self, data: List[Dict[str, Any]], patches: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        def _warn(msg: str, *args: Any):
            if hasattr(self.ctx, "logger"):
                self.ctx.logger("include").warn(msg, *args)
            else:
                sys.stderr.write(f"[Cordis Include Warning] {msg % args if args else msg}\n")

        return apply_entry_patches(data, patches, warn=_warn)

    def check_access(self) -> None:
        if not self.type:
            return
        if os.path.exists(self.filename) and not os.access(self.filename, os.W_OK):
            self.readonly = True

    def _read_file(self, forced: bool = False) -> Optional[Dict[str, Any]]:
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as error:
            raise ConfigFileError("read", self.filename, error)

        if not forced and self.content == content:
            return None

        try:
            if self.type == "application/yaml":
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
        except Exception as error:
            raise ConfigFileError("parse", self.filename, error)

        if not isinstance(data, list):
            raise ConfigFileError("validate", self.filename, TypeError("config file must be a top-level array"))

        return {"content": content, "data": data}

    async def read(self, forced: bool = False) -> Optional[Dict[str, Any]]:
        """Read and parse the backing config file with stage-specific error classification."""
        return self._read_file(forced=forced)

    def init(self) -> Any:
        """
        Service.init lifecycle hook matching TS async* [Service.init]().
        Yields a cleanup disposer to register with Fiber effect, then applies initial config.
        """
        candidate = None
        try:
            candidate = self._read_file(forced=True)
        except ConfigFileError as error:
            if error.stage == "read" and isinstance(error.cause, FileNotFoundError):
                if "initial" in self.config and isinstance(self.config["initial"], list):
                    self._write_file_sync(self.config["initial"])
                    candidate = self._read_file(forced=True)
                else:
                    raise ConfigFileError("read", self.filename, FileNotFoundError(f"config file not found: {self.filename}"))
            else:
                raise error

        if candidate:
            patched = self.apply_patches(candidate["data"], self.config.get("patches"))
            self.root.update(patched)
            self.content = candidate["content"]
            self.data = candidate["data"]
            self.check_access()

        # Register teardown disposer
        def _teardown():
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.stop())
            except RuntimeError:
                asyncio.run(self.stop())

        yield _teardown

    async def stop(self) -> None:
        """Stop child entries and flush pending writes."""
        self.root.stop()
        await self.flush_write()

    async def refresh(self) -> None:
        """Re-read backing file and transactionally update child entries under applyQueue lock."""
        async with self._apply_lock:
            candidate = await self.read()
            if not candidate:
                return
            patched = self.apply_patches(candidate["data"], self.config.get("patches"))
            self.root.update(patched)
            self.content = candidate["content"]
            self.data = candidate["data"]
            self.check_access()

    def _write_file_sync(self, config_data: List[Dict[str, Any]]) -> None:
        """Synchronously write config data."""
        if self.readonly:
            raise PermissionError(f"cannot overwrite readonly config: {self.filename}")

        tmp_filename = self.filename + ".tmp"
        if self.type == "application/yaml":
            self.content = yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True)
        else:
            self.content = json.dumps(config_data, indent=2, ensure_ascii=False)

        with open(tmp_filename, "w", encoding="utf-8") as f:
            f.write(self.content)

        for retry in range(WRITE_RETRY_LIMIT):
            try:
                if os.path.exists(self.filename):
                    os.replace(tmp_filename, self.filename)
                else:
                    os.rename(tmp_filename, self.filename)
                return
            except (OSError, PermissionError):
                if retry >= WRITE_RETRY_LIMIT - 1:
                    raise
                time.sleep(WRITE_RETRY_DELAY_SEC * (retry + 1))

    async def _write_file_async(self, config_data: List[Dict[str, Any]]) -> None:
        """Asynchronously write config data with retry on Win7 lock contention."""
        if self.readonly:
            raise PermissionError(f"cannot overwrite readonly config: {self.filename}")

        tmp_filename = self.filename + ".tmp"
        if self.type == "application/yaml":
            self.content = yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True)
        else:
            self.content = json.dumps(config_data, indent=2, ensure_ascii=False)

        with open(tmp_filename, "w", encoding="utf-8") as f:
            f.write(self.content)

        for retry in range(WRITE_RETRY_LIMIT):
            try:
                if os.path.exists(self.filename):
                    os.replace(tmp_filename, self.filename)
                else:
                    os.rename(tmp_filename, self.filename)
                return
            except (OSError, PermissionError):
                if retry >= WRITE_RETRY_LIMIT - 1:
                    raise
                await asyncio.sleep(WRITE_RETRY_DELAY_SEC * (retry + 1))

    def write(self) -> None:
        """Schedule a write of current root entry data."""
        if hasattr(self.ctx, "emit"):
            self.ctx.emit("loader/config-update")
        self.write_file(self.root.data)

    def write_file(self, config_data: List[Dict[str, Any]]) -> None:
        self.pending_write = config_data
        try:
            loop = asyncio.get_running_loop()
            if self._write_task:
                self._write_task.cancel()
            self._write_task = loop.call_soon(lambda: asyncio.create_task(self.flush_write()))
        except RuntimeError:
            self._write_file_sync(config_data)

    async def flush_write(self) -> None:
        config_data = self.pending_write
        self.pending_write = None
        if config_data is None:
            return
        async with self._write_lock:
            try:
                await self._write_file_async(config_data)
            except Exception as e:
                if hasattr(self.ctx, "logger"):
                    self.ctx.logger("include").warn("Failed to write config file %s: %s", self.filename, e)
                else:
                    sys.stderr.write(f"[Cordis Include Error] Failed to write {self.filename}: {e}\n")


IncludeService = Include
