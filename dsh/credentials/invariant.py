"""
Package-owned invariant companions for dsh.credentials and dsh.authorization.
1:1 with reference @deepseek-ai/dsh-credentials/invariant and @deepseek-ai/dsh-authorization/invariant.
Python 3.8.10 compatible.
"""

from typing import Any, Callable, Optional

CREDENTIALS_PACKAGE_NAME = "@deepseek-ai/dsh-credentials"
credentials_invariant_name = "credentials-invariant"
credentials_inject = ["invariants"]


def install_credentials_invariant(ctx: Any, fail: Callable[[str], None]) -> None:
    def on_reference_updated(ref: str) -> None:
        creds = ctx.get("credentials") if hasattr(ctx, "get") else None
        if creds is None:
            fail(f'credentials/reference-updated for "{ref}" emitted without a live credentials service')

    if hasattr(ctx, "on"):
        ctx.on("credentials/reference-updated", on_reference_updated)


def apply_credentials_invariant(ctx: Any) -> Optional[Any]:
    if hasattr(ctx, "invariants") and hasattr(ctx.invariants, "register"):
        return ctx.invariants.register(CREDENTIALS_PACKAGE_NAME, install_credentials_invariant)
    return None


AUTHORIZATION_PACKAGE_NAME = "@deepseek-ai/dsh-authorization"
authorization_invariant_name = "authorization-invariant"
authorization_inject = ["invariants"]


def install_authorization_invariant(ctx: Any, fail: Callable[[str], None]) -> None:
    def on_authorization_settled(key: str, settlement: str) -> None:
        auth = ctx.get("authorization") if hasattr(ctx, "get") else None
        if auth is None:
            fail(f'authorization/settled for "{key}" emitted without a live authorization service')
            return
        entry = auth.describe(key)
        if entry and entry.get("inFlight") is True:
            fail(f'authorization/settled for "{key}" left the key in flight, wedging every later attempt')

    if hasattr(ctx, "on"):
        ctx.on("authorization/settled", on_authorization_settled)


def apply_authorization_invariant(ctx: Any) -> Optional[Any]:
    if hasattr(ctx, "invariants") and hasattr(ctx.invariants, "register"):
        return ctx.invariants.register(AUTHORIZATION_PACKAGE_NAME, install_authorization_invariant)
    return None
