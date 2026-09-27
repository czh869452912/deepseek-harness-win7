"""
Package-owned invariant companion for `@deepseek-ai/dsh-shell-env`.
1:1 with reference/packages/shell/shell-env/src/invariant.ts.
Python 3.8.10 compatible.
"""

from typing import Any, Callable, Optional

PACKAGE_NAME = "@deepseek-ai/dsh-shell-env"
name = "shell-env-invariant"
inject = ["invariants"]


def install(ctx: Any, fail: Callable[[str], None]) -> None:
    """
    No runtime invariant: the environment registry validates ownership and
    collected values at each registration/collection; it publishes no
    independent snapshot that a companion could cross-check.
    """


def apply(ctx: Any) -> Optional[Any]:
    invariants_svc = ctx.get("invariants") if hasattr(ctx, "get") else None
    if invariants_svc is not None and hasattr(invariants_svc, "register"):
        return registration_result(invariants_svc.register(PACKAGE_NAME, install))
    return None


from dsh.diagnostics.invariants import registration_result
