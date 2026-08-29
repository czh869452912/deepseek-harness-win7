"""
Invariant Registry and InvariantError matching reference @deepseek-ai/dsh-invariants.
"""

import re
from typing import Any, Callable, Dict, List, Optional, Set

from dsh.cordis.context import Context
from dsh.cordis.service import Service


class InvariantError(Exception):
    code = "INVARIANT"

    def __init__(self, package_name: str, message: str):
        super().__init__(f'invariant violated by "{package_name}": {message}')
        self.name = "InvariantError"
        self.package_name = package_name


class InvariantRegistry(Service):
    name = "invariants"

    def __init__(self, ctx: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(ctx, name="invariants")
        self.owner_ctx = ctx
        self.config = config or {}
        self.enabled: bool = bool(self.config.get("enabled", True))
        self.package_allowlist = [re.compile(p) for p in self.config.get("package_allowlist", [])]
        self.package_blocklist = [re.compile(p) for p in self.config.get("package_blocklist", [])]
        self.registrations: Set[str] = set()

    def selected(self, package_name: str) -> bool:
        if not self.enabled:
            return False
        if self.package_allowlist:
            if not any(p.search(package_name) for p in self.package_allowlist):
                return False
        if self.package_blocklist:
            if any(p.search(package_name) for p in self.package_blocklist):
                return False
        return True

    def register(self, package_name: str, installer: Callable[..., Any]) -> Callable[[], None]:
        if not package_name or not package_name.strip() or any(c.isspace() for c in package_name):
            raise ValueError("invariants: packageName must be non-blank and contain no whitespace")
        if package_name in self.registrations:
            raise ValueError(f'invariants: package "{package_name}" is already registered')

        ctx = self.owner_ctx
        self.registrations.add(package_name)

        if not self.selected(package_name):
            def _clean():
                self.registrations.discard(package_name)
            return _clean

        def fail_fn(message: str):
            raise InvariantError(package_name, message)

        child_fiber = None
        try:
            inj = getattr(installer, "inject", None)

            def _install_entry(child_ctx: Context):
                return installer(child_ctx, fail_fn)

            if inj:
                setattr(_install_entry, "inject", inj)

            child_fiber = ctx.plugin(_install_entry)
        except Exception:
            self.registrations.discard(package_name)
            raise

        def disposer():
            if child_fiber:
                try:
                    import asyncio
                    loop = asyncio.get_running_loop()
                    loop.create_task(child_fiber.dispose())
                except RuntimeError:
                    pass
            self.registrations.discard(package_name)

        if hasattr(ctx, "effect"):
            return ctx.effect(disposer, label=f'invariants.register("{package_name}")')
        return disposer