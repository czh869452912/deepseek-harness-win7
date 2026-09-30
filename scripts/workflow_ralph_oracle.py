"""Compare the actual pinned JS body with its reviewed Python translation.

Node and TypeScript are development oracle dependencies, never host dependencies.
This gate covers the fixed program only, not general JavaScript execution.
"""

import argparse
import asyncio
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dsh.workflow.ralph import execute_ralph
from dsh.workflow.workflow_service import render_error

CONTINUE = dict(status="continue", summary="Implemented the first slice.", evidence=["Focused tests pass."],
                nextSteps=["Implement the second slice."], blocker="")
COMPLETE = dict(status="complete", summary="The objective is complete.", evidence=["All required gates pass."], nextSteps=[], blocker="")
BLOCKED = dict(status="blocked", summary="No local work can progress.", evidence=["The service is unavailable."],
               nextSteps=["Retry after recovery."], blocker="The service is down.")


def fixtures():
    rows = [
        ("complete", [COMPLETE]), ("blocked", [BLOCKED]), ("continue-complete", [CONTINUE, COMPLETE]),
        ("round-limit", [CONTINUE, CONTINUE]), ("first-child-failed", [None]), ("second-child-failed", [CONTINUE, None]),
        ("empty-summary", [dict(COMPLETE, summary=" ")]),
        ("bom-summary", [dict(COMPLETE, summary="\ufeffdone")]),
        ("js-retained-control", [dict(COMPLETE, summary="\u0085done\u0085")]),
        ("lone-surrogate", [dict(COMPLETE, summary="done\ud800")]),
        ("explicit-surrogate-pair", [dict(COMPLETE, summary="done\ud83d\ude00")]),
        ("bad-evidence", [dict(COMPLETE, evidence=[" bad"])]),
        ("continue-without-next", [dict(CONTINUE, nextSteps=[])]),
        ("complete-without-evidence", [dict(COMPLETE, evidence=[])]),
        ("blocked-without-blocker", [dict(BLOCKED, blocker="")]),
        ("unknown-status", [dict(COMPLETE, status="unknown")]),
        ("extra-report-field", [dict(COMPLETE, extra="kept by fixed script; rejected by tool decoder")]),
        ("astral-handoff-limit", [dict(COMPLETE, summary="\U0001f600" * 40)]),
    ]
    return [dict(name=name, reports=copy.deepcopy(reports),
                 args=dict(objective="Finish concrete work", maxRounds=len(reports),
                           maxHandoffChars=200 if name == "astral-handoff-limit" else 16384)) for name, reports in rows]


class NativeProbe:
    def __init__(self, fixture):
        self.fixture, self.args = fixture, copy.deepcopy(fixture["args"])
        self.calls, self.phases = [], []

    def phase(self, title):
        self.phases.append(title)

    async def agent(self, prompt, opts):
        report = self.fixture["reports"][len(self.calls)]
        self.calls.append(copy.deepcopy(dict(prompt=prompt, opts=opts)))
        return copy.deepcopy(report)


async def python_observations(rows):
    observations = []
    for fixture in rows:
        run = NativeProbe(fixture)
        observation = dict(name=fixture["name"], calls=run.calls, phases=run.phases)
        try:
            observation["value"] = await execute_ralph(run)
        except Exception as error:
            observation["error"] = render_error(error)
        observations.append(observation)
    return observations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.node:
        parser.error("Node is required for the development oracle")
    target = json.loads((ROOT / "migration/baseline.json").read_text(encoding="utf-8"))["target_upstream"]
    actual = subprocess.check_output(["git", "-C", str(ROOT / "reference"), "rev-parse", "HEAD"], encoding="utf-8").strip()
    if target != actual:
        parser.error("reference differs from the pinned migration target")
    rows = fixtures()
    result = subprocess.run([args.node, "scripts/oracles/ralph-fixed-program.mjs"], cwd=str(ROOT),
                            input=json.dumps(rows, ensure_ascii=True), encoding="utf-8", capture_output=True)
    if result.returncode:
        sys.stderr.write(result.stderr)
        return result.returncode
    official = json.loads(result.stdout)
    native = asyncio.run(python_observations(rows))
    if [row["name"] for row in official] != [row["name"] for row in rows]:
        parser.error("missing, duplicate or reordered official observations")
    # The wire represents an astral code point and its UTF-16 pair identically.
    mismatches = [dict(name=left["name"], official=left, python=right)
                  for left, right in zip(official, native)
                  if json.dumps(left, ensure_ascii=True, sort_keys=True) != json.dumps(right, ensure_ascii=True, sort_keys=True)]
    report = dict(upstream=target, cases=len(rows),
                  matched=len(rows) - len(mismatches), mismatches=mismatches, official=official, python=native,
                  scope="fixed Ralph script, hook arguments, handoffs and validation; no general JS engine certification")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print("Ralph fixed program: {} / {} observations matched".format(report["matched"], report["cases"]))
    if mismatches:
        print(json.dumps(mismatches, ensure_ascii=True, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
