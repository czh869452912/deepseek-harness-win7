"""Whole-project Goose scheduling, worktrees and serialized integration. Python 3.8."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import yaml

from parity_runner import Runner, Stream, git, snapshot, changed, safe_path, save_json, run_process, ROOT, SCHEMA, parse_result
from project_store import Store, digest
from project_seed import discover


STRINGS = {"type": "array", "items": {"type": "string"}}
TASK_SCHEMA = {"type": "object", "properties": {
    **{k: {"type": "string"} for k in ("id", "owner", "goal", "evidence")},
    "wave": {"type": "integer"}, "priority": {"type": "integer"},
    "consumes": STRINGS, "provides": STRINGS, "upstream_paths": STRINGS,
    "dependencies": {"type": "array", "items": {"type": "object", "properties": {
        "task": {"type": "string"}, "kind": {"type": "string", "enum": ["implementation", "contract", "acceptance", "change"]},
        "evidence": {"type": "string"}}, "required": ["task", "kind", "evidence"]}}},
    "required": ["id", "owner", "goal", "evidence", "wave", "dependencies", "consumes", "provides"]}
CONTRACT_SCHEMA = {"type": "object", "properties": {
    **{k: {"type": "string"} for k in ("id", "owner", "evidence", "description")}, "paths": STRINGS},
    "required": ["id", "owner", "evidence", "paths"]}
PLAN_SCHEMA = {"type": "object", "properties": {
    "tasks": {"type": "array", "items": TASK_SCHEMA},
    "contracts": {"type": "array", "items": CONTRACT_SCHEMA}}, "required": ["tasks", "contracts"]}
# Optional graph proposals are machine-actionable; old role results remain valid.
SCHEMA["properties"]["work_plan"] = PLAN_SCHEMA


def process_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied means unknown/live.
        try:
            return api.WaitForSingleObject(handle, 0) != 0
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def scheduler_guard(folder):
    lock = folder / "scheduler.lock"
    token = str(os.getpid()) + ":" + str(time.time_ns())
    if lock.exists():
        previous = lock.read_text(encoding="utf-8")
        try:
            pid = int(previous.split(":")[0])
        except ValueError:
            raise ValueError("Unreadable scheduler lock; inspect " + str(lock))
        if process_alive(pid):
            raise ValueError("Project scheduler is active (PID %d); its tasks cannot be reclaimed" % pid)
        if lock.read_text(encoding="utf-8") == previous:
            lock.unlink()
    descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(token)
        yield
    finally:
        if lock.exists() and lock.read_text(encoding="utf-8") == token:
            lock.unlink()


def dashboard(store, folder):
    view = store.view()
    save_json(folder / "status.json", view)
    rows = []
    for task in view["tasks"]:
        live = {}
        if task["run_dir"]:
            status = Path(task["run_dir"]) / "status.json"
            if status.exists():
                live = json.loads(status.read_text(encoding="utf-8"))
        activity = live.get("last_activity", {})
        rows.append("<tr>" + "".join("<td>" + html.escape(str(value)) + "</td>" for value in
                    (task["id"], task["spec"].get("wave"), task["state"],
                     live.get("phase", "") + " / " + live.get("execution_state", ""),
                     activity.get("time", "") + " " + str(activity.get("message", ""))[:500],
                     ", ".join(task["waiting_on"]), task["round"], task["head"] or "",
                     task["error"] or "", task["run_dir"] or "")) + "</tr>")
    body = """<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="10">
    <title>Goose project progress</title><style>body{font:14px system-ui;margin:24px}
    table{border-collapse:collapse;width:100%%}td,th{padding:9px;border:1px solid #ddd;text-align:left}
    td{max-width:28em;overflow-wrap:anywhere}th{background:#eee;position:sticky;top:0}</style>
    <h1>Goose project progress</h1><p>Integrated %d / %d discovered tasks. Refreshes every 10 seconds.
    Discovery may increase the denominator; this is not a fixed completion percentage.</p>
    <table><tr><th>Task</th><th>Wave</th><th>State</th><th>Phase</th><th>Latest activity</th><th>Waiting on</th><th>Round</th>
    <th>Commit</th><th>Reason</th><th>Run artifacts</th></tr>%s</table>""" % (
        sum(t["state"] == "INTEGRATED" for t in view["tasks"]), len(rows), "".join(rows))
    temporary = folder / ("index." + str(time.time_ns()) + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    os.replace(str(temporary), str(folder / "index.html"))
    return view


def worktree(root, path, branch, base):
    if path.exists():
        if git(path, "rev-parse", "--show-toplevel").replace("\\", "/").lower() != path.as_posix().lower():
            raise ValueError("Unexpected worktree path " + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "worktree", "add", "-b", branch, str(path), base], cwd=str(root))
    if (path / ".gitmodules").exists():
        subprocess.check_call(["git", "-c", "protocol.file.allow=always", "submodule", "update", "--init",
                               "--reference", str(root / "reference"), "reference"], cwd=str(path))


class Project:
    def __init__(self, root, goose, jobs=2):
        self.root = root.resolve()
        self.folder = self.root / ".goose/runs/project"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.folder / "state.sqlite3")
        self.goose, self.jobs = goose, jobs
        self.integration_lock = threading.Lock()
        self.display_lock = threading.Lock()
        self.stop = threading.Event()

    def show(self):
        with self.display_lock:
            return dashboard(self.store, self.folder)

    def init(self):
        revision = git(self.root / "reference", "rev-parse", "HEAD")
        existing = self.store.meta("upstream")
        if existing and revision != existing:
            raise ValueError("Pinned upstream changed; create a new project DB or explicitly replan/revalidate")
        if not self.store.rows():
            plan = discover(self.root)
            save_json(self.folder / "seed-plan.json", plan)
            self.store.apply_plan(plan)
            self.store.meta("upstream", revision)
            self.store.meta("base", git(self.root, "rev-parse", "HEAD"))
        elif not (self.folder / "integration").exists() and all(
                r["state"] == "READY" and not r["worktree"] for r in self.store.rows()):
            # init can precede committing the controller itself; freeze the baseline
            # when execution actually starts, then never silently move it.
            self.store.meta("base", git(self.root, "rev-parse", "HEAD"))
        self.show()

    def integration(self):
        path = self.folder / "integration"
        worktree(self.root, path, "codex/parity-integration-" + digest(str(self.root))[:8], self.store.meta("base"))
        return path

    def architect(self):
        """Read-only planning using the same installed Goose, no work quota."""
        self.init()
        before = snapshot(self.root)
        head = git(self.root, "rev-parse", "HEAD")
        index = git(self.root, "diff", "--cached", "--binary")
        path = self.folder / ("architecture-" + str(time.time_ns()) + ".yaml")
        instructions = (self.root / ".agents/agents/parity-architect.md").read_text(encoding="utf-8")
        config = yaml.safe_load((self.root / ".goose/recipes/parity-unit.yaml").read_text(encoding="utf-8"))
        defaults = {p["key"]: p.get("default") for p in config["parameters"]}
        recipe = {"version": "1.0.0", "title": "parity-architect", "description": "Discover project dependencies",
                  "settings": {"goose_provider": defaults["judge_provider"], "goose_model": defaults["judge_model"]},
                  "extensions": [{"type": "platform", "name": x} for x in ("developer", "analyze")],
                  "instructions": instructions + "\nExisting task graph: " + str(self.folder / "status.json") +
                  "\nReturn incremental tasks/contracts using this plan example: " + json.dumps(discover(self.root)["tasks"][:1]) +
                  "\nDependency kinds: implementation, contract, acceptance, change. Every edge needs evidence. "
                  "Every task requires id, owner, goal, evidence, wave, dependencies, consumes, provides. "
                  "Contracts require id, owner(task ID), evidence, paths(Python implementation paths). "
                  "Use work tasks for missing runtime contracts, not package-directory restrictions. "
                  "Do not modify files or Git state. Inspect any relevant code. Do not claim historical verdicts as fresh evidence.",
                  "prompt": "Review the pinned architecture and refine core-first task priorities and cross-module contracts.",
                  "response": {"json_schema": PLAN_SCHEMA}}
        save_json(path, recipe)
        name = path.stem
        command = [self.goose, "run", "--recipe", str(path), "--name", name, "--output-format", "stream-json"]
        continuation = 0
        while True:
            stream = Stream(lambda k, v: print("[architect]", k, v, flush=True))
            log = path.with_suffix(".%d.events.jsonl" % continuation)
            code = run_process(command, self.root, log, stream.notify, 0, stream, cancel_event=self.stop)
            if code or not stream.complete or not stream.action_limit_reached:
                break
            continuation += 1
            command = [self.goose, "run", "--resume", "--name", name, "--output-format", "stream-json",
                       "--text", "Continue architecture planning with your existing context/tools until correct; return the structured plan."]
        if code or not stream.complete or stream.accepted_result is None:
            raise ValueError("Architect did not complete a structured plan; retained its log")
        if (snapshot(self.root) != before or git(self.root, "rev-parse", "HEAD") != head or
                git(self.root, "diff", "--cached", "--binary") != index):
            raise ValueError("Architect mutated worktree; inspect before applying plan")
        plan = stream.accepted_result
        self.store.apply_plan(plan)
        save_json(path.with_suffix(".plan.json"), plan)
        self.store.meta("architecture", self.store.meta("upstream"))
        self.show()

    def task_runner(self, group):
        record = group["records"][0]
        if record["state"] in ("INTEGRATED", "NEEDS_REVALIDATION"):
            record["run_dir"], record["round"] = None, 0
        task_key = digest(group["ids"])[:12]
        path = Path(record["worktree"]) if record["worktree"] else self.folder / "worktrees" / task_key
        with self.integration_lock:
            integration = self.integration()
            base = record["base"] or git(integration, "rev-parse", "HEAD")
            worktree(self.root, path, "codex/parity-task-" + task_key, base)
            saved_paths = {r["worktree"] for r in group["records"] if r["worktree"]}
            previous = json.loads(record["feedback"]) if record["feedback"] else {}
            saved_paths.update(previous.get("pending_sources", []))
            extras = sorted(saved_paths - {str(path)})
            tip = git(integration, "rev-parse", "HEAD")
            if base != tip and not git(path, "status", "--porcelain"):
                path, conflicts = self.candidate(group, path, tip)
                base = tip
                record["run_dir"] = None
                record["round"] = 0
                previous["integration_refresh"] = {"baseline": tip, "conflicts": conflicts,
                    "instruction": "Resolve conflicting source on this combined baseline, preserving both contracts."}
            if extras:
                previous["pending_sources"] = extras
                if not git(path, "status", "--porcelain"):
                    for offset, extra in enumerate(extras):
                        if git(Path(extra), "status", "--porcelain"):
                            raise ValueError("New cyclic group includes unfinished edits; preserve and checkpoint " + extra +
                                             " before consolidating this group")
                        path, conflicts = self.candidate(group, Path(extra), git(path, "rev-parse", "HEAD"))
                        previous["pending_sources"] = extras[offset + 1:]
                        previous["group_consolidation"] = {"source": extra, "conflicts": conflicts}
                        record["run_dir"], record["round"] = None, 0
                        if conflicts:
                            break
            record["feedback"] = json.dumps(previous)
        # Honor saved worktrees and reports. Controller code/config come from the main checkout.
        args = argparse.Namespace(unit="; ".join(group["ids"]), goose=self.goose, max_rounds=0,
                                  max_turns=0, phase_timeout=0, no_commit=False, adopt_existing=True,
                                  cancel_event=self.stop,
                                  control_root=self.root, task_contract={"tasks": group["tasks"],
                                  "guidance": "Verify this task's acceptance contract, not every transitive provider. "
                                  "Missing cross-module owners become work_plan tasks with dependency evidence. "
                                  "Do not hide missing capability with stubs. The project scheduler runs full-suite "
                                  "verification at integration; use targeted tests in this task worktree."})
        agent = Runner(args, root=path)
        original_notify = agent.notify
        def notify(kind, value):
            original_notify(kind, "[" + ", ".join(group["ids"]) + "] " + str(value))
        agent.notify = notify
        if record["run_dir"] and Path(record["run_dir"]).is_dir():
            agent.run_dir = Path(record["run_dir"])
        agent.state["round"] = record["round"]
        self.store.update(group, worktree=str(path), base=base, run_dir=str(agent.run_dir),
                          round=record["round"], feedback=json.loads(record["feedback"]) if record["feedback"] else None)
        return agent

    def cached_phase(self, agent, phase, feedback=None):
        stem = "%02d-%s" % (agent.state["round"], phase)
        result_path = agent.run_dir / (stem + ".result.json")
        if result_path.exists():
            binding = agent.run_dir / (stem + ".binding.json")
            if binding.exists():
                evidence = json.loads(binding.read_text(encoding="utf-8"))
                if (evidence["files"] == snapshot(agent.root) and evidence["scope"] == agent.args.task_contract and
                        (phase == "migrate" or evidence.get("head") == git(agent.root, "rev-parse", "HEAD"))):
                    return parse_result(result_path.read_text(encoding="utf-8"), phase)
            # Current files or acceptance scope changed. Old results are retained, not reused.
            archive = agent.run_dir / (stem + ".stale-" + str(time.time_ns()) + ".json")
            shutil.copyfile(str(result_path), str(archive))
        else:
            # A crash can happen after protocol completion and before result serialization.
            start = agent.run_dir / (stem + ".start.json")
            completion = agent.run_dir / (stem + ".completion.json")
            logs = list(agent.run_dir.glob(stem + "*.events.jsonl"))
            if start.exists() and completion.exists() and logs:
                bound = json.loads(start.read_text(encoding="utf-8"))
                completed = json.loads(completion.read_text(encoding="utf-8"))
                latest = max(logs, key=lambda p: p.stat().st_mtime_ns)
                stream = Stream(lambda *args: None)
                for line in latest.read_text(encoding="utf-8").splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    stream.feed(event)
                files = snapshot(agent.root)
                same_head = bound.get("head") == git(agent.root, "rev-parse", "HEAD")
                same_index = bound.get("index") == git(agent.root, "diff", "--cached", "--binary")
                if (stream.complete and not stream.action_limit_reached and same_head and same_index and
                        completed == {"files": files, "head": bound["head"], "index": bound["index"]} and
                        bound.get("scope") == agent.args.task_contract and
                        (phase == "migrate" or bound["files"] == files)):
                    value = stream.result(phase)
                    value["observed_changes"] = changed(bound["files"], files)
                    if phase == "migrate":
                        value["changed_files"] = sorted(set(value["changed_files"]) | set(value["observed_changes"]))
                        for name in value["changed_files"]:
                            safe_path(agent.root, name)
                    save_json(result_path, value)
                    save_json(agent.run_dir / (stem + ".binding.json"),
                              {"head": bound["head"], "files": files, "scope": agent.args.task_contract})
                    agent.notify("recovered", "Reused completed protocol result for " + phase)
                    return value
        return agent.phase(phase, feedback)

    def execute(self, group):
        try:
            agent = self.task_runner(group)
            record = group["records"][0]
            feedback = json.loads(record["feedback"]) if record["feedback"] else None
            saved_round = agent.state["round"]
            agent.state["round"] = saved_round or 1
            # A READY task with a saved unfinished round resumes phase results, not the whole analysis.
            hashes = self.store.contract_hashes()
            migration = self.cached_phase(agent, "migrate", feedback)
            ok = agent.verify_chunk(migration)
            if ok:
                agent.checkpoint(migration)
            self.store.update(group, round=agent.state["round"], head=git(agent.root, "rev-parse", "HEAD"))
            if feedback and feedback.get("pending_sources"):
                feedback.update(migration=migration, targeted_checks_passed=ok)
                self.store.update(group, "READY", feedback=feedback, round=agent.state["round"] + 1)
                return
            review = self.cached_phase(agent, "review")
            feedback = {"migration": migration, "review": review, "targeted_checks_passed": ok}
            proposal = migration.get("work_plan") or review.get("work_plan")
            if proposal and not self.store.plan_is_current(proposal):
                # Persist proposals, then apply between active waves. Never rewrite a
                # running peer's acceptance scope or repeatedly enqueue an identical plan.
                feedback["proposed_work_plan"] = proposal
                self.store.update(group, "WAITING_PLAN", feedback=feedback, round=agent.state["round"] + 1)
                return
            signature = digest({"issues": sorted(i["id"] for i in review["issues"]), "files": snapshot(agent.root)})
            previous = json.loads(record["feedback"]) if record["feedback"] else {}
            feedback["signature"] = signature
            needs_judge = ("ESCALATE" in (migration["status"], review["status"]) or
                           (review["status"] == "PASS" and bool(migration["issues"])) or
                           ((review["status"] != "PASS" or migration["status"] != "READY" or not ok) and
                            signature == previous.get("signature")))
            if needs_judge:
                judgment = self.cached_phase(agent, "judge", feedback)
                feedback["judgment"] = judgment
                if judgment["status"] == "BLOCKED":
                    self.store.update(group, "NEEDS_ARBITRATION", feedback=feedback, error=judgment["summary"])
                    return
            if review["status"] != "PASS" or migration["status"] != "READY" or not ok or needs_judge:
                self.store.update(group, "READY", feedback=feedback, round=agent.state["round"] + 1)
                return
            if git(agent.root, "status", "--porcelain", "--untracked-files=normal"):
                raise ValueError("Uncommitted task changes remain; cannot bind blind review to a commit")
            head = git(agent.root, "rev-parse", "HEAD")
            self.store.record_evidence(group, self.store.meta("upstream"), head, hashes, review["test_paths"])
            self.store.update(group, "VERIFIED", head=head, feedback=feedback)
            self.merge(group, agent, hashes, review)
        except Exception as error:
            self.store.update(group, "FAILED_INFRA", error=str(error))
            print("[project]", group["ids"], str(error), flush=True)
        finally:
            self.show()

    def candidate(self, group, source, tip):
        """Preserve the source branch; combine all its commits with current integration."""
        path = self.folder / "candidates" / (digest(group["ids"])[:8] + "-" + str(time.time_ns()))
        worktree(self.root, path, "codex/parity-candidate-" + path.name, tip)
        head = git(source, "rev-parse", "HEAD")
        result = subprocess.run(["git", "merge", "--no-ff", "--no-commit", head], cwd=str(path),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
        conflicts = git(path, "diff", "--name-only", "--diff-filter=U").splitlines()
        if result.returncode and not conflicts:
            raise ValueError("Candidate merge failed at " + str(path) + ": " + result.stdout)
        if conflicts:
            # This new controller-owned candidate has no user edits. Keep every merged
            # file/marker while releasing only its index/merge state for agent repair.
            git(path, "reset", "--mixed", "HEAD")
        elif subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=str(path),
                            stdout=subprocess.DEVNULL).returncode == 0:
            git(path, "commit", "-m", "chore(parity): integration candidate " + ", ".join(group["ids"]))
        return path, conflicts

    def apply_proposals(self):
        rows = self.store.rows()
        owners = {r["owner"] for r in rows if r["state"] == "WAITING_PLAN"}
        for owner in owners:
            members = [r for r in rows if r["owner"] == owner]
            group = {"ids": [r["id"] for r in members], "token": owner}
            feedback = members[0]["feedback"]
            try:
                self.store.apply_plan(feedback["proposed_work_plan"])
                feedback["plan_applied"] = True
            except (ValueError, KeyError, TypeError) as error:
                feedback["plan_error"] = str(error)
            self.store.update(group, "READY", feedback=feedback)

    def merge(self, group, agent, hashes, review):
        with self.integration_lock:
            current_hashes = self.store.contract_hashes()
            consumes = {c for t in group["tasks"] for c in t.get("consumes", [])}
            stale = any(hashes.get(c) != current_hashes.get(c) for c in consumes)
            integration = self.integration()
            if git(integration, "status", "--porcelain"):
                raise ValueError("Integration worktree has unresolved changes; preserve and inspect")
            saved = next(r for r in self.store.rows() if r["id"] == group["ids"][0])
            base = saved["base"]
            # Merge in a candidate worktree. Never reset a shared checkout on failure.
            tip = git(integration, "rev-parse", "HEAD")
            candidate, conflicts = self.candidate(group, agent.root, tip)
            if stale or base != tip or conflicts:
                self.store.update(group, "READY", worktree=str(candidate), base=tip, run_dir=None, round=0,
                                  error="Combined baseline needs fresh migration/review",
                                  feedback={"baseline": tip, "conflicts": conflicts, "consumed_contract_changed": stale,
                                            "instruction": "Repair any merge conflicts and verify this combined baseline."})
                return
            # Every merge rechecks the combined baseline; a clean cherry-pick is not semantic evidence.
            code = run_process([sys.executable, "-m", "pytest", "tests"], candidate,
                               candidate / ".goose/runs-integration.log", agent.notify, 0, cancel_event=self.stop)
            if code:
                self.store.update(group, "READY", error="Integration tests failed; continuing repair on combined candidate",
                                  worktree=str(candidate), base=tip, round=agent.state["round"] + 1,
                                  feedback={"candidate": str(candidate), "tests": "tests", "review": review,
                                            "full_suite_failure": (candidate / ".goose/runs-integration.log").read_text(encoding="utf-8")[-40000:]})
                return
            combined = git(candidate, "rev-parse", "HEAD")
            if git(candidate, "status", "--porcelain"):
                raise ValueError("Integration tests modified source/index; retain candidate " + str(candidate))
            if git(integration, "rev-parse", "HEAD") != tip:
                raise ValueError("Integration baseline changed unexpectedly")
            subprocess.check_call(["git", "merge", "--ff-only", combined], cwd=str(integration))
            names = git(candidate, "diff", "--name-only", tip, combined).splitlines()
            tree = snapshot(candidate)
            changes = {name: tree.get(name) for name in names}
            self.store.record_evidence(group, self.store.meta("upstream"), combined, current_hashes,
                                       {"targeted": review["test_paths"], "integration": "python -m pytest tests"})
            self.store.integrate(group, combined, changes, str(candidate))
            print("[integrated]", ",".join(group["ids"]), combined, flush=True)

    def run(self):
        with scheduler_guard(self.folder):
            self.init()
            if self.store.meta("architecture") != self.store.meta("upstream"):
                self.architect()
            with ThreadPoolExecutor(max_workers=self.jobs) as pool:
                running = set()
                try:
                    while True:
                        if not running:
                            self.apply_proposals()
                        # Let active rounds finish before applying proposed dependency changes.
                        waiting_plan = any(r["state"] == "WAITING_PLAN" for r in self.store.rows())
                        while len(running) < self.jobs and not waiting_plan:
                            group = self.store.claim(str(os.getpid()))
                            if not group:
                                break
                            running.add(pool.submit(self.execute, group))
                        self.show()
                        if not running:
                            rows = self.store.rows()
                            complete = bool(rows) and all(r["state"] == "INTEGRATED" for r in rows)
                            print("PROJECT COMPLETE" if complete else "WAITING: inspect task dependencies/errors in " + str(self.folder / "index.html"))
                            return 0 if complete else 2
                        finished, running = wait(running, timeout=15, return_when=FIRST_COMPLETED)
                        for future in finished:
                            future.result()
                except BaseException:
                    self.stop.set()
                    raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "status", "plan", "apply", "run", "recover"])
    parser.add_argument("--goose", default=os.environ.get("GOOSE_EXE", "goose.exe"))
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--task")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("jobs must be positive")
    if sys.version_info[:2] != (3, 8):
        parser.error("Use the repository Python 3.8 interpreter")
    project = Project(ROOT, args.goose, args.jobs)
    if args.command == "status":
        view = project.show()
        print(json.dumps({"tasks": len(view["tasks"]), "dashboard": str(project.folder / "index.html")}, indent=2))
    elif args.command == "run":
        return project.run()
    else:
        with scheduler_guard(project.folder):
            if args.command == "init":
                project.init()
            elif args.command == "plan":
                project.architect()
            elif args.command == "apply":
                if not args.file:
                    parser.error("apply requires --file")
                project.store.apply_plan(json.loads(args.file.read_text(encoding="utf-8")))
            elif args.command == "recover":
                if not args.task:
                    parser.error("recover requires --task")
                project.store.recover(args.task)
            project.show()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
