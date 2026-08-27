"""Package-owned invariant companion for session checkpoint policy."""

from typing import Any, Callable, Optional

PACKAGE_NAME = "@deepseek-ai/dsh-session-checkpoint-policy"
name = "session-checkpoint-policy-invariant"
inject = ["invariants"]


def install(ctx: Any, fail: Callable[[str], None]) -> None:
    # The upstream companion is intentionally stateless; checkpoint ordering
    # is enforced by the policy waterfalls and persistence boundary.
    return None


def apply(ctx: Any) -> Optional[Any]:
    invariants = getattr(ctx, "invariants", None)
    if invariants is not None and hasattr(invariants, "register"):
        return invariants.register(PACKAGE_NAME, install)
    return None

