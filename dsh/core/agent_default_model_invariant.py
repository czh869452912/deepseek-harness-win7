"""Invariant companion for the default Agent model selection."""

from typing import Any, Callable


PACKAGE_NAME = "@deepseek-ai/dsh-agent-default-model"
name = "agent-default-model-invariant"
inject = ["invariants"]


def install(_ctx: Any, _fail: Callable[[str], None]) -> None:
    """Settings validation owns this package's only mutable relationship."""


def apply(ctx: Any) -> Any:
    return ctx.invariants.register(PACKAGE_NAME, install)
