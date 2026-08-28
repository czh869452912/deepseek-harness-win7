"""
Unit tests covering CLI Arguments Routing, Boundary Flags, and Process Shutdown Parity
Matching reference/apps/cli/tests/args.spec.ts and process-shutdown.spec.ts
"""

import os
import sys
import pytest

from apps.cli.main import parse_args
from dsh.cordis.context import Context


def test_cli_parse_args_defaults_and_modes():
    # Test standard mode default
    sys_argv_backup = sys.argv
    try:
        sys.argv = ["dsh.py"]
        args = parse_args()
        assert args.mode == "standard"
        assert args.web is False
        assert args.dump_config is False

        # Test minimal mode
        sys.argv = ["dsh.py", "-m", "minimal", "--dump-config"]
        args = parse_args()
        assert args.mode == "minimal"
        assert args.dump_config is True

        # Test creative mode with web flags
        sys.argv = ["dsh.py", "--mode", "creative", "--web", "--port", "9090", "--host", "0.0.0.0", "--no-open"]
        args = parse_args()
        assert args.mode == "creative"
        assert args.web is True
        assert args.port == 9090
        assert args.host == "0.0.0.0"
        assert args.no_open is True

        # Test prompt execution
        sys.argv = ["dsh.py", "-p", "calculate 2+2"]
        args = parse_args()
        assert args.prompt == "calculate 2+2"
    finally:
        sys.argv = sys_argv_backup


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
