"""Controller regressions: real stream deltas, bounded phases and Git ownership."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import shutil

import pytest


SPEC = importlib.util.spec_from_file_location(
    "goose_parity_runner", Path(__file__).resolve().parents[1] / ".goose/parity_runner.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def result(status="READY", issues=None):
    return dict(status=status, summary="checked", coverage_complete=status == "PASS",
                issues=issues or [], changed_files=[], test_paths=["tests/test_unit.py"],
                dependencies=[], test_map=["upstream case -> tests/test_unit.py -> PORTED"],
                observed_changes=[])


def message(mid, text, role="assistant"):
    return {"type": "message", "message": {"id": mid, "role": role,
            "content": [{"type": "text", "text": text}]}}


def test_stream_displays_thinking_without_using_it_as_final_result():
    seen = []
    stream = runner.Stream(lambda k, v: seen.append((k, v)))
    text = json.dumps(result())
    stream.feed(message("first", "I am checking dependencies."))
    stream.feed(message("tool-result", json.dumps(result("PASS")), "user"))
    stream.feed({"type": "message", "message": {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "not public output"}]}})
    for fragment in [text[:30], text[30:81], text[81:]]:
        stream.feed(message("final", fragment))
    stream.feed({"type": "complete"})
    assert stream.result("migrate")["status"] == "READY"
    assert ("thinking", "not public output") in seen


def test_stream_cannot_reuse_an_earlier_valid_result():
    stream = runner.Stream(lambda *args: None)
    stream.feed(message("old", json.dumps(result())))
    stream.feed(message("new", "Yes - what would you like me to do?"))
    stream.feed({"type": "complete"})
    with pytest.raises(ValueError, match="No complete structured result"):
        stream.result("migrate")


def test_missing_complete_event_is_a_failure():
    stream = runner.Stream(lambda *args: None)
    stream.feed(message("final", json.dumps(result())))
    with pytest.raises(ValueError, match="without a complete"):
        stream.result("migrate")


def test_legacy_complete_requires_judge_instead_of_reimplementing():
    value = result('COMPLETE', [{'id': 'loopless', 'detail': 'adaptation needs a verdict', 'evidence': 'fiber.ts'}])
    normalized = runner.parse_result(json.dumps(value), 'migrate')
    assert normalized['status'] == 'ESCALATE'
    assert normalized['issues'] == value['issues']
    assert normalized['test_paths'] == value['test_paths']


def test_pass_requires_complete_mapping_and_no_issues():
    data = result("PASS")
    data["coverage_complete"] = False
    with pytest.raises(ValueError, match="PASS requires"):
        runner.parse_result(json.dumps(data), "review")


def test_final_tool_acknowledgement_survives_missing_text_and_rejected_attempt():
    stream = runner.Stream(lambda *args: None)
    def request(call_id, value):
        return {"type": "message", "message": {"role": "assistant", "content": [
            {"type": "toolRequest", "id": call_id, "toolCall": {"value": {
                "name": "recipe__final_output", "arguments": value}}}]}}
    def response(call_id, status):
        return {"type": "message", "message": {"role": "user", "content": [
            {"type": "toolResponse", "id": call_id, "toolResult": {"status": status,
             "value": {"isError": status != "success"}}}]}}
    stream.feed(request("bad", result("PASS")))
    stream.feed(response("bad", "error"))
    assert stream.accepted_result is None
    stream.feed(request("good", result("MUST_FIX")))
    stream.feed(response("good", "success"))
    stream.feed({"type": "complete"})
    assert stream.result("review")["status"] == "MUST_FIX"


@pytest.mark.parametrize("child_holds_pipe", [False, True])
def test_complete_ends_protocol_even_when_process_or_descendant_keeps_pipe(tmp_path, child_holds_pipe):
    import time
    code = "import json,time,subprocess,sys\n"
    if child_holds_pipe:
        code += "subprocess.Popen([sys.executable,'-c','import time; time.sleep(45)'])\n"
    code += "print(json.dumps({'type':'complete'}),flush=True)\n"
    if not child_holds_pipe:
        code += "time.sleep(45)\n"
    stream = runner.Stream(lambda *args: None)
    start = time.monotonic()
    assert runner.run_process([sys.executable, "-c", code], tmp_path, tmp_path / "events.jsonl",
                              lambda *args: None, 0, stream, exit_grace=0.1) == 0
    assert stream.complete
    assert time.monotonic() - start < 8


@pytest.fixture
def repo(tmp_path):
    subprocess.check_call(["git", "init", "-q", str(tmp_path)])
    runner.git(tmp_path, "config", "user.name", "Test")
    runner.git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "module.py").write_text("x = 1\n", encoding="utf-8")
    runner.git(tmp_path, "add", "module.py")
    runner.git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


class Harness(runner.Runner):
    def __init__(self, root, phases, rounds=3):
        self.root = root
        self.args = argparse.Namespace(max_rounds=rounds, no_commit=False, adopt_existing=False, unit="core/session")
        self.state = {"phase": "startup", "round": 0, "commits": [], "issues": []}
        self.run_dir = root
        self.initial_dirty = set()
        self.phases = iter(phases)
        self.calls = []
        self.notifications = []

    def notify(self, kind, message):
        self.notifications.append((kind, message))

    def phase(self, phase, feedback=None):
        self.calls.append((phase, feedback))
        expected, response = next(self.phases)
        assert phase == expected
        if phase == "review":
            assert feedback is None
        return response

    def verify_chunk(self, value):
        return True

    def checkpoint(self, value):
        pass

    def check(self, name, args):
        return True


def test_unchanged_findings_trigger_judge_instead_of_stopping(repo):
    review = result("MUST_FIX", [{"id": "session/null", "detail": "missing", "evidence": "upstream:1"}])
    h = Harness(repo, [("migrate", result()), ("review", review)] * 2 +
                [("judge", result("RESOLVED")), ("migrate", result()), ("review", result("PASS"))])
    assert h.run() == 0
    assert h.state["status"] == "COMPLETE"
    assert h.calls[4][0] == "judge"


def test_round_limit_is_hard_even_with_new_findings(repo):
    h = Harness(repo, [("migrate", result()), ("review", result("MUST_FIX"))], rounds=1)
    assert h.run() == 2
    assert h.state["status"] == "INCOMPLETE"
    assert len(h.calls) == 2


def test_failed_full_suite_returns_to_migrator(repo):
    h = Harness(repo, [("migrate", result()), ("review", result("PASS"))] * 2, rounds=0)
    (repo / "01-full-suite.log").write_text("FAILED integration test", encoding="utf-8")
    outcomes = iter([False, True])
    h.check = lambda *args: next(outcomes)
    assert h.run() == 0
    assert h.state["status"] == "COMPLETE"
    assert h.calls[2][1]["full_suite_failure"] == "FAILED integration test"


def test_single_judge_and_fresh_blind_review_after_correction(repo):
    h = Harness(repo, [("migrate", result("ESCALATE")), ("review", result("ESCALATE")),
                       ("judge", result("RESOLVED")), ("migrate", result()),
                       ("review", result("PASS"))])
    assert h.run() == 0
    assert h.state["status"] == "COMPLETE"
    assert h.calls[3][1]["judgment"]["status"] == "RESOLVED"
    assert h.calls[4][1] is None


def test_checkpoint_does_not_capture_preexisting_edits(repo):
    h = Harness(repo, [])
    h.initial_dirty = {"module.py"}
    (repo / "module.py").write_text("x = 2\n", encoding="utf-8")
    original = runner.git(repo, "rev-parse", "HEAD")
    data = result()
    data["observed_changes"] = ["module.py"]
    runner.Runner.checkpoint(h, data)
    assert runner.git(repo, "rev-parse", "HEAD") == original
    assert runner.git(repo, "diff", "--cached", "--name-only") == ""
    assert "pre-existing" in str(h.notifications)


def test_explicit_adoption_commits_only_the_verified_paths(repo):
    h = Harness(repo, [])
    h.initial_dirty = {"module.py"}
    h.args.adopt_existing = True
    (repo / "module.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "unrelated.txt").write_text("keep me", encoding="utf-8")
    data = result()
    data["observed_changes"] = ["module.py"]
    runner.Runner.checkpoint(h, data)
    assert "unreviewed" in runner.git(repo, "log", "-1", "--format=%s")
    assert runner.git(repo, "show", "--format=", "--name-only", "HEAD") == "module.py"
    assert "unrelated.txt" in runner.dirty_paths(repo)


def test_existing_index_is_preserved(repo):
    h = Harness(repo, [])
    (repo / "module.py").write_text("x = 2\n", encoding="utf-8")
    runner.git(repo, "add", "module.py")
    before = runner.git(repo, "diff", "--cached")
    data = result()
    data["observed_changes"] = ["module.py"]
    runner.Runner.checkpoint(h, data)
    assert runner.git(repo, "diff", "--cached") == before
    assert not h.state["commits"]


def test_resuming_after_checkpoint_does_not_attempt_an_empty_commit(repo):
    h = Harness(repo, [])
    (repo / "module.py").write_text("x = 2\n", encoding="utf-8")
    data = result()
    data["observed_changes"] = ["module.py"]
    runner.Runner.checkpoint(h, data)
    head = runner.git(repo, "rev-parse", "HEAD")
    runner.Runner.checkpoint(h, data)
    assert runner.git(repo, "rev-parse", "HEAD") == head
    assert len(h.state["commits"]) == 1


def test_process_timeout_stops_a_silent_child(tmp_path):
    with pytest.raises(TimeoutError):
        runner.run_process([sys.executable, "-c", "import time; time.sleep(30)"],
                           tmp_path, tmp_path / "log.txt", lambda *args: None, 0.1)


@pytest.mark.parametrize("name", ["../outside.py", "tests/../../outside", "C:/outside", ".git/config"])
def test_test_paths_cannot_escape_repository(tmp_path, name):
    with pytest.raises(ValueError):
        runner.safe_path(tmp_path, name)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CLI integration")
@pytest.mark.parametrize("native_stop", [False, True])
def test_complete_cli_pipeline_with_fake_goose(repo, native_stop):
    """Real child processes, target/full tests, structured output and checkpoint."""
    source = Path(__file__).resolve().parents[1]
    for name in [".goose/parity_runner.py", ".goose/console_runtime.py", ".goose/agent-config.json", ".goose/recipes/parity-unit.yaml"] + [
            ".agents/agents/" + role + ".md" for role in runner.ROLES.values()]:
        dest = repo / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source / name), str(dest))
    (repo / ".gitignore").write_text(".goose/runs/\n__pycache__/\n.pytest_cache/\nsaved-recipe.json\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests/test_unit.py").write_text("def test_unit():\n    assert 1 == 1\n", encoding="utf-8")
    fake = repo / "fake.py"
    fake.write_text('''import json, sys
from pathlib import Path
args = sys.argv[1:]
assert '--max-tool-repetitions' not in args
assert '--max-turns' not in args
assert '--no-profile' not in args
if '--resume' in args:
    recipe = json.loads(Path('saved-recipe.json').read_text(encoding='utf-8'))
else:
    recipe = json.loads(Path(args[args.index('--recipe') + 1]).read_text(encoding='utf-8'))
    assert 'max_turns' not in recipe['settings']
    Path('saved-recipe.json').write_text(json.dumps(recipe), encoding='utf-8')
if Path('native-stop').exists() and '--resume' not in args:
    print(json.dumps({'type':'message','message':{'id':'limit','role':'assistant',
        'content':[{'type':'text','text':"I've reached the maximum number of actions I can do without user input. Would you like me to continue?"}]}}), flush=True)
    print(json.dumps({'type':'complete'}), flush=True)
    sys.exit(0)
phase = recipe['title']
changed = []
if phase == 'parity-migrator':
    Path('module.py').write_text('x = 2\\n', encoding='utf-8')
    changed = ['module.py']
else:
    assert 'Continuation evidence' not in recipe['instructions']
value = dict(status='READY' if changed else 'PASS', summary='verified',
             coverage_complete=not changed, issues=[], changed_files=changed,
             test_paths=['tests/test_unit.py'], dependencies=['canonical owner checked'],
             test_map=['upstream case -> tests/test_unit.py -> PORTED'])
text = json.dumps(value)
for part in [text[:17], text[17:]]:
    print(json.dumps({'type':'message','message':{'id':'final','role':'assistant',
          'content':[{'type':'text','text':part}]}}), flush=True)
print(json.dumps({'type':'complete'}), flush=True)
''', encoding="utf-8")
    executable = repo / "fake-goose.cmd"
    executable.write_text('@echo off\n"' + sys.executable + '" "' + str(fake) + '" %*\n', encoding="utf-8")
    if native_stop:
        (repo / "native-stop").write_text("enabled", encoding="utf-8")
    runner.git(repo, "add", ".")
    runner.git(repo, "commit", "-qm", "controller fixture")
    proc = subprocess.run([sys.executable, str(repo / ".goose/parity_runner.py"),
                           "--unit", "core/session", "--goose", str(executable),
                           "--max-rounds", "1"], cwd=str(repo), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    status_files = list((repo / ".goose/runs").glob("*/status.json"))
    state = json.loads(status_files[0].read_text(encoding="utf-8"))
    assert state["status"] == "COMPLETE"
    assert len(state["commits"]) == 1
    assert "unreviewed" in runner.git(repo, "log", "-1", "--format=%s")
    assert "progress:" in proc.stdout
    if native_stop:
        assert "resuming the same session with its tools" in proc.stdout
    assert not (repo / ".goose/runs/active.lock").exists()


def make_review_runner(repo):
    args = argparse.Namespace(unit="core/session", goose=None, max_rounds=0, no_commit=True,
                              adopt_existing=False, max_turns=0, phase_timeout=0,
                              control_root=Path(__file__).resolve().parents[1])
    h = runner.Runner(args, root=repo)
    h.args.goose = repo / "fake-goose.cmd"
    return h


@pytest.mark.parametrize('change_scope', [False, True])
def test_interrupted_phase_resumes_native_session_only_for_same_scope(repo, monkeypatch, change_scope):
    h = make_review_runner(repo)
    h.args.task_contract = {'scope': 'original'}
    calls = []
    def process(command, root, log, notify, timeout, stream, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise InterruptedError('pause')
        for event in REVIEW_EVENTS:
            stream.feed(event)
        return 0
    monkeypatch.setattr(runner, 'run_process', process)
    with pytest.raises(InterruptedError):
        h.phase('review')
    assert (h.run_dir / '00-review.resume.json').exists()
    if change_scope:
        h.args.task_contract = {'scope': 'changed'}
    assert h.phase('review')['status'] == 'MUST_FIX'
    assert ('--resume' in calls[1]) == (not change_scope)
    if not change_scope:
        assert 'coverage_complete' in calls[1][-1] and 'required' in calls[1][-1]
    assert not (h.run_dir / '00-review.resume.json').exists()


REVIEW_EVENTS = [
    {"type": "message", "message": {"id": "final", "role": "assistant", "content": [
        {"type": "toolRequest", "id": "t1", "toolCall": {"value": {
            "name": "recipe__final_output", "arguments": {
                "status": "MUST_FIX", "summary": "checked", "coverage_complete": False, "issues": [],
                "changed_files": [], "test_paths": ["tests/test_unit.py"], "dependencies": [],
                "test_map": ["upstream case -> tests/test_unit.py -> PORTED"]}}}}]}},
    {"type": "message", "message": {"role": "user", "content": [
        {"type": "toolResponse", "id": "t1", "toolResult": {"status": "success", "value": {}}}]}},
    {"type": "complete"},
]


def review_fake(repo, once):
    fake = repo / "fake-review.py"
    fake.write_text(
        "import json,sys\n"
        "from pathlib import Path\n"
        "recipe = Path(sys.argv[sys.argv.index('--recipe') + 1])\n"
        "counter = recipe.parent / 'invocations.txt'\n"
        "count = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(count + 1))\n"
        + ("if count == 0:\n    Path('scratch-$null').write_text('junk')\n" if once
           else "Path('scratch-$null').write_text('junk')\n")
        + "events = json.loads(r'''REPLACE''')\n"
        .replace("REPLACE", json.dumps(REVIEW_EVENTS))
        + "for e in events:\n    print(json.dumps(e), flush=True)\n",
        encoding="utf-8")
    executable = repo / "fake-goose.cmd"
    executable.write_text('@echo off\n"' + sys.executable + '" "' + str(fake) + '" %*\n', encoding="utf-8")
    return executable


def test_review_heals_untracked_scratch_and_reruns_blind(repo):
    h = make_review_runner(repo)
    h.args.goose = review_fake(repo, once=True)
    seen = []
    h.notify = lambda k, m: seen.append((k, m))
    result = h.phase("review")
    assert result["status"] == "MUST_FIX"
    assert not (repo / "scratch-$null").exists()
    assert ("repair", "Read-only phase left untracked scratch files (scratch-$null); "
            "removed them and rerunning the blind phase") in seen
    assert (h.run_dir / "00-review-blind-retry.result.json").exists()


def test_review_repeated_mutation_stays_a_hard_failure(repo):
    h = make_review_runner(repo)
    h.args.goose = review_fake(repo, once=False)
    h.notify = lambda *a: None
    with pytest.raises(ValueError, match="Read-only phase mutated files"):
        h.phase("review")
    assert (repo / "scratch-$null").exists()  # preserved for inspection


def test_save_json_retries_while_a_reader_holds_the_target(tmp_path):
    import threading
    target = tmp_path / "status.json"
    runner.save_json(target, {"n": 0})
    with open(target, "r", encoding="utf-8") as handle:
        threading.Timer(0.2, handle.close).start()
        runner.save_json(target, {"n": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"n": 1}


def test_verify_chunk_rejects_malformed_test_paths_as_feedback(repo):
    h = make_review_runner(repo)
    seen = []
    h.notify = lambda k, m: seen.append((k, m))
    bad = "apps/web/tests (mirrored official lane: 90 *.e2e.ts, snapshots/**)"
    assert h.verify_chunk({"test_paths": [bad], "changed_files": []}) is False
    assert any(k == "verification" and "Rejected test path" in m for k, m in seen)
    assert h.verify_chunk({"test_paths": [], "changed_files": []}) is False


def test_migrate_filters_malformed_changed_file_entries(repo):
    h = make_review_runner(repo)
    fake = repo / "fake-migrate.py"
    fake.write_text(
        "import json,sys\n"
        "from pathlib import Path\n"
        "Path('real-change.txt').write_text('work')\n"
        "value = dict(status='READY', summary='worked', coverage_complete=True, issues=[],\n"
        "             changed_files=['real-change.txt', 'apps/web/dist (upstream build payload: *)'],\n"
        "             test_paths=['tests/test_unit.py'], dependencies=[],\n"
        "             test_map=['upstream case -> tests/test_unit.py -> PORTED'])\n"
        "events = [\n"
        " {'type':'message','message':{'id':'final','role':'assistant','content':["
        "{'type':'toolRequest','id':'t1','toolCall':{'value':{'name':'recipe__final_output','arguments':value}}}]}},\n"
        " {'type':'message','message':{'role':'user','content':["
        "{'type':'toolResponse','id':'t1','toolResult':{'status':'success','value':{}}}]}},\n"
        " {'type':'complete'},\n"
        "]\n"
        "for e in events:\n"
        "    print(json.dumps(e), flush=True)\n",
        encoding="utf-8")
    executable = repo / "fake-goose.cmd"
    executable.write_text('@echo off\n"' + sys.executable + '" "' + str(fake) + '" %*\n', encoding="utf-8")
    h.args.goose = executable
    seen = []
    h.notify = lambda k, m: seen.append((k, m))
    result = h.phase("migrate")
    assert result["changed_files"] == ["real-change.txt"]
    assert any(k == "files" and "Rejected changed-file entry" in m for k, m in seen)
