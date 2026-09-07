"""
1:1 Parity Tests for parseDshArgs
Port of reference/apps/cli/tests/args.spec.ts
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import sys
import pytest
from typing import List
from apps.cli.args import parse_dsh_args, parseDshArgs


def parse(argv: List[str]):
    return parse_dsh_args(argv, "1.2.3")


def exit_code(argv: List[str], monkeypatch) -> int:
    """Capture process exit code while muting stdout/stderr, mirroring TS exitCode()."""
    captured_code = None

    def fake_exit(code=0):
        nonlocal captured_code
        captured_code = code
        raise SystemExit(code)

    monkeypatch.setattr(sys, "exit", fake_exit)
    monkeypatch.setattr(sys.stdout, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys.stderr, "write", lambda *args, **kwargs: None)

    try:
        parse(argv)
        raise AssertionError(f"expected {argv} to exit")
    except SystemExit:
        return captured_code if captured_code is not None else 0


def test_routes_profile_boots_and_web_alias():
    """Routes profile boots and the web alias, handing the rest to the app."""
    assert parse(["--profile", "tui"]) == {
        "mode": "profile",
        "profile": "tui",
        "patches": [],
        "args": [],
    }
    assert parse(["--profile", "tui", "--patch", "a.yml", "--patch", "b.yml"]) == {
        "mode": "profile",
        "profile": "tui",
        "patches": ["a.yml", "b.yml"],
        "args": [],
    }
    assert parse(["web"]) == {
        "mode": "profile",
        "profile": "web",
        "patches": [],
        "args": [],
    }
    assert parse(["web", "--patch", "web.yml"]) == {
        "mode": "profile",
        "profile": "web",
        "patches": ["web.yml"],
        "args": [],
    }


def test_ends_launcher_flags_at_first_unowned_token():
    """Ends the launcher flags at the first token it does not own."""
    # App flags, including its -h, and positionals reach the app verbatim.
    assert parse(["--profile", "tui", "--resume", "abc"]) == {
        "mode": "profile",
        "profile": "tui",
        "patches": [],
        "args": ["--resume", "abc"],
    }
    assert parse(["--profile", "web", "-h"]) == {
        "mode": "profile",
        "profile": "web",
        "patches": [],
        "args": ["-h"],
    }
    assert parse(["web", "--host", "127.0.0.1", "--port", "8080", "--no-open", "--future-web-flag"]) == {
        "mode": "profile",
        "profile": "web",
        "patches": [],
        "args": ["--host", "127.0.0.1", "--port", "8080", "--no-open", "--future-web-flag"],
    }
    assert parse(["--profile", "headless", "run", "the", "tests"]) == {
        "mode": "profile",
        "profile": "headless",
        "patches": [],
        "args": ["run", "the", "tests"],
    }
    # Launcher flags placed after that boundary belong to the app too.
    assert parse(["--profile", "tui", "--patch", "a.yml", "--resume", "b", "--patch", "late.yml"]) == {
        "mode": "profile",
        "profile": "tui",
        "patches": ["a.yml"],
        "args": ["--resume", "b", "--patch", "late.yml"],
    }


def test_routes_plugin_pnpm_forwarder():
    """Routes the plugin pnpm forwarder."""
    assert parse(["plugin", "--profile", "tui", "add", "turtle-ui"]) == {
        "mode": "plugin",
        "profile": "tui",
        "args": ["add", "turtle-ui"],
    }
    assert parse(["plugin", "--profile", "tui", "remove", "turtle-ui"]) == {
        "mode": "plugin",
        "profile": "tui",
        "args": ["remove", "turtle-ui"],
    }
    assert parse(["plugin", "--profile", "tui", "why", "@deepseek-ai/cordis"]) == {
        "mode": "plugin",
        "profile": "tui",
        "args": ["why", "@deepseek-ai/cordis"],
    }
    # Unknown pnpm flags forward verbatim.
    assert parse(["plugin", "--profile", "tui", "add", "--save-dev", "x"]) == {
        "mode": "plugin",
        "profile": "tui",
        "args": ["add", "--save-dev", "x"],
    }


def test_routes_profile_and_web_config_dumps():
    """Routes profile and web config dumps."""
    assert parse(["--profile", "web", "--dump-config"]) == {
        "mode": "dump-config",
        "profile": "web",
        "defaultOnly": False,
        "patches": [],
    }
    assert parse(["--profile", "web", "--dump-default-config"]) == {
        "mode": "dump-config",
        "profile": "web",
        "defaultOnly": True,
        "patches": [],
    }
    assert parse(["--profile", "tui", "--dump-config", "--patch", "x.yml"]) == {
        "mode": "dump-config",
        "profile": "tui",
        "defaultOnly": False,
        "patches": ["x.yml"],
    }
    assert parse(["web", "--dump-config"]) == {
        "mode": "dump-config",
        "profile": "web",
        "defaultOnly": False,
        "patches": [],
    }
    assert parse(["web", "--dump-default-config"]) == {
        "mode": "dump-config",
        "profile": "web",
        "defaultOnly": True,
        "patches": [],
    }


def test_rejects_missing_profile_removed_flags_and_contradictory_inputs(monkeypatch):
    """Rejects missing profile, removed flags, and contradictory inputs."""
    assert exit_code([], monkeypatch) == 1
    assert exit_code(["tui"], monkeypatch) == 1
    assert exit_code(["--config", "c.yml"], monkeypatch) == 1
    assert exit_code(["-p", "task"], monkeypatch) == 1
    assert exit_code(["run", "task"], monkeypatch) == 1
    assert exit_code(["--profile", ""], monkeypatch) == 1
    assert exit_code(["--profile", "x", "--patch="], monkeypatch) == 1
    assert exit_code(["--dump-config"], monkeypatch) == 1
    assert exit_code(["--profile", "x", "--dump-config", "--dump-default-config"], monkeypatch) == 1
    assert exit_code(["--profile", "x", "--dump-default-config", "--patch", "p.yml"], monkeypatch) == 1
    assert exit_code(["--profile", "x", "--dump-config", "task"], monkeypatch) == 1
    assert exit_code(["--bogus"], monkeypatch) == 1
    assert exit_code(["--profile", "x", "web"], monkeypatch) == 1
    assert exit_code(["web", "--dump-config", "--dump-default-config"], monkeypatch) == 1
    assert exit_code(["web", "--dump-default-config", "--patch", "w.yml"], monkeypatch) == 1
    assert exit_code(["web", "--patch="], monkeypatch) == 1
    assert exit_code(["web", "--dump-config", "--port", "8080"], monkeypatch) == 1
    assert exit_code(["--profile", "web", "--dump-config", "-h"], monkeypatch) == 1
    assert exit_code(["plugin", "add", "x"], monkeypatch) == 1
    assert exit_code(["plugin", "--profile", "tui"], monkeypatch) == 1
    assert exit_code(["plugin", "--profile", ""], monkeypatch) == 1
    assert exit_code(["--profile", "x", "plugin", "add", "y"], monkeypatch) == 1


def test_keeps_own_help_for_invocation_with_no_app(monkeypatch):
    """Keeps its own help for an invocation with no app to hand it to."""
    assert exit_code(["--help"], monkeypatch) == 0
    assert exit_code(["-h"], monkeypatch) == 0
    assert exit_code(["--version"], monkeypatch) == 0
