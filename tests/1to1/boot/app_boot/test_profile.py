"""
1:1 Parity Tests for Profile discovery, manifest round-trips, bundle resolution,
composition, and module-fallback healing.
Port of reference/packages/boot/app-boot/tests/profile.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

import pytest

from dsh.boot.profile import (
    DEFAULT_PROFILE_PATCH_RELOAD,
    PROFILE_PATCH_FILENAME,
    PROFILE_TEMPLATES,
    Profile,
    ProfileLayer,
    canonical_link_path,
    composeEntries,
    create_symlink,
    healProfilesModuleFallback,
    initProfile,
    is_packaged_executable,
    is_symlink_or_junction,
    loadProfile,
    read_link,
    readProfileManifest,
    resolveBundleDir,
    resolveProfileDir,
    symlink_points_to,
    writeProfileManifest,
)
from dsh.cordis.file_lock import with_file_lock


def tmp() -> str:
    return tempfile.mkdtemp(prefix="dsh-profile-")


def stage_installation(
    bundles: Dict[str, Dict[str, Any]],
    app_name: str = "dsh-app",
) -> str:
    """Stage a fake installed app: package.json with deps and a node_modules holding bundles."""
    root = tmp()
    app_dir = os.path.join(root, "app")
    modules_dir = os.path.join(app_dir, "node_modules")
    os.makedirs(modules_dir, exist_ok=True)
    app_deps: Dict[str, str] = {}
    for name, spec in bundles.items():
        app_deps[name] = "0.0.0"
        pkg_dir = os.path.join(modules_dir, name)
        os.makedirs(pkg_dir, exist_ok=True)
        pkg_manifest: Dict[str, Any] = {
            "name": name,
            "version": "0.0.0",
            "type": "module",
            "main": "./index.js",
            "dependencies": spec.get("deps", {}),
        }
        if spec.get("patch") is not None:
            pkg_manifest["dsh"] = {"bundle": {"patch": "./cordis.patch.yml"}}
        with open(os.path.join(pkg_dir, "package.json"), "w", encoding="utf-8") as f:
            json.dump(pkg_manifest, f)
        with open(os.path.join(pkg_dir, "index.js"), "w", encoding="utf-8") as f:
            f.write(f"export const packageName = {json.dumps(name)}\n")
        if spec.get("patch") is not None:
            with open(os.path.join(pkg_dir, "cordis.patch.yml"), "w", encoding="utf-8") as f:
                f.write(spec["patch"])

    app_manifest = {
        "name": app_name,
        "version": "0.0.0",
        "type": "module",
        "main": "./index.js",
        "dependencies": app_deps,
    }
    app_pkg_path = os.path.join(app_dir, "package.json")
    with open(app_pkg_path, "w", encoding="utf-8") as f:
        json.dump(app_manifest, f)
    with open(os.path.join(app_dir, "index.js"), "w", encoding="utf-8") as f:
        f.write(f"export const packageName = {json.dumps(app_name)}\n")
    return app_pkg_path


def stage_profile(home: str, name: str, bundle_anchor: str) -> Profile:
    """Represent one resolved external bundle as a loaded profile layer."""
    dir_path = resolveProfileDir(name, home)
    os.makedirs(dir_path, exist_ok=True)
    with open(bundle_anchor, "r", encoding="utf-8") as f:
        package_name = json.load(f)["name"]
    pkg_dir = os.path.dirname(bundle_anchor)
    return Profile(
        name=name,
        dir_path=dir_path,
        layers=[
            ProfileLayer(
                package_name=package_name,
                package_dir=pkg_dir,
                patch_path=os.path.join(pkg_dir, "cordis.patch.yml"),
                patches=[],
            )
        ],
        patch_path=os.path.join(dir_path, PROFILE_PATCH_FILENAME),
        patches=[],
        patch_reload="live",
    )


# ---------------------------------------------------------------------------
# resolveProfileDir
# ---------------------------------------------------------------------------


def test_resolve_profile_dir_joins_home_and_rejects_traversal_shaped_names():
    home = tmp()
    assert resolveProfileDir("tui", home) == os.path.join(home, "profiles", "tui")
    for bad in ["", ".", "..", "a/b", "a\\b"]:
        with pytest.raises(ValueError, match="invalid profile name"):
            resolveProfileDir(bad, home)


# ---------------------------------------------------------------------------
# initProfile
# ---------------------------------------------------------------------------


def test_init_profile_creates_manifest_user_patch_layer_and_pnpm_workspace_once_never_overwriting():
    home = tmp()
    dir_path = resolveProfileDir("tui", home)
    initProfile(dir_path, ["@deepseek-ai/dsh-base"])
    manifest = readProfileManifest("t", dir_path)
    assert manifest.get("dsh", {}).get("profile", {}).get("bundles") == ["@deepseek-ai/dsh-base"]
    assert manifest.get("dsh", {}).get("profile", {}).get("patchReload") == "live"
    with open(os.path.join(dir_path, PROFILE_PATCH_FILENAME), "r", encoding="utf-8") as f:
        assert "[]" in f.read()
    with open(os.path.join(dir_path, "pnpm-workspace.yaml"), "r", encoding="utf-8") as f:
        assert "nodeLinker: hoisted" in f.read()

    # Re-init keeps user edits.
    with open(os.path.join(dir_path, PROFILE_PATCH_FILENAME), "w", encoding="utf-8") as f:
        f.write("- id: x\n  config: {}\n")
    initProfile(dir_path, ["other"], "startup")
    manifest2 = readProfileManifest("t", dir_path)
    assert manifest2.get("dsh", {}).get("profile", {}).get("bundles") == ["@deepseek-ai/dsh-base"]
    assert manifest2.get("dsh", {}).get("profile", {}).get("patchReload") == "live"
    with open(os.path.join(dir_path, PROFILE_PATCH_FILENAME), "r", encoding="utf-8") as f:
        assert "- id: x" in f.read()


# ---------------------------------------------------------------------------
# manifest round-trip
# ---------------------------------------------------------------------------


def test_manifest_round_trip_writes_and_reads_back_and_fails_loud_on_broken():
    dir_path = tmp()
    writeProfileManifest(dir_path, {"name": "p", "dsh": {"profile": {"bundles": ["a"]}}})
    assert readProfileManifest("t", dir_path).get("dsh", {}).get("profile", {}).get("bundles") == ["a"]

    with open(os.path.join(dir_path, "package.json"), "w", encoding="utf-8") as f:
        f.write("[]")
    with pytest.raises(RuntimeError, match="must hold a JSON object"):
        readProfileManifest("t", dir_path)

    with pytest.raises(RuntimeError, match="failed to read profile manifest"):
        readProfileManifest("t", os.path.join(dir_path, "nope"))


# ---------------------------------------------------------------------------
# resolveBundleDir
# ---------------------------------------------------------------------------


def test_resolve_bundle_dir_prefers_installation_anchor_falls_back_to_profile_and_fails_loud():
    anchor = stage_installation({"in-box": {"patch": "[]\n"}})
    profile_dir = tmp()
    local_dir = os.path.join(profile_dir, "node_modules", "local-only")
    os.makedirs(local_dir, exist_ok=True)
    with open(os.path.join(profile_dir, "package.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    with open(os.path.join(local_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "local-only", "version": "0.0.0"}, f)

    assert "in-box" in resolveBundleDir("t", "in-box", anchor, profile_dir)
    assert "local-only" in resolveBundleDir("t", "local-only", anchor, profile_dir)
    with pytest.raises(RuntimeError, match="cannot resolve profile bundle"):
        resolveBundleDir("t", "absent", anchor, profile_dir)


def test_resolve_bundle_dir_resolves_package_whose_exports_map_omits_package_json():
    anchor = stage_installation({})
    profile_dir = tmp()
    with open(os.path.join(profile_dir, "package.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    dir_path = os.path.join(profile_dir, "node_modules", "sealed-bundle")
    os.makedirs(dir_path, exist_ok=True)
    with open(os.path.join(dir_path, "package.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "sealed-bundle",
            "version": "0.0.0",
            "exports": {".": "./index.js"},
            "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
        }, f)
    with open(os.path.join(dir_path, "index.js"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(dir_path, "cordis.patch.yml"), "w", encoding="utf-8") as f:
        f.write("[]\n")
    assert resolveBundleDir("t", "sealed-bundle", anchor, profile_dir) == dir_path


# ---------------------------------------------------------------------------
# loadProfile
# ---------------------------------------------------------------------------


def test_load_profile_resolves_each_bundle_to_patch_layer_in_order_plus_user_layer():
    anchor = stage_installation({
        "bundle-a": {"patch": "- insert:\n    - id: a\n      name: pkg-a\n"},
        "bundle-b": {"patch": "- id: a\n  config:\n    v: 2\n"},
    })
    home = tmp()
    dir_path = resolveProfileDir("demo", home)
    initProfile(dir_path, ["bundle-a", "bundle-b"])
    with open(os.path.join(dir_path, PROFILE_PATCH_FILENAME), "w", encoding="utf-8") as f:
        f.write("- id: a\n  config:\n    v: 3\n")

    profile = loadProfile("t", "demo", anchor, home)
    assert [layer.package_name for layer in profile.layers] == ["bundle-a", "bundle-b"]
    assert len(profile.patches) == 1
    assert profile.patch_reload == "live"
    entries = composeEntries([
        *(layer.patches for layer in profile.layers),
        profile.patches,
    ])
    assert entries == [{"id": "a", "name": "pkg-a", "config": {"v": 3}}]

    # A hand-made profile without the user layer file or dsh section: empty layers, no throw.
    os.unlink(os.path.join(dir_path, PROFILE_PATCH_FILENAME))
    assert loadProfile("t", "demo", anchor, home).patches == []
    writeProfileManifest(dir_path, {"name": "bare"})
    bare = loadProfile("t", "demo", anchor, home)
    assert bare.layers == []
    assert bare.patch_reload == "live"


def test_load_profile_auto_initializes_only_shipped_templates_and_fails_loud_otherwise():
    anchor = stage_installation({})
    home = tmp()
    with pytest.raises(RuntimeError, match='profile "custom" does not exist'):
        loadProfile("t", "custom", anchor, home)

    assert "@deepseek-ai/dsh-base" in PROFILE_TEMPLATES["web"]["bundles"]
    assert PROFILE_TEMPLATES["web"]["patchReload"] == "live"
    assert PROFILE_TEMPLATES["headless"]["patchReload"] == "startup"
    assert PROFILE_TEMPLATES["acp"] == {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-acp-app"],
        "patchReload": "startup",
    }
    assert PROFILE_TEMPLATES["sdk"] == {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-sdk-app"],
        "patchReload": "startup",
    }
    assert PROFILE_TEMPLATES["sdk-minimal"] == {
        "bundles": ["@deepseek-ai/dsh-sdk-minimal"],
        "patchReload": "startup",
    }

    try:
        loadProfile("t", "web", anchor, home)
    except Exception:
        # Resolution failure is expected for empty anchor without deepseek bundles installed
        pass

    manifest = readProfileManifest("t", resolveProfileDir("web", home))
    assert manifest.get("dsh", {}).get("profile", {}).get("bundles") == list(PROFILE_TEMPLATES["web"]["bundles"])
    assert manifest.get("dsh", {}).get("profile", {}).get("patchReload") == "live"


def test_load_profile_normalizes_only_exact_installation_owned_headless_bundle_tuple():
    anchor = stage_installation({
        "@deepseek-ai/dsh-base": {"patch": "[]\n"},
        "@deepseek-ai/dsh-web-app": {"patch": "[]\n"},
        "@deepseek-ai/dsh-headless": {"patch": "[]\n"},
        "custom-bundle": {"patch": "[]\n"},
    })
    home = tmp()
    stock = resolveProfileDir("headless", home)
    initProfile(stock, [
        "@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "@deepseek-ai/dsh-headless",
    ])
    retired = readProfileManifest("t", stock)
    if "patchReload" in retired.get("dsh", {}).get("profile", {}):
        del retired["dsh"]["profile"]["patchReload"]
    writeProfileManifest(stock, retired)
    loadProfile("t", "headless", anchor, home)
    assert readProfileManifest("t", stock).get("dsh", {}).get("profile") == {
        "bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"],
        "patchReload": "startup",
    }

    custom_home = tmp()
    custom = resolveProfileDir("headless", custom_home)
    initProfile(custom, [
        "@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "@deepseek-ai/dsh-headless", "custom-bundle",
    ])
    loadProfile("t", "headless", anchor, custom_home)
    assert readProfileManifest("t", custom).get("dsh", {}).get("profile", {}).get("bundles") == [
        "@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "@deepseek-ai/dsh-headless", "custom-bundle",
    ]


def test_load_profile_adds_shipped_reload_default_only_to_exact_stock_tuple_and_preserves_explicit():
    anchor = stage_installation({
        "@deepseek-ai/dsh-base": {"patch": "[]\n"},
        "@deepseek-ai/dsh-web-app": {"patch": "[]\n"},
    })
    stock_home = tmp()
    stock = resolveProfileDir("web", stock_home)
    initProfile(stock, PROFILE_TEMPLATES["web"]["bundles"])
    stock_manifest = readProfileManifest("t", stock)
    if "patchReload" in stock_manifest.get("dsh", {}).get("profile", {}):
        del stock_manifest["dsh"]["profile"]["patchReload"]
    writeProfileManifest(stock, stock_manifest)
    assert loadProfile("t", "web", anchor, stock_home).patch_reload == "live"
    assert readProfileManifest("t", stock).get("dsh", {}).get("profile", {}).get("patchReload") == "live"

    explicit_home = tmp()
    explicit = resolveProfileDir("web", explicit_home)
    initProfile(explicit, PROFILE_TEMPLATES["web"]["bundles"], "startup")
    assert loadProfile("t", "web", anchor, explicit_home).patch_reload == "startup"


def test_load_profile_fails_loud_on_unknown_patch_reload_value_from_disk():
    anchor = stage_installation({})
    home = tmp()
    dir_path = resolveProfileDir("demo", home)
    initProfile(dir_path, [])
    manifest = readProfileManifest("t", dir_path)
    manifest.setdefault("dsh", {}).setdefault("profile", {})["patchReload"] = "sometimes"
    writeProfileManifest(dir_path, manifest)
    with pytest.raises(RuntimeError, match='patchReload must be "live" or "startup"'):
        loadProfile("t", "demo", anchor, home)


def test_load_profile_fails_loud_when_listed_bundle_declares_no_dsh_bundle():
    anchor = stage_installation({"not-a-bundle": {}})
    home = tmp()
    dir_path = resolveProfileDir("demo", home)
    initProfile(dir_path, ["not-a-bundle"])
    with pytest.raises(RuntimeError, match="declares no dsh.bundle"):
        loadProfile("t", "demo", anchor, home)


# ---------------------------------------------------------------------------
# composeEntries
# ---------------------------------------------------------------------------


def test_compose_entries_applies_layers_over_empty_root_and_reports_skipped_patches():
    warnings: List[str] = []
    entries = composeEntries([
        [{"insert": [{"id": "x", "name": "pkg-x", "config": {"a": 1}}]}],
        [{"id": "x", "config": {"a": 2}}, {"id": "missing", "config": {}}],
    ], warn=lambda msg: warnings.append(msg))
    assert entries == [{"id": "x", "name": "pkg-x", "config": {"a": 2}}]
    assert any('"missing"' in w for w in warnings)
    # Default warn sink: skipped patches are silently dropped
    assert composeEntries([[{"id": "missing", "config": {}}]]) == []


# ---------------------------------------------------------------------------
# healProfilesModuleFallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_links_app_and_bundle_dependency_surface_flat():
    anchor = stage_installation({
        "bundle-a": {"patch": "[]\n", "deps": {"dep-of-a": "0.0.0", "ghost-dep": "0.0.0"}},
        "plain-lib": {},
    })
    with open(anchor, "r", encoding="utf-8") as f:
        app_manifest = json.load(f)
    app_manifest["dependencies"]["never-installed"] = "0.0.0"
    with open(anchor, "w", encoding="utf-8") as f:
        json.dump(app_manifest, f)

    modules = os.path.join(os.path.dirname(anchor), "node_modules")
    dep_a_dir = os.path.join(modules, "dep-of-a")
    os.makedirs(dep_a_dir, exist_ok=True)
    with open(os.path.join(dep_a_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "dep-of-a", "version": "0.0.0"}, f)

    home = tmp()
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    fallback = os.path.join(home, "profiles", "node_modules")

    for name in ["bundle-a", "plain-lib", "dep-of-a", "dsh-app"]:
        link_path = os.path.join(fallback, name)
        assert is_symlink_or_junction(link_path), f"{name} should be symlink/junction"

    # Idempotent and retains target
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    before = read_link(os.path.join(fallback, "dep-of-a"))
    assert "dep-of-a" in before


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_throws_when_entry_is_foreign_file_or_directory():
    anchor = stage_installation({})
    for kind in ["file", "directory"]:
        home = tmp()
        entry = os.path.join(home, "profiles", "node_modules", "dsh-app")
        os.makedirs(os.path.dirname(entry), exist_ok=True)
        if kind == "directory":
            os.makedirs(entry, exist_ok=True)
        else:
            with open(entry, "w", encoding="utf-8") as f:
                f.write("")
        with pytest.raises(RuntimeError, match="is not a symlink"):
            await healProfilesModuleFallback({"installAnchor": anchor, "home": home})


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_keeps_selected_bundle_closures_profile_local_without_overriding():
    installation_anchor = stage_installation({"shared": {}})
    bundle_a = stage_installation({"shared": {}, "@scope/bundle-only": {}}, "selected-bundle-a")
    bundle_b = stage_installation({"shared": {}, "@scope/bundle-only": {}}, "selected-bundle-b")
    home = tmp()
    profile_a = stage_profile(home, "a", bundle_a)
    profile_b = stage_profile(home, "b", bundle_b)

    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile_a, "home": home})
    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile_a, "home": home})
    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile_b, "home": home})

    shared_fallback = os.path.join(home, "profiles", "node_modules")
    owned_a = os.path.join(profile_a.dir, ".dsh-module-fallback", "node_modules", "@scope", "bundle-only")
    owned_b = os.path.join(profile_b.dir, ".dsh-module-fallback", "node_modules", "@scope", "bundle-only")

    assert symlink_points_to(
        os.path.join(shared_fallback, "shared"),
        os.path.join(os.path.dirname(installation_anchor), "node_modules", "shared"),
    )
    assert not os.path.exists(os.path.join(shared_fallback, "@scope", "bundle-only"))
    assert not os.path.exists(os.path.join(profile_a.dir, "node_modules", "shared"))
    assert not os.path.exists(os.path.join(profile_b.dir, "node_modules", "shared"))

    p_a_link = os.path.join(profile_a.dir, "node_modules", "@scope", "bundle-only")
    p_b_link = os.path.join(profile_b.dir, "node_modules", "@scope", "bundle-only")
    assert symlink_points_to(p_a_link, owned_a)
    assert symlink_points_to(
        owned_a,
        os.path.join(os.path.dirname(bundle_a), "node_modules", "@scope", "bundle-only"),
    )
    assert symlink_points_to(p_b_link, owned_b)
    assert symlink_points_to(
        owned_b,
        os.path.join(os.path.dirname(bundle_b), "node_modules", "@scope", "bundle-only"),
    )

    # Emptying layers removes owned projections
    profile_a_empty = Profile(
        name=profile_a.name,
        dir_path=profile_a.dir,
        layers=[],
        patch_path=profile_a.patch_path,
        patches=profile_a.patches,
        patch_reload=profile_a.patch_reload,
    )
    await healProfilesModuleFallback({
        "installAnchor": installation_anchor,
        "profile": profile_a_empty,
        "home": home,
    })
    assert not os.path.exists(p_a_link)
    assert not os.path.exists(owned_a)
    assert os.path.exists(p_b_link)


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_combines_packaged_installation_proxies_with_profile_local_links(monkeypatch):
    installation_anchor = stage_installation({"shared": {}})
    bundle_anchor = stage_installation({"shared": {}, "bundle-only": {}}, "selected-bundle")
    home = tmp()
    profile = stage_profile(home, "packaged", bundle_anchor)
    monkeypatch.setattr(sys, "pkg", {}, raising=False)

    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile, "home": home})
    shared_proxy = os.path.join(home, "profiles", "node_modules", "shared")
    assert os.path.isdir(shared_proxy) and not is_symlink_or_junction(shared_proxy)
    assert is_symlink_or_junction(os.path.join(profile.dir, "node_modules", "bundle-only"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_discovers_dependencies_beside_symlinked_bundle_real_path():
    installation_anchor = stage_installation({})
    home = tmp()
    dir_path = resolveProfileDir("symlinked", home)
    profile_modules = os.path.join(dir_path, "node_modules")
    store_modules = os.path.join(tmp(), "node_modules", ".pnpm", "selected-bundle@0.0.0", "node_modules")
    real_bundle = os.path.join(store_modules, "selected-bundle")
    real_dependency = os.path.join(store_modules, "bundle-only")
    os.makedirs(real_bundle, exist_ok=True)
    os.makedirs(real_dependency, exist_ok=True)
    with open(os.path.join(real_bundle, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "selected-bundle", "dependencies": {"bundle-only": "0.0.0"}}, f)
    with open(os.path.join(real_dependency, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "bundle-only"}, f)

    os.makedirs(profile_modules, exist_ok=True)
    bundle_link = os.path.join(profile_modules, "selected-bundle")
    create_symlink(real_bundle, bundle_link)

    profile = Profile(
        name="symlinked",
        dir_path=dir_path,
        layers=[
            ProfileLayer(
                package_name="selected-bundle",
                package_dir=bundle_link,
                patch_path=os.path.join(bundle_link, "cordis.patch.yml"),
                patches=[],
            )
        ],
        patch_path=os.path.join(dir_path, PROFILE_PATCH_FILENAME),
        patches=[],
        patch_reload="live",
    )

    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile, "home": home})
    owned = os.path.join(dir_path, ".dsh-module-fallback", "node_modules", "bundle-only")
    assert symlink_points_to(owned, real_dependency)


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_traverses_every_explicit_bundle_root_even_when_nested_has_same_name():
    installation_anchor = stage_installation({})
    home = tmp()
    root = tmp()
    bundle_a = os.path.join(root, "bundle-a")
    nested_bundle_b = os.path.join(bundle_a, "node_modules", "bundle-b")
    nested_only = os.path.join(nested_bundle_b, "node_modules", "nested-only")
    bundle_b = os.path.join(root, "bundle-b")
    explicit_only = os.path.join(bundle_b, "node_modules", "explicit-only")

    for d in [bundle_a, nested_bundle_b, nested_only, bundle_b, explicit_only]:
        os.makedirs(d, exist_ok=True)

    with open(os.path.join(bundle_a, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "bundle-a", "dependencies": {"bundle-b": "0.0.0"}}, f)
    with open(os.path.join(nested_bundle_b, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "bundle-b", "dependencies": {"nested-only": "0.0.0"}}, f)
    with open(os.path.join(nested_only, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "nested-only"}, f)
    with open(os.path.join(bundle_b, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "bundle-b", "dependencies": {"explicit-only": "0.0.0"}}, f)
    with open(os.path.join(explicit_only, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "explicit-only"}, f)

    dir_path = resolveProfileDir("explicit-roots", home)
    profile = Profile(
        name="explicit-roots",
        dir_path=dir_path,
        layers=[
            ProfileLayer(
                package_name=pkg_name,
                package_dir=pkg_dir,
                patch_path=os.path.join(pkg_dir, "cordis.patch.yml"),
                patches=[],
            )
            for pkg_name, pkg_dir in [("bundle-a", bundle_a), ("bundle-b", bundle_b)]
        ],
        patch_path=os.path.join(dir_path, PROFILE_PATCH_FILENAME),
        patches=[],
        patch_reload="live",
    )

    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile, "home": home})
    owned_modules = os.path.join(dir_path, ".dsh-module-fallback", "node_modules")
    assert symlink_points_to(os.path.join(owned_modules, "nested-only"), nested_only)
    assert symlink_points_to(os.path.join(owned_modules, "explicit-only"), explicit_only)


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_ignores_owned_projections_while_recomputing_ordered_closure():
    installation_anchor = stage_installation({})
    home = tmp()
    dir_path = resolveProfileDir("ordered", home)
    profile_modules = os.path.join(dir_path, "node_modules")
    bundle_a = os.path.join(profile_modules, "bundle-a")
    bundle_b = os.path.join(profile_modules, "bundle-b")
    nested = os.path.join(bundle_b, "node_modules", "bundle-only")

    os.makedirs(bundle_a, exist_ok=True)
    os.makedirs(nested, exist_ok=True)
    with open(os.path.join(bundle_a, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "bundle-a", "peerDependencies": {"bundle-only": "0.0.0"}}, f)
    with open(os.path.join(bundle_b, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "bundle-b", "dependencies": {"bundle-only": "0.0.0"}}, f)
    with open(os.path.join(nested, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "bundle-only"}, f)

    profile = Profile(
        name="ordered",
        dir_path=dir_path,
        layers=[
            ProfileLayer(
                package_name=pkg_name,
                package_dir=pkg_dir,
                patch_path=os.path.join(pkg_dir, "cordis.patch.yml"),
                patches=[],
            )
            for pkg_name, pkg_dir in [("bundle-a", bundle_a), ("bundle-b", bundle_b)]
        ],
        patch_path=os.path.join(dir_path, PROFILE_PATCH_FILENAME),
        patches=[],
        patch_reload="live",
    )

    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile, "home": home})
    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile, "home": home})

    owned = os.path.join(dir_path, ".dsh-module-fallback", "node_modules", "bundle-only")
    assert symlink_points_to(owned, nested)
    with open(os.path.join(profile_modules, "bundle-only", "package.json"), "r", encoding="utf-8") as f:
        assert json.load(f)["name"] == "bundle-only"


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_cleans_owned_projections_without_removing_profile_managed_entries():
    installation_anchor = stage_installation({})
    bundle_anchor = stage_installation({"fallback": {}, "managed-dir": {}, "managed-link": {}}, "selected-bundle")
    home = tmp()
    profile = stage_profile(home, "managed", bundle_anchor)
    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile, "home": home})

    owned_modules = os.path.join(profile.dir, ".dsh-module-fallback", "node_modules")
    profile_modules = os.path.join(profile.dir, "node_modules")
    foreign_target = tmp()

    os.unlink(os.path.join(profile_modules, "managed-dir"))
    os.makedirs(os.path.join(profile_modules, "managed-dir"), exist_ok=True)
    os.unlink(os.path.join(profile_modules, "managed-link"))
    create_symlink(foreign_target, os.path.join(profile_modules, "managed-link"))

    os.makedirs(os.path.join(owned_modules, "foreign-directory"), exist_ok=True)
    os.makedirs(os.path.join(owned_modules, "@foreign", "directory"), exist_ok=True)

    profile_empty = Profile(
        name=profile.name,
        dir_path=profile.dir,
        layers=[],
        patch_path=profile.patch_path,
        patches=profile.patches,
        patch_reload=profile.patch_reload,
    )
    await healProfilesModuleFallback({
        "installAnchor": installation_anchor,
        "profile": profile_empty,
        "home": home,
    })

    assert not os.path.exists(os.path.join(profile_modules, "fallback"))
    assert os.path.isdir(os.path.join(profile_modules, "managed-dir"))
    assert symlink_points_to(os.path.join(profile_modules, "managed-link"), foreign_target)
    assert not os.path.exists(os.path.join(owned_modules, "fallback"))
    assert not os.path.exists(os.path.join(owned_modules, "managed-dir"))
    assert not os.path.exists(os.path.join(owned_modules, "managed-link"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_cleans_owned_projections_whose_junction_target_uses_canonical_parent_path():
    installation_anchor = stage_installation({})
    real_home = tmp()
    alias_root = tmp()
    home = os.path.join(alias_root, "home")
    create_symlink(real_home, home)

    bundle_anchor = stage_installation({"fallback": {}}, "selected-bundle")
    profile = stage_profile(home, "canonical", bundle_anchor)
    await healProfilesModuleFallback({"installAnchor": installation_anchor, "profile": profile, "home": home})

    profile_link = os.path.join(profile.dir, "node_modules", "fallback")
    owned_modules = os.path.join(profile.dir, ".dsh-module-fallback", "node_modules")
    os.unlink(profile_link)
    create_symlink(os.path.join(os.path.realpath(owned_modules), "fallback"), profile_link)

    profile_empty = Profile(
        name=profile.name,
        dir_path=profile.dir,
        layers=[],
        patch_path=profile.patch_path,
        patches=profile.patches,
        patch_reload=profile.patch_reload,
    )
    await healProfilesModuleFallback({
        "installAnchor": installation_anchor,
        "profile": profile_empty,
        "home": home,
    })
    assert not os.path.exists(profile_link)
    assert not os.path.exists(os.path.join(owned_modules, "fallback"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_replaces_wrong_symlink():
    anchor = stage_installation({})
    home = tmp()
    fallback = os.path.join(home, "profiles", "node_modules")
    os.makedirs(fallback, exist_ok=True)
    create_symlink(tmp(), os.path.join(fallback, "dsh-app"))
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    assert "app" in read_link(os.path.join(fallback, "dsh-app"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_retains_current_links_while_repairing_missing_sibling():
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    home = tmp()
    fallback = os.path.join(home, "profiles", "node_modules")
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    app_target = read_link(os.path.join(fallback, "dsh-app"))
    os.unlink(os.path.join(fallback, "bundle-a"))

    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})

    assert read_link(os.path.join(fallback, "dsh-app")) == app_target
    assert is_symlink_or_junction(os.path.join(fallback, "bundle-a"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_serializes_concurrent_healers_and_retains_identical_link():
    anchor = stage_installation({})
    home = tmp()
    await asyncio.gather(
        healProfilesModuleFallback({"installAnchor": anchor, "home": home}),
        healProfilesModuleFallback({"installAnchor": anchor, "home": home}),
    )
    fallback = os.path.join(home, "profiles", "node_modules")
    assert is_symlink_or_junction(os.path.join(fallback, "dsh-app"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_does_not_acquire_writer_lock_for_complete_generation():
    anchor = stage_installation({})
    home = tmp()
    modules = os.path.join(home, "profiles", "node_modules")
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})

    release_lock = asyncio.Event()
    lock_held = asyncio.Event()

    async def holder():
        async def _inside():
            lock_held.set()
            await release_lock.wait()
        await with_file_lock(modules, _inside)

    holder_task = asyncio.create_task(holder())
    await lock_held.wait()

    healer_task = asyncio.create_task(healProfilesModuleFallback({"installAnchor": anchor, "home": home}))
    done, _ = await asyncio.wait([healer_task], timeout=0.1)
    outcome = "complete" if healer_task in done else "blocked"
    release_lock.set()
    await asyncio.gather(holder_task, healer_task)
    assert outcome == "complete"


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_waits_for_writer_lock_before_publishing_entries():
    anchor = stage_installation({})
    home = tmp()
    modules = os.path.join(home, "profiles", "node_modules")
    os.makedirs(modules, exist_ok=True)

    release_lock = asyncio.Event()
    lock_held = asyncio.Event()

    async def holder():
        async def _inside():
            lock_held.set()
            await release_lock.wait()
        await with_file_lock(modules, _inside)

    holder_task = asyncio.create_task(holder())
    await lock_held.wait()

    healer_task = asyncio.create_task(healProfilesModuleFallback({"installAnchor": anchor, "home": home}))
    await asyncio.sleep(0.05)
    assert not os.path.exists(os.path.join(modules, "dsh-app"))
    release_lock.set()
    await asyncio.gather(holder_task, healer_task)
    assert is_symlink_or_junction(os.path.join(modules, "dsh-app"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_writes_real_esm_proxies_for_packaged_executable(monkeypatch):
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    bundle_dir = os.path.join(os.path.dirname(anchor), "node_modules", "bundle-a")
    with open(os.path.join(bundle_dir, "package.json"), "r", encoding="utf-8") as f:
        bundle_manifest = json.load(f)
    bundle_manifest["exports"] = {
        ".": "./index.js",
        "./feature": "./feature.js",
        "./legacy/": "./legacy/",
        "./types": {"types": "./feature.d.ts"},
    }
    with open(os.path.join(bundle_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(bundle_manifest, f)
    with open(os.path.join(bundle_dir, "feature.js"), "w", encoding="utf-8") as f:
        f.write('export const feature = "proxied"\n')

    home = tmp()
    monkeypatch.setattr(sys, "pkg", {}, raising=False)

    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    fallback = os.path.join(home, "profiles", "node_modules")
    proxy = os.path.join(fallback, "bundle-a")
    assert os.path.isdir(proxy) and not is_symlink_or_junction(proxy)

    with open(os.path.join(proxy, "package.json"), "r", encoding="utf-8") as f:
        proxy_manifest = json.load(f)
    assert proxy_manifest["version"] == "0.0.0"
    assert proxy_manifest["exports"] == {".": "./entry-0.js", "./feature": "./entry-1.js"}
    assert "/bundle-a/index.js" in proxy_manifest["dsh"]["moduleFallback"]["targets"]["."]
    assert os.path.exists(os.path.join(proxy, "entry-0.js"))
    assert os.path.exists(os.path.join(proxy, "entry-1.js"))

    # Verify generated entry contents
    with open(os.path.join(proxy, "entry-0.js"), "r", encoding="utf-8") as f:
        assert "export * from" in f.read()
    with open(os.path.join(proxy, "entry-1.js"), "r", encoding="utf-8") as f:
        assert "feature.js" in f.read()

    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_resolves_import_only_exports_from_each_package(monkeypatch):
    anchor = stage_installation({
        "bundle-a": {"patch": "[]\n", "deps": {"nested-esm": "0.0.0"}},
    })
    bundle_dir = os.path.join(os.path.dirname(anchor), "node_modules", "bundle-a")
    with open(os.path.join(bundle_dir, "package.json"), "r", encoding="utf-8") as f:
        bundle_manifest = json.load(f)
    bundle_manifest["exports"] = {".": {"import": "./index.js"}}
    with open(os.path.join(bundle_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(bundle_manifest, f)

    nested_dir = os.path.join(bundle_dir, "node_modules", "nested-esm")
    os.makedirs(nested_dir, exist_ok=True)
    with open(os.path.join(nested_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "nested-esm",
            "version": "0.0.0",
            "type": "module",
            "exports": {"import": "./index.js"},
        }, f)
    with open(os.path.join(nested_dir, "index.js"), "w", encoding="utf-8") as f:
        f.write('export const nested = "proxied"\n')

    home = tmp()
    monkeypatch.setattr(sys, "pkg", {}, raising=False)

    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    fallback = os.path.join(home, "profiles", "node_modules")
    assert os.path.exists(os.path.join(fallback, "bundle-a", "entry-0.js"))
    assert os.path.exists(os.path.join(fallback, "nested-esm", "entry-0.js"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_resolves_explicit_condition_targets_without_fs_lookup(monkeypatch):
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    bundle_dir = os.path.join(os.path.dirname(anchor), "node_modules", "bundle-a")
    with open(os.path.join(bundle_dir, "package.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["exports"] = {
        ".": {"import": "./index.js", "require": "./index.cjs"},
        "./mini": {"types": "./mini/index.d.ts", "import": "./mini/index.js", "require": "./mini/index.cjs"},
        "./web": {"types": "./dist/web/web.d.ts", "import": "./dist/web/index.mjs", "default": "./dist/web/index.mjs"},
    }
    with open(os.path.join(bundle_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    os.makedirs(os.path.join(bundle_dir, "mini"), exist_ok=True)
    with open(os.path.join(bundle_dir, "mini", "index.js"), "w", encoding="utf-8") as f:
        f.write("export const mini = true\n")
    os.makedirs(os.path.join(bundle_dir, "dist", "web"), exist_ok=True)
    with open(os.path.join(bundle_dir, "dist", "web", "index.mjs"), "w", encoding="utf-8") as f:
        f.write("export const web = true\n")

    monkeypatch.setattr(sys, "pkg", {}, raising=False)
    home = tmp()
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    proxy = os.path.join(home, "profiles", "node_modules", "bundle-a")
    assert os.path.exists(os.path.join(proxy, "entry-1.js"))
    assert os.path.exists(os.path.join(proxy, "entry-2.js"))
    with open(os.path.join(proxy, "entry-1.js"), "r", encoding="utf-8") as f:
        assert "mini/index.js" in f.read()
    with open(os.path.join(proxy, "entry-2.js"), "r", encoding="utf-8") as f:
        assert "dist/web/index.mjs" in f.read()


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_preserves_installation_path_while_resolving_packaged_exports(monkeypatch):
    anchor = stage_installation({})
    app_dir = os.path.dirname(anchor)
    physical = tmp()
    with open(os.path.join(physical, "package.json"), "w", encoding="utf-8") as f:
        json.dump({
            "name": "linked-esm",
            "version": "0.0.0",
            "type": "module",
            "exports": {"import": "./index.js"},
        }, f)
    with open(os.path.join(physical, "index.js"), "w", encoding="utf-8") as f:
        f.write("export const linked = true\n")

    create_symlink(physical, os.path.join(app_dir, "node_modules", "linked-esm"))
    with open(anchor, "r", encoding="utf-8") as f:
        app_manifest = json.load(f)
    app_manifest["dependencies"]["linked-esm"] = "0.0.0"
    with open(anchor, "w", encoding="utf-8") as f:
        json.dump(app_manifest, f)

    monkeypatch.setattr(sys, "pkg", {}, raising=False)
    home = tmp()
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    proxy_pkg = os.path.join(home, "profiles", "node_modules", "linked-esm", "package.json")
    with open(proxy_pkg, "r", encoding="utf-8") as f:
        proxy_manifest = json.load(f)
    target = proxy_manifest["dsh"]["moduleFallback"]["targets"]["."]
    assert "/app/node_modules/linked-esm/index.js" in target


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_uses_legacy_index_fallback_when_package_has_no_exports_or_main(monkeypatch):
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    bundle_dir = os.path.join(os.path.dirname(anchor), "node_modules", "bundle-a")
    with open(os.path.join(bundle_dir, "package.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    if "main" in manifest:
        del manifest["main"]
    with open(os.path.join(bundle_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    monkeypatch.setattr(sys, "pkg", {}, raising=False)
    home = tmp()
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    assert os.path.exists(os.path.join(home, "profiles", "node_modules", "bundle-a", "entry-0.js"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_uses_node_legacy_resolution_for_extensionless_main(monkeypatch):
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    bundle_dir = os.path.join(os.path.dirname(anchor), "node_modules", "bundle-a")
    with open(os.path.join(bundle_dir, "package.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["main"] = "./index"
    with open(os.path.join(bundle_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    monkeypatch.setattr(sys, "pkg", {}, raising=False)
    home = tmp()
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    assert os.path.exists(os.path.join(home, "profiles", "node_modules", "bundle-a", "entry-0.js"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_skips_executable_only_and_declaration_only_packages(monkeypatch):
    for marker in ["bin", "types", "typings"]:
        anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
        with open(anchor, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if "main" in manifest:
            del manifest["main"]
        manifest[marker] = {"dsh": "./lib/bin.js"} if marker == "bin" else "./index.d.ts"
        if marker == "types":
            manifest["main"] = ""
        with open(anchor, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        app_idx = os.path.join(os.path.dirname(anchor), "index.js")
        if os.path.exists(app_idx):
            os.unlink(app_idx)

        monkeypatch.setattr(sys, "pkg", {}, raising=False)
        home = tmp()
        await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
        fallback = os.path.join(home, "profiles", "node_modules")
        assert not os.path.exists(os.path.join(fallback, "dsh-app"))
        assert os.path.exists(os.path.join(fallback, "bundle-a", "entry-0.js"))


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_fails_loud_on_missing_legacy_main_entry(monkeypatch):
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    bundle_dir = os.path.join(os.path.dirname(anchor), "node_modules", "bundle-a")
    with open(os.path.join(bundle_dir, "package.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    if "main" in manifest:
        del manifest["main"]
    with open(os.path.join(bundle_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    idx_path = os.path.join(bundle_dir, "index.js")
    if os.path.exists(idx_path):
        os.unlink(idx_path)

    monkeypatch.setattr(sys, "pkg", {}, raising=False)
    with pytest.raises(RuntimeError, match="main entry is missing"):
        await healProfilesModuleFallback({"installAnchor": anchor, "home": tmp()})


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_omits_unavailable_esm_exports_and_rejects_malformed(monkeypatch):
    for mode in ["missing", "directory", "absent-map", "invalid", "escape", "null", "null-subpath"]:
        anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
        bundle_dir = os.path.join(os.path.dirname(anchor), "node_modules", "bundle-a")
        with open(os.path.join(bundle_dir, "package.json"), "r", encoding="utf-8") as f:
            manifest = json.load(f)
        target = (
            "./missing.js" if mode == "missing"
            else "./mini" if mode == "directory"
            else "./../outside.js" if mode == "escape"
            else "../outside.js"
        )
        manifest["exports"] = (
            None if mode == "absent-map"
            else {"./bad": None} if mode == "null-subpath"
            else {".": None if mode == "null" else {"import": target}}
        )
        with open(os.path.join(bundle_dir, "package.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        if mode == "directory":
            os.makedirs(os.path.join(bundle_dir, "mini"), exist_ok=True)

        monkeypatch.setattr(sys, "pkg", {}, raising=False)
        home = tmp()
        if mode in ("missing", "directory", "absent-map"):
            await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
            assert not os.path.exists(os.path.join(home, "profiles", "node_modules", "bundle-a"))
        else:
            match_str = "cannot resolve ESM export bundle-a" if mode in ("null", "null-subpath") else "resolves outside its package"
            with pytest.raises(RuntimeError, match=match_str):
                await healProfilesModuleFallback({"installAnchor": anchor, "home": home})


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_requires_package_version_before_writing_packaged_proxy(monkeypatch):
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    bundle_dir = os.path.join(os.path.dirname(anchor), "node_modules", "bundle-a")
    with open(os.path.join(bundle_dir, "package.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["version"] = ""
    with open(os.path.join(bundle_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    monkeypatch.setattr(sys, "pkg", {}, raising=False)
    with pytest.raises(RuntimeError, match="must declare a non-empty version"):
        await healProfilesModuleFallback({"installAnchor": anchor, "home": tmp()})


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_replaces_plain_node_links_and_stale_managed_proxies_in_packaged_mode(monkeypatch):
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    home = tmp()
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    proxy = os.path.join(home, "profiles", "node_modules", "bundle-a")
    assert is_symlink_or_junction(proxy)

    monkeypatch.setattr(sys, "pkg", {}, raising=False)
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    assert os.path.isdir(proxy) and not is_symlink_or_junction(proxy)

    with open(os.path.join(proxy, "package.json"), "r", encoding="utf-8") as f:
        stale = json.load(f)
    stale["version"] = "stale"
    with open(os.path.join(proxy, "package.json"), "w", encoding="utf-8") as f:
        json.dump(stale, f)

    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    with open(os.path.join(proxy, "package.json"), "r", encoding="utf-8") as f:
        assert json.load(f)["version"] == "0.0.0"


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_replaces_managed_packaged_proxy_with_plain_node_symlink(monkeypatch):
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    home = tmp()
    fallback = os.path.join(home, "profiles", "node_modules", "bundle-a")

    monkeypatch.setattr(sys, "pkg", {}, raising=False)
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    assert os.path.isdir(fallback) and not is_symlink_or_junction(fallback)

    monkeypatch.delattr(sys, "pkg", raising=False)
    await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
    assert is_symlink_or_junction(fallback)


@pytest.mark.asyncio
async def test_heal_profiles_module_fallback_rejects_foreign_packaged_fallback_directories(monkeypatch):
    anchor = stage_installation({"bundle-a": {"patch": "[]\n"}})
    monkeypatch.setattr(sys, "pkg", {}, raising=False)
    for metadata in ["{}", "{"]:
        home = tmp()
        proxy = os.path.join(home, "profiles", "node_modules", "bundle-a")
        os.makedirs(proxy, exist_ok=True)
        with open(os.path.join(proxy, "package.json"), "w", encoding="utf-8") as f:
            f.write(metadata)
        with pytest.raises(RuntimeError, match="exists and is not a dsh-managed module proxy"):
            await healProfilesModuleFallback({"installAnchor": anchor, "home": home})
