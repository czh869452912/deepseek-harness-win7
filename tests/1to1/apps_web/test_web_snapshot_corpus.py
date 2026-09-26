"""
Corpus lane for the recorded-session snapshots the `apps/web` tests resolve.

The reference `apps/web` lane reads its fixtures from the repository snapshot
tree (`reference/apps/web/tests/*.snapshot.ts` ->
`fileURLToPath(new URL('../../../snapshots/web/<scenario>', import.meta.url))`).
Per `reference/snapshots/AGENTS.md` every scenario owns one primary
`session.jsonl` plus contiguous child files, or declares a read-only shared
source in its `snapshot.yml`; the manifest is the executable record of which
profile, composition, header class, workspace oracle, and replay override the
scenario needs.

The scenarios' goldens come in two faces:

  - **host face** — `session.jsonl` (the recorded Session the scenario boots
    from), `system-prompt.expected.md` and `tool-schemas.expected.json` (the
    request the Host assembles), and `protocol.expected.json` (the served
    Remote transcript). These are reproducible by a Python Host composition and
    are the half this port can execute without a browser;
  - **UI face** — the `*.expected.md` aria/geometry goldens a browser renders
    (`ui.expected.md`, `geometry.expected.md`, `sidebar.expected.md`, ...).

The cases below carry the corpus and pin the structure every scenario must
satisfy before either face can be replayed: the manifest, the resolvable
session source, the scrub/redaction invariants (`assertFixtureInventory`), and a
per-artifact classification so no golden is silently unowned. Replaying the
recorded sessions against the shipped profile is the `tests/web-snapshot-lane`
work item; the UI half additionally needs the Chromium lane
(`apps/web-browser-e2e-lane`).
"""

import os

from .snapshot_fixtures import assertFixtureInventory, snapshot_support

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CORPUS_ROOT = os.path.join(REPO_ROOT, "snapshots", "web")
REFERENCE_ROOT = os.path.join(REPO_ROOT, "reference", "snapshots", "web")

#: Host-face artifacts: the recorded Session plus the request/transcript goldens.
HOST_FACE = frozenset([
    "session.jsonl",
    "snapshot.yml",
    "system-prompt.expected.md",
    "tool-schemas.expected.json",
    "protocol.expected.json",
])

#: Manifest/support files a scenario may carry besides its goldens.
SUPPORT = frozenset(["input.json", "replay.override.json", "started.txt", "stdout.expected.jsonl"])


def scenarios(root=CORPUS_ROOT):
    """Every scenario directory of the corpus, sorted by name."""
    return sorted(name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name)))


def artifacts(directory):
    """Every file a scenario owns, as corpus-relative names."""
    found = []
    for dirpath, _dirnames, filenames in os.walk(directory):
        for name in filenames:
            found.append(os.path.relpath(os.path.join(dirpath, name), directory).replace(os.sep, "/"))
    return sorted(found)


def classify(name):
    """Which face consumes one artifact; `None` when the corpus has no owner for it."""
    base = name.rsplit("/", 1)[-1]
    if name.startswith("workspace.expected/"):
        # The committed workspace oracle of a mutating scenario (`snapshot.yml`
        # `workspace.final: true`); it is an independent oracle, never rewritten
        # by record or refresh.
        return "workspace-oracle"
    if base in HOST_FACE:
        return "host-face"
    if base in SUPPORT:
        return "host-face-support"
    if base.endswith(".expected.md") or base.endswith(".expected.json"):
        return "ui-face"
    if base == "SKILL.md":
        # A skill root's own document, seeded for the recorded session.
        return "seed"
    if base == ".gitkeep":
        return "marker"
    return None


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def test_the_web_snapshot_corpus_is_carried_verbatim():
    """
    Every scenario directory the reference lane resolves exists in the port.

    The port ships the corpus itself, not a rewritten copy: a scenario whose
    `session.jsonl` or golden drifted locally would make the lane compare
    against a fixture the recorded behavior never produced.
    """
    assert os.path.isdir(CORPUS_ROOT), CORPUS_ROOT
    official = scenarios(REFERENCE_ROOT)
    assert len(official) == 33, official
    assert scenarios() == official

    for name in official:
        expected = artifacts(os.path.join(REFERENCE_ROOT, name))
        actual = artifacts(os.path.join(CORPUS_ROOT, name))
        assert actual == expected, name
        for relative in expected:
            reference = os.path.join(REFERENCE_ROOT, name, relative)
            with open(reference, "rb") as handle:
                reference_bytes = handle.read()
            with open(os.path.join(CORPUS_ROOT, name, relative), "rb") as handle:
                assert handle.read() == reference_bytes, "%s/%s" % (name, relative)


def test_every_web_scenario_manifest_resolves_its_session_source():
    """
    Each manifest names the `web` profile and a Session source that resolves.

    `assertFixtureInventory` is the reference scaffold's own contract
    (`scaffold.ts:1231`): the manifest profile, a `session.jsonl` owner for a
    scenario that owns its recording, a resolvable declared source for a
    scenario that shares one, and logs that are already scrubbed of
    request-header bulk and tokenized identities.
    """
    support = snapshot_support()
    counts = {"manifest": 0, "session.jsonl": 0, "system-prompt.expected.md": 0,
              "tool-schemas.expected.json": 0, "protocol.expected.json": 0}
    owners = set()
    shared = set()

    for name in scenarios():
        directory = os.path.join(CORPUS_ROOT, name)
        entries = sorted(os.listdir(directory))
        assert "snapshot.yml" in entries, name
        manifest = support.parseSnapshotManifest(
            read_text(os.path.join(directory, "snapshot.yml")), os.path.join(directory, "snapshot.yml")
        )
        assert manifest["scenario"] == name
        assert manifest["profile"] == "web"
        assert manifest["header"] is not None and isinstance(manifest["header"]["class"], str)
        counts["manifest"] += 1

        source = manifest.get("session")
        if source is None:
            owners.add(name)
            assert "session.jsonl" in entries, name
        else:
            shared.add(name)
            resolved = os.path.normpath(os.path.join(directory, source["source"]))
            assert os.path.isfile(resolved), "%s: %s" % (name, source["source"])

        for entry in entries:
            if entry in counts:
                counts[entry] += 1

        # The reference's inventory contract, over the scenario's top level.
        assertFixtureInventory(directory, [entry for entry in entries if entry != "snapshot.yml"])

    # The corpus is not a hand-picked subset: every scenario owns a manifest,
    # and the recorded-session owners and their shared readers stay disjoint.
    assert counts["manifest"] == 33
    assert counts["session.jsonl"] == 20
    assert counts["system-prompt.expected.md"] == 4
    assert counts["tool-schemas.expected.json"] == 4
    assert counts["protocol.expected.json"] == 1
    assert owners and shared and not (owners & shared)

    # Two scenarios deliberately reference a recorded Session outside the web
    # corpus (a cross-profile replay); the web manifests are the only web-owned
    # readers of those logs.
    external = {
        "bash-abort-row": "../../acp/cancel-tool-calls/session.jsonl",
        "skill-tool-row": "../../session/skill-load/session.jsonl",
        "workflow-run": "../../session/workflow-run/session.jsonl",
    }
    for name, declared in external.items():
        manifest = support.parseSnapshotManifest(
            read_text(os.path.join(CORPUS_ROOT, name, "snapshot.yml")),
            os.path.join(CORPUS_ROOT, name, "snapshot.yml"),
        )
        assert manifest["session"]["source"] == declared
        assert os.path.isfile(os.path.normpath(os.path.join(REPO_ROOT, "snapshots", declared[6:])))


def test_host_face_goldens_are_classified_apart_from_the_ui_goldens():
    """
    Per-artifact classification of the whole corpus.

    The host-face goldens the composition can reproduce are exactly the ones
    four scenarios pin (`cordis-tool-round`, `fresh-round-trip`,
    `minimal-preset`, `ptc-round`) plus the served Remote transcript
    `message-feedback-protocol`; every other `*.expected.*` file is a UI golden
    only a rendered browser produces. A golden that belongs to neither bucket
    would be a scenario artifact no lane reads.
    """
    buckets = {"host-face": [], "host-face-support": [], "ui-face": [], "seed": [], "marker": [],
               "workspace-oracle": []}
    prompt_goldens = set()
    schema_goldens = set()
    protocol_goldens = set()

    for name in scenarios():
        for relative in artifacts(os.path.join(CORPUS_ROOT, name)):
            bucket = classify(relative)
            assert bucket is not None, "%s/%s has no owning lane" % (name, relative)
            buckets[bucket].append("%s/%s" % (name, relative))
            if relative == "system-prompt.expected.md":
                prompt_goldens.add(name)
            if relative == "tool-schemas.expected.json":
                schema_goldens.add(name)
            if relative == "protocol.expected.json":
                protocol_goldens.add(name)

    assert prompt_goldens == {"cordis-tool-round", "fresh-round-trip", "minimal-preset", "ptc-round"}
    assert schema_goldens == prompt_goldens
    assert protocol_goldens == {"message-feedback-protocol"}

    # The host-face request goldens always travel with the recorded Session the
    # request was assembled from, never as a bare sidecar.
    for name in sorted(prompt_goldens):
        directory = os.path.join(CORPUS_ROOT, name)
        entries = sorted(os.listdir(directory))
        assert "session.jsonl" in entries, name

    # The UI bucket is the majority of the corpus: this is the half that needs
    # the browser lane, and it is recorded as such rather than deleted.
    assert len(buckets["ui-face"]) > 50, len(buckets["ui-face"])
    assert len(buckets["host-face"]) > 30, len(buckets["host-face"])
    assert all("/../" not in entry for entry in buckets["ui-face"])
