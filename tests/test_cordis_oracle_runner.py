"""Protocol and comparison regressions, independent of the modern Node runner."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

SPEC = importlib.util.spec_from_file_location(
    "cordis_oracle", Path(__file__).resolve().parents[1] / "scripts/cordis_oracle.py"
)
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


def test_event_order_and_types_cannot_be_normalized_away():
    assert oracle.differences(["enter", "exit"], ["exit", "enter"])
    assert oracle.differences({"value": 1}, {"value": True})
    assert oracle.differences({"value": None}, {})
    assert not oracle.differences({"a": 1, "b": 2}, {"b": 2, "a": 1})


def test_unload_checkpoint_difference_is_reported_at_the_observation_boundary():
    upstream = {"immediate": {"log": []}, "final": 4}
    python = {"immediate": {"log": ["unloaded"]}, "final": 4}
    assert oracle.differences(upstream, python) == [
        {"path": "$.immediate.log", "upstream": [], "python": ["unloaded"]}
    ]


@pytest.mark.parametrize("code", [
    "print('not json')",
    "print('{}')",
    "print('{\"case\":\"C2\",\"observation\":{}}')",
    "print('{\"case\":\"C1\",\"observation\":{}}'); raise SystemExit(1)",
])
def test_invalid_or_failed_probe_is_infrastructure_error(code):
    result = oracle.execute([sys.executable, "-c", code], 1, 5)
    assert result["status"] == "runner-error"
    assert "stdout" in result


def test_timeout_retains_runner_failure_classification(monkeypatch):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(oracle.subprocess, "run", timeout)
    result = oracle.execute(["missing"], 1, 1)
    assert result["status"] == "runner-error"
    assert result["command"] == ["missing"]


def test_probe_stderr_is_preserved_without_becoming_a_pass_claim():
    code = "import sys; print('notice', file=sys.stderr); print('{\"case\":\"C1\",\"observation\":{\"state\":4}}')"
    result = oracle.execute([sys.executable, "-c", code], 1, 5)
    assert result["status"] == "observed"
    assert result["observation"] == {"state": 4}
    assert "notice" in result["stderr"]
