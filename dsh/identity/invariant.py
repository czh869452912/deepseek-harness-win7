"""
Package-owned invariant companion for dsh.identity.
1:1 with reference @deepseek-ai/dsh-anonymous-user-id/invariant.
Python 3.8.10 compatible.
"""

from typing import Any, Callable, Optional

PACKAGE_NAME = "@deepseek-ai/dsh-anonymous-user-id"
name = "anonymous-user-id-invariant"
inject = ["invariants"]


def install(ctx: Any, fail: Callable[[str], None]) -> None:
    pass


def apply(ctx: Any) -> Optional[Any]:
    if hasattr(ctx, "invariants") and hasattr(ctx.invariants, "register"):
        return ctx.invariants.register(PACKAGE_NAME, install)
    return None
