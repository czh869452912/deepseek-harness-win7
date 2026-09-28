import os
from pathlib import Path
import subprocess
import sys

import pytest

from dsh.cordis.context import Context
from dsh.sandbox.local import LocalSandboxProvider
from dsh.sandbox.vocabulary import SandboxUnavailableError


@pytest.mark.parametrize("config", [
    {"runnerCommand": ["runner"]}, {"runnerFailureSignatures": ["failure"]},
    {"runnerCommand": ["runner"], "runnerFailureSignatures": ["\n"]},
    {"probeTimeoutMs": 0}, {"probeTimeoutMs": float("inf")},
])
def test_invalid_configuration_fails_before_publishing_service(config):
    ctx = Context()
    with pytest.raises(ValueError):
        LocalSandboxProvider(ctx, config)
    assert ctx.get("sandbox") is None


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL lifecycle")
@pytest.mark.asyncio
async def test_provider_owns_reusable_isolated_temp_capabilities(tmp_path):
    ctx = Context()
    fiber = ctx.plugin(LocalSandboxProvider)
    await fiber.await_settled()
    provider = ctx.get("sandbox")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = {"mode": "workspace-write", "workspaceRoot": str(workspace), "sessionId": "one"}
    payload = [sys.executable, "-c", "import os; print(os.environ['TEMP'])"]
    first = provider.confine(payload, policy)
    assert provider.confine(payload, policy) == first
    second = provider.confine(payload, dict(policy, sessionId="two"))
    assert first["argv"] != second["argv"]
    first_temp = first["argv"][first["argv"].index("--temp") + 1]
    second_temp = second["argv"][second["argv"].index("--temp") + 1]
    assert first["enforcement"] == "partial"
    result = subprocess.run(first["argv"], cwd=str(workspace), stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == first_temp
    assert Path(first_temp).is_dir()
    attack = [sys.executable, "-c", "import pathlib; pathlib.Path(%r,'attack').write_text('bad')" % second_temp]
    refused = subprocess.run(provider.confine(attack, policy)["argv"], cwd=str(workspace),
                             stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             encoding="utf-8", timeout=15)
    assert refused.returncode != 0 and "PermissionError" in refused.stderr
    downgraded = provider.confine(payload, dict(policy, mode="read-only"))
    assert "--write-sid" not in downgraded["argv"]
    await fiber.dispose()
    assert ctx.get("sandbox") is None
    assert not Path(first_temp).exists() and not Path(second_temp).exists()
    with pytest.raises(SandboxUnavailableError):
        provider.confine(payload, policy)


def test_custom_runner_preserves_exact_argv_and_failure_contract():
    provider = LocalSandboxProvider(Context(), {"runnerCommand": ["custom", "--flag"],
                                                "runnerFailureSignatures": ["custom: failed"]})
    wrapped = provider.confine(["command", "spaced arg"], {"mode": "read-only", "workspaceRoot": "/"})
    assert wrapped["argv"][:2] == ["custom", "--flag"]
    assert wrapped["argv"][-3:] == ["--", "command", "spaced arg"]
    assert wrapped["runnerFailureRules"] == [{"fatalSignatures": ["custom: failed"]}]
