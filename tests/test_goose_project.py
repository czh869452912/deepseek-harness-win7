"""Project scheduling regressions, including real Git/worktrees and child processes."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys

import pytest


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / ".goose"))
try:
    import project_runner as project
    from project_store import Store
    from project_seed import discover
finally:
    sys.path.pop(0)


def task(name, dependencies=(), wave=3):
    return {"id": name, "owner": name, "goal": "Port " + name, "evidence": "reference/" + name,
            "wave": wave, "priority": 0, "dependencies": [
                {"task": d, "kind": "implementation", "evidence": "source import"} for d in dependencies],
            "provides": [name], "consumes": list(dependencies)}


def plan(*tasks):
    return {"tasks": list(tasks), "contracts": [
        {"id": t["id"], "owner": t["id"], "evidence": t["evidence"], "paths": [t["id"] + ".py"]}
        for t in tasks]}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "state.db")


def test_priority_dependencies_and_cycle_are_scheduled_atomically(store):
    store.apply_plan(plan(task("plugin", ["a"], wave=7), task("a", ["b"]), task("b", ["a"]), task("util", wave=1)))
    first = store.claim("1")
    assert first["ids"] == ["util"]
    second = store.claim("2")
    assert second["ids"] == ["a", "b"]
    assert store.claim("3") is None
    store.integrate(second, "abc", {"a.py": "hash"})
    assert store.claim("3")["ids"] == ["plugin"]


def test_claim_is_transactional_and_survives_restart(store):
    store.apply_plan(plan(task("a")))
    with ThreadPoolExecutor(2) as pool:
        groups = list(pool.map(lambda n: Store(store.path).claim(str(n)), [1, 2]))
    assert sum(g is not None for g in groups) == 1
    group = next(g for g in groups if g)
    store.update(group, worktree="kept", run_dir="logs", round=2)
    restarted = Store(store.path)
    assert restarted.claim("new") is None
    restarted.recover("a")
    resumed = restarted.claim("new")
    assert resumed["records"][0]["worktree"] == "kept"
    assert resumed["records"][0]["round"] == 2
    with pytest.raises(ValueError, match="ownership"):
        store.update(group, "INTEGRATED")


def test_plan_validation_rolls_back_and_consumed_contract_creates_edge(store):
    a, b = task("a"), task("b")
    b["consumes"] = ["a"]
    store.apply_plan(plan(a, b))
    assert store.view()["tasks"][1]["waiting_on"] == ["a"]
    broken = task("c", ["unknown"])
    with pytest.raises(ValueError, match="Unknown dependency"):
        store.apply_plan(plan(task("new"), broken))
    assert [r["id"] for r in store.rows()] == ["a", "b"]


def test_provider_changes_invalidate_transitive_consumers_not_unrelated(store):
    original = plan(task("a"), task("b", ["a"]), task("c", ["b"]), task("z"))
    store.apply_plan(original)
    for _ in range(4):
        group = store.claim("worker")
        store.integrate(group, "baseline", {})
    store.recover("a")
    group = store.claim("worker")
    store.integrate(group, "new", {"a.py": "new hash"})
    states = {r["id"]: r["state"] for r in store.rows()}
    assert states == {"a": "INTEGRATED", "b": "NEEDS_REVALIDATION", "c": "NEEDS_REVALIDATION", "z": "INTEGRATED"}
    hashes = store.contract_hashes()
    store.apply_plan(original)
    assert store.contract_hashes() == hashes  # Replanning preserves controller implementation hashes.


def test_task_acceptance_change_invalidates_downstream(store):
    store.apply_plan(plan(task("a"), task("b", ["a"])))
    for _ in range(2):
        store.integrate(store.claim("w"), "old", {})
    revised = task("a")
    revised["goal"] = "Additional invariant"
    store.apply_plan(plan(revised))
    assert all(r["state"] == "NEEDS_REVALIDATION" for r in store.rows())


def test_scheduler_lock_never_reclaims_live_owner(tmp_path):
    with project.scheduler_guard(tmp_path):
        with pytest.raises(ValueError, match="active"):
            with project.scheduler_guard(tmp_path):
                pytest.fail("Must not acquire")
    assert not (tmp_path / "scheduler.lock").exists()


@pytest.fixture
def repo(tmp_path):
    project.git(tmp_path, "init", "-q")
    project.git(tmp_path, "config", "user.name", "Test")
    project.git(tmp_path, "config", "user.email", "test@example.invalid")
    for name in [".goose/recipes/parity-unit.yaml"] + [
            ".agents/agents/" + role + ".md" for role in ("parity-migrator", "parity-reviewer", "parity-judge", "parity-architect")]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(SOURCE / name), str(target))
    (tmp_path / ".gitignore").write_text(".goose/runs/\n*.log\n__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    for name in ("a", "b"):
        (tmp_path / (name + ".py")).write_text("value = 0\n", encoding="utf-8")
        (tmp_path / ("tests/test_" + name + ".py")).write_text(
            "from pathlib import Path\ndef test_value():\n    assert Path('" + name + ".py').read_text().strip() == 'value = 0'\n", encoding="utf-8")
    project.git(tmp_path, "add", ".")
    project.git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


def make_project(repo):
    p = project.Project(repo, "unused", jobs=2)
    p.store.meta("base", project.git(repo, "rev-parse", "HEAD"))
    p.store.meta("upstream", "pinned-fixture")
    p.store.meta("architecture", "pinned-fixture")
    p.init = lambda: None
    return p


def test_new_baseline_merges_source_and_requeues_for_fresh_review(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    agent = p.task_runner(group)
    (agent.root / "a.py").write_text("value = 1\n", encoding="utf-8")
    project.git(agent.root, "commit", "-am", "task change")
    integration = p.integration()
    (integration / "b.py").write_text("value = 2\n", encoding="utf-8")
    project.git(integration, "commit", "-am", "independent change")
    tip = project.git(integration, "rev-parse", "HEAD")
    p.merge(group, agent, p.store.contract_hashes(), {"test_paths": []})
    saved = p.store.rows()[0]
    assert saved["state"] == "READY"
    candidate = Path(saved["worktree"])
    assert (candidate / "a.py").read_text().strip() == "value = 1"
    assert (candidate / "b.py").read_text().strip() == "value = 2"
    assert project.git(integration, "rev-parse", "HEAD") == tip
    assert saved["run_dir"] is None


def test_merge_conflicts_are_preserved_for_repair(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    agent = p.task_runner(group)
    (agent.root / "a.py").write_text("value = 1\n", encoding="utf-8")
    project.git(agent.root, "commit", "-am", "worker change")
    integration = p.integration()
    (integration / "a.py").write_text("value = 2\n", encoding="utf-8")
    project.git(integration, "commit", "-am", "provider change")
    p.merge(group, agent, p.store.contract_hashes(), {"test_paths": []})
    saved = p.store.rows()[0]
    assert saved["state"] == "READY"
    assert saved["feedback"]["conflicts"] == ["a.py"]
    assert "<<<<<<<" in (Path(saved["worktree"]) / "a.py").read_text()
    assert (agent.root / "a.py").read_text().strip() == "value = 1"
    assert (integration / "a.py").read_text().strip() == "value = 2"


@pytest.mark.skipif(os.name != "nt", reason="Windows fake CLI")
def test_parallel_end_to_end_integrates_only_reviewed_tested_commits(repo):
    script = repo / "fake.py"
    script.write_text('''import json,re,sys
from pathlib import Path
args = sys.argv
recipe = json.loads(Path(args[args.index('--recipe')+1]).read_text(encoding='utf-8'))
name = re.search(r'Unit: (.*?)\\n', recipe['instructions']).group(1)
phase = recipe['title']
paths = [name+'.py', 'tests/test_'+name+'.py']
if phase == 'parity-migrator':
    Path(paths[0]).write_text('value = 1\\n', encoding='utf-8')
    Path(paths[1]).write_text("from pathlib import Path\\ndef test_value():\\n    assert Path('"+name+".py').read_text().strip() == 'value = 1'\\n", encoding='utf-8')
else:
    assert Path(paths[0]).read_text().strip() == 'value = 1'
    assert 'Continuation evidence' not in recipe['instructions']
value = dict(status='READY' if phase == 'parity-migrator' else 'PASS', summary='verified',
             coverage_complete=True, issues=[], changed_files=paths if phase == 'parity-migrator' else [],
             test_paths=[paths[1]], dependencies=[], test_map=['upstream invariant -> '+paths[1]])
print(json.dumps({'type':'message','message':{'role':'assistant','id':'final','content':[{'type':'text','text':json.dumps(value)}]}}),flush=True)
print(json.dumps({'type':'complete'}),flush=True)
''', encoding="utf-8")
    executable = repo / "fake.cmd"
    executable.write_text('@echo off\n"' + sys.executable + '" "' + str(script) + '" %*\n', encoding="utf-8")
    project.git(repo, "add", ".")
    project.git(repo, "commit", "-qm", "fake CLI fixture")
    original = project.git(repo, "rev-parse", "HEAD")
    p = make_project(repo)
    p.goose = str(executable)
    p.store.apply_plan(plan(task("a"), task("b")))
    assert p.run() == 0
    assert all(r["state"] == "INTEGRATED" for r in p.store.rows())
    integration = p.integration()
    for name in ("a", "b"):
        assert (integration / (name + ".py")).read_text().strip() == "value = 1"
        assert (repo / (name + ".py")).read_text().strip() == "value = 0"
    assert project.git(repo, "rev-parse", "HEAD") == original
    with p.store.connect() as db:
        assert db.execute("SELECT count(*) FROM evidence").fetchone()[0] == 2
    assert not (p.folder / "scheduler.lock").exists()


def test_completed_result_recovery_is_bound_to_files_and_commit(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    agent = p.task_runner(group)
    agent.state["round"] = 1
    value = {"status": "PASS", "summary": "checked", "coverage_complete": True, "issues": [],
             "changed_files": [], "test_paths": ["tests/test_a.py"], "dependencies": [], "test_map": ["case -> tests/test_a.py"]}
    bound = {"head": project.git(agent.root, "rev-parse", "HEAD"), "files": project.snapshot(agent.root),
             "index": "", "scope": agent.args.task_contract}
    project.save_json(agent.run_dir / "01-review.start.json", bound)
    project.save_json(agent.run_dir / "01-review.completion.json", {k: bound[k] for k in ("head", "files", "index")})
    events = [{"type": "message", "message": {"role": "assistant", "id": "final", "content": [
        {"type": "text", "text": json.dumps(value)}]}}, {"type": "complete"}]
    (agent.run_dir / "01-review.events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    agent.phase = lambda *args: pytest.fail("Completed review should be recovered")
    assert p.cached_phase(agent, "review")["status"] == "PASS"
    (agent.root / "a.py").write_text("changed\n", encoding="utf-8")
    agent.phase = lambda *args: {"status": "fresh"}
    assert p.cached_phase(agent, "review")["status"] == "fresh"


def test_new_cycle_consolidates_both_existing_clean_worktrees(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a"), task("b")))
    for name in ("a", "b"):
        group = p.store.claim("w")
        assert group["ids"] == [name]
        agent = p.task_runner(group)
        (agent.root / (name + ".py")).write_text("value = 1\n", encoding="utf-8")
        project.git(agent.root, "commit", "-am", "saved " + name)
        p.store.update(group, "VERIFIED")
    p.store.apply_plan(plan(task("a", ["b"]), task("b", ["a"])))
    combined = p.store.claim("w")
    assert combined["ids"] == ["a", "b"]
    agent = p.task_runner(combined)
    assert (agent.root / "a.py").read_text().strip() == "value = 1"
    assert (agent.root / "b.py").read_text().strip() == "value = 1"
    assert not project.git(agent.root, "status", "--porcelain")


def test_integration_failure_requeues_combined_candidate_for_repair(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    agent = p.task_runner(group)
    (agent.root / "a.py").write_text("value = 1\n", encoding="utf-8")
    project.git(agent.root, "commit", "-am", "targeted change")
    def failed_check(command, root, log, *args, **kwargs):
        log.write_text("FAILED integration invariant", encoding="utf-8")
        return 1
    monkeypatch.setattr(project, "run_process", failed_check)
    tip = project.git(p.integration(), "rev-parse", "HEAD")
    p.merge(group, agent, p.store.contract_hashes(), {"test_paths": ["tests/test_a.py"]})
    row = p.store.rows()[0]
    assert row["state"] == "READY"
    assert "FAILED integration invariant" in row["feedback"]["full_suite_failure"]
    assert project.git(p.integration(), "rev-parse", "HEAD") == tip


def test_cross_owner_implementation_change_invalidates_actual_contract_owner(store):
    store.apply_plan(plan(task("a"), task("b", ["a"]), task("z")))
    groups = {}
    for _ in range(3):
        group = store.claim("w")
        groups[group["ids"][0]] = group
        store.integrate(group, "old", {})
    store.recover("z")
    group = store.claim("w")
    store.integrate(group, "new", {"a.py": "cross-module repair"})
    states = {r["id"]: r["state"] for r in store.rows()}
    assert states["a"] == states["b"] == "NEEDS_REVALIDATION"
    assert states["z"] == "INTEGRATED"


def test_incremental_plan_errors_return_to_proposer_and_valid_plans_create_dependencies(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    p.store.update(group, "WAITING_PLAN", feedback={"proposed_work_plan": plan(task("a", ["unknown"]))})
    p.apply_proposals()
    row = p.store.rows()[0]
    assert row["state"] == "READY"
    assert "Unknown dependency" in row["feedback"]["plan_error"]
    group = p.store.claim("w")
    proposed = plan(task("a", ["b"]), task("b"))
    p.store.update(group, "WAITING_PLAN", feedback={"proposed_work_plan": proposed})
    p.apply_proposals()
    assert p.store.claim("w")["ids"] == ["b"]
    assert p.store.plan_is_current(proposed)


def test_architect_resumes_native_stop_and_applies_acknowledged_plan(repo, monkeypatch):
    p = make_project(repo)
    calls = []
    proposed = plan(task("a"))
    def process(command, root, log, notify, timeout, stream, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            assert "--recipe" in command and "--max-turns" not in command
            text = "I've reached the maximum number of actions I can do without user input"
            stream.feed({"type": "message", "message": {"id": "limit", "role": "assistant", "content": [
                {"type": "text", "text": text}]}})
        else:
            assert "--resume" in command
            stream.feed({"type": "message", "message": {"role": "assistant", "content": [
                {"type": "toolRequest", "id": "plan", "toolCall": {"value": {
                    "name": "recipe__final_output", "arguments": proposed}}}]}})
            stream.feed({"type": "message", "message": {"role": "user", "content": [
                {"type": "toolResponse", "id": "plan", "toolResult": {"status": "success", "value": {}}}]}})
        stream.feed({"type": "complete"})
        return 0
    monkeypatch.setattr(project, "run_process", process)
    before = project.git(repo, "rev-parse", "HEAD")
    p.architect()
    assert len(calls) == 2
    assert p.store.plan_is_current(proposed)
    assert p.store.meta("architecture") == "pinned-fixture"
    assert project.git(repo, "rev-parse", "HEAD") == before


def test_architect_repairs_saved_invalid_plan_in_original_session(repo, monkeypatch):
    p = make_project(repo)
    p.store.meta("architecture", "not-planned")
    invalid = plan(task("a"))
    invalid["tasks"][0]["provides"] += ["contract:branded-identifiers", "contract:settings"]
    valid = json.loads(json.dumps(invalid))
    valid["contracts"] += [{"id": cid, "owner": "a", "evidence": "reference/a.py", "paths": ["a.py"]}
                           for cid in invalid["tasks"][0]["provides"][1:]]
    recipe = p.folder / "architecture-123.yaml"
    recipe.write_text("{}", encoding="utf-8")
    project.save_json(p.folder / "architecture-123.0.events.accepted.json", invalid)
    (p.folder / "architecture-123.0.events.jsonl").write_text('{"type":"complete"}\n', encoding="utf-8")
    calls = []
    def repair(command, root, log, notify, timeout, stream, **kwargs):
        calls.append(command)
        assert "--resume" in command and command[command.index("--name") + 1] == "architecture-123"
        assert "contract:branded-identifiers" in command[-1] and "contract:settings" in command[-1]
        assert p.store.rows() == []  # The rejected plan was not partially applied.
        stream.accepted_result = valid
        stream.complete = True
        return 0
    monkeypatch.setattr(project, "run_process", repair)
    p.architect()
    assert len(calls) == 1
    assert p.store.plan_is_current(valid)
    assert not (p.folder / "architecture-pending.json").exists()
    assert json.loads((p.folder / "architecture-status.json").read_text())["state"] == "APPLIED"


def test_architect_requests_tool_submission_after_text_only_completion(repo, monkeypatch):
    p = make_project(repo)
    p.store.meta("architecture", "not-planned")
    invalid = plan(task("a"))
    invalid["tasks"][0]["provides"] += ["contract:ghost"]
    valid = json.loads(json.dumps(invalid))
    valid["tasks"][0]["provides"].remove("contract:ghost")
    recipe = p.folder / "architecture-123.yaml"
    recipe.write_text("{}", encoding="utf-8")
    project.save_json(p.folder / "architecture-123.0.events.accepted.json", invalid)
    (p.folder / "architecture-123.0.events.jsonl").write_text('{"type":"complete"}\n', encoding="utf-8")
    project.save_json(p.folder / "architecture-pending.json",
                      {"recipe": str(recipe), "upstream": "pinned-fixture"})
    calls = []
    def process(command, root, log, notify, timeout, stream, **kwargs):
        calls.append(command)
        stream.complete = True
        if len(calls) == 1:
            assert "recipe__final_output" in command[-1]  # plan-rejection repair prompt
            return 0  # session finished but answered with plain text, no tool result
        assert "arrived as plain text" in command[-1]
        stream.accepted_result = valid
        return 0
    monkeypatch.setattr(project, "run_process", process)
    p.architect()
    assert len(calls) == 2
    assert p.store.plan_is_current(valid)
    assert not (p.folder / "architecture-pending.json").exists()
    assert json.loads((p.folder / "architecture-status.json").read_text())["state"] == "APPLIED"


def test_architect_applies_plan_recovered_from_text_when_tool_result_missing(repo, monkeypatch):
    p = make_project(repo)
    expected = plan(task("a"))
    calls = []
    def process(command, root, log, notify, timeout, stream, **kwargs):
        calls.append(command)
        stream.complete = True
        stream.messages["m1"] = "The plan follows: " + json.dumps(expected) + " Thank you."
        return 0
def test_architect_applies_plan_recovered_from_text_when_tool_result_missing(repo, monkeypatch):
    p = make_project(repo)
    expected = plan(task("a"))
    calls = []
    def process(command, root, log, notify, timeout, stream, **kwargs):
        calls.append(command)
        stream.complete = True
        stream.messages["m1"] = "The plan follows: " + json.dumps(expected) + " Thank you."
        return 0
    monkeypatch.setattr(project, "run_process", process)
    p.architect()
    assert len(calls) == 1
    assert p.store.plan_is_current(expected)
    assert not (p.folder / "architecture-pending.json").exists()
    assert json.loads((p.folder / "architecture-status.json").read_text())["state"] == "APPLIED"


def test_worktree_inits_submodule_offline_from_local_module_store(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    project.git(upstream, "init", "-q")
    project.git(upstream, "config", "user.name", "Test")
    project.git(upstream, "config", "user.email", "test@example.invalid")
    (upstream / "marker.txt").write_text("pinned", encoding="utf-8")
    project.git(upstream, "add", ".")
    project.git(upstream, "commit", "-qm", "sub")
    main = tmp_path / "main"
    main.mkdir()
    project.git(main, "init", "-q")
    project.git(main, "config", "user.name", "Test")
    project.git(main, "config", "user.email", "test@example.invalid")
    project.git(main, "commit", "-qm", "base", "--allow-empty")
    project.git(main, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(upstream), "reference")
    project.git(main, "commit", "-qm", "submodule")
    # A recorded remote overrides .gitmodules; make it unreachable on purpose.
    project.git(main, "config", "submodule.reference.url", "https://127.0.0.1:1/x.git")
    target = tmp_path / "wt"
    project.worktree(main, target, "task-offline-submodule", "HEAD")
    assert (target / "reference" / "marker.txt").read_text(encoding="utf-8") == "pinned"
    # A worktree left without its submodule heals in place.
    project.shutil.rmtree(str(target / "reference"))
    project.worktree(main, target, "task-offline-submodule", "HEAD")
    assert (target / "reference" / "marker.txt").read_text(encoding="utf-8") == "pinned"


def test_unknown_contract_validation_reports_all_missing_references(store):
    invalid = plan(task("a"), task("b"))
    invalid["tasks"][0]["consumes"] = ["missing-a"]
    invalid["tasks"][1]["provides"].append("missing-b")
    with pytest.raises(ValueError) as error:
        store.apply_plan(invalid)
    assert "missing-a" in str(error.value) and "missing-b" in str(error.value)
    assert store.rows() == []


@pytest.mark.skipif(os.name != "nt", reason="Windows fake CLI")
def test_empty_work_plan_does_not_block_integration(repo):
    script = repo / "fake.py"
    script.write_text('''import json,sys
from pathlib import Path
args = sys.argv
recipe = json.loads(Path(args[args.index('--recipe')+1]).read_text(encoding='utf-8'))
name = recipe['instructions'].split('Unit: ')[1].split('\\n')[0]
phase = recipe['title']
value = dict(status='READY' if phase == 'parity-migrator' else 'PASS', summary='verified',
             coverage_complete=phase != 'parity-migrator', issues=[], changed_files=[],
             test_paths=['tests/test_'+name+'.py'], dependencies=[],
             test_map=['upstream case -> tests/test_'+name+'.py -> PORTED'])
if phase == 'parity-migrator':
    Path(name+'.py').write_text('value = 1\\n', encoding='utf-8')
    Path('tests/test_'+name+'.py').write_text("from pathlib import Path\\ndef test_value():\\n    assert Path('"+name+".py').read_text().strip() == 'value = 1'\\n", encoding='utf-8')
    value['changed_files'] = [name+'.py', 'tests/test_'+name+'.py']
else:
    value['work_plan'] = {"tasks": [], "contracts": []}
print(json.dumps({'type':'message','message':{'role':'assistant','id':'final','content':[{'type':'text','text':json.dumps(value)}]}}),flush=True)
print(json.dumps({'type':'complete'}),flush=True)
''', encoding="utf-8")
    executable = repo / "fake.cmd"
    executable.write_text('@echo off\n"' + sys.executable + '" "' + str(script) + '" %*\n', encoding="utf-8")
    project.git(repo, "add", ".")
    project.git(repo, "commit", "-qm", "fake CLI fixture")
    p = make_project(repo)
    p.goose = str(executable)
    p.store.apply_plan(plan(task("a")))
    assert p.run() == 0
    assert all(r["state"] == "INTEGRATED" for r in p.store.rows())
