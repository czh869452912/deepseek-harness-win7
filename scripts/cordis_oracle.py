"""Run isolated, observation-only C1-C51 scenarios against pinned TS and Python.

Exit 0: all selected observations match; 1: behavioral difference;
2: runner/source/adapter failure. This does not certify the whole contract.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def execute(command, case, timeout):
    try:
        run = subprocess.run(command, cwd=str(ROOT), encoding="utf-8", errors="strict",
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "error": str(exc), "status": "runner-error"}
    result = {"command": command, "stdout": run.stdout, "stderr": run.stderr, "exit_code": run.returncode}
    try:
        if run.returncode:
            raise ValueError("subprocess failed")
        value = json.loads(run.stdout)
        if value.get("case") != "C%d" % case or "observation" not in value:
            raise ValueError("invalid observation envelope")
        result.update(status="observed", observation=value["observation"])
    except (ValueError, AttributeError) as exc:
        result.update(status="runner-error", error=str(exc))
    return result


def differences(left, right, path="$"):
    if type(left) is not type(right):
        return [{"path": path, "upstream": left, "python": right}]
    if isinstance(left, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                result.append({"path": path + "." + key, "missing": "upstream" if key not in left else "python"})
            else:
                result.extend(differences(left[key], right[key], path + "." + key))
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": path, "upstream": left, "python": right}]
        return [row for i, pair in enumerate(zip(left, right)) for row in differences(*pair, path=path + "[%d]" % i)]
    return [] if left == right else [{"path": path, "upstream": left, "python": right}]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tsx", type=Path, default=ROOT / "scripts/oracles/node_modules/tsx/dist/cli.mjs")
    parser.add_argument("--node", default="node")
    parser.add_argument("--cases", type=int, nargs="+", default=list(range(1, 52)))
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.tsx.is_file() or any(n not in range(1, 52) for n in args.cases):
        parser.error("tsx launcher must exist; cases must be within 1..51")
    tsx_package = json.loads((args.tsx.resolve().parent.parent / "package.json").read_text(encoding="utf-8"))
    if tsx_package.get("version") != "4.22.4":
        parser.error("oracle requires the pinned tsx 4.22.4 launcher")
    base = json.loads((ROOT / "migration/baseline.json").read_text(encoding="utf-8"))
    def git(*parts):
        return subprocess.check_output(["git"] + list(parts), cwd=str(ROOT), encoding="utf-8").strip()
    if git("-C", "reference", "rev-parse", "HEAD") != base["target_upstream"]:
        parser.error("reference is not pinned target")
    if git("-C", "reference", "status", "--porcelain", "--untracked-files=no"):
        parser.error("reference has tracked modifications")
    report = {"schema_version": 1, "target_upstream": base["target_upstream"],
              "product_base": git("rev-parse", "HEAD"), "python": sys.version,
              "node": subprocess.check_output([args.node, "--version"], encoding="utf-8").strip(),
              "os": platform.platform(), "tsx": tsx_package["version"],
              "cwd": str(ROOT), "cases": [], "inputs": [],
              "normalization": "JSON undefined return -> null; runtime states retain numeric values; no event sorting"}
    sources = list((ROOT / "scripts/oracles").glob("*.py")) + list((ROOT / "scripts/oracles").glob("*.mts"))
    sources += [Path(__file__).resolve(), ROOT / "scripts/oracles/tsconfig.json",
                ROOT / "scripts/oracles/package.json", ROOT / "scripts/oracles/package-lock.json"]
    for directory, pattern in [("reference/vendor/cordis/src", "*.ts"), ("reference/vendor/cosmokit/src", "*.ts"), ("reference/vendor/timer/src", "*.ts"), ("reference/vendor/loader/src", "*.ts"), ("reference/vendor/hmr/src", "*.ts"), ("reference/vendor/include/src", "*.ts"), ("reference/vendor/schemastery/src", "*.ts"), ("dsh/cordis", "*.py")]:
        sources.extend((ROOT / directory).rglob(pattern))
    for path in sorted(set(sources)):
        report["inputs"].append({"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    code = 0
    for case in args.cases:
        upstream = execute([args.node, str(args.tsx.resolve()), "--expose-internals", "--tsconfig", "scripts/oracles/tsconfig.json", "scripts/oracles/cordis.mts", str(case)], case, args.timeout)
        python = execute([sys.executable, "scripts/oracles/cordis_python.py", str(case)], case, args.timeout)
        row = {"case": "C%d" % case, "upstream": upstream, "python": python}
        if any(side["status"] != "observed" for side in (upstream, python)):
            row["status"] = "runner-error"
            code = 2
        else:
            row["differences"] = differences(upstream["observation"], python["observation"])
            row["status"] = "different" if row["differences"] else "matched"
            if row["differences"] and not code:
                code = 1
        report["cases"].append(row)
        print(row["case"] + ": " + row["status"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return code


if __name__ == "__main__":
    sys.exit(main())
