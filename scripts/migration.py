"""Read-only migration gates and generated status; Python 3.8, stdlib only.

This is not a scheduler. A single coordinator edits the versioned records;
workers submit changes for review and never acquire leases through this CLI.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATES = {"draft", "ready", "running", "review", "verified", "queued", "integrated"}
SHA = re.compile(r"^[0-9a-f]{40}$")
ID = re.compile(r"^[A-Z][A-Z0-9-]*$")


class RecordError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise RecordError(message)


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecordError("{}: {}".format(path, exc))
    need(isinstance(value, dict), "{}: expected JSON object".format(path))
    return value


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root)] + list(args), encoding="utf-8", errors="strict"
    ).strip()


def source_inventory(root):
    """Include every tracked manifest, including fixtures and non-workspace SDKs."""
    ref = root / "reference"
    paths = git(ref, "ls-files", "--", "*package.json").splitlines()
    rows = []
    for name in paths:
        path = ref / name
        manifest = read_json(path)
        rows.append({
            "path": "reference/" + name,
            "name": manifest.get("name"),
            # Git checkouts may use CRLF on Windows. JSON line endings are not
            # semantic and must not invalidate an unchanged upstream manifest.
            "sha256": hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
            "classification": "fixture" if "/tests/fixtures/" in name else "untriaged",
        })
    return rows


def records(root, folder):
    result = {}
    for path in sorted((root / "migration" / folder).glob("*.json")):
        row = read_json(path)
        key = row.get("id")
        need(isinstance(key, str) and ID.fullmatch(key), str(path) + ": invalid id")
        need(path.stem == key, str(path) + ": filename must equal id")
        need(key not in result, "duplicate id " + key)
        result[key] = row
    return result


def fields(row, names, where):
    need(isinstance(row, dict), where + ": expected object")
    for name, kind in names.items():
        need(name in row and isinstance(row[name], kind), where + ": invalid/missing " + name)


def strings(value, where, nonempty=False):
    need(isinstance(value, list), where + ": expected list")
    need(all(isinstance(x, str) and x.strip() for x in value), where + ": expected nonempty strings")
    need(not nonempty or bool(value), where + ": must not be empty")


def file_path(root, name):
    need(isinstance(name, str) and bool(name), "invalid file path")
    path = (root / name).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise RecordError("path outside repository: " + name)
    need(path.is_file(), "missing file: " + name)
    return path


def require_sha(value, where):
    need(isinstance(value, str) and SHA.fullmatch(value), where + ": full SHA required")


def acceptance_digest(task):
    keys = ("id", "goal", "kind", "target_upstream", "requires", "provides", "acceptance")
    value = {key: task[key] for key in keys}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load(root):
    base = read_json(root / "migration/baseline.json")
    modules = read_json(root / "migration/modules.json")
    return {"baseline": base, "modules": modules,
            **{name: records(root, name) for name in ("contracts", "tasks", "evidence", "mappings")}}


def validate(data, root):
    base = data["baseline"]
    need(base.get("schema_version") == 1, "unsupported baseline schema")
    for key in ("product_commit", "target_upstream"):
        require_sha(base.get(key), "baseline." + key)
    for key in ("accepted_upstream", "observed_upstream"):
        need(key in base, "baseline missing " + key)
        if base[key] is not None:
            require_sha(base[key], "baseline." + key)
    target = base["target_upstream"]
    contracts, tasks, evidence = (data[x] for x in ("contracts", "tasks", "evidence"))
    all_ids = [key for name in ("contracts", "tasks", "evidence", "mappings") for key in data[name]]
    need(len(all_ids) == len(set(all_ids)), "ids must be globally unique")
    for key, contract in contracts.items():
        fields(contract, {"revision": int, "target_upstream": str, "status": str,
                          "invariants": list, "source_paths": list, "consumers": list,
                          "open_questions": list}, key)
        need(type(contract["revision"]) is int and contract["revision"] > 0, key + ": invalid revision")
        need(contract["target_upstream"] == target, key + ": target mismatch")
        need(contract["status"] in {"draft", "specified"}, key + ": unsupported status")
        for name in ("invariants", "source_paths"):
            strings(contract[name], key + "." + name, True)
        for name in contract["source_paths"]:
            file_path(root, name)
        if contract["status"] == "specified":
            for name in ("identity", "ownership", "ordering", "errors", "cancellation", "adaptation"):
                need(isinstance(contract.get(name), str) and bool(contract[name].strip()), key + ": specified contract missing " + name)
    for key, run in evidence.items():
        fields(run, {"target_upstream": str, "product_commit": str, "result": str,
                     "validity": str, "commands": list, "environment": dict,
                     "contract_revisions": dict, "artifacts": list, "kind": str}, key)
        require_sha(run["target_upstream"], key)
        require_sha(run["product_commit"], key)
        need(run["result"] in {"passed", "failed", "unknown"}, key + ": invalid result")
        need(run["validity"] in {"current", "historical", "stale"}, key + ": invalid validity")
        strings(run["commands"], key + ".commands", True)
        run["_inputs_current"] = True
        if run["kind"] == "acceptance":
            fields(run, {"task_id": str, "acceptance_digest": str, "inputs": list,
                         "exit_code": int}, key)
            need(run["task_id"] in tasks, key + ": unknown acceptance task")
            need(bool(run["inputs"]) and bool(run["artifacts"]), key + ": acceptance needs inputs and artifacts")
            for name in ("python", "os", "cwd"):
                need(isinstance(run["environment"].get(name), str) and bool(run["environment"][name]), key + ": environment missing " + name)
            for item in run["inputs"]:
                fields(item, {"path": str, "sha256": str}, key + ".input")
                need(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), key + ": invalid input hash")
                try:
                    path = file_path(root, item["path"])
                    same = hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
                except RecordError:
                    same = False
                run["_inputs_current"] = run["_inputs_current"] and same
        for cid, rev in run["contract_revisions"].items():
            need(cid in contracts and type(rev) is int and rev > 0, key + ": unknown contract/revision")
        for artifact in run["artifacts"]:
            fields(artifact, {"path": str, "sha256": str}, key + ".artifact")
            path = file_path(root, artifact["path"])
            need(hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"], key + ": artifact hash mismatch")
    graph = {}
    # Validate the dependency surface before following references to later rows.
    for key, task in tasks.items():
        fields(task, {"provides": list, "requires": list, "conflicts_with": list,
                      "state": str, "evidence_ids": list}, key)
    for key, task in tasks.items():
        fields(task, {"goal": str, "kind": str, "state": str, "target_upstream": str,
                      "base_product": str, "requires": list, "provides": list,
                      "acceptance": list, "evidence_ids": list, "expected_paths": list,
                      "open_findings": list, "next_action": str, "conflicts_with": list}, key)
        need(task["state"] in STATES, key + ": invalid state")
        need(task["kind"] in {"analysis", "implementation", "verification", "release"}, key + ": invalid kind")
        require_sha(task["target_upstream"], key + ".target_upstream")
        historical = task["state"] == "integrated"
        need(historical or task["target_upstream"] == target, key + ": target mismatch")
        require_sha(task["base_product"], key + ".base_product")
        for name in ("acceptance", "evidence_ids", "expected_paths", "open_findings", "conflicts_with"):
            strings(task[name], key + "." + name, name == "acceptance" and task["state"] != "draft")
        need(task["goal"].strip() and task["next_action"].strip(), key + ": empty goal/next_action")
        if task["state"] not in {"draft", "ready"}:
            need(isinstance(task.get("owner"), str) and bool(task["owner"]), key + ": owner required")
        for eid in task["evidence_ids"]:
            need(eid in evidence, key + ": unknown evidence " + eid)
        for other in task["conflicts_with"]:
            need(other in tasks and other != key, key + ": invalid conflicting task")
        for item in task["provides"]:
            fields(item, {"contract": str, "revision": int}, key + ".provides")
            need(item["contract"] in contracts, key + ": unknown provided contract")
            current_revision = contracts[item["contract"]]["revision"]
            need(type(item["revision"]) is int and item["revision"] > 0 and
                 (item["revision"] <= current_revision if historical else item["revision"] == current_revision), key + ": stale provided revision")
        graph[key] = []
        for dep in task["requires"]:
            fields(dep, {"task": str, "contract": str, "revision": int}, key + ".requires")
            need(dep["task"] in tasks, key + ": missing dependency " + dep["task"])
            need(dep["contract"] in contracts, key + ": missing dependency contract")
            current_revision = contracts[dep["contract"]]["revision"]
            need(type(dep["revision"]) is int and dep["revision"] > 0 and
                 (dep["revision"] <= current_revision if historical else dep["revision"] == current_revision), key + ": stale dependency revision")
            need({"contract": dep["contract"], "revision": dep["revision"]} in tasks[dep["task"]]["provides"], key + ": dependency does not provide contract")
            graph[key].append(dep["task"])
    visited, active = set(), set()

    def visit(key):
        need(key not in active, "dependency cycle at " + key)
        if key in visited:
            return
        active.add(key)
        for dep in graph[key]:
            visit(dep)
        active.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)
    for key, task in tasks.items():
        if task["state"] in {"verified", "queued", "integrated"}:
            require_sha(task.get("candidate_commit"), key + ".candidate_commit")
            if task["state"] == "integrated":
                require_sha(task.get("integrated_commit"), key + ".integrated_commit")
            need(not task["open_findings"], key + ": unresolved findings prevent verification")
            need(bool(valid_runs(task, data, current=task["state"] != "integrated")), key + ": no matching passing evidence")
            if task["state"] != "integrated":
                need(not blockers(task, data), key + ": unresolved dependency/conflict")
    for key, mapping in data["mappings"].items():
        fields(mapping, {"target_upstream": str, "cases": list}, key)
        need(mapping["target_upstream"] == target, key + ": target mismatch")
        seen = set()
        for case in mapping["cases"]:
            fields(case, {"id": str, "origin": str, "contract": str, "test": str, "status": str}, key)
            need(case["id"] not in seen, key + ": duplicate case " + case["id"])
            seen.add(case["id"])
            need(case["contract"] in contracts, key + ": unknown contract")
            need(case["origin"] in {"source-derived", "official-test"}, key + ": invalid case origin")
            need(case["status"] == "indexed-unverified", key + ": this index cannot certify parity")
            path, sep, symbol = case["test"].partition("::")
            text = file_path(root, path).read_text(encoding="utf-8")
            need(sep and re.search(r"(?:async\s+)?def\s+" + re.escape(symbol) + r"\s*\(", text), key + ": missing test symbol")
    inventory = data["modules"]
    need(inventory.get("target_upstream") == target, "inventory target mismatch")
    fields(inventory, {"manifests": list, "non_package_surfaces": list}, "inventory")
    seen = set()
    for row in inventory["manifests"]:
        fields(row, {"path": str, "sha256": str, "classification": str}, "manifest")
        need(row["path"] not in seen, "duplicate manifest " + row["path"])
        need(row["classification"] in {"untriaged", "fixture", "runtime", "frontend", "tooling", "platform", "example"}, "invalid manifest classification")
        seen.add(row["path"])
        file_path(root, row["path"])
    for surface in inventory["non_package_surfaces"]:
        fields(surface, {"path": str, "status": str}, "non-package surface")
        path = (root / surface["path"]).resolve()
        need(root.resolve() in path.parents and path.exists(), "missing/outside non-package surface: " + surface["path"])


def valid_runs(task, data, current=True):
    """Only exact candidate/contract evidence can satisfy a gate; no model PASS."""
    revisions = {row["contract"]: row["revision"] for row in task["provides"] + task["requires"]}
    if current and (task["target_upstream"] != data["baseline"]["target_upstream"] or
                    any(data["contracts"][cid]["revision"] != rev for cid, rev in revisions.items())):
        return []
    commit = task.get("integrated_commit") if task["state"] == "integrated" else task.get("candidate_commit")
    return [data["evidence"][eid] for eid in task["evidence_ids"]
            if data["evidence"][eid]["result"] == "passed"
            and (not current or (data["evidence"][eid]["validity"] == "current" and data["evidence"][eid].get("_inputs_current", False)))
            and data["evidence"][eid]["kind"] == "acceptance"
            and data["evidence"][eid].get("exit_code") == 0
            and data["evidence"][eid].get("task_id") == task["id"]
            and data["evidence"][eid].get("acceptance_digest") == acceptance_digest(task)
            and data["evidence"][eid]["product_commit"] == commit
            and data["evidence"][eid]["target_upstream"] == task["target_upstream"]
            and all(data["evidence"][eid]["contract_revisions"].get(k) == v for k, v in revisions.items())
            and data["evidence"][eid]["artifacts"]]


def blockers(task, data):
    reasons = []
    if task.get("blocked_reason"):
        reasons.append(task["blocked_reason"])
    for dep in task["requires"]:
        provider = data["tasks"][dep["task"]]
        contract = data["contracts"][dep["contract"]]
        if contract["status"] != "specified" or provider["state"] != "integrated" or not valid_runs(provider, data):
            reasons.append("requires {} {}@{}".format(dep["task"], dep["contract"], dep["revision"]))
    for key, other in data["tasks"].items():
        conflict = key in task["conflicts_with"] or task["id"] in other["conflicts_with"]
        if conflict and other["state"] in {"running", "review", "verified", "queued"}:
            reasons.append("active conflict " + key)
    return reasons


def validate_checkout(data, root):
    need(git(root / "reference", "rev-parse", "HEAD") == data["baseline"]["target_upstream"], "reference HEAD differs from target")
    need(not git(root / "reference", "status", "--porcelain", "--untracked-files=no"), "reference has tracked modifications")
    actual = {r["path"]: r["sha256"] for r in source_inventory(root)}
    recorded = {r["path"]: r["sha256"] for r in data["modules"]["manifests"]}
    need(actual == recorded, "manifest inventory drift: inspect additions/removals/hash changes")
    subprocess.check_call(["git", "-C", str(root), "merge-base", "--is-ancestor",
                           data["baseline"]["product_commit"], "HEAD"])
    for task in data["tasks"].values():
        if task["state"] == "integrated":
            subprocess.check_call(["git", "-C", str(root), "merge-base", "--is-ancestor",
                                   task["integrated_commit"], "HEAD"])


def render_status(data):
    base = data["baseline"]
    counts = Counter(row["classification"] for row in data["modules"]["manifests"])
    lines = ["# Migration status", "", "Generated by scripts/migration.py status; do not edit.", "",
             "- Product baseline: `{}`".format(base["product_commit"]),
             "- Target upstream: `{}`".format(base["target_upstream"]),
             "- Accepted upstream: {}".format(base["accepted_upstream"] or "not established"),
             "- Observed upstream: {}".format(base["observed_upstream"] or "not checked"),
             "- Manifest inventory: {} (includes fixtures; not a module completion count).".format(sum(counts.values())),
             "- Classifications: " + ", ".join("{}={}".format(k, v) for k, v in sorted(counts.items())),
             "- Indexed scenarios: {} (not certified parity).".format(sum(len(m["cases"]) for m in data["mappings"].values())),
             "", "| Task | State | Eligibility / blockers | Next action |", "|---|---|---|---|"]
    for key, task in sorted(data["tasks"].items()):
        reason = "; ".join(blockers(task, data)) or ("eligible" if task["state"] == "ready" else "not ready")
        if task["state"] == "integrated":
            reason = "current acceptance" if valid_runs(task, data) else "historical integration; revalidation required"
        cells = [key, task["state"], reason, task["next_action"]]
        lines.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    lines += ["", "Evidence:", ""]
    for key, run in sorted(data["evidence"].items()):
        validity = "stale-inputs" if not run.get("_inputs_current", True) else run["validity"]
        lines.append("- {}: {} / {} / {}".format(key, run["kind"], run["result"], validity))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "ready", "status", "inventory"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true", help="Write migration/status.md (status command only)")
    args = parser.parse_args(argv)
    try:
        need(not args.write or args.command == "status", "--write is only supported by status")
        if args.command == "inventory":
            print(json.dumps(source_inventory(args.root), ensure_ascii=False, indent=2))
            return 0
        data = load(args.root)
        validate(data, args.root)
        validate_checkout(data, args.root)
        if args.command == "status":
            rendered = render_status(data)
            if args.write:
                path = args.root / "migration/status.md"
                temporary = path.with_suffix(".md.tmp")
                temporary.write_text(rendered, encoding="utf-8")
                temporary.replace(path)
                print("Wrote migration/status.md")
            else:
                print(rendered, end="")
        elif args.command == "ready":
            for key, task in sorted(data["tasks"].items()):
                if task["state"] == "ready" and not blockers(task, data):
                    print(key + ": " + task["goal"])
        else:
            print("Migration records and pinned inventory are valid (not a parity certification).")
        return 0
    except (RecordError, OSError, subprocess.SubprocessError) as exc:
        print("migration: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
