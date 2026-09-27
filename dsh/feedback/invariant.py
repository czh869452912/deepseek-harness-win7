"""
Package-owned invariant companion for `@deepseek-ai/dsh-message-feedback`.
Aligned 1:1 with official `packages/feedback/message-feedback/src/invariant.ts`.

No runtime invariant exists: the private typed writer owns current row
mutations, the domain schema validates rows on reopen, and no second authority
exists. The companion still reserves the package name so a second registration
fails loudly.
"""

from typing import Any, Callable

PACKAGE_NAME = "@deepseek-ai/dsh-message-feedback"

#: Cordis companion plugin name.
name = "message-feedback-invariant"

#: Services required before the companion can reserve and check package ownership.
inject = ["invariants"]


def _install(ctx: Any, fail: Any) -> None:
    """No runtime invariant: see the module docstring."""


#: `Object.assign(() => {}, { inject: ['messageFeedback'] })`
_install.inject = ["messageFeedback"]  # type: ignore[attr-defined]

install: Callable[[], None] = _install


def apply(ctx: Any) -> Any:
    """Register this package's invariant companion."""
    return registration_result(ctx.invariants.register(PACKAGE_NAME, install))


from dsh.diagnostics.invariants import registration_result
