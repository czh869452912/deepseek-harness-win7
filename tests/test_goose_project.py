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
    store.apply_plan(plan(task("plugin", ["a"], wave=7), dict(task("a", ["b"]), atomic_group="shared"),
                          dict(task("b", ["a"]), atomic_group="shared"), task("util", wave=1)))
    first = store.claim("1")
    assert first["ids"] == ["util"]
    second = store.claim("2")
    assert second["ids"] == ["a", "b"]
    assert store.claim("3") is None
    store.integrate(second, "abc", {"a.py": "hash"})
    assert store.claim("3")["ids"] == ["plugin"]


def test_equal_priority_selection_does_not_depend_on_scoring_duration(store, monkeypatch):
    import project_store
    store.apply_plan(plan(task('a'), task('b')))
    with store.connect() as db:
        db.execute('UPDATE tasks SET created=0')
    ticks = iter(range(1000, 1100))
    monkeypatch.setattr(project_store.time, 'time', lambda: next(ticks))
    assert store.claim('w')['ids'] == ['a']


def test_pilot_replan_cannot_silently_enroll_another_full_task(store):
    store.apply_plan(plan(task('a'), task('b')))
    allowed = {'a'}
    store.apply_plan(plan(dict(task('a'), atomic_group='combined'),
                          dict(task('b'), atomic_group='combined')))
    assert store.claim('w', 'a', allowed) is None
    rows = {r['id']: r for r in store.rows()}
    assert rows['a']['state'] == 'NEEDS_ARBITRATION'
    assert 'expanded' in rows['a']['error']
    assert rows['b']['state'] != 'RUNNING'


def test_unapproved_acceptance_cycle_is_visible_not_a_giant_worker(store):
    a, b = task("a", ["b"]), task("b", ["a"])
    b["dependencies"][0]["kind"] = "acceptance"
    store.apply_plan(plan(a, b, task("independent")))
    assert store.view()["unresolved_cycles"] == [["a", "b"]]
    assert store.claim("w")["ids"] == ["independent"]
    assert store.claim("w2") is None


def test_explicit_atomic_scope_can_join_endpoints_without_fabricating_cycle(store):
    store.apply_plan(plan(dict(task("a"), atomic_group="api-change"),
                          dict(task("b"), atomic_group="api-change")))
    assert store.claim("w")["ids"] == ["a", "b"]


def test_pending_scope_change_blocks_affected_peer_not_independent_work(store):
    store.apply_plan(plan(task("a"), task("b"), task("z")))
    group = store.claim("a")
    store.update(group, "WAITING_PLAN", feedback={"proposed_work_plan": plan(task("b", ["a"]))})
    assert store.claim("other")["ids"] == ["z"]
    assert store.claim("peer") is None


def test_different_contract_ids_with_overlapping_paths_serialize(store):
    a, b = task("a"), task("b")
    a["write_paths"] = ["dsh/cordis"]
    b["write_paths"] = ["dsh/cordis/schema.py"]
    store.apply_plan(plan(a, b, task("z")))
    first = store.claim("one")
    assert first["ids"] == ["a"]
    assert store.claim("two")["ids"] == ["z"]
    assert store.claim("three") is None
    store.integrate(first, "head", {})
    assert store.claim("three")["ids"] == ["b"]


def test_cross_module_scope_expansion_preserves_work_and_waits_for_owner(store):
    store.apply_plan(plan(task("a"), task("b")))
    a, b = store.claim("a"), store.claim("b")
    assert store.observe_writes(a, ["b.py"]) == ["b"]
    store.update(a, "READY", worktree="retained", round=3)
    assert store.claim("retry") is None
    assert store.view()["tasks"][0]["waiting_for_writer"] == ["b"]
    store.integrate(b, "provider", {})
    resumed = store.claim("retry")
    assert resumed["ids"] == ["a"]
    assert resumed["records"][0]["round"] == 3


@pytest.mark.parametrize("value,expected", [
    ({"verdict": "MIGRATOR_CORRECT", "summary": "free prose"}, "MIGRATOR_CORRECT"),
    ({"summary": "JUDGE_RESULT: verdict MIGRATOR_CORRECT. Evidence follows."}, "MIGRATOR_CORRECT"),
    ({"summary": "verdict: ADAPTATION_ALLOWED"}, "ADAPTATION_ALLOWED"),
    ({"summary": "verdict: MIGRATOR_CORRECT or verdict: BOTH_INCOMPLETE"}, None),
])
def test_structured_and_historical_judge_results(value, expected):
    assert project.judge_verdict(value) == expected


def test_issue_lifecycle_does_not_escalate_resolved_findings():
    assert project.open_issues({"issues": [{"state": "resolved"}, {"state": "informational"}]}) == []
    assert project.open_issues({"issues": [{"id": "legacy"}, {"state": "open"}]}) == [{"id": "legacy"}, {"state": "open"}]


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


def test_template_source_is_external_data_and_review_remains_blind(repo, monkeypatch):
    import parity_runner
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    agent = p.task_runner(p.store.claim("w"))
    def stop_after_recipe(*args, **kwargs):
        raise InterruptedError()
    monkeypatch.setattr(parity_runner, "run_process", stop_after_recipe)
    with pytest.raises(InterruptedError):
        agent.phase("migrate", {"source": "{{cwd}} {% if dangerous %} secret-review-claim"})
    recipe = json.loads((agent.run_dir / "00-migrate.yaml").read_text(encoding="utf-8"))
    context = (agent.run_dir / "00-migrate.context.json").read_text(encoding="utf-8")
    assert "{{" not in recipe["instructions"] and "{%" not in recipe["instructions"]
    assert "{{cwd}}" in context
    with pytest.raises(InterruptedError):
        agent.phase("review", {"source": "secret-review-claim"})
    assert "secret-review-claim" not in (agent.run_dir / "00-review.context.json").read_text(encoding="utf-8")


def test_split_tasks_fork_shared_checkpoint_without_losing_progress(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a"), task("b")))
    a = p.store.claim("a")
    worker = p.task_runner(a)
    (worker.root / "a.py").write_text("value = 8\n", encoding="utf-8")
    project.git(worker.root, "commit", "-am", "retained progress")
    p.store.update(a, "READY")
    with p.store.connect() as db:
        db.execute("UPDATE tasks SET worktree=?,base=? WHERE id='b'", (str(worker.root), project.git(repo, "rev-parse", "HEAD")))
    resumed = p.task_runner(p.store.claim("next"))
    assert resumed.root != worker.root
    assert (resumed.root / "a.py").read_text() == (worker.root / "a.py").read_text()
    assert p.store.rows()[0]["feedback"]["inherited_checkpoint"]["worktree"] == str(worker.root)


def test_publication_prepares_without_moving_master_then_publishes(repo, monkeypatch):
    p = make_project(repo)
    branch = project.git(repo, "branch", "--show-current")
    integration = p.integration()
    (integration / "a.py").write_text("value = 1\n", encoding="utf-8")
    project.git(integration, "commit", "-am", "migrated")
    original = project.git(repo, "rev-parse", "HEAD")
    (repo / "b.py").write_text("value = 2\n", encoding="utf-8")
    project.git(repo, "commit", "-am", "controller")
    target = project.git(repo, "rev-parse", "HEAD")
    calls = []
    monkeypatch.setattr(project, "run_process", lambda *args, **kwargs: calls.append(args) or 0)
    p.prepare_main(branch)
    assert project.git(repo, "rev-parse", "HEAD") == target != original
    assert len(calls) == 1
    p.publish_main()
    assert project.git(repo, "rev-parse", "HEAD") == project.git(integration, "rev-parse", "HEAD")
    assert (repo / "a.py").read_text().strip() == "value = 1"
    assert (repo / "b.py").read_text().strip() == "value = 2"


def test_publication_refuses_changed_candidate_or_target(repo, monkeypatch):
    p = make_project(repo)
    branch = project.git(repo, "branch", "--show-current")
    monkeypatch.setattr(project, "run_process", lambda *args, **kwargs: 0)
    p.prepare_main(branch)
    publication = p.store.meta("publication")
    (Path(publication["candidate"]) / "a.py").write_text("unchecked\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty"):
        p.publish_main()


def test_publication_conflict_preserves_both_sources_without_running_tests(repo, monkeypatch):
    p = make_project(repo)
    integration = p.integration()
    for path, value in ((repo, 1), (integration, 2)):
        (path / "a.py").write_text("value = %d\n" % value, encoding="utf-8")
        project.git(path, "commit", "-am", "conflicting design")
    heads = [project.git(path, "rev-parse", "HEAD") for path in (repo, integration)]
    monkeypatch.setattr(project, "run_process", lambda *a, **k: pytest.fail("Resolve conflict before test"))
    with pytest.raises(ValueError, match="conflicts"):
        p.prepare_main(project.git(repo, "branch", "--show-current"))
    candidate = p.store.meta("publication")
    assert candidate["state"] == "NEEDS_REPAIR"
    assert "<<<<<<<" in (Path(candidate["candidate"]) / "a.py").read_text()
    assert heads == [project.git(path, "rev-parse", "HEAD") for path in (repo, integration)]


def test_unrelated_baseline_reuses_review_but_checks_combined_candidate(repo, monkeypatch):
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
    checks = []
    def verify(command, cwd, *args, **kwargs):
        assert (cwd / "a.py").read_text().strip() == "value = 1"
        assert (cwd / "b.py").read_text().strip() == "value = 2"
        checks.append(command)
        return 0
    monkeypatch.setattr(project, "run_process", verify)
    p.merge(group, agent, p.store.contract_hashes(), {"test_paths": []})
    saved = p.store.rows()[0]
    assert saved["state"] == "INTEGRATED"
    candidate = Path(saved["worktree"])
    assert (candidate / "a.py").read_text().strip() == "value = 1"
    assert (candidate / "b.py").read_text().strip() == "value = 2"
    assert project.git(integration, "rev-parse", "HEAD") != tip
    assert checks == [[sys.executable, "-m", "pytest", "tests"]]


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
    assert saved["state"] == "INTEGRATION_REPAIR"
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
    p.store.apply_plan(plan(dict(task("a", ["b"]), atomic_group="shared"),
                            dict(task("b", ["a"]), atomic_group="shared")))
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
    assert row["state"] == "INTEGRATION_REPAIR"
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


def test_incremental_plan_errors_park_without_rerunning_implementation(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    p.store.update(group, "WAITING_PLAN", feedback={"proposed_work_plan": plan(task("a", ["unknown"]))})
    p.apply_proposals()
    row = p.store.rows()[0]
    assert row["state"] == "PLAN_REPAIR"
    assert "Unknown dependency" in row["feedback"]["plan_error"]
    assert p.store.claim("w") is None
    proposed = plan(task("a", ["b"]), task("b"))
    p.store.update(group, "WAITING_PLAN", feedback={"proposed_work_plan": proposed})
    p.apply_proposals()
    assert p.store.claim("w")["ids"] == ["b"]
    assert p.store.plan_is_current(proposed)


def test_plan_repair_uses_registry_without_replaying_code(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    group = p.store.claim('w')
    retained = {'proposed_work_plan': plan(task('a', ['missing'])), 'migration': {'summary': 'retained'},
                'review': {'summary': 'retained review'}}
    p.store.update(group, 'WAITING_PLAN', feedback=retained, round=5)
    p.apply_proposals()
    corrected = plan(task('a', ['b']), task('b'))
    def repair(command, root, log, notify, timeout, stream, **kwargs):
        recipe = json.loads(Path(command[command.index('--recipe') + 1]).read_text(encoding='utf-8'))
        assert recipe['extensions'] == []
        assert 'registry' in recipe['instructions']
        stream.accepted_result = corrected
        stream.complete = True
        return 0
    monkeypatch.setattr(project, 'run_process', repair)
    monkeypatch.setattr(p, 'task_runner', lambda *a: pytest.fail('Implementation must not run'))
    p.repair_plans()
    row = next(r for r in p.store.rows() if r['id'] == 'a')
    assert row['state'] == 'READY'
    assert row['round'] == 5
    assert row['feedback']['review']['summary'] == 'retained review'
    assert row['feedback']['migration']['summary'] == 'retained'
    assert 'plan_error' not in row['feedback']
    assert p.store.claim('w')['ids'] == ['b']


def test_historical_plan_error_routes_before_task_runner(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    group = p.store.claim('w')
    p.store.update(group, 'READY', feedback={'plan_error': 'Unknown contract',
                   'proposed_work_plan': plan(task('a'))}, round=6)
    group = p.store.claim('w')
    monkeypatch.setattr(p, 'task_runner', lambda *a: pytest.fail('Do not restart code for a plan error'))
    p.execute(group)
    assert p.store.rows()[0]['state'] == 'PLAN_REPAIR'
    assert p.store.rows()[0]['round'] == 6


def test_repair_exhaustion_retains_evidence_for_arbitration(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    group = p.store.claim('w')
    p.store.update(group, 'PLAN_REPAIR', feedback={'plan_error': 'bad contract',
                   'proposed_work_plan': plan(task('a')), 'review': {'summary': 'keep'}}, round=3)
    monkeypatch.setattr(project, 'run_process', lambda *a, **kw: 1)
    for _ in range(3):
        p.repair_plans()
    row = p.store.rows()[0]
    assert row['state'] == 'NEEDS_ARBITRATION'
    assert row['feedback']['plan_repair_attempts'] == 2
    assert row['feedback']['review']['summary'] == 'keep'
    assert row['round'] == 3


def test_phase_reads_current_allocation_and_records_requested_model(repo, monkeypatch):
    from console_runtime import load_config, write_config, config_revision
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    agent = p.task_runner(p.store.claim('w'))
    agent.state['round'] = 1
    seen = []
    def fake_process(command, root, path, notify, timeout, stream, **kwargs):
        recipe = json.loads(Path(command[command.index('--recipe') + 1]).read_text(encoding='utf-8'))
        seen.append(recipe['settings']['goose_model'])
        phase = agent.state['phase']
        stream.accepted_result = dict(status='READY' if phase == 'migrate' else 'PASS', summary='verified',
               coverage_complete=True, issues=[], changed_files=[], test_paths=['tests/test_a.py'],
               dependencies=[], test_map=['upstream case -> tests/test_a.py -> PORTED'])
        stream.complete = True
        return 0
    monkeypatch.setattr(project.sys.modules['parity_runner'], 'run_process', fake_process)
    agent.phase('migrate')
    first_revision = agent.state['config_revision']
    config = load_config(repo)
    revision = config_revision(config)
    config['roles']['reviewer']['model'] = 'new-review-model'
    write_config(repo, config, revision)
    agent.phase('review')
    assert seen == ['deepseek-flash', 'new-review-model']
    assert agent.state['model'] == 'new-review-model'
    assert agent.state['config_revision'] != first_revision
    assert len(list(agent.run_dir.glob('*.config.json'))) == 2


def test_targeted_claim_never_starts_other_ready_work(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a'), task('b')))
    group = p.store.claim('w', 'b')
    assert group['ids'] == ['b']
    assert next(r['state'] for r in p.store.rows() if r['id'] == 'a') == 'READY'
    assert p.store.claim('w', 'does-not-exist') is None


def test_integration_adjudicates_then_repairs_and_reviews_only_combination(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    group = p.store.claim('w')
    agent = p.task_runner(group)
    calls = []
    prior = {'status': 'PASS', 'test_paths': ['tests/test_a.py']}
    feedback = {'integration_handoff': {'source_review': prior, 'needs_decision': True,
                                       'affected_paths': ['a.py']}}
    def phase(worker, name, data=None):
        calls.append(name)
        assert data['integration_handoff']['source_review'] == prior
        if name == 'judge':
            return dict(status='RESOLVED', verdict='REVIEWER_CORRECT', summary='source contract decided')
        assert data['contract_decision']['verdict'] == 'REVIEWER_CORRECT'
        return dict(status='READY' if name == 'integrate' else 'PASS', changed_files=[],
                    observed_changes=[], test_paths=['tests/test_a.py'], issues=[])
    monkeypatch.setattr(p, 'cached_phase', phase)
    monkeypatch.setattr(agent, 'verify_chunk', lambda result: True)
    monkeypatch.setattr(agent, 'checkpoint', lambda result: None)
    monkeypatch.setattr(p, 'merge', lambda *args: calls.append('merge'))
    p.execute_integration(group, agent, feedback)
    assert calls == ['judge', 'integrate', 'integration_review', 'merge']
    assert p.store.rows()[0]['state'] == 'VERIFIED'


def test_pilot_stops_after_selected_task_without_claiming_siblings(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a'), task('b')))
    monkeypatch.setattr(p, 'init', lambda: None)
    p.store.meta('architecture', p.store.meta('upstream'))
    called = []
    def execute(group):
        called.extend(group['ids'])
        p.store.update(group, 'INTEGRATED')
    monkeypatch.setattr(p, 'execute', execute)
    p.jobs = 1
    assert p.run('a') == 0
    assert called == ['a']
    assert p.store.meta('scheduler') == 'PAUSED'
    assert next(r['state'] for r in p.store.rows() if r['id'] == 'b') == 'READY'


@pytest.mark.parametrize('verdict,expected', [('BLOCKED', 'NEEDS_ARBITRATION'),
                                             ('BOTH_INCOMPLETE', 'PLAN_REPAIR')])
def test_conflicting_optional_plans_cannot_bypass_judge(repo, monkeypatch, verdict, expected):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    group = p.store.claim('w')
    agent = p.task_runner(group)
    monkeypatch.setattr(p, 'task_runner', lambda group: agent)
    monkeypatch.setattr(agent, 'verify_chunk', lambda value: True)
    monkeypatch.setattr(agent, 'checkpoint', lambda value: None)
    calls = []
    def phase(agent, name, feedback=None):
        calls.append(name)
        if name == 'judge':
            return dict(status='BLOCKED', verdict=verdict, summary='source based decision')
        spec = task('a')
        spec['goal'] = 'proposal from ' + name
        return dict(status='ESCALATE' if name == 'migrate' else 'MUST_FIX', summary='disputed',
                    coverage_complete=False, issues=[], changed_files=[], observed_changes=[],
                    test_paths=['tests/test_a.py'], dependencies=[], test_map=[], work_plan=plan(spec))
    monkeypatch.setattr(p, 'cached_phase', phase)
    p.execute(group)
    assert calls == ['migrate', 'review', 'judge']
    assert p.store.rows()[0]['feedback']['judgment']['status'] == 'BLOCKED'
    assert p.store.rows()[0]['state'] == expected
    if verdict == 'BOTH_INCOMPLETE':
        row = p.store.rows()[0]
        assert row['feedback']['resume_round_after_plan'] == row['round'] + 1
        feedback = row['feedback']
        feedback['proposed_work_plan'] = plan(task('a'))
        p.store.update(group, 'WAITING_PLAN', feedback=feedback)
        p.apply_proposals()
        repaired = p.store.rows()[0]
        assert repaired['state'] == 'READY'
        assert repaired['round'] == row['round'] + 1
        assert repaired['feedback']['applied_proposals_signature'] == feedback['proposals_signature']


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


@pytest.mark.parametrize('unresolved', [False, True])
def test_scope_arbitration_can_overrule_review_only_with_no_remaining_gaps(repo, monkeypatch, unresolved):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    group = p.store.claim('w')
    invalid_plan = plan(dict(task('a'), provides=['undefined-review-contract']))
    group['records'][0]['feedback'] = json.dumps({
        'arbitration_request': 'Classify existing provider-owned behavior',
        'plan_error': 'undefined-review-contract', 'proposed_work_plan': invalid_plan})
    agent = p.task_runner(group)
    monkeypatch.setattr(p, 'task_runner', lambda group: agent)
    monkeypatch.setattr(agent, 'verify_chunk', lambda value: True)
    monkeypatch.setattr(agent, 'checkpoint', lambda value: None)
    calls = []
    issue = dict(id='provider#rollback', detail='provider transaction', evidence='reference/provider', state='open')
    def phase(agent, name, feedback=None):
        calls.append(name)
        value = dict(status='READY', summary='verified', coverage_complete=True, issues=[],
                     changed_files=[], test_paths=[], dependencies=[], test_map=[])
        if name == 'review':
            value.update(status='MUST_FIX', issues=[issue], work_plan=invalid_plan)
        elif name == 'judge':
            assert feedback['arbitration_request']
            value.update(status='RESOLVED', verdict='MIGRATOR_CORRECT', issues=[issue] if unresolved else [],
                         work_plan={'tasks': [], 'contracts': []})
        return value
    monkeypatch.setattr(p, 'cached_phase', phase)
    monkeypatch.setattr(p.store, 'record_evidence', lambda *args: None)
    monkeypatch.setattr(p, 'merge', lambda group, *args: p.store.update(group, 'INTEGRATED'))
    p.execute(group)
    assert calls == ['migrate', 'review', 'judge']
    assert p.store.rows()[0]['state'] == ('READY' if unresolved else 'INTEGRATED')


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


def test_cached_phase_recovery_filters_malformed_changed_files(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    agent = p.task_runner(group)
    run_dir = agent.run_dir
    head = project.git(agent.root, "rev-parse", "HEAD")
    files = project.snapshot(agent.root)
    index = project.git(agent.root, "diff", "--cached", "--binary")
    project.save_json(run_dir / "00-migrate.start.json",
                      {"head": head, "files": files, "index": index,
                       "scope": getattr(agent.args, "task_contract", None)})
    project.save_json(run_dir / "00-migrate.completion.json",
                      {"files": files, "head": head, "index": index})
    value = dict(status="READY", summary="worked", coverage_complete=True, issues=[],
                 changed_files=["a.py", "apps/web/dist (upstream build payload: *)"],
                 test_paths=["tests/test_a.py"], dependencies=[],
                 test_map=["upstream case -> tests/test_a.py -> PORTED"])
    events = [
        {"type": "message", "message": {"id": "final", "role": "assistant", "content": [
            {"type": "toolRequest", "id": "t1", "toolCall": {"value": {
                "name": "recipe__final_output", "arguments": value}}}]}},
        {"type": "message", "message": {"role": "user", "content": [
            {"type": "toolResponse", "id": "t1", "toolResult": {"status": "success", "value": {}}}]}},
        {"type": "complete"},
    ]
    (run_dir / "00-migrate.events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    result = p.cached_phase(agent, "migrate", None)
    assert result["changed_files"] == ["a.py"]
    assert (run_dir / "00-migrate.result.json").exists()


def test_cached_phase_recovery_falls_back_after_interrupted_generation(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    agent = p.task_runner(group)
    run_dir = agent.run_dir
    head = project.git(agent.root, "rev-parse", "HEAD")
    files = project.snapshot(agent.root)
    index = project.git(agent.root, "diff", "--cached", "--binary")
    project.save_json(run_dir / "00-migrate.start.json",
                      {"head": head, "files": files, "index": index,
                       "scope": getattr(agent.args, "task_contract", None)})
    project.save_json(run_dir / "00-migrate.completion.json",
                      {"files": files, "head": head, "index": index})
    events = [
        {"type": "message", "message": {"id": "mid", "role": "assistant", "content": [
            {"type": "text", "text": "Writing probe scripts and analyzing the unit..."}]}},
        {"type": "complete"},
    ]
    (run_dir / "00-migrate.events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    sentinel = dict(status="READY", summary="fresh", coverage_complete=True, issues=[],
                    changed_files=[], test_paths=["tests/test_a.py"], dependencies=[],
                    test_map=["upstream case -> tests/test_a.py -> PORTED"])
    calls = []
    monkeypatch.setattr(agent, "phase", lambda phase, feedback=None: calls.append(phase) or sentinel)
    result = p.cached_phase(agent, "migrate", None)
    assert calls == ["migrate"]
    assert result is sentinel


@pytest.mark.skipif(os.name != "nt", reason="Windows fake CLI")
def test_judge_migrator_correct_verdict_completes_the_gate(repo):
    script = repo / "fake.py"
    script.write_text('''import json,sys
from pathlib import Path
args = sys.argv
recipe = json.loads(Path(args[args.index('--recipe')+1]).read_text(encoding='utf-8'))
name = recipe['instructions'].split('Unit: ')[1].split('\\n')[0]
phase = recipe['title']
value = dict(status='READY', summary='worked', coverage_complete=True, issues=[],
             changed_files=[], test_paths=['tests/test_'+name+'.py'], dependencies=[],
             test_map=['upstream case -> tests/test_'+name+'.py -> PORTED'])
if phase == 'parity-migrator':
    Path(name+'.py').write_text('value = 1\\n', encoding='utf-8')
    Path('tests/test_'+name+'.py').write_text("from pathlib import Path\\ndef test_value():\\n    assert Path('"+name+".py').read_text().strip() == 'value = 1'\\n", encoding='utf-8')
    value['changed_files'] = [name+'.py', 'tests/test_'+name+'.py']
elif phase == 'parity-reviewer':
    value['status'] = 'ESCALATE'
    value['coverage_complete'] = False
else:
    value['status'] = 'RESOLVED'
    value['summary'] = 'JUDGE_RESULT\\nverdict: MIGRATOR_CORRECT\\nrequired_action: final verification'
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


def test_recover_stale_reclaims_dead_owner_tasks(repo):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    with p.store.connect() as db:
        db.execute("UPDATE tasks SET owner='999999:deadbeef', state='RUNNING' WHERE id='a'")
    assert p.recover_stale() == ["a"]
    assert p.store.rows()[0]["state"] == "READY"
    group = p.store.claim("w2")
    with p.store.connect() as db:
        db.execute("UPDATE tasks SET owner=?, state='RUNNING' WHERE id='a'", (str(os.getpid()) + ":alive",))
    assert p.recover_stale() == []
    assert p.store.rows()[0]["state"] == "RUNNING"


def test_execute_parks_groups_on_scheduler_interrupt(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task("a")))
    group = p.store.claim("w")
    def interrupted(group_arg):
        raise InterruptedError("Project scheduler interrupted; owned process tree stopped")
    monkeypatch.setattr(p, "task_runner", interrupted)
    p.execute(group)
    row = p.store.rows()[0]
    assert row["state"] == "READY"
    assert not row["error"]


def test_run_honors_pause_flag(repo, monkeypatch):
    p = make_project(repo)
    def write_flag():
        (p.folder / "pause.flag").write_text("", encoding="utf-8")
    monkeypatch.setattr(p, "apply_proposals", write_flag)
    assert p.run() == 0
    assert not (p.folder / "pause.flag").exists()


def test_dashboard_sharing_violation_does_not_cancel_the_pilot(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    monkeypatch.setattr(p, 'init', lambda: None)
    p.store.meta('architecture', p.store.meta('upstream'))
    def locked(*args):
        raise PermissionError('Windows display file sharing violation')
    monkeypatch.setattr(project, 'dashboard', locked)
    def execute(group):
        assert not p.stop.is_set()
        assert p.store.meta('pilot')['state'] == 'RUNNING'
        p.store.update(group, 'INTEGRATED')
    monkeypatch.setattr(p, 'execute', execute)
    assert p.run('a') == 0
    assert p.store.rows()[0]['state'] == 'INTEGRATED'


def test_paused_pilot_never_prepares_or_publishes_main(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    monkeypatch.setattr(project, 'Project', lambda *args: p)
    monkeypatch.setattr(sys, 'argv', ['project_runner.py', 'pilot', '--task', 'a'])
    monkeypatch.setattr(p, 'run', lambda task: 0)
    def forbidden(*args):
        raise AssertionError('a paused pilot must not publish')
    monkeypatch.setattr(p, 'prepare_main', forbidden)
    monkeypatch.setattr(p, 'publish_main', forbidden)
    assert project.main() == 0
    assert p.store.meta('pilot')['state'] == 'PAUSED'


def test_dashboard_tolerates_unreadable_live_status(repo, monkeypatch):
    p = make_project(repo)
    p.store.apply_plan(plan(task('a')))
    group = p.store.claim('w')
    run_dir = p.folder / 'live'
    run_dir.mkdir()
    p.store.update(group, run_dir=str(run_dir))
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path == run_dir / 'status.json':
            raise PermissionError('replace in progress')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    project.dashboard(p.store, p.folder)
    assert 'RUNNING' in (p.folder / 'index.html').read_text(encoding='utf-8')


@pytest.mark.skipif(os.name != "nt", reason="Windows console signals")
def test_pause_flag_parks_and_exits_promptly(repo):
    import subprocess
    import time
    script = repo / "fake.py"
    script.write_text("import time\ntime.sleep(45)\n", encoding="utf-8")
    executable = repo / "fake.cmd"
    executable.write_text('@echo off\n"' + sys.executable + '" "' + str(script) + '" %*\n', encoding="utf-8")
    project.git(repo, "add", ".")
    project.git(repo, "commit", "-qm", "fake CLI fixture")
    reference = repo / "reference"
    reference.mkdir()
    project.git(reference, "init", "-q")
    project.git(reference, "config", "user.name", "Test")
    project.git(reference, "config", "user.email", "test@example.invalid")
    (reference / "index.ts").write_text("export const pinned = true\n", encoding="utf-8")
    project.git(reference, "add", ".")
    project.git(reference, "commit", "-qm", "pinned upstream")
    revision = project.git(reference, "rev-parse", "HEAD")
    p = make_project(repo)
    p.goose = str(executable)
    p.store.meta("upstream", revision)
    p.store.meta("architecture", revision)
    p.store.apply_plan(plan(task("a")))
    for module in ("project_runner.py", "parity_runner.py", "project_store.py", "project_seed.py", "console_runtime.py", "agent-config.json"):
        copy = repo / ".goose" / module
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(SOURCE / ".goose" / module), str(copy))
    controller = subprocess.Popen(
        [sys.executable, str(repo / ".goose" / "project_runner.py"), "run",
         "--goose", str(executable), "--jobs", "1"],
        cwd=str(repo), creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=open(repo / "controller.log", "w", encoding="utf-8"),
        stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 90
        started = False
        while time.monotonic() < deadline:
            rows = p.store.rows()
            if rows and rows[0]["state"] == "RUNNING" and rows[0]["run_dir"]:
                runs = list(Path(rows[0]["run_dir"]).glob("*.events.jsonl"))
                if runs:
                    started = True
                    break
            time.sleep(0.5)
        if not started:
            controller.kill()
            raise AssertionError("controller never started the phase: " +
                                 (repo / "controller.log").read_text(encoding="utf-8", errors="replace")[-2000:])
        (repo / ".goose" / "runs" / "project" / "pause.flag").write_text("", encoding="utf-8")
        code = controller.wait(timeout=45)
        assert code == 0, code
    finally:
        if controller.poll() is None:
            controller.kill()
    rows = p.store.rows()
    assert rows[0]["state"] == "READY", rows[0]["state"]
    assert not rows[0]["error"]
