"""
Storage hub (`ctx.storage`): a named backend registry plus mounted data-form facilities.
Aligned 1:1 with official `@deepseek-ai/dsh-storage/src/index`.
"""

import os
from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.plugin import Plugin
from dsh.storage.backend import StorageBackend
from dsh.storage.error import StorageError
from dsh.storage.registry import BackendRegistry


class Storage:
    """
    The storage hub service.
    Backends register under `backend`; data forms mount under `forms` and are reached as `ctx.storage.<form>`.
    """

    def __init__(self, ctx: Any = None, root_dir: Optional[str] = None):
        self.ctx = ctx
        if self.ctx and hasattr(self.ctx, "set_service"):
            self.ctx.set_service("storage", self)

        self.backend = BackendRegistry()
        self._forms: Dict[str, Any] = {}
        self.root_dir = root_dir or os.path.join(resolve_dsh_home(), "storages")

        # Register default JSON backend
        from dsh.storage.storage_json import JsonStorageBackend
        self.backend.register("json", JsonStorageBackend(self.root_dir))

        # Mount default DomainFacility
        from dsh.storage.domain_impl import DomainFacility
        self._facility = DomainFacility(self.ctx, {"backend": "json", "routes": {}}, root_dir=self.root_dir)
        self.mount("domain", self._facility)

        if self.ctx and hasattr(self.ctx, "provide"):
            self.ctx.provide("storageDomain", self._facility)

    def mount(self, form_name: str, facility: Any) -> Callable[[], None]:
        """Mount a data-form facility on the hub."""
        if form_name in self._forms:
            raise StorageError("duplicate-mount", f"storage form '{form_name}' is already mounted")
        self._forms[form_name] = facility
        if form_name == "domain":
            self._facility = facility
            if hasattr(facility, "root_dir"):
                facility.root_dir = self.root_dir

        def unmount():
            if self._forms.get(form_name) is facility:
                del self._forms[form_name]

        return unmount

    def form(self, form_name: str) -> Any:
        """Resolve a mounted data form."""
        if form_name not in self._forms:
            raise StorageError("form-not-mounted", f"storage form '{form_name}' is not mounted")
        return self._forms[form_name]

    @property
    def domain(self) -> Any:
        """Domain data form."""
        return self.form("domain")

    def list_domains(self) -> List[str]:
        """Diagnostic / legacy listing of available domain unit files under root_dir."""
        if not os.path.exists(self.root_dir):
            return []
        found = set()
        files = os.listdir(self.root_dir)
        for fn in files:
            if fn.endswith(".json"):
                found.add(fn[:-5])
        return sorted(found)


# Alias for legacy compatibility
StorageService = Storage


class StoragePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-storage`: Mounts `ctx.storage` hub.
    """

    id = "storage"
    name = "@deepseek-ai/dsh-storage"

    def apply(self, ctx: Any) -> None:
        root_dir = self.config.get("root") if self.config else None
        svc = Storage(ctx, root_dir=root_dir)
        ctx.set_service("storage", svc)
        ctx.provide("storageDomain", svc.domain)
