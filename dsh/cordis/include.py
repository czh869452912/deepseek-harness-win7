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

        enable_logs_val = self.config.get("enableLogs")
        self.enable_logs = enable_logs_val if enable_logs_val is not None else getattr(parent_tree, "enable_logs", False)
        raw_path = self.config.get("path", "")
        if raw_path.startswith("file://"):
            import urllib.parse
            p = urllib.parse.unquote(urllib.parse.urlparse(raw_path).path)
            if sys.platform == "win32" and p.startswith("/"):
                p = p[1:]
            self.filename = os.path.abspath(os.path.normpath(p))
        else:
            base_dir = self.ctx.base_url or getattr(self.ctx, "baseUrl", None) or os.getcwd()
            if base_dir.startswith("file://"):
                import urllib.parse
                p = urllib.parse.unquote(urllib.parse.urlparse(base_dir).path)
                if sys.platform == "win32" and p.startswith("/"):
                    p = p[1:]
                base_dir = os.path.normpath(p)
            self.filename = os.path.abspath(os.path.join(base_dir, raw_path))

        ext = os.path.splitext(self.filename)[1]
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f'extension "{ext}" not supported')

        self.type = "application/yaml" if ext in (".yaml", ".yml") else "application/json"
        self.readonly = False
        self.content: Optional[str] = None
        self.data: Optional[List[Dict[str, Any]]] = None

        self.base_url = os.path.dirname(self.filename)
        self.baseUrl = self.base_url
        self.ctx.base_url = self.base_url
        self.ctx.baseUrl = self.base_url

        try:
            self._apply_lock = asyncio.Lock()
            self._write_lock = asyncio.Lock()
        except RuntimeError:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._apply_lock = asyncio.Lock()
                self._write_lock = asyncio.Lock()
            except Exception:
                self._apply_lock = None
                self._write_lock = None
        self.pending_write: Optional[List[Dict[str, Any]]] = None
        self._write_task: Optional[Any] = None

        async def _on_update(new_config: Any, *args: Any, **kwargs: Any) -> Any:
            next_fn = args[-1] if args and callable(args[-1]) else kwargs.get("next_fn")
            if not isinstance(new_config, dict) or new_config.get("path") != self.config.get("path"):
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

        ctx.on("internal/update", _on_update)

    def apply_patches(self, data: List[Dict[str, Any]], patches: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        def _warn(msg: str, *args: Any):
            logger_ctx = getattr(self.ctx, "root", self.ctx)
            if hasattr(logger_ctx, "logger"):
                logger_ctx.logger("loader").warn(msg, *args)
            else:
                sys.stderr.write(f"[Cordis Loader Warning] {msg % args if args else msg}\n")

        return apply_entry_patches(data, patches, warn=_warn)

    def check_access(self) -> None:
        if not self.type:
            return
        if not os.access(self.filename, os.W_OK):
            self.readonly = True
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
        Returns dual generator supporting both synchronous (list/iter) and async iteration.
        """
        return _IncludeInitDual(self)


    async def stop(self) -> None:
        """Stop child entries and flush pending writes matching TS stop()."""
        res = self.root.stop()
        if inspect.isawaitable(res):
            await res
        await self.flush_write()

    async def refresh(self) -> None:
        """Re-read backing file and transactionally update child entries under applyQueue lock."""
        async with self._apply_lock:
            candidate = await self.read()
            if not candidate:
                return
            patched = self.apply_patches(candidate["data"], self.config.get("patches"))
            res = self.root.update(patched)
            if inspect.isawaitable(res):
                await res
            self.content = candidate["content"]
            self.data = candidate["data"]
            self.check_access()

    @staticmethod
    def _retryable_write_error(error: Exception) -> bool:
        import errno
        err = getattr(error, "errno", None)
        winerr = getattr(error, "winerror", None)
        if err in (errno.EACCES, errno.EBUSY, getattr(errno, "EPERM", None)):
            return True
        if winerr in (5, 32, 33):  # Access denied, sharing violation, lock violation on Windows
            return True
        return isinstance(error, PermissionError)

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

        for retry in range(WRITE_RETRY_LIMIT + 1):
            try:
                if os.path.exists(self.filename):
                    os.replace(tmp_filename, self.filename)
                else:
                    os.rename(tmp_filename, self.filename)
                return
            except Exception as e:
                if not self._retryable_write_error(e) or retry >= WRITE_RETRY_LIMIT:
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

        for retry in range(WRITE_RETRY_LIMIT + 1):
            try:
                if os.path.exists(self.filename):
                    os.replace(tmp_filename, self.filename)
                else:
                    os.rename(tmp_filename, self.filename)
                return
            except Exception as e:
                if not self._retryable_write_error(e) or retry >= WRITE_RETRY_LIMIT:
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
            if getattr(self, "_write_task", None) and not self._write_task.done():
                self._write_task.cancel()
            async def _run_flush():
                try:
                    await self.flush_write()
                except Exception as e:
                    logger_ctx = getattr(self.ctx, "root", self.ctx)
                    if hasattr(logger_ctx, "logger"):
                        logger_ctx.logger("loader").warn("Failed to write config file %s: %s", self.filename, e)
                    else:
                        sys.stderr.write(f"[Cordis Include Error] Failed to write {self.filename}: {e}\n")
            self._write_task = loop.create_task(_run_flush())
        except RuntimeError:
            self._write_file_sync(config_data)

    async def flush_write(self) -> None:
        config_data = self.pending_write
        self.pending_write = None
        if config_data is None:
            if getattr(self, "_write_task", None) and not self._write_task.done():
                await self._write_task
            return
        async with self._write_lock:
            await self._write_file_async(config_data)


setattr(Include, EntryGroup.key, True)

IncludeService = Include


class _IncludeInitDual:
    def __init__(self, include: "Include"):
        self.include = include
        self.candidate = self._prepare_candidate()
        if self.candidate:
            patched = self.include.apply_patches(self.candidate["data"], self.include.config.get("patches"))
            res = self.include.root.update(patched)
            if inspect.iscoroutine(res):
                try:
                    loop = asyncio.get_running_loop()
                    self.include._update_task = loop.create_task(res)
                    self._update_res = self.include._update_task
                except RuntimeError:
                    self._update_res = res
            elif inspect.isawaitable(res):
                self.include._update_task = res
                self._update_res = res
            else:
                self._update_res = None
        else:
            self._update_res = None

    def _prepare_candidate(self) -> Optional[Dict[str, Any]]:
        try:
            candidate = self.include._read_file(forced=True)
        except ConfigFileError as error:
            if error.stage == "read" and isinstance(error.cause, FileNotFoundError):
                if "initial" in self.include.config and isinstance(self.include.config["initial"], list):
                    self.include._write_file_sync(self.include.config["initial"])
                    candidate = self.include._read_file(forced=True)
                else:
                    raise ConfigFileError("read", self.include.filename, FileNotFoundError(f"config file not found: {self.include.filename}"))
            else:
                raise error
        if candidate:
            self.include.content = candidate["content"]
            self.include.data = candidate["data"]
            self.include.check_access()
        return candidate

    def __iter__(self):
        yield self.include.stop

    async def __aiter__(self):
        yield self.include.stop
        if self._update_res is not None and inspect.isawaitable(self._update_res):
            await self._update_res

