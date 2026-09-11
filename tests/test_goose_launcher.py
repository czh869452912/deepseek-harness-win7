"""Exercise the Windows Goose launcher without network calls or credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell required")


def test_launcher_requires_scope():
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / ".goose/run-parity.ps1")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
        errors="replace",
    )
    assert result.returncode != 0
    assert "Specify -MigrationUnit" in result.stderr


def test_launcher_passes_scope_and_normalizes_url(tmp_path):
    fake = tmp_path / "fake goose.ps1"
    log = tmp_path / "calls.jsonl"
    fake.write_text(
        "@{arguments=@($args); cwd=(Get-Location).Path; "
        "url=$env:OPENAI_BASE_URL} | ConvertTo-Json -Compress | "
        "Add-Content -LiteralPath $env:GOOSE_TEST_LOG -Encoding UTF8\nexit 0\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    for key in ("GOOSE_SUBAGENT_MODEL", "GOOSE_SUBAGENT_PROVIDER"):
        env.pop(key, None)
    env.update(GOOSE_TEST_LOG=str(log),
               OPENAI_BASE_URL="[https://example.test/v1](https://example.test/v1)")
    unit = "reference/core <-> dsh/core"
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / ".goose/run-parity.ps1"), "-GooseExe", str(fake),
         "-PythonExe", str(fake), "-MigrationUnit", unit], cwd=str(tmp_path), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8-sig").splitlines()]
    assert calls[0]["arguments"] == ["recipe", "validate", ".goose/recipes/parity-unit.yaml"]
    assert calls[1]["arguments"] == [str(ROOT / ".goose/parity_runner.py"),
                                      "--unit", unit, "--goose", str(fake),
                                      "--max-rounds", "3", "--max-turns", "60",
                                      "--phase-timeout", "1800"]
    assert Path(calls[1]["cwd"]) == ROOT
    assert calls[1]["url"] == "https://example.test/v1"


@pytest.mark.parametrize("verdict,success", [("SMOKE_FAIL", False), ("**SMOKE_PASS**", True)])
def test_smoke_checks_verdict_not_only_process_exit(tmp_path, verdict, success):
    fake = tmp_path / "fake goose.ps1"
    fake.write_text("Write-Output '" + verdict + "'\nexit 0\n", encoding="utf-8")
    env = dict(os.environ)
    for key in ("GOOSE_SUBAGENT_MODEL", "GOOSE_SUBAGENT_PROVIDER"):
        env.pop(key, None)
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / ".goose/run-parity.ps1"), "-GooseExe", str(fake), "-Smoke"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace",
    )
    assert (result.returncode == 0) is success
