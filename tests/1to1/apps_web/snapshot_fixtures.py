"""
Port of the reference scaffold's fixture-inventory contract
(`reference/apps/web/tests/scaffold.ts:1231`, `assertFixtureInventory`).

Every web snapshot directory owns an optional `snapshot.yml` manifest plus its
artifacts; the manifest must name the `web` profile (and either own a
`session.jsonl` or point at another recorded Session source), and every
recorded Session log must already be scrubbed of request-header bulk and
tokenized ids, so a fixture can never leak a run-owned identity.
"""

import importlib
import io
import os
from typing import Any, List


def snapshot_support() -> Any:
    """
    Import the ported snapshot test-support package.

    The suite's import mode exposes `tests/1to1` as a search root, so the
    support package is reachable as `1to1._support...`; the fully-qualified
    spelling is kept as the fallback for runners that root the repository
    itself.
    """
    last_error: Exception
    for name in ("1to1._support.session_snapshot", "tests.1to1._support.session_snapshot"):
        try:
            return importlib.import_module(name)
        except ImportError as error:  # pragma: no cover - depends on the runner's sys.path
            last_error = error
    raise last_error


def _read(path: str) -> str:
    with io.open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def assertFixtureInventory(directory: str, expected: List[str]) -> None:
    """`assertFixtureInventory(dir, expected)` from the reference scaffold."""
    support = snapshot_support()
    entries = sorted(os.listdir(directory))
    owns_manifest = "snapshot.yml" in entries
    artifacts = [name for name in entries if name != "snapshot.yml"]
    assert artifacts == sorted(expected)
    if owns_manifest:
        manifest_path = os.path.join(directory, "snapshot.yml")
        manifest = support.parseSnapshotManifest(_read(manifest_path), manifest_path)
        assert manifest["profile"] == "web"
        if manifest.get("session") is None:
            assert "session.jsonl" in artifacts, "%s: session owner must carry session.jsonl" % directory
        else:
            assert os.path.exists(
                os.path.join(directory, manifest["session"]["source"])
            ), "%s: session source" % directory
    for entry in [name for name in artifacts if name.endswith(".jsonl")]:
        content = _read(os.path.join(directory, entry))
        assert support.scrubRequestHeaders(content) == content, (
            "%s/%s carries request-header bulk" % (directory, entry)
        )
        assert support.redactSessionSnapshotIds([content]) == [content], (
            "%s/%s carries unredacted identities" % (directory, entry)
        )
