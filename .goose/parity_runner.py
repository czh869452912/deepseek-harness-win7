"""Observable Goose parity workflow. Python 3.8; development tooling only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLES = {"migrate": "parity-migrator", "review": "parity-reviewer", "judge": "parity-judge"}
STATUSES = {
    "migrate": {"READY", "INCOMPLETE", "ESCALATE"},
    "review": {"PASS", "MUST_FIX", "ESCALATE"},
    "judge": {"RESOLVED", "BLOCKED"},
}
SCOPE = """
The unit is a starting point for dependency discovery, NOT a filesystem boundary.
Read any relevant repository source, upstream dependency, caller, generator or test.
There is no read allowlist, line-range limit, or limit on how often you read a file.
Implement necessary cross-module fixes at their canonical owning service/plugin.
Record each added dependency and why it is necessary. Do not create a reduced
bridge, shim, duplicate implementation or stub merely to stay inside a directory.
An absent Python subsystem is MISSING work, not a platform exclusion. If a full
dependency is too large, report the concrete gap and next chunk; do not fake parity.
Map upstream cases individually with exact titles and Python test locations;
matching case counts alone is not evidence. Existing regression tests may count
if their bodies faithfully map to the upstream case; directory names alone do not
prove or disprove a port. Never weaken assertions or add skipped placeholders.
Do not read credentials or unrelated private files. Do not modify reference/.
The controller handles checkpoint commits and phase transitions. Reports go in the final response,
not source files. Do not read .goose/runs/, .goose/out/, or old review conclusions
during blind review. Review/judge may inspect all dependencies but must not mutate
any worktree file. The migrator may change relevant implementation, tests and docs.
Provide brief visible progress updates (action, finding, next step) while working.
Work until the phase is correct. Return an honest JSON result with remaining gaps
when another role is needed; continue autonomously without asking for continuation.
"""
SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"}, "summary": {"type": "string"},
        "coverage_complete": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "detail": {"type": "string"},
            "evidence": {"type": "string"}}, "required": ["id", "detail", "evidence"]}},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "test_paths": {"type": "array", "items": {"type": "string"}},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "test_map": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary", "coverage_complete", "issues", "changed_files",
                 "test_paths", "dependencies", "test_map"],
}


def save_json(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temp), str(path))


def git(root, *args):
    return subprocess.check_output(["git"] + list(args), cwd=str(root)).decode("utf-8").strip()


def snapshot(root):
    """Hash tracked and nonignored untracked files, including pre-existing edits."""
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=str(root))
    result = {}
    for name in names.decode("utf-8").split("\0"):
        if not name or name.startswith((".goose/runs/", ".goose/out/")):
            continue
        path = root / name
        if path.is_symlink():
            result[name] = "symlink:" + os.readlink(str(path))
        elif path.is_file():
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif path.is_dir() and (path / ".git").exists():
            for child, digest in snapshot(path).items():
                result[name + "/" + child] = digest
        elif not path.exists():
            result[name] = None
    return result


def changed(before, after):
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def dirty_paths(root):
    names = set()
    for args in [("diff", "--name-only", "-z", "HEAD"),
                 ("ls-files", "--others", "--exclude-standard", "-z")]:
        raw = subprocess.check_output(["git"] + list(args), cwd=str(root))
        names.update(filter(None, raw.decode("utf-8").split("\0")))
    return names


def safe_path(root, name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("Paths must be nonempty repository-relative forward-slash paths")
    path = Path(name)
    if path.is_absolute() or any(p in ("..", ".git", ".env") for p in path.parts):
        raise ValueError("Invalid repository path: " + name)
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise ValueError("Path escapes repository: " + name)
    return resolved


def parse_result(text, phase):
    """Only parse the final assistant message, never tool responses or old results."""
    candidates = []
    for match in re.finditer(r"\{", text):
        try:
            value, end = json.JSONDecoder().raw_decode(text[match.start():])
            if isinstance(value, dict) and all(k in value for k in SCHEMA["required"]):
                candidates.append(value)
        except ValueError:
            pass
    if not candidates:
        raise ValueError("No complete structured result; turn limit or interrupted generation")
    value = candidates[-1]
    if value["status"] not in STATUSES[phase] or not isinstance(value["summary"], str):
        raise ValueError("Invalid phase status/summary")
    if not isinstance(value["coverage_complete"], bool):
        raise ValueError("coverage_complete must be boolean")
    for field in ("changed_files", "test_paths", "dependencies", "test_map"):
        if not isinstance(value[field], list) or not all(isinstance(x, str) for x in value[field]):
            raise ValueError("Invalid " + field)
    if not isinstance(value["issues"], list):
        raise ValueError("Invalid issues")
    for issue in value["issues"]:
        if not isinstance(issue, dict) or not all(isinstance(issue.get(k), str) and issue[k]
                                                for k in ("id", "detail", "evidence")):
            raise ValueError("Each issue requires a stable id, detail and evidence")
    if phase == "review" and value["status"] == "PASS":
        if value["issues"] or not value["coverage_complete"] or not value["test_map"]:
            raise ValueError("PASS requires complete case mapping and zero open issues")
    return value


class Stream:
    """Goose stream-json message deltas; exclude thinking and tool-result text."""
    def __init__(self, notify):
        self.notify = notify
        self.messages = {}
        self.last_id = None
        self.complete = False
        self.buffer = ""
        self.action_limit_reached = False

    def feed(self, event):
        if event.get("type") == "complete":
            self.complete = True
            self.flush()
            return
        if event.get("type") == "error":
            raise ValueError("Goose stream error: " + str(event.get("error", event.get("message", "unknown"))))
        message = event.get("message", {})
        if message.get("role") != "assistant":
            return
        for block in message.get("content", []):
            if block.get("type") == "text":
                mid = message.get("id", "assistant")
                self.last_id = mid
                text = block.get("text", "")
                self.messages[mid] = self.messages.get(mid, "") + text
                if "I've reached the maximum number of actions I can do without user input" in self.messages[mid]:
                    self.action_limit_reached = True
                self.buffer += text
                if "\n" in self.buffer or len(self.buffer) > 240:
                    self.flush()
            elif block.get("type") == "toolRequest":
                self.flush()
                call = block.get("toolCall", {}).get("value", {})
                args = call.get("arguments", {})
                description = args.get("command", args.get("path", ""))
                self.notify("tool", call.get("name", "tool") + " " + str(description)[:180])

    def flush(self):
        if self.buffer.strip():
            self.notify("agent", self.buffer.strip())
        self.buffer = ""

    def result(self, phase):
        self.flush()
        if not self.complete:
            raise ValueError("Goose stopped without a complete event")
        return parse_result(self.messages.get(self.last_id, ""), phase)


def stop_process(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_process(command, root, log_path, notify, timeout, stream=None):
    """Drain output on a reader thread, so quiet tools still get timed heartbeats."""
    proc = subprocess.Popen(command, cwd=str(root), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            encoding="utf-8", errors="replace", bufsize=1)
    lines = queue.Queue()

    def read():
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    started = last_activity = last_heartbeat = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8") as log:
            while True:
                now = time.monotonic()
                if timeout and now - started >= timeout:
                    raise TimeoutError("Phase wall-time limit reached; child process tree stopped")
                if now - last_heartbeat >= 15:
                    notify("heartbeat", "running %.0fs; output idle %.0fs (not proof of deadlock)" %
                           (now - started, now - last_activity))
                    last_heartbeat = now
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    continue
                if line is None:
                    break
                last_activity = time.monotonic()
                if stream:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        # Startup banners and stderr are useful, but not model results.
                        log.write(line)
                        log.flush()
                        continue
                    msg = event.get("message", {})
                    if "content" in msg:
                        msg["content"] = [b for b in msg["content"]
                                          if b.get("type") not in ("thinking", "redactedThinking")]
                    log.write(json.dumps(event, ensure_ascii=False) + "\n")
                    stream.feed(event)
                else:
                    log.write(line)
                    notify("check", line.rstrip())
                log.flush()
        return proc.wait(timeout=5)
    finally:
        stop_process(proc)
        proc.stdout.close()
        reader.join(timeout=2)


class Runner:
    def __init__(self, args, root=ROOT):
        self.args, self.root = args, root
        self.run_dir = root / ".goose/runs" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        self.run_dir.mkdir(parents=True)
        self.state = {"unit": args.unit, "status": "RUNNING", "phase": "startup", "round": 0,
                      "max_rounds": args.max_rounds, "issues": [], "commits": [], "history": []}
        self.initial_dirty = dirty_paths(root)
        self.start_head = git(root, "rev-parse", "HEAD")
        self.config = yaml.safe_load((root / ".goose/recipes/parity-unit.yaml").read_text(encoding="utf-8"))
        self.defaults = {p["key"]: p.get("default") for p in self.config["parameters"]}

    def notify(self, kind, message):
        record = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "phase": self.state["phase"],
                  "round": self.state["round"], "kind": kind, "message": message}
        print("[{time}] [{phase} {round}] {kind}: {message}".format(**record), flush=True)
        with (self.run_dir / "progress.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.state["last_activity"] = record
        save_json(self.run_dir / "status.json", self.state)

    def phase(self, phase, feedback=None):
        self.state["phase"] = phase
        role = ROLES[phase]
        prefix = {"migrate": "migrator", "review": "reviewer", "judge": "judge"}[phase]
        provider, model = (self.defaults[prefix + "_" + x] for x in ("provider", "model"))
        body = (self.root / (".agents/agents/" + role + ".md")).read_text(encoding="utf-8")
        body = body.split("---", 2)[-1]
        prompt = "Unit: " + self.args.unit + "\n" + SCOPE
        prompt += "\nThis controller contract replaces the agent's final text-block format and full-suite step. "
        prompt += "The controller runs targeted tests after each chunk and the full suite at the final gate. "
        prompt += "Return one final JSON object matching the schema. Allowed status: " + ", ".join(sorted(STATUSES[phase]))
        prompt += ". Issues use stable upstream-path + case/invariant identifiers, with evidence. "
        prompt += "test_paths must be existing repository-relative pytest paths under tests/ (no flags). "
        prompt += "test_map records exact upstream case titles -> Python locations -> classification. "
        if feedback and phase != "review":
            prompt += "\nContinuation evidence (verify against source; preserve completed work):\n" + json.dumps(feedback, ensure_ascii=False)
        prompt += "\nDo not commit. Existing uncommitted work must be inspected and preserved."
        if self.args.adopt_existing and phase == "migrate":
            prompt += "\nThe user selected adoption of prior work: include verified prior migration files in changed_files, even if unchanged this round."
        turns = self.args.max_turns
        recipe = {"version": "1.0.0", "title": role, "description": "Parity " + phase,
                  "settings": {"goose_provider": provider, "goose_model": model},
                  "extensions": [{"type": "platform", "name": x} for x in ("developer", "analyze")],
                  "instructions": body + "\n\n" + prompt,
                  "prompt": "Execute this phase and return its structured result.",
                  "response": {"json_schema": SCHEMA}}
        if turns:
            recipe["settings"]["max_turns"] = turns
        stem = "%02d-%s" % (self.state["round"], phase)
        recipe_path = self.run_dir / (stem + ".yaml")
        save_json(recipe_path, recipe)  # JSON is valid YAML; no templated shell commands.
        self.notify("start", role + " / " + provider + " / " + model)
        before = snapshot(self.root)
        head = git(self.root, "rev-parse", "HEAD")
        index = git(self.root, "diff", "--cached", "--binary")
        stream = Stream(self.notify)
        session_name = self.run_dir.name + "-" + stem
        started = time.monotonic()
        command = [self.args.goose, "run", "--recipe", str(recipe_path),
                   "--name", session_name, "--output-format", "stream-json"]
        if turns:
            command += ["--max-turns", str(turns)]
        continuation = 0
        while True:
            log_name = stem + (".continue-%d" % continuation if continuation else "") + ".events.jsonl"
            remaining = self.args.phase_timeout
            if remaining:
                remaining -= time.monotonic() - started
                if remaining <= 0:
                    raise TimeoutError("Explicit phase timeout reached")
            code = run_process(command, self.root, self.run_dir / log_name,
                               self.notify, remaining, stream)
            if code or not stream.complete or not stream.action_limit_reached or turns:
                break
            continuation += 1
            self.notify("continue", "Goose native action limit reached; resuming the same session with its tools")
            stream = Stream(self.notify)
            command = [self.args.goose, "run", "--resume", "--name", session_name,
                       "--output-format", "stream-json", "--text",
                       "Continue the current phase with your existing context and tools. "
                       "Work until correct; do not restart completed analysis or ask for permission to continue. "
                       "Return the required structured result when this phase is done."]
        after = snapshot(self.root)
        changes = changed(before, after)
        if git(self.root, "rev-parse", "HEAD") != head:
            self.notify("git", "Agent updated HEAD; preserving the commit")
        if git(self.root, "diff", "--cached", "--binary") != index:
            self.notify("git", "Agent updated the index; automatic checkpoint will preserve staged work")
        if phase != "migrate" and changes:
            raise ValueError("Read-only phase mutated files; preserved for inspection: " + ", ".join(changes))
        if code:
            raise ValueError("Goose exited with code " + str(code))
        result = stream.result(phase)
        result["observed_changes"] = changes
        if phase == "migrate":
            for name in result["changed_files"]:
                safe_path(self.root, name)
            missing = set(changes) - set(result["changed_files"])
            if missing:
                self.notify("files", "Including observed changes omitted from report: " + ", ".join(sorted(missing)))
                result["changed_files"] = sorted(set(result["changed_files"]) | missing)
        save_json(self.run_dir / (stem + ".result.json"), result)
        self.state["history"].append({"phase": phase, "round": self.state["round"],
                                      "status": result["status"], "issues": len(result["issues"])})
        self.notify("result", result["status"] + ": " + result["summary"])
        for dependency in result["dependencies"]:
            self.notify("dependency", dependency)
        return result

    def check(self, name, args):
        self.state["phase"] = name
        self.notify("start", " ".join(args))
        code = run_process([sys.executable] + args, self.root,
                           self.run_dir / ("%02d-%s.log" % (self.state["round"], name)),
                           self.notify, self.args.phase_timeout)
        self.notify("result", "exit=" + str(code))
        return code == 0

    def verify_chunk(self, result):
        paths = result["test_paths"]
        if not paths:
            self.notify("verification", "No targeted test paths: no checkpoint")
            return False
        for name in paths:
            path = safe_path(self.root, name)
            if not name.startswith("tests/") or not path.exists() or "::" in name:
                raise ValueError("Invalid pytest path: " + name)
        if not self.check("targeted", ["-m", "pytest"] + paths + ["-q"]):
            return False
        files = [name for name in result["changed_files"] if name.endswith(".py")
                 and (self.root / name).is_file()]
        if files and not self.check("compile", ["-m", "compileall", "-q"] + files):
            return False
        return True

    def checkpoint(self, result):
        paths = set(result["observed_changes"])
        if self.args.adopt_existing:
            paths.update(set(result["changed_files"]) & self.initial_dirty)
        paths = sorted(paths)
        if not paths or self.args.no_commit:
            self.notify("checkpoint", "No changes or -NoCommit selected")
            return
        overlap = set(paths) & self.initial_dirty
        if overlap and not self.args.adopt_existing:
            self.notify("checkpoint", "SKIPPED: pre-existing edits in " + ", ".join(sorted(overlap)) +
                        "; use -AdoptExisting on the next run to include prior migration work")
            return
        if git(self.root, "diff", "--cached", "--name-only"):
            self.notify("checkpoint", "SKIPPED: existing staged changes; index preserved")
            return
        for name in paths:
            safe_path(self.root, name)
        git(self.root, "add", "--", *paths)
        try:
            git(self.root, "commit", "-m", "chore(parity): checkpoint %s round %d (unreviewed)" %
                (self.args.unit, self.state["round"]))
        except subprocess.CalledProcessError:
            self.notify("checkpoint", "Commit failed; staged files retained for inspection")
            raise
        commit = git(self.root, "rev-parse", "HEAD")
        self.state["commits"].append(commit)
        self.initial_dirty.difference_update(paths)
        self.notify("checkpoint", commit + " — targeted tests passed; NOT a parity-complete claim")

    def finish(self, status, reason):
        self.state.update(status=status, reason=reason)
        self.notify("finish", status + ": " + reason)
        self.notify("artifacts", str(self.run_dir / "status.json"))
        return 0 if status == "COMPLETE" else 2

    def run(self):
        feedback = None
        last_signature = None
        try:
            self.notify("artifacts", str(self.run_dir))
            round_number = 0
            while not self.args.max_rounds or round_number < self.args.max_rounds:
                round_number += 1
                self.state["round"] = round_number
                migration = self.phase("migrate", feedback)
                verified = self.verify_chunk(migration)
                if verified:
                    self.checkpoint(migration)
                review = self.phase("review")  # No migration or previous review evidence is passed.
                self.state["issues"] = review["issues"]
                self.notify("progress", "round %d/%s; open issues=%d; coverage_complete=%s" %
                            (round_number, self.args.max_rounds or "unlimited", len(review["issues"]), review["coverage_complete"]))
                needs_judge = ("ESCALATE" in (migration["status"], review["status"]) or
                               (review["status"] == "PASS" and bool(migration["issues"])))
                if review["status"] == "PASS" and verified and not needs_judge:
                    if self.check("full-suite", ["-m", "pytest", "tests"]):
                        return self.finish("COMPLETE", "Independent review and full test suite passed")
                    log = self.run_dir / ("%02d-full-suite.log" % round_number)
                    feedback = {"migration": migration, "review": review,
                                "full_suite_failure": log.read_text(encoding="utf-8")[-40000:]}
                    self.notify("repair", "Full suite failed; returning failures to migrator for correction")
                    continue
                feedback = {"migration": migration, "review": review, "targeted_checks_passed": verified}
                signature = (tuple(sorted(i["id"] for i in review["issues"])),
                             tuple(sorted(snapshot(self.root).items())))
                if signature == last_signature:
                    self.notify("progress", "Same findings and files; requesting arbitration to change approach")
                    needs_judge = True
                last_signature = signature
                if needs_judge:
                    judgment = self.phase("judge", feedback)
                    if judgment["status"] == "BLOCKED":
                        return self.finish("BLOCKED", judgment["summary"])
                    feedback["judgment"] = judgment
            return self.finish("INCOMPLETE", "Round budget exhausted; retained results and checkpoints. No silent continuation.")
        except KeyboardInterrupt:
            return self.finish("INTERRUPTED", "Interrupted; child process stopped and changes preserved")
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            return self.finish("BLOCKED", str(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--goose", required=True)
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--max-turns", type=int, default=0)
    parser.add_argument("--phase-timeout", type=int, default=0)
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--adopt-existing", action="store_true")
    args = parser.parse_args()
    if min(args.max_rounds, args.max_turns, args.phase_timeout) < 0:
        parser.error("Limits must be nonnegative; zero means unlimited")
    if sys.version_info[:2] != (3, 8):
        parser.error("Use the repository Python 3.8 interpreter for compile/test verification")
    lock = ROOT / ".goose/runs/active.lock"
    lock.parent.mkdir(exist_ok=True)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        parser.error("Another run owns .goose/runs/active.lock; check its PID before removing a stale lock")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(str(os.getpid()))
        return Runner(args).run()
    finally:
        lock.unlink()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
