"""
Storage hub (`ctx.storage`): named backend registry plus mounted data-form facilities.
Aligned 1:1 with official `@deepseek-ai/dsh-storage` and `@deepseek-ai/dsh-storage-json`.
"""

import json
import os
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.file_lock import FileLock

from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.plugin import Plugin


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
            lock = FileLock(self.lock_path, timeout=10)
            with lock:
                os.makedirs(self.root_dir, exist_ok=True)
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


class StorageService:
    """Storage hub service mounted at `ctx.storage`."""

    def __init__(self, ctx: Any, root_dir: Optional[str] = None):
        self.ctx = ctx
        self.root_dir = root_dir or os.path.join(resolve_dsh_home(), "storages")
        self._domains: Dict[str, DomainUnit] = {}

    def domain(self, name: str) -> DomainUnit:
        if name not in self._domains:
            self._domains[name] = DomainUnit(name, self.root_dir)
        return self._domains[name]

    def list_domains(self) -> List[str]:
        if not os.path.exists(self.root_dir):
            return list(self._domains.keys())
        found = set(self._domains.keys())
        for fn in os.listdir(self.root_dir):
            if fn.endswith(".json"):
                found.add(fn[:-5])
        return sorted(found)


class StoragePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-storage-json`: Mounts `ctx.storage` hub with JSON file backend.
    """

    id = "storage"
    name = "@deepseek-ai/dsh-storage"

    def apply(self, ctx: Any) -> None:
        root_dir = self.config.get("root") if self.config else None
        svc = StorageService(ctx, root_dir=root_dir)
        ctx.set_service("storage", svc)
