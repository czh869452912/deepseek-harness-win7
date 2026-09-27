"""
Package-owned invariant companion for dsh.settings.
Aligned 1:1 with reference @deepseek-ai/dsh-settings/invariant.
"""

from typing import Any, Callable

PACKAGE_NAME = "@deepseek-ai/dsh-settings"
name = "settings-invariant"
inject = ["invariants"]


def install(ctx: Any, fail: Callable[[str], None]) -> None:
    """
    Install the commit-event contract: `settings/updated` fires only for a
    currently registered namespace, only when the resolved value changed, and
    only with the service's authoritative resolved value, all judged with the
    seam's own equality predicate.
    """
    from dsh.settings.provider import deep_equal_json

    def on_settings_updated(ns: str, next_val: Any, prev_val: Any, source: str) -> None:
        settings = ctx.get("settings")
        if settings is None:
            fail(f'settings/updated for "{ns}" emitted without a live settings service')
            return
        current = settings.get(ns)
        if current is None:
            fail(f'settings/updated for "{ns}" emitted while the namespace is unregistered')
            return
        if not deep_equal_json(current, next_val):
            fail(f'settings/updated for "{ns}" does not match the authoritative resolved value')
            return
        if deep_equal_json(next_val, prev_val):
            fail(f'settings/updated for "{ns}" emitted without a resolved-value change')

    ctx.on("settings/updated", on_settings_updated)


def apply(ctx: Any) -> Any:
    """
    Register this package's invariant companion.

    :param ctx: Cordis context carrying the invariant service.
    :returns: the installed registration's disposer after setup succeeds.
    """
    return registration_result(ctx.invariants.register(PACKAGE_NAME, install))


from dsh.diagnostics.invariants import registration_result
