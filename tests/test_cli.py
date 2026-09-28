"""Canonical launcher dispatch; legacy flags never select a second runtime."""
from types import SimpleNamespace
import sys
from unittest.mock import AsyncMock

import pytest
from apps.cli import main as cli


def test_only_profile_boot_receives_app_arguments(monkeypatch):
    runner = AsyncMock(return_value={"shutdown": SimpleNamespace(exit_code=7)})
    monkeypatch.setattr(cli, "run_profile", runner)
    monkeypatch.setattr(cli, "load_layered_env", lambda _: "environment")
    monkeypatch.setattr(sys, "argv", ["dsh", "--profile", "headless", "--model", "app-owned"])
    with pytest.raises(SystemExit) as exit:
        cli.main()
    assert exit.value.code == 7
    assert runner.call_args.args[0]["args"] == ["--model", "app-owned"]
    assert runner.call_args.args[0]["profile"] == "headless"


@pytest.mark.parametrize("args", [[], ["--mode", "minimal"], ["--web"], ["-p", "hello"]])
def test_legacy_launcher_invocations_are_rejected(monkeypatch, args):
    runner = AsyncMock()
    monkeypatch.setattr(cli, "run_profile", runner)
    monkeypatch.setattr(sys, "argv", ["dsh"] + args)
    with pytest.raises(SystemExit) as exit:
        cli.main()
    assert exit.value.code == 1
    runner.assert_not_called()
