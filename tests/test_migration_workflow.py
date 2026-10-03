"""Migration gates reject false progress and preserve historical integration."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "migration_workflow", Path(__file__).resolve().parents[1] / "scripts/migration.py"
)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
SHA = "a" * 40


@pytest.fixture
def ledger(tmp_path):
    (tmp_path / "source.py").write_text("def test_case(): pass\n", encoding="utf-8")
    (tmp_path / "result.txt").write_text("passed\n", encoding="utf-8")
    contract = {"id": "CON-A", "revision": 1, "target_upstream": SHA,
                "status": "specified", "source_paths": ["source.py"],
                "invariants": ["one invariant"], "consumers": [], "open_questions": []}
    contract.update({key: "source-backed requirement" for key in
                     ("identity", "ownership", "ordering", "errors", "cancellation", "adaptation")})
    task = {"id": "TASK-A", "goal": "verify A", "kind": "verification", "state": "ready",
            "target_upstream": SHA, "base_product": SHA, "requires": [],
            "provides": [{"contract": "CON-A", "revision": 1}], "acceptance": ["real consumer"],
            "expected_paths": [], "evidence_ids": [], "open_findings": [],
            "next_action": "run scenario", "conflicts_with": [], "owner": None,
            "candidate_commit": None, "integrated_commit": None}
    data = {"baseline": {"schema_version": 1, "product_commit": SHA, "target_upstream": SHA,
                         "accepted_upstream": None, "observed_upstream": None},
            "modules": {"target_upstream": SHA, "manifests": [], "non_package_surfaces": []},
            "contracts": {"CON-A": contract}, "tasks": {"TASK-A": task},
            "evidence": {}, "mappings": {}}
    return data, tmp_path


def add_consumer(data):
    task = copy.deepcopy(data["tasks"]["TASK-A"])
    task.update(id="TASK-B", goal="consumer", provides=[],
                requires=[{"task": "TASK-A", "contract": "CON-A", "revision": 1}])
    data["tasks"]["TASK-B"] = task
    return task


def certify(data, root, state="integrated"):
    task = data["tasks"]["TASK-A"]
    task.update(state=state, owner="coordinator", candidate_commit=SHA,
                integrated_commit=SHA if state == "integrated" else None,
                evidence_ids=["RUN-A"])
    def digest(name):
        return hashlib.sha256((root / name).read_bytes()).hexdigest()
    run = {"id": "RUN-A", "task_id": "TASK-A", "acceptance_digest": m.acceptance_digest(task),
           "kind": "acceptance", "result": "passed", "validity": "current",
           "target_upstream": SHA, "product_commit": SHA, "exit_code": 0,
           "environment": {"python": "3.8.10", "os": "test", "cwd": str(root)},
           "commands": ["pytest"], "contract_revisions": {"CON-A": 1},
           "inputs": [{"path": "source.py", "sha256": digest("source.py")}],
           "artifacts": [{"path": "result.txt", "sha256": digest("result.txt")}]}
    data["evidence"]["RUN-A"] = run
    return run


def test_dependency_requires_integrated_exact_contract_evidence(ledger):
    data, root = ledger
    consumer = add_consumer(data)
    m.validate(data, root)
    assert m.blockers(consumer, data)
    certify(data, root, "verified")
    m.validate(data, root)
    assert m.blockers(consumer, data)
    certify(data, root)
    m.validate(data, root)
    assert not m.blockers(consumer, data)


def test_shared_evidence_reads_each_file_once_and_rechecks_in_next_validation(ledger, monkeypatch):
    data, root = ledger
    run = certify(data, root)
    second = copy.deepcopy(run)
    second['id'] = 'RUN-B'
    second['inputs'][0]['sha256'] = '0' * 64
    data['evidence']['RUN-B'] = second
    calls = []
    original = Path.read_bytes
    def read(path):
        calls.append(path.name)
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', read)
    m.validate(data, root)
    assert calls.count('source.py') == 1 and calls.count('result.txt') == 1
    assert run['_inputs_current'] is True and second['_inputs_current'] is False
    (root / 'source.py').write_text('changed input\n', encoding='utf-8')
    m.validate(data, root)
    assert run['_inputs_current'] is False and calls.count('source.py') == 2
    (root / 'result.txt').write_text('changed receipt\n', encoding='utf-8')
    with pytest.raises(m.RecordError, match='artifact hash mismatch'):
        m.validate(data, root)


@pytest.mark.parametrize("change", ["stale", "input", "deleted-input"])
def test_stale_evidence_blocks_consumers_without_erasing_integration(ledger, change):
    data, root = ledger
    consumer = add_consumer(data)
    run = certify(data, root)
    if change == "stale":
        run["validity"] = "stale"
    elif change == "input":
        (root / "source.py").write_text("def test_case(): return 42\n", encoding="utf-8")
    else:
        # The deleted input is distinct from the required contract source.
        run["inputs"][0]["path"] = "removed-consumer.py"
    m.validate(data, root)
    assert data["tasks"]["TASK-A"]["state"] == "integrated"
    assert m.blockers(consumer, data)


@pytest.mark.parametrize("change", ["result", "commit", "target", "revision", "spec", "exit", "task", "artifacts"])
def test_cannot_certify_wrong_or_self_reported_evidence(ledger, change):
    data, root = ledger
    run = certify(data, root, "verified")
    if change == "result":
        run["result"] = "failed"
    elif change == "commit":
        run["product_commit"] = "b" * 40
    elif change == "target":
        run["target_upstream"] = "b" * 40
    elif change == "revision":
        run["contract_revisions"]["CON-A"] = 2
    elif change == "spec":
        data["tasks"]["TASK-A"]["acceptance"].append("new requirement")
    elif change == "exit":
        run["exit_code"] = 1
    elif change == "task":
        run["task_id"] = "TASK-B"
    else:
        run["artifacts"] = []
    with pytest.raises(m.RecordError):
        m.validate(data, root)


def test_artifact_tampering_is_not_a_product_failure(ledger):
    data, root = ledger
    certify(data, root)
    (root / "result.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(m.RecordError, match="artifact hash mismatch"):
        m.validate(data, root)


def test_missing_and_stale_dependency_rejected(ledger):
    data, root = ledger
    consumer = add_consumer(data)
    consumer["requires"][0]["task"] = "UNKNOWN"
    with pytest.raises(m.RecordError, match="missing dependency"):
        m.validate(data, root)
    consumer["requires"][0]["task"] = "TASK-A"
    consumer["requires"][0]["revision"] = 2
    with pytest.raises(m.RecordError, match="stale dependency revision"):
        m.validate(data, root)


def test_real_cycle_rejected_instead_of_silently_dropping_edge(ledger):
    data, root = ledger
    consumer = add_consumer(data)
    consumer["provides"] = [{"contract": "CON-A", "revision": 1}]
    data["tasks"]["TASK-A"]["requires"] = [{"task": "TASK-B", "contract": "CON-A", "revision": 1}]
    with pytest.raises(m.RecordError, match="cycle"):
        m.validate(data, root)


def test_one_sided_conflict_blocks_both_directions(ledger):
    data, root = ledger
    peer = add_consumer(data)
    peer.update(requires=[], state="running", owner="worker")
    peer["conflicts_with"] = ["TASK-A"]
    m.validate(data, root)
    assert m.blockers(data["tasks"]["TASK-A"], data) == ["active conflict TASK-B"]


def test_paths_are_advisory_not_write_whitelists(ledger):
    data, root = ledger
    data["tasks"]["TASK-A"]["expected_paths"] = ["new-provider", "new-consumer"]
    m.validate(data, root)
    assert not m.blockers(data["tasks"]["TASK-A"], data)


def test_draft_contract_cannot_unlock_consumers(ledger):
    data, root = ledger
    consumer = add_consumer(data)
    certify(data, root)
    data["contracts"]["CON-A"]["status"] = "draft"
    m.validate(data, root)
    assert m.blockers(consumer, data)


def test_contract_upgrade_keeps_old_integrated_fact_but_invalidates_eligibility(ledger):
    data, root = ledger
    certify(data, root)
    data["contracts"]["CON-A"]["revision"] = 2
    m.validate(data, root)
    assert data["tasks"]["TASK-A"]["provides"][0]["revision"] == 1
    assert not m.valid_runs(data["tasks"]["TASK-A"], data)
    assert "historical integration; revalidation required" in m.render_status(data)


def test_new_target_does_not_rewrite_historical_integration(ledger):
    data, root = ledger
    certify(data, root)
    newer = "b" * 40
    data["baseline"]["target_upstream"] = newer
    data["modules"]["target_upstream"] = newer
    data["contracts"]["CON-A"]["target_upstream"] = newer
    m.validate(data, root)
    assert data["tasks"]["TASK-A"]["target_upstream"] == SHA
    assert not m.valid_runs(data["tasks"]["TASK-A"], data)


def test_status_does_not_claim_global_parity(ledger):
    data, root = ledger
    m.validate(data, root)
    status = m.render_status(data)
    assert "not established" in status
    assert "not certified parity" in status
    assert "eligible" in status


def test_bad_json_reports_path_not_stack_trace(tmp_path, capsys):
    (tmp_path / "migration").mkdir()
    (tmp_path / "migration/baseline.json").write_text("{bad", encoding="utf-8")
    assert m.main(["check", "--root", str(tmp_path)]) == 1
    assert "baseline.json" in capsys.readouterr().err


def test_new_upstream_manifest_is_not_silently_ignored(ledger, monkeypatch):
    data, root = ledger
    monkeypatch.setattr(m, "git", lambda root, *args: SHA if args[0] == "rev-parse" else "")
    monkeypatch.setattr(m, "source_inventory", lambda root: [{"path": "new/package.json", "sha256": "new"}])
    with pytest.raises(m.RecordError, match="inventory drift"):
        m.validate_checkout(data, root)


def test_tracked_inventory_includes_non_workspace_sdk_and_fixtures(tmp_path, monkeypatch):
    paths = ["python/sdk-runtime/package.json", "packages/p/tests/fixtures/f/package.json"]
    for name in paths:
        path = tmp_path / "reference" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": name}), encoding="utf-8")
    monkeypatch.setattr(m, "git", lambda *args: "\n".join(paths))
    rows = m.source_inventory(tmp_path)
    assert len(rows) == 2
    assert rows[0]["classification"] == "untriaged"
    assert rows[1]["classification"] == "fixture"


@pytest.mark.parametrize("bad", [None, [], "invalid"])
def test_malformed_dependencies_have_actionable_error(ledger, bad):
    data, root = ledger
    data["tasks"]["TASK-A"]["requires"] = [bad]
    with pytest.raises(m.RecordError, match="requires: expected object"):
        m.validate(data, root)
