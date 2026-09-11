"""
Minimal Typert registry service (`ctx.typert`).

Ported from reference `packages/typert/registry/src/service.ts`, restricted to
the dependency-inversion surface that `@deepseek-ai/dsh-session` consumes:
`ctx.typert.lookups.register(key, provider)` / `.get(key)` with fiber-scoped
withdrawal. The Remote/Context/generation layers of the reference registry are
out of this migration unit's boundary and are not ported.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Callable, Dict, List, Optional

from dsh.cordis.service import Service
from dsh.typert.protocol import (
    TypertDisposer,
    TypertLookupDefinition,
    TypertLookupProvider,
)


class LookupRegistry:
    """
    Runtime registry for Host object lookup providers, 1:1 with reference
    `TypertLookupRegistry` (protocol/types.ts:465-509) for the minimal surface:

    - `register(key, provider)` returns a disposer withdrawing the exact
      provider (a later provider for the same key is not withdrawn by an older
      disposer);
    - `get(key)` returns the live provider or `None` (`undefined`);
    - `keys()` is a snapshot of registered provider keys;
    - `definitions()` are the lookup declarations observed during the registry's
      lifetime — the declaration survives provider withdrawal, exactly like the
      reference `TypertLookupDefinition` contract.
    """

    def __init__(self) -> None:
        self._providers: Dict[str, TypertLookupProvider] = {}
        self._definitions: List[TypertLookupDefinition] = []

    def register(self, key: str, provider: TypertLookupProvider) -> TypertDisposer:
        self._providers[key] = provider
        if not any(d.key == key for d in self._definitions):
            self._definitions.append(TypertLookupDefinition.from_provider(key, provider))

        def dispose() -> None:
            # Withdraw THIS registration only: a provider registered later under
            # the same key stays live.
            if self._providers.get(key) is provider:
                del self._providers[key]

        return dispose

    def get(self, key: str) -> Optional[TypertLookupProvider]:
        return self._providers.get(key)

    def has(self, key: str) -> bool:
        return key in self._providers

    def keys(self) -> List[str]:
        return list(self._providers.keys())

    def definitions(self) -> List[TypertLookupDefinition]:
        return list(self._definitions)


class TypertRegistry(Service):
    """
    The Typert Service mounted at `ctx.typert`
    (`@deepseek-ai/dsh-typert-registry`).
    """

    id = "typert"
    name = "@deepseek-ai/dsh-typert-registry"

    def __init__(self, ctx: Any = None) -> None:
        super().__init__(ctx, "typert")
        # `lookups` is the live Host object lookup registry consumed through
        # dependency inversion (`ctx.inject(['typert'], ...)`).
        self.lookups = LookupRegistry()

    def apply(self, ctx: Any = None) -> None:
        target_ctx = ctx or self.ctx
        if target_ctx and not target_ctx.has("typert"):
            target_ctx.set_service("typert", self)


default = TypertRegistry

__all__ = ["LookupRegistry", "TypertRegistry", "default", "TypertDisposer", "TypertLookupProvider"]
