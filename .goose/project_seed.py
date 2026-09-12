"""Discover pinned workspace package and peer dependency graph with provenance."""
import json
from pathlib import Path


def wave(name):
    if name.startswith("vendor/") or name.startswith("util/"):
        return 1
    if name.startswith(("boot/", "typert/")) or name in ("core/scope", "llm/llm"):
        return 2
    if name.startswith("core/"):
        return 4 if name == "core/agent-loop" else 3
    if name == "session/session-persistence":
        return 4
    if name.startswith(("fs/", "subprocess/", "shell/", "llm/", "session/")):
        return 5
    if name.startswith(("api/", "client/", "bundle/", "preset/", "apps/")):
        return 7
    return 6


def discover(root):
    reference = Path(root) / "reference"
    manifests = list(reference.glob("packages/*/*/package.json"))
    manifests += list(reference.glob("vendor/*/package.json"))
    manifests += list(reference.glob("apps/*/package.json"))
    found = {}
    for path in sorted(manifests):
        relative = path.parent.relative_to(reference).as_posix()
        if relative.startswith("packages/experimental/"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        task_id = relative.replace("packages/", "", 1) if relative.startswith("packages/") else relative
        found[data["name"]] = (task_id, path, data)
    tasks, contracts = [], []
    for package, (task_id, path, data) in sorted(found.items()):
        source = path.relative_to(root).as_posix()
        dependencies = []
        consumes = []
        for field in ("dependencies", "peerDependencies"):
            for dep in data.get(field, {}):
                if dep in found:
                    target = found[dep][0]
                    dependencies.append({"task": target, "kind": "implementation" if field == "dependencies" else "contract",
                                         "evidence": source + "#" + field + "/" + dep})
                    consumes.append("package:" + target)
        tasks.append({"id": task_id, "owner": package, "wave": wave(task_id), "priority": 0,
                      "goal": "Verify and port " + package + " public contract and official tests; report runtime dependencies and split missing providers into owned tasks.",
                      "evidence": source, "upstream_paths": [path.parent.relative_to(root).as_posix()],
                      "dependencies": dependencies, "consumes": sorted(set(consumes)),
                      "provides": ["package:" + task_id]})
        contracts.append({"id": "package:" + task_id, "owner": task_id, "evidence": source,
                          "description": "Discovery seed: confirm actual service/events and Python ownership before claiming parity.",
                          "paths": [], "exports": data.get("exports", {})})
    return {"tasks": tasks, "contracts": contracts,
            "notes": ["Package/peer dependency seeds are not a complete runtime graph. Architect must inspect inject/events/config and official tests.",
                      "Experimental packages excluded from official target; add explicit tasks if desired."]}
