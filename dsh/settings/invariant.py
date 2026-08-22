"""
Package-owned invariant companion for dsh.settings.
Aligned 1:1 with reference @deepseek-ai/dsh-settings/invariant.
"""

from typing import Any, Callable, Optional

PACKAGE_NAME = "@deepseek-ai/dsh-settings"
name = "settings-invariant"
inject = ["invariants"]


def install(ctx: Any, fail: Callable[[str], None]) -> None:
    def on_settings_updated(ns: str, next_val: Any, prev_val: Any, source: str) -> None:
        settings = ctx.get("settings") if hasattr(ctx, "get") else None
        if settings is None:
            fail(f'settings/updated for "{ns}" emitted without a live settings service')
            return
        current = settings.get(ns)
        if current is None:
            fail(f'settings/updated for "{ns}" emitted while the namespace is unregistered')
            return
        from dsh.settings.provider import deep_equal_json
        if not deep_equal_json(current, next_val):
            fail(f'settings/updated for "{ns}" does not match the authoritative resolved value')
            return
        if deep_equal_json(next_val, prev_val):
            fail(f'settings/updated for "{ns}" emitted without a resolved-value change')
            return

    if hasattr(ctx, "on"):
        ctx.on("settings/updated", on_settings_updated)


def apply(ctx: Any) -> Optional[Any]:
    if hasattr(ctx, "invariants") and hasattr(ctx.invariants, "register"):
        return ctx.invariants.register(PACKAGE_NAME, install)
    return None
