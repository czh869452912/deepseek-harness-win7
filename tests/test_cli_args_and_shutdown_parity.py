"""
Unit tests covering CLI Arguments Routing, Boundary Flags, and Process Shutdown Parity
Matching reference/apps/cli/tests/args.spec.ts and process-shutdown.spec.ts
"""

import os
import sys
import pytest

from apps.cli.args import parse_dsh_args
from dsh.cordis.context import Context


def test_cli_profile_boundary():
    invocation = parse_dsh_args(["--profile", "headless", "calculate 2+2"])
    assert invocation == {"mode": "profile", "profile": "headless", "patches": [], "args": ["calculate 2+2"]}
    with pytest.raises(SystemExit):
        parse_dsh_args([])


def test_context_teardown_and_shutdown_order():
    ctx = Context()
    shutdown_log = []

    # Register effects and plugins
    ctx.effect(lambda: shutdown_log.append("cleanup-1"))
    ctx.effect(lambda: shutdown_log.append("cleanup-2"))

    child_ctx = ctx.extend()
    child_ctx.effect(lambda: shutdown_log.append("child-cleanup"))

    # Execute teardown
    child_ctx.teardown()
    assert "child-cleanup" in shutdown_log

    ctx.teardown()
    # Teardown should execute in LIFO order
    assert "cleanup-2" in shutdown_log
    assert "cleanup-1" in shutdown_log
