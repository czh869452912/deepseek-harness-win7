"""Compare replay metering, permitting only an exact reviewed upstream input-anchor bug."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUG_TARGET = "cd5ef8148158c3a752a658978873241fdf8e2bbc"
BUG_CASE = dict(mode="late-input-anchor", actions=[dict(op="input-call", input="abcd", usage=dict(inputTokens=100, outputTokens=20)), dict(op="measure")])


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-16-le", "surrogatepass")


def reviewed_input_anchor_difference(left, right, spec, target):
    if target != BUG_TARGET or spec != BUG_CASE or left.get("mode") != "late-input-anchor":
        return False
    import copy
    corrected = copy.deepcopy(left)
    if len(corrected.get("output", [])) != 1:
        return False
    measurement = corrected["output"][0]["measurement"]
    if measurement["baseline"] != dict(kind="usage", tokens=120, usage=dict(inputTokens=100, outputTokens=20)):
        return False
    if measurement["surfaceDeltaTokens"] != 9 or measurement["totalTokens"] != 129:
        return False
    measurement["surfaceDeltaTokens"], measurement["totalTokens"] = 0, 120
    return wire(corrected) == wire(right)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".goose/out/token-meter-paired.json")
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status="runner-error", cases=[])
    try:
        target = json.loads((ROOT / "migration/baseline.json").read_text(encoding="utf-8"))["target_upstream"]
        actual = subprocess.check_output(["git", "-C", str(ROOT / "reference"), "rev-parse", "HEAD"], encoding="utf-8").strip()
        if actual != target:
            raise ValueError("reference differs from target")
        report["target_upstream"] = target
        specs = json.loads((ROOT / "scripts/oracles/token-meter-cases.json").read_text(encoding="utf-8"))
        modes = [spec["mode"] for spec in specs]
        if len(set(modes)) != len(modes) or not modes:
            raise ValueError("empty or duplicate case identities")
        paths = [output.with_suffix(".ts.json"), output.with_suffix(".python.json")]
        env = dict(os.environ, TOKEN_METER_OUTPUT=str(paths[0]))
        commands = [["node", "scripts/oracles/official/node_modules/vitest/vitest.mjs", "run", "--config", "scripts/oracles/vitest.token-meter-probe.config.mts"],
                    [sys.executable, "scripts/oracles/token_meter_python.py", str(paths[1])]]
        observations = []
        for index, command in enumerate(commands):
            paths[index].unlink(missing_ok=True)
            result = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=45)
            output.with_suffix(".%d.log" % index).write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError("runner %d failed (%d)" % (index, result.returncode))
            rows = json.loads(paths[index].read_text(encoding="utf-8"))
            if [row["mode"] for row in rows] != modes:
                raise ValueError("missing, duplicate or unexpected observations")
            observations.append(rows)
        for spec, left, right in zip(specs, *observations):
            status = "matched" if wire(left) == wire(right) else ("reviewed-upstream-bug" if reviewed_input_anchor_difference(left, right, spec, target) else "different")
            report["cases"].append(dict(mode=left["mode"], status=status, upstream=left, python=right))
        report["status"] = "passed" if all(row["status"] in ("matched", "reviewed-upstream-bug") for row in report["cases"]) else "different"
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(report["status"])
    return {"passed": 0, "different": 1, "runner-error": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
