"""
Package-owned invariant companion for `@deepseek-ai/dsh-command-feedback`.
1:1 with reference/packages/feedback/command-feedback/src/invariant.ts.
Python 3.8.10 compatible.
"""

from typing import Any, Callable, Optional

PACKAGE_NAME = "@deepseek-ai/dsh-command-feedback"
name = "command-feedback-invariant"
inject = ["invariants"]


def install(ctx: Any, fail: Callable[[str], None]) -> None:
    """
    No runtime invariant: each `feedback/record` is an independent append-only
    fact with no cross-event or mutable-data relationship.
    """


def apply(ctx: Any) -> Optional[Any]:
    invariants_svc = ctx.get("invariants") if hasattr(ctx, "get") else None
    if invariants_svc is not None and hasattr(invariants_svc, "register"):
        return registration_result(invariants_svc.register(PACKAGE_NAME, install))
    return None


from dsh.diagnostics.invariants import registration_result
