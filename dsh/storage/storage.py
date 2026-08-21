"""
Storage hub (`ctx.storage`): named backend registry plus mounted data-form facilities.
Aligned 1:1 with official `@deepseek-ai/dsh-storage` and `@deepseek-ai/dsh-storage-json`.
"""

import json
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.plugin import Plugin


def get_dsh_home() -> str:
    return os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")


class DomainUnit:
    """A named schema-validated KV unit backed by a JSON file."""

    def __init__(self, name: str, root_dir: str):
        self.name = name
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)
        self.file_path = os.path.join(self.root_dir, f"{name}.json")
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        # Atomic write
        temp_fd, temp_path = tempfile.mkstemp(dir=self.root_dir, prefix=f"{self.name}_", suffix=".tmp")
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            # Atomic replace on Windows (Python 3.8 os.replace handles overwrite atomically)
            os.replace(temp_path, self.file_path)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
            raise

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


class StorageService:
    """Storage hub service mounted at `ctx.storage`."""

    def __init__(self, ctx: Any, root_dir: Optional[str] = None):
        self.ctx = ctx
        self.root_dir = root_dir or os.path.join(get_dsh_home(), "storages")
        self._domains: Dict[str, DomainUnit] = {}

    def domain(self, name: str) -> DomainUnit:
        if name not in self._domains:
            self._domains[name] = DomainUnit(name, self.root_dir)
        return self._domains[name]


class StoragePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-storage-json`: Mounts `ctx.storage` hub with JSON file backend.
    """

    id = "storage"
    name = "@deepseek-ai/dsh-storage"

    def apply(self, ctx: Any) -> None:
        root_dir = self.config.get("root")
        svc = StorageService(ctx, root_dir=root_dir)
        ctx.set_service("storage", svc)
