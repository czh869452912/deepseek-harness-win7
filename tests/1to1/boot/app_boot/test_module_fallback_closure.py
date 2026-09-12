"""
1:1 parity suite for the installation module-fallback closure
(`dsh/boot/profile.py: resolve_module_fallback_entries`).

Upstream is `reference/packages/boot/app-boot/src/profile.ts`
`resolveModuleFallbackEntries` and its pinned case
`reference/packages/boot/app-boot/tests/profile.spec.ts` >
"healProfilesModuleFallback" > "links the app and bundle dependency surface flat
under profiles/node_modules": the healed `$DSH_HOME/profiles/node_modules`
mirrors every dependency and peer dependency reachable from the install anchor,
resolved the way Node resolves it (nearest wins; an uninstalled dependency is
skipped rather than failing the boot).

The Python runtime has no Node module graph, so the pinned workspace layout
stands in for it. This suite derives the expected closure from the pinned
manifests itself and compares the sets, so a hardcoded resolution list cannot
pass: the closure must equal what the manifests require.
"""

import asyncio
import json
import os
import shutil
import tempfile
from typing import Dict, List, Set

import pytest

import dsh.boot.profile as profile_module
from dsh.boot.profile import (
    heal_profiles_module_fallback,
    is_symlink_or_junction,
    read_module_fallback_manifest,
    resolve_module_fallback_entries,
)
from dsh.boot.plugin_registry import installation_module_roots
from dsh.boot.profile_boot import INSTALL_ANCHOR
from dsh.cordis.loader import exports_subpath_target, resolve_module_specifier


def _repository_root() -> str:
    """Walk up from this test to the checkout root that carries packages/bundle."""
    current = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(current, "packages", "bundle")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError("test_module_fallback_closure: cannot locate the repository root")
        current = parent


REPOSITORY_ROOT = _repository_root()


def _inventory() -> Dict[str, str]:
    """
    Every package the checkout carries, by name.

    The test reads the manifests itself: a name -> directory map built here is
    independent evidence, not a call into the resolution under test.
    """
    found: Dict[str, str] = {}
    roots = [
        os.path.join(REPOSITORY_ROOT, "packages"),
        os.path.join(REPOSITORY_ROOT, "reference", "packages"),
        os.path.join(REPOSITORY_ROOT, "apps"),
        os.path.join(REPOSITORY_ROOT, "reference", "apps"),
        os.path.join(REPOSITORY_ROOT, "vendor"),
        os.path.join(REPOSITORY_ROOT, "reference", "vendor"),
    ]
    for base in roots:
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base)):
            first = os.path.join(base, entry)
            candidates: List[str] = []
            if os.path.isfile(os.path.join(first, "package.json")):
                candidates.append(first)
            if os.path.isdir(first):
                for nested in sorted(os.listdir(first)):
                    second = os.path.join(first, nested)
                    if os.path.isfile(os.path.join(second, "package.json")):
                        candidates.append(second)
            for directory in candidates:
                try:
                    with open(os.path.join(directory, "package.json"), "r", encoding="utf-8") as f:
                        name = json.load(f).get("name")
                except Exception:
                    continue
                if isinstance(name, str) and name and name not in found:
                    found[name] = directory
    return found


def expected_closure(anchor: str) -> Set[str]:
    """
    Every dependency and peer dependency reachable from `anchor`, nearest-wins.

    @param anchor: absolute path of the install anchor manifest.
    @returns: the package names the healed closure must carry.
    """
    inventory = _inventory()
    manifest = read_module_fallback_manifest(anchor)
    links: Dict[str, str] = {}
    if isinstance(manifest.get("name"), str):
        links[manifest["name"]] = os.path.dirname(os.path.abspath(anchor))
    queue = [(anchor, manifest)]
    while queue:
        _, current = queue.pop(0)
        names = list(current.get("dependencies", {})) + list(current.get("peerDependencies", {}))
        for name in names:
            if name in links:
                continue
            directory = inventory.get(name)
            # A declared-but-uninstalled dependency cannot be loader-visible and
            # is skipped, exactly as the healing pass skips it.
            if directory is None:
                continue
            links[name] = directory
            queue.append((os.path.join(directory, "package.json"), read_module_fallback_manifest(os.path.join(directory, "package.json"))))
    return set(links)


def test_the_pinned_manifests_reach_more_than_the_app_dependency_surface():
    """
    Guard the fixture itself: the closure is a real closure over the pinned
    manifests, not the app's own dependency list.
    """
    app = read_module_fallback_manifest(INSTALL_ANCHOR)
    assert len(expected_closure(INSTALL_ANCHOR)) > len(app.get("dependencies", {}))
    assert len(expected_closure(INSTALL_ANCHOR)) >= 200


@pytest.mark.asyncio
async def test_resolves_every_dependency_and_peer_dependency_the_pinned_manifests_reach():
    """
    The resolved closure equals the dependency and peer-dependency closure of
    the pinned manifests: no workspace category is invisible to it.
    """
    entries, names = resolve_module_fallback_entries(INSTALL_ANCHOR)
    expected = expected_closure(INSTALL_ANCHOR)
    assert names == expected
    assert len(entries) == len(names)
    for entry in entries:
        assert entry["kind"] == "symlink"
        assert os.path.isdir(entry["packageDir"])
        assert os.path.isfile(os.path.join(entry["packageDir"], "package.json"))
        assert read_module_fallback_manifest(os.path.join(entry["packageDir"], "package.json"))["name"] == entry["packageName"]


@pytest.mark.asyncio
async def test_every_healed_package_is_declared_by_a_manifest_the_closure_reaches():
    """
    The Node-anchor invariant, checked against the healed generation itself.

    Node can only import a package some reachable manifest declares, so every
    healed entry must be named by the anchor manifest or by the manifest of
    another healed entry. This reads the resolver's own output and the pinned
    manifests, so an over-resolving workspace scan (a package merely present in
    the checkout) fails here even though the inventory-based expectation above
    would still agree with it.
    """
    entries, names = resolve_module_fallback_entries(INSTALL_ANCHOR)
    declared: Set[str] = set()
    app_manifest = read_module_fallback_manifest(INSTALL_ANCHOR)
    declared.update(app_manifest.get("dependencies", {}))
    declared.update(app_manifest.get("peerDependencies", {}))
    if isinstance(app_manifest.get("name"), str):
        declared.add(app_manifest["name"])
    for entry in entries:
        manifest = read_module_fallback_manifest(
            os.path.join(entry["packageDir"], "package.json")
        )
        declared.update(manifest.get("dependencies", {}))
        declared.update(manifest.get("peerDependencies", {}))
    assert names <= declared


@pytest.mark.asyncio
async def test_the_closure_carries_packages_no_bundle_category_list_names():
    """
    The rows the profiles mount live outside the bundles' own categories; a
    category-filtered probe cannot answer them.
    """
    _, names = resolve_module_fallback_entries(INSTALL_ANCHOR)
    for name in (
        "@deepseek-ai/dsh-llm-deepseek",
        "@deepseek-ai/dsh-terminal",
        "@deepseek-ai/dsh-sandbox-local",
        "@deepseek-ai/dsh-api-gateway",
        "@deepseek-ai/dsh-client-connection",
    ):
        assert name in names


@pytest.mark.asyncio
async def test_heals_the_whole_closure_flat_and_is_idempotent():
    """The healed generation publishes one link per resolved package, once."""
    home = tempfile.mkdtemp(prefix="dsh-closure-heal-")
    try:
        entries, names = resolve_module_fallback_entries(INSTALL_ANCHOR)
        await heal_profiles_module_fallback({"installAnchor": INSTALL_ANCHOR, "home": home})
        modules = os.path.join(home, "profiles", "node_modules")
        for entry in entries:
            link = os.path.join(modules, entry["packageName"])
            assert is_symlink_or_junction(link), entry["packageName"]

        # A second heal over a current generation rewrites nothing.
        before = {
            entry["packageName"]: os.path.getmtime(os.path.join(modules, entry["packageName"]))
            for entry in entries
        }
        await heal_profiles_module_fallback({"installAnchor": INSTALL_ANCHOR, "home": home})
        after = {
            entry["packageName"]: os.path.getmtime(os.path.join(modules, entry["packageName"]))
            for entry in entries
        }
        assert before == after
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_the_workspace_scan_runs_once_per_workspace(monkeypatch):
    """
    Resolution is index-backed: hundreds of anchors inside one workspace share
    one scan, so the heal cost stays bounded as the closure grows.
    """
    scans: List[str] = []
    original = profile_module._workspace_manifests

    def counted(directory: str):
        scans.append(directory)
        return original(directory)

    monkeypatch.setattr(profile_module, "_workspace_manifests", counted)
    profile_module._WORKSPACE_PACKAGE_INDEX_CACHE.clear()
    profile_module._NODE_MODULES_CHAIN_CACHE.clear()

    entries, names = resolve_module_fallback_entries(INSTALL_ANCHOR)
    assert len(names) > 100
    first_pass = len(scans)
    # One scan per ancestor the resolution scope carries, never one per anchor:
    # 219 packages resolved by ~320 lookups cost the same scan as the anchor's
    # own first lookup.
    assert 0 < first_pass < 20

    # A second resolution reuses the index: no further filesystem walk at all.
    entries_again, names_again = resolve_module_fallback_entries(INSTALL_ANCHOR)
    assert names_again == names
    assert len(entries_again) == len(entries)
    assert len(scans) == first_pass


@pytest.mark.asyncio
async def test_the_healed_generation_resolves_every_shipped_subpath_row_through_its_exports_map():
    """
    The pinned Node-anchor contract, end to end on the real installation.

    A row named `<package>/<subpath>` (dsh-web-app/startup, dsh-headless/startup,
    dsh-tool-subagent-control/list-agents) resolves the way Node resolves it:
    the healed `$DSH_HOME/profiles/node_modules` link makes the package root
    reachable, and the package's own `exports` map answers the subpath. No
    synthetic staging is involved: this heals the pinned installation anchor and
    then resolves from an ordinary profile directory.
    """
    home = tempfile.mkdtemp(prefix="dsh-subpath-closure-")
    try:
        await heal_profiles_module_fallback({"installAnchor": INSTALL_ANCHOR, "home": home})
        profile_dir = os.path.join(home, "profiles", "standard")
        os.makedirs(profile_dir, exist_ok=True)
        config = os.path.join(profile_dir, "cordis.yml")
        with open(config, "w", encoding="utf-8") as f:
            f.write("[]\n")
        roots = installation_module_roots(config, home)
        for row, package, subpath in (
            ("@deepseek-ai/dsh-web-app/startup", "@deepseek-ai/dsh-web-app", "startup"),
            ("@deepseek-ai/dsh-headless/startup", "@deepseek-ai/dsh-headless", "startup"),
            (
                "@deepseek-ai/dsh-tool-subagent-control/list-agents",
                "@deepseek-ai/dsh-tool-subagent-control",
                "list-agents",
            ),
        ):
            resolved = resolve_module_specifier(row, profile_dir, roots)
            assert resolved is not None, row
            # The resolved target is the package's own declared export target,
            # computed from the manifest the healed link points at.
            package_link = os.path.join(
                home, "profiles", "node_modules", *package.split("/")
            )
            assert os.path.isdir(package_link), package
            with open(os.path.join(package_link, "package.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f)
            target = exports_subpath_target(manifest.get("exports"), subpath)
            assert isinstance(target, str), f"{package} declares no ./{subpath} export"
            assert os.path.realpath(resolved) == os.path.realpath(
                os.path.join(os.path.realpath(package_link), target)
            )
    finally:
        shutil.rmtree(home, ignore_errors=True)
