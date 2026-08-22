"""
Named backend registry of the storage hub.
Aligned 1:1 with official `@deepseek-ai/dsh-storage/src/registry`.
"""

from typing import Callable, Dict, List
from dsh.storage.backend import StorageBackend
from dsh.storage.error import StorageError


class BackendRegistry:
    """Mutable name -> backend table."""

    def __init__(self):
        self._backends: Dict[str, StorageBackend] = {}

    def register(self, name: str, backend: StorageBackend) -> Callable[[], None]:
        """
        Register a named backend. Registration returns a disposer callback.
        """
        if name in self._backends:
            raise StorageError("duplicate-backend", f"storage backend '{name}' is already registered")
        self._backends[name] = backend

        def unregister():
            if self._backends.get(name) is backend:
                del self._backends[name]

        return unregister

    def get(self, name: str) -> StorageBackend:
        """Resolve a backend by name."""
        backend = self._backends.get(name)
        if not backend:
            reg_names = ", ".join(self._backends.keys()) or "none"
            raise StorageError(
                "backend-not-found",
                f"storage backend '{name}' is not registered (registered: {reg_names})",
            )
        return backend

    def names(self) -> List[str]:
        """Registered backend names."""
        return list(self._backends.keys())
