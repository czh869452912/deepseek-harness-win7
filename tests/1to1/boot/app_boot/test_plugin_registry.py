"""
1:1 parity suite for the installation-owned Loader resolution table
(`dsh/boot/plugin_registry.py`) that `boot` installs before the config tree
mounts.

Upstream: `reference/packages/boot/app-boot/src/index.ts` `boot` mounts the
Loader before the config tree so a bare row name resolves from the installation
module closure; `healProfilesModuleFallback`
(`reference/packages/boot/app-boot/src/profile.ts`) heals that closure into
`$DSH_HOME/profiles/node_modules`, which Node then walks by ordinary parent
lookup. The pinned app-boot suite is
`reference/packages/boot/app-boot/tests/app-boot.spec.ts`.

The Python runtime has no Node module graph, so the installation-owned half of
that resolution is expressed as a name -> plugin-class table
(`HARNESS_PLUGIN_CLASSES`). This suite derives the shipped row inventory from the
pinned bundle patches (`packages/bundle/*/cordis.patch.yml`, byte-identical to
`reference/packages/bundle/*/cordis.patch.yml`) rather than a hand-picked list,
so a shipped row can never fall out of resolution unnoticed:

- every enabled row the installation implements resolves to its table class and
  is mountable;
- every enabled row it does not implement fails loud (``Cannot find module``)
  instead of being silently skipped or answered by a stub;
- the unresolved shipped rows are exactly the frozen provider gap below, and the
  real ``run_profile`` boot path reports that same set.

When a provider row lands, ``SHIPPED_PROVIDER_GAP`` must shrink in the same
change; the equality assertions below make that mandatory.
"""

import asyncio
import json
import os
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional, Set

import pytest

from dsh.boot.app_boot import boot, load_overlay_patches, path_to_file_url
from dsh.boot.plugin_registry import (
    HARNESS_PLUGIN_CLASSES,
    harness_plugin_names,
    install_harness_plugin_classes,
    install_installation_module_roots,
    installation_module_roots,
    resolve_harness_plugin,
)
from dsh.boot.profile import PROFILE_TEMPLATES, compose_entries, is_symlink_or_junction
from dsh.cordis.context import Context
from dsh.cordis.loader import (
    Loader,
    eval_condition,
    evaluate_expr,
    exports_subpath_target,
    is_installation_owned_module,
    resolve_module_specifier,
)
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service

NAME = "dsh"

def _repository_root() -> str:
    """Walk up from this test to the checkout root that carries packages/bundle."""
    current = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(current, "packages", "bundle")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError("test_plugin_registry: cannot locate the repository root")
        current = parent


REPOSITORY_ROOT = _repository_root()

# The shipped bundle packages (reference/packages/bundle/*) matched to their
# directory under packages/bundle/.
BUNDLE_DIRS: Dict[str, str] = {
    "@deepseek-ai/dsh-base": "base",
    "@deepseek-ai/dsh-web-app": "web-app",
    "@deepseek-ai/dsh-headless": "headless",
    "@deepseek-ai/dsh-acp-app": "acp-app",
    "@deepseek-ai/dsh-sdk-app": "sdk-app",
    "@deepseek-ai/dsh-sdk-minimal": "sdk-minimal",
}

PROFILES: List[str] = ["web", "standard", "headless", "creative", "acp", "sdk", "minimal"]

# The enabled rows of each shipped profile that the installation does not
# implement yet. Every one of them is a real provider package named by the
# pinned bundle patches; none can be answered by a stub, so a profile boot fails
# loud over exactly this set. The list is frozen: it may only shrink, and only
# together with the provider that lands.
SHIPPED_PROVIDER_GAP: Dict[str, List[str]] = {
    "web": [
        "@deepseek-ai/dsh-api-remotes",
        "@deepseek-ai/dsh-api-session-controller",
        "@deepseek-ai/dsh-api-settings-controller",
        "@deepseek-ai/dsh-api-workspace-controller",
        "@deepseek-ai/dsh-client-hmr",
        "@deepseek-ai/dsh-cordis-host-runner",
        "@deepseek-ai/dsh-session-log-export",
        "@deepseek-ai/dsh-session-reference",
        "@deepseek-ai/dsh-session-telemetry-otel",
    ],
    "standard": [
        "@deepseek-ai/dsh-session-telemetry-otel",
    ],
    "headless": [
        "@deepseek-ai/dsh-session-telemetry-otel",
    ],
    "creative": [
        "@deepseek-ai/dsh-session-telemetry-otel",
    ],
    "acp": [
        "@deepseek-ai/dsh-acp-app",
        "@deepseek-ai/dsh-session-telemetry-otel",
    ],
    "sdk": [
        "@deepseek-ai/dsh-session-telemetry-otel",
    ],
    "minimal": [
    ],
}


def tmp() -> str:
    return tempfile.mkdtemp(prefix="dsh-plugin-registry-")


def safe_rmtree(path: str) -> None:
    """
    Remove a test temp tree, unlinking a healed fallback entry instead of descending into it.

    `healProfilesModuleFallback` writes junctions on Windows. Removing the junction itself
    (`os.rmdir` / `RemoveDirectory`) keeps cleanup independent of how the host treats
    reparse points, so the installation a link points at is never at risk.
    """
    if is_symlink_or_junction(path):
        os.rmdir(path)
        return
    if os.path.islink(path):
        os.unlink(path)
        return
    if not os.path.isdir(path):
        os.remove(path)
        return
    for name in os.listdir(path):
        safe_rmtree(os.path.join(path, name))
    os.rmdir(path)


def _shipped_bundle_patches(bundle_package: str) -> List[Dict[str, Any]]:
    """Load one shipped bundle patch through the same parser profile boot uses."""
    path = os.path.join(
        REPOSITORY_ROOT, "packages", "bundle", BUNDLE_DIRS[bundle_package], "cordis.patch.yml"
    )
    return load_overlay_patches(NAME, path)


def shipped_enabled_rows(profile: str, ctx: Optional[Context] = None) -> List[str]:
    """
    Every enabled (id, name) row one shipped profile composes, in precedence order.

    Derived from the pinned bundle patches the profile template names, with each
    row's `disabled` expression evaluated the way the Loader evaluates it.
    """
    cond_ctx = ctx if ctx is not None else Context()
    template = PROFILE_TEMPLATES[profile]
    layers = [_shipped_bundle_patches(bundle) for bundle in template["bundles"]]
    entries = compose_entries(layers)
    rows: List[str] = []
    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        if eval_condition(entry.get("disabled", False), cond_ctx):
            continue
        rows.append(name)
    return rows


def _is_plugin_shape(cls: Any) -> bool:
    """Cordis accepts a class plugin through its Service base or its apply()."""
    return issubclass(cls, (Plugin, Service)) or callable(getattr(cls, "apply", None))


def _loader_with_table() -> Loader:
    ctx = Context()
    loader = Loader(ctx)
    ctx.set_service("loader", loader)
    install_harness_plugin_classes(loader)
    return loader


# --- The table answers the implemented installation rows ----------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_every_implemented_shipped_row_resolves_to_a_mountable_table_class(profile):
    ctx = Context()
    implemented = sorted(
        {name for name in shipped_enabled_rows(profile, ctx) if name in HARNESS_PLUGIN_CLASSES}
    )
    # The profile must actually exercise implemented rows, or the audit below is
    # vacuous.
    assert implemented
    loader = _loader_with_table()
    for name in implemented:
        cls = resolve_harness_plugin(name)
        assert cls is not None, name
        assert isinstance(cls, type), name
        assert _is_plugin_shape(cls), name
        # The Loader resolves the row to that exact class: no JS mock, no
        # directory path, no unrelated module.
        assert loader.import_plugin(name) is cls


@pytest.mark.parametrize("profile", PROFILES)
def test_shipped_unresolved_rows_are_exactly_the_frozen_provider_gap(profile):
    """
    The enabled shipped rows the installation cannot answer are the recorded gap.

    Equality (not intersection) on purpose: a new unresolved row fails the test,
    and a provider landing must shrink the list in the same change.
    """
    unresolved = sorted(
        {name for name in shipped_enabled_rows(profile) if name not in HARNESS_PLUGIN_CLASSES}
    )
    assert unresolved == sorted(SHIPPED_PROVIDER_GAP[profile])


@pytest.mark.parametrize("profile", PROFILES)
def test_every_unresolved_shipped_row_fails_loud_instead_of_being_stubbed(profile):
    """An unimplemented shipped row raises; it is never silently skipped."""
    loader = _loader_with_table()
    for name in SHIPPED_PROVIDER_GAP[profile]:
        assert name not in HARNESS_PLUGIN_CLASSES
        assert resolve_harness_plugin(name) is None
        with pytest.raises(ModuleNotFoundError) as raised:
            loader.import_plugin(name)
        assert str(raised.value) == f"Cannot find module '{name}'"


def _stage_healed_installation(home: str, package: str, marker: str) -> str:
    """
    Stage one package inside the healed installation fallback.

    The fallback links carry the installation's built JS artifact, exactly as
    `healProfilesModuleFallback` publishes them; the Python implementation of an
    installation row is the class table, not that artifact.
    """
    package_dir = os.path.join(home, "profiles", "node_modules", package)
    os.makedirs(os.path.join(package_dir, "lib"), exist_ok=True)
    with open(os.path.join(package_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"name": package, "type": "module", "main": "lib/index.js", "exports": {".": {"default": "./lib/index.js"}}},
            f,
        )
    with open(os.path.join(package_dir, "lib", "index.js"), "w", encoding="utf-8") as f:
        f.write(
            f'export const name = "{marker}"\n'
            f'export function apply(ctx) {{ ctx.provide("{marker}ArtifactLoaded", true) }}\n'
        )
    return package_dir


def test_installation_rows_are_answered_by_the_table_not_by_the_shipped_artifact():
    """
    A bare row that resolves through the healed installation fallback is an
    installation row: the table answers it, and a row the installation does not
    implement fails loud instead of loading the shipped JS stand-in.
    """
    home = tmp()
    try:
        _stage_healed_installation(home, "@deepseek-ai/dsh-tools", "tools")
        _stage_healed_installation(home, "@deepseek-ai/dsh-api-remotes", "web")
        profile_dir = os.path.join(home, "profiles", "standard")
        os.makedirs(profile_dir, exist_ok=True)
        config = os.path.join(profile_dir, "cordis.yml")
        with open(config, "w", encoding="utf-8") as f:
            f.write("- id: tools\n  name: '@deepseek-ai/dsh-tools'\n")

        ctx = Context()
        loader = Loader(ctx)
        ctx.set_service("loader", loader)
        ctx.base_url = path_to_file_url(profile_dir) + "/"
        install_harness_plugin_classes(loader)
        roots = install_installation_module_roots(loader, config, home)
        assert roots == installation_module_roots(config, home)
        assert loader.installation_module_roots == roots

        assert loader.import_plugin("@deepseek-ai/dsh-tools") is resolve_harness_plugin("@deepseek-ai/dsh-tools")
        with pytest.raises(ModuleNotFoundError) as raised:
            loader.import_plugin("@deepseek-ai/dsh-api-remotes")
        assert str(raised.value) == "Cannot find module '@deepseek-ai/dsh-api-remotes'"
    finally:
        safe_rmtree(home)


def test_an_installation_row_behind_a_healed_link_is_installation_owned_too():
    """The profile-owned projection link is an installation path as well."""
    from dsh.boot.profile import create_symlink

    home = tmp()
    try:
        real = _stage_healed_installation(home, ".dsh-module-fallback-pack", "unused")
        profile_dir = os.path.join(home, "profiles", "standard")
        owned = os.path.join(profile_dir, ".dsh-module-fallback", "node_modules", "@deepseek-ai", "dsh-tools")
        os.makedirs(os.path.dirname(owned), exist_ok=True)
        os.rename(real, owned)
        link = os.path.join(profile_dir, "node_modules", "@deepseek-ai", "dsh-tools")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        try:
            create_symlink(owned, link)
        except OSError as error:  # a host without link privileges
            pytest.skip(f"cannot create the healed fallback link: {error}")

        config = os.path.join(profile_dir, "cordis.yml")
        with open(config, "w", encoding="utf-8") as f:
            f.write("- id: tools\n  name: '@deepseek-ai/dsh-tools'\n")

        ctx = Context()
        loader = Loader(ctx)
        ctx.set_service("loader", loader)
        ctx.base_url = path_to_file_url(profile_dir) + "/"
        install_harness_plugin_classes(loader)
        install_installation_module_roots(loader, config, home)

        assert loader.import_plugin("@deepseek-ai/dsh-tools") is resolve_harness_plugin("@deepseek-ai/dsh-tools")
    finally:
        safe_rmtree(home)


@pytest.mark.asyncio
async def test_a_config_project_module_still_wins_over_the_installation_fallback(monkeypatch):
    """The table stays the last anchor: a project-local package is not bypassed."""
    home = tmp()
    try:
        _stage_healed_installation(home, "@deepseek-ai/dsh-tools", "tools")
        profile_dir = os.path.join(home, "profiles", "standard")
        shadow = os.path.join(profile_dir, "node_modules", "@deepseek-ai", "dsh-tool-ask-user")
        os.makedirs(shadow, exist_ok=True)
        with open(os.path.join(shadow, "package.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"name": "@deepseek-ai/dsh-tool-ask-user", "type": "module", "exports": "./index.mjs"}, f
            )
        with open(os.path.join(shadow, "index.mjs"), "w", encoding="utf-8") as f:
            f.write('export function apply(ctx) { ctx.provide("projectShadowLoaded", true) }\n')
        config = os.path.join(profile_dir, "cordis.yml")
        with open(config, "w", encoding="utf-8") as f:
            f.write(
                "- id: ask-user\n  name: '@deepseek-ai/dsh-tool-ask-user'\n"
                "- id: tools\n  name: '@deepseek-ai/dsh-tools'\n"
            )
        monkeypatch.setenv("DSH_HOME", home)

        ctx = await boot(NAME, config)
        try:
            # The project's own package is the row's implementation...
            assert ctx.get("projectShadowLoaded") is True
            # ...while the installation row below the healed fallback answers from
            # the table instead of the JS artifact beside it.
            assert ctx.get("toolsArtifactLoaded") is None
            assert ctx.get("tools").__class__.__name__ == "ToolsService"
        finally:
            await ctx.fiber.dispose()
    finally:
        safe_rmtree(home)


def _stage_healed_subpath_package(home: str, package: str, manifest_path: str) -> str:
    """
    Stage one package inside the healed installation with its pinned manifest.

    The Python runtime answers the row from the class table, but the row must
    still resolve the way Node resolves it: through the package root and, for a
    subpath row, through that package's exports map.
    """
    package_dir = _stage_healed_installation(home, package, package.rsplit("/", 1)[-1])
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    with open(os.path.join(package_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    return package_dir


def test_a_package_subpath_row_resolves_through_the_package_exports_map():
    """
    A row naming a package subpath (`@deepseek-ai/dsh-web-app/startup`) resolves
    through that package's exports map, so the Loader classifies the row as
    installation owned and answers it from the table.
    """
    home = tmp()
    try:
        manifest = os.path.join(REPOSITORY_ROOT, "reference", "packages", "bundle", "web-app", "package.json")
        package_dir = _stage_healed_subpath_package(home, "@deepseek-ai/dsh-web-app", manifest)
        profile_dir = os.path.join(home, "profiles", "standard")
        os.makedirs(profile_dir, exist_ok=True)
        config = os.path.join(profile_dir, "cordis.yml")
        with open(config, "w", encoding="utf-8") as f:
            f.write("- id: web-startup\n  name: '@deepseek-ai/dsh-web-app/startup'\n")

        roots = installation_module_roots(config, home)
        resolved = resolve_module_specifier("@deepseek-ai/dsh-web-app/startup", profile_dir, roots)
        assert os.path.normpath(resolved) == os.path.normpath(os.path.join(package_dir, "lib", "startup.js"))
        assert is_installation_owned_module(resolved, roots)

        loader = _loader_with_table()
        install_installation_module_roots(loader, config, home)
        assert loader.import_plugin("@deepseek-ai/dsh-web-app/startup") is resolve_harness_plugin(
            "@deepseek-ai/dsh-web-app/startup"
        )
        # The package root keeps its own `exports["."]` resolution.
        root_resolved = resolve_module_specifier("@deepseek-ai/dsh-web-app", profile_dir, roots)
        assert os.path.normpath(root_resolved) == os.path.normpath(os.path.join(package_dir, "lib", "index.js"))
    finally:
        safe_rmtree(home)


def test_a_package_subpath_the_exports_map_omits_does_not_resolve():
    """A subpath the exports map omits has no module, exactly as Node reports."""
    home = tmp()
    try:
        manifest = os.path.join(REPOSITORY_ROOT, "reference", "packages", "bundle", "web-app", "package.json")
        _stage_healed_subpath_package(home, "@deepseek-ai/dsh-web-app", manifest)
        profile_dir = os.path.join(home, "profiles", "standard")
        os.makedirs(profile_dir, exist_ok=True)
        config = os.path.join(profile_dir, "cordis.yml")
        with open(config, "w", encoding="utf-8") as f:
            f.write("[]\n")

        roots = installation_module_roots(config, home)
        assert resolve_module_specifier("@deepseek-ai/dsh-web-app/not-exported", profile_dir, roots) is None
        assert exports_subpath_target(
            json.load(open(manifest, encoding="utf-8"))["exports"], "not-exported"
        ) is None
        assert exports_subpath_target(
            json.load(open(manifest, encoding="utf-8"))["exports"], "startup"
        ) == "./lib/startup.js"

        loader = _loader_with_table()
        install_installation_module_roots(loader, config, home)
        with pytest.raises(ModuleNotFoundError) as raised:
            loader.import_plugin("@deepseek-ai/dsh-web-app/not-exported")
        assert str(raised.value) == "Cannot find module '@deepseek-ai/dsh-web-app/not-exported'"
    finally:
        safe_rmtree(home)


@pytest.mark.asyncio
async def test_a_config_project_subpath_row_still_wins_over_the_installation_table(monkeypatch):
    """A project-local package subpath is imported from the project, not the table."""
    home = tmp()
    try:
        profile_dir = os.path.join(home, "profiles", "standard")
        shadow = os.path.join(profile_dir, "node_modules", "@deepseek-ai", "dsh-local-pkg")
        os.makedirs(shadow, exist_ok=True)
        with open(os.path.join(shadow, "package.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "name": "@deepseek-ai/dsh-local-pkg",
                    "type": "module",
                    "exports": {".": "./index.mjs", "./startup": "./startup.mjs"},
                },
                f,
            )
        with open(os.path.join(shadow, "index.mjs"), "w", encoding="utf-8") as f:
            f.write('export function apply(ctx) { ctx.provide("localRootLoaded", true) }\n')
        with open(os.path.join(shadow, "startup.mjs"), "w", encoding="utf-8") as f:
            f.write('export function apply(ctx) { ctx.provide("localStartupLoaded", true) }\n')
        config = os.path.join(profile_dir, "cordis.yml")
        with open(config, "w", encoding="utf-8") as f:
            f.write("- id: local-startup\n  name: '@deepseek-ai/dsh-local-pkg/startup'\n")
        monkeypatch.setenv("DSH_HOME", home)

        roots = installation_module_roots(config, home)
        resolved = resolve_module_specifier("@deepseek-ai/dsh-local-pkg/startup", profile_dir, roots)
        assert resolved == os.path.join(shadow, "startup.mjs")
        assert not is_installation_owned_module(resolved, roots)

        ctx = await boot(NAME, config)
        try:
            assert ctx.get("localStartupLoaded") is True
            assert ctx.get("localRootLoaded") is None
        finally:
            await ctx.fiber.dispose()
    finally:
        safe_rmtree(home)


def test_the_table_answers_only_the_installation_owned_names():
    # An unknown bare name still resolves nowhere: the table must not turn a
    # name the installation does not carry into a silent success.
    loader = _loader_with_table()
    assert resolve_harness_plugin("@deepseek-ai/dsh-not-a-real-package") is None
    assert "@deepseek-ai/dsh-not-a-real-package" not in HARNESS_PLUGIN_CLASSES
    with pytest.raises(ModuleNotFoundError):
        loader.import_plugin("@deepseek-ai/dsh-not-a-real-package")


def test_the_frozen_gap_is_the_union_of_every_shipped_profile():
    union: Set[str] = set()
    for profile in PROFILES:
        union.update(SHIPPED_PROVIDER_GAP[profile])
    # Every gap row is named by a shipped bundle patch, so it can never become
    # resolvable without touching a pinned bundle.
    shipped_names: Set[str] = set()
    for bundle in sorted(set(BUNDLE_DIRS.values())):
        for patch in load_overlay_patches(
            NAME, os.path.join(REPOSITORY_ROOT, "packages", "bundle", bundle, "cordis.patch.yml")
        ):
            def collect(node: Any) -> None:
                if isinstance(node, list):
                    for item in node:
                        collect(item)
                elif isinstance(node, dict):
                    name = node.get("name")
                    if isinstance(name, str):
                        shipped_names.add(name)
                    for key, value in node.items():
                        if key == "name":
                            continue
                        collect(value)

            collect(patch)
    assert union <= shipped_names
    assert len(union) == 10


# --- boot installs and consults the table ------------------------------------


@pytest.mark.asyncio
async def test_boot_resolves_installation_rows_named_by_the_config():
    """A bare row the config project does not own resolves from the installation."""
    d = tmp()
    rows = [
        "- id: timer\n  name: '@deepseek-ai/cordis-plugin-timer'",
        "- id: system-prompt\n  name: '@deepseek-ai/dsh-system-prompt'\n  config:\n    persona: booted",
        "- id: tools\n  name: '@deepseek-ai/dsh-tools'",
    ]
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")

    ctx = await boot(NAME, os.path.join(d, "cordis.yml"))
    try:
        assert ctx.get("timer") is not None
        prompt = ctx.get("systemPrompt")
        assert prompt is not None
        assert prompt.layers.global_layer.sections.data["deployment:persona"]["text"] == "booted"
        assert ctx.get("tools") is not None
        entries = {entry.options.get("name"): entry for entry in ctx.loader.entries()}
        for name in (
            "@deepseek-ai/cordis-plugin-timer",
            "@deepseek-ai/dsh-system-prompt",
            "@deepseek-ai/dsh-tools",
        ):
            assert entries[name].fiber is not None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_boot_installs_the_table_before_the_config_tree_mounts():
    """
    `boot` mounts the Loader, hands it the installation table, and only then
    mounts the config tree — matching the pinned boot order so the first row it
    resolves already sees the installation.
    """
    d = tmp()
    seen: List[bool] = []
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: timer\n  name: '@deepseek-ai/cordis-plugin-timer'\n")

    def prepare(host_ctx: Context) -> None:
        loader = host_ctx.get("loader")
        assert loader is not None
        assert loader.harness_plugins
        seen.append(True)

    ctx = await boot(NAME, os.path.join(d, "cordis.yml"), None, prepare)
    try:
        assert seen == [True]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_boot_rejects_a_config_naming_an_unimplemented_shipped_row():
    """
    The shipped fail-loud contract: a row the installation does not carry is
    reported with its name, never skipped.
    """
    d = tmp()
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write(
            "- id: timer\n  name: '@deepseek-ai/cordis-plugin-timer'\n"
            "- id: gateway\n  name: '@deepseek-ai/dsh-api-remotes'\n"
        )
    with pytest.raises(RuntimeError) as raised:
        await boot(NAME, os.path.join(d, "cordis.yml"))
    message = str(raised.value)
    assert message.startswith(f"{NAME}: plugin tree failed to load")
    assert "failed to import loader entry gateway (@deepseek-ai/dsh-api-remotes): Cannot find module '@deepseek-ai/dsh-api-remotes'" in message


@pytest.mark.asyncio
async def test_web_row_mounts_the_real_provider_selecting_service(tmp_path):
    config = tmp_path / "cordis.yml"
    config.write_text("- id: web\n  name: '@deepseek-ai/dsh-web'\n", encoding="utf-8")
    ctx = await boot(NAME, str(config))
    try:
        from dsh.web.web_service import WebError
        web = ctx.get("web")
        assert web is not None
        with pytest.raises(WebError) as failure:
            await web.search({"query": "unconfigured"})
        assert failure.value.code == "WEB_PROVIDER_UNAVAILABLE"
    finally:
        await ctx.fiber.dispose()
    assert ctx.get("web") is None


@pytest.mark.asyncio
async def test_installing_the_table_is_a_fallback_not_a_shadowing_registry():
    """A config-project module of the same name still wins over the table."""
    d = tmp()
    shadow = os.path.join(d, "node_modules", "@deepseek-ai", "dsh-tool-ask-user")
    os.makedirs(shadow, exist_ok=True)
    with open(os.path.join(shadow, "package.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"name": "@deepseek-ai/dsh-tool-ask-user", "type": "module", "exports": "./index.mjs"}, f
        )
    with open(os.path.join(shadow, "index.mjs"), "w", encoding="utf-8") as f:
        f.write('export function apply(ctx) { ctx.provide("shadowToolAskUserLoaded", true) }\n')
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: ask-user\n  name: '@deepseek-ai/dsh-tool-ask-user'\n")

    ctx = await boot(NAME, os.path.join(d, "cordis.yml"))
    try:
        assert ctx.get("shadowToolAskUserLoaded") is True
        assert ctx.get("askUser") is None
        assert ctx.loader.harness_plugins.get("@deepseek-ai/dsh-tool-ask-user") is not None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_install_through_the_service_proxy_reaches_the_loader_the_entries_read():
    """
    `boot` reaches the Loader through a service proxy; the table must land on
    the mapping the entry import path reads, not on the proxy instance.
    """
    ctx = Context()
    await ctx.plugin(Loader)
    try:
        proxy = ctx.get("loader")
        installed = install_harness_plugin_classes(proxy)
        assert installed
        assert proxy.import_plugin("@deepseek-ai/cordis-plugin-timer") is installed[
            "@deepseek-ai/cordis-plugin-timer"
        ]
        # Re-installing replaces the mapping instead of rebinding the proxy.
        again = install_harness_plugin_classes(proxy)
        assert again == installed
        assert proxy.import_plugin("@deepseek-ai/dsh-tools") is again["@deepseek-ai/dsh-tools"]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_build_harness_preset_rows_resolve_through_the_table():
    from dsh.harness import build_harness

    ctx = await build_harness(mode="minimal")
    loader = ctx.get("loader")
    assert loader.harness_plugins
    # A preset-only row name (`dsh-cordis-manager`) and a plain row both resolve.
    assert loader.import_plugin("@deepseek-ai/dsh-cordis-manager") is not None
    assert loader.import_plugin("@deepseek-ai/dsh-persona") is not None


def test_table_keeps_the_cordis_manager_row_alias_the_presets_name():
    # dsh/presets/*.yaml name the `dsh-cordis-manager` row; the package
    # publishes itself as `dsh-tool-cordis`. Both names resolve to one class.
    assert resolve_harness_plugin("@deepseek-ai/dsh-cordis-manager") is resolve_harness_plugin(
        "@deepseek-ai/dsh-tool-cordis"
    )


def test_table_names_are_sorted_and_unique():
    names = harness_plugin_names()
    assert names == sorted(names)
    assert len(names) == len(set(names))
    assert len(names) == len(HARNESS_PLUGIN_CLASSES)


# --- The shipped profile boot path ------------------------------------------


# The inner arguments each shipped profile's own command line requires: the
# one-shot profiles answer exactly one task, the others name no positional.
PROFILE_INVOCATION_ARGS: Dict[str, List[str]] = {
    "web": [],
    "standard": ["run the tests"],
    "headless": ["run the tests"],
    "creative": ["run the tests"],
    "acp": [],
    "sdk": [],
    "minimal": [],
}


# The only activation failure a shipped profile may report besides the
# unimplemented imports. Frozen like SHIPPED_PROVIDER_GAP: it may only shrink,
# and only together with the provider that lands.
SHIPPED_ACTIVATION_GAP: Dict[str, List[str]] = {
    "web": [],
    "standard": [],
    "headless": [],
    "creative": [],
    "acp": [],
    "sdk": [],
    "minimal": [],
}


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.asyncio
async def test_run_profile_reports_exactly_the_shipped_provider_gap(profile, monkeypatch):
    """
    The acceptance path: `run_profile` for a shipped profile composes and mounts
    every row it can and rejects over exactly the unimplemented provider rows —
    the same set the derived inventory reports. It never exits half-empty, and no
    row the installation does implement fails to activate.

    `SHIPPED_ACTIVATION_GAP` freezes the activation failures of implemented
    rows; it is empty now that the web `webserver` row's injected `webStartup`
    provider (`@deepseek-ai/dsh-web-app/startup`) is implemented. Like
    `SHIPPED_PROVIDER_GAP` it may only shrink, and only together with the
    provider that lands.

    Each invocation carries the arguments its own app command line requires
    (`dsh --profile headless "<task>"`), so a profile whose startup provider
    row is implemented parses a real invocation instead of rejecting its own
    usage and shutting down before the unresolved rows are reached.
    """
    from dsh.boot.profile_boot import run_profile

    if not os.path.exists(os.path.join(REPOSITORY_ROOT, "reference", "apps", "cli", "package.json")):
        pytest.skip("the pinned reference installation is required to resolve profile bundles")

    from dsh.boot.cmdline import internals
    read_fd, write_fd = os.pipe()
    stdin = os.fdopen(read_fd, 'rb', buffering=0)
    monkeypatch.setattr(internals, 'stdin', stdin)
    home = tmp()
    try:
        if not SHIPPED_PROVIDER_GAP[profile]:
            result = await asyncio.wait_for(run_profile(dict(profile=profile, dshHome=home,
                waitForExit=False, args=PROFILE_INVOCATION_ARGS[profile])), timeout=30)
            try:
                assert result['ctx'].get('agents') is not None
            finally:
                result['shutdown'].shutdown(0)
                await result['shutdown'].wait()
            return
        with pytest.raises(RuntimeError) as raised:
            await asyncio.wait_for(
                run_profile(
                    {
                        "profile": profile,
                        "dshHome": home,
                        "waitForExit": False,
                        "args": PROFILE_INVOCATION_ARGS[profile],
                    }
                ),
                timeout=300,
            )
        message = str(raised.value)
        assert "plugin tree failed to load" in message
        reported = sorted(
            set(
                re.findall(
                    r"failed to import loader entry \S+ \((@deepseek-ai/[^)]+)\): Cannot find module",
                    message,
                )
            )
        )
        assert reported == sorted(SHIPPED_PROVIDER_GAP[profile])

        parts = re.split(r"(?=failed to (?:apply|import) loader entry )", message)
        activation = sorted(
            {
                part.strip().rstrip(",")
                for part in parts
                if "Cannot find module" not in part
                and re.match(r"failed to apply loader entry \S+ \(@deepseek-ai/", part.strip())
            }
        )
        assert activation == SHIPPED_ACTIVATION_GAP[profile]
    finally:
        stdin.close()
        os.close(write_fd)
        safe_rmtree(home)


def test_the_activation_gap_is_empty_and_the_web_startup_provider_landed():
    """
    Guard the frozen activation gap itself: the web `webserver` row injects
    `webStartup`, so its provider row must be implemented in the table (and out
    of the provider gap) for no profile to report an activation failure of an
    implemented row.
    """
    assert resolve_harness_plugin("@deepseek-ai/dsh-web-app/startup") is not None
    for profile in PROFILES:
        assert SHIPPED_ACTIVATION_GAP[profile] == []
        assert "@deepseek-ai/dsh-web-app/startup" not in SHIPPED_PROVIDER_GAP[profile]


# --- The shipped `!!js` bodies evaluate with JS semantics --------------------
#
# Upstream evaluates an `!!js` body with the JS engine
# (`with (ctx) { return eval(expr) }`, reference/vendor/loader/src/config/utils.ts),
# so a row's config value is exactly what that expression yields. These cases
# derive the bodies from the pinned bundle patches rather than a hand-picked list,
# and pin the values the base/web/sdk layers depend on.


def _iter_js_expressions(value: Any) -> List[str]:
    """Every `!!js` body inside one composed row value."""
    if isinstance(value, dict):
        if set(value) == {"__jsExpr"}:
            return [value["__jsExpr"]]
        found: List[str] = []
        for item in value.values():
            found.extend(_iter_js_expressions(item))
        return found
    if isinstance(value, list):
        found = []
        for item in value:
            found.extend(_iter_js_expressions(item))
        return found
    return []


def shipped_js_expressions(profile: str) -> List[str]:
    """Every `!!js` body one shipped profile's pinned layers carry, in order."""
    template = PROFILE_TEMPLATES[profile]
    layers = [_shipped_bundle_patches(bundle) for bundle in template["bundles"]]
    expressions: List[str] = []
    for entry in compose_entries(layers):
        for key in ("config", "disabled"):
            for expr in _iter_js_expressions(entry.get(key)):
                if expr not in expressions:
                    expressions.append(expr)
    return expressions


@pytest.mark.parametrize("profile", PROFILES)
def test_every_shipped_js_expression_evaluates(profile):
    """
    No shipped `!!js` body fails to translate. A row whose body reads a service
    the row itself injects (`ctx.webStartup.*`, `ctx.headlessStartup.*`,
    `ctx.webRuntime.*`) is resolved by the Loader only once that service exists,
    so the service-independent bodies are the ones evaluated here.
    """
    expressions = shipped_js_expressions(profile)
    assert expressions, f"profile {profile} composes no !!js body to check"

    ctx = Context()
    ctx.provide("dshHomePath", lambda sub="": os.path.join("H", sub) if sub else "H")
    for expr in expressions:
        if expr.startswith("ctx."):
            continue
        evaluate_expr(ctx, expr)


def test_shipped_js_bodies_evaluate_to_their_upstream_values(monkeypatch):
    """
    The exact bodies the pinned bundles carry, evaluated with JS precedence:
    nullish coalescing binds tighter than the ternary, `||`/`??` keep their JS
    fallback semantics, and the referenced globals are bound.
    """
    ctx = Context()

    permission_policy = "(process.env.DSH_PERMISSION_MODE ?? 'workspace-write') === 'danger-full-access' ? 'never' : 'ask'"
    monkeypatch.delenv("DSH_PERMISSION_MODE", raising=False)
    assert evaluate_expr(ctx, permission_policy) == "ask"
    monkeypatch.setenv("DSH_PERMISSION_MODE", "danger-full-access")
    assert evaluate_expr(ctx, permission_policy) == "never"
    monkeypatch.setenv("DSH_PERMISSION_MODE", "workspace-write")
    assert evaluate_expr(ctx, permission_policy) == "ask"
    monkeypatch.delenv("DSH_PERMISSION_MODE", raising=False)

    monkeypatch.delenv("DSH_CONTEXT_WINDOW", raising=False)
    assert evaluate_expr(ctx, "Number(process.env.DSH_CONTEXT_WINDOW ?? 1000000)") == 1000000
    monkeypatch.setenv("DSH_CONTEXT_WINDOW", "4096")
    assert evaluate_expr(ctx, "Number(process.env.DSH_CONTEXT_WINDOW ?? 1000000)") == 4096
    monkeypatch.delenv("DSH_CONTEXT_WINDOW", raising=False)

    monkeypatch.delenv("DSH_TELEMETRY_MODE", raising=False)
    assert evaluate_expr(ctx, "process.env.DSH_TELEMETRY_MODE || 'FEEDBACK_ONLY'") == "FEEDBACK_ONLY"
    monkeypatch.setenv("DSH_TELEMETRY_MODE", "FULL")
    assert evaluate_expr(ctx, "process.env.DSH_TELEMETRY_MODE || 'FEEDBACK_ONLY'") == "FULL"
    monkeypatch.delenv("DSH_TELEMETRY_MODE", raising=False)

    monkeypatch.delenv("DSH_TELEMETRY_OTLP_URL", raising=False)
    assert (
        evaluate_expr(
            ctx,
            "process.env.DSH_TELEMETRY_OTLP_URL ?? 'https://harness-telemetry.deepseeksvc.com/v1/logs'",
        )
        == "https://harness-telemetry.deepseeksvc.com/v1/logs"
    )

    monkeypatch.delenv("DSH_MAX_TOKENS_AS_SUCCESS", raising=False)
    max_tokens = "process.env.DSH_MAX_TOKENS_AS_SUCCESS === undefined ? true : JSON.parse(process.env.DSH_MAX_TOKENS_AS_SUCCESS)"
    assert evaluate_expr(ctx, max_tokens) is True
    monkeypatch.setenv("DSH_MAX_TOKENS_AS_SUCCESS", "false")
    assert evaluate_expr(ctx, max_tokens) is False
    monkeypatch.delenv("DSH_MAX_TOKENS_AS_SUCCESS", raising=False)

    assert evaluate_expr(ctx, "process.platform === 'win32'") == (sys.platform == "win32")
    assert evaluate_expr(ctx, "process.platform !== 'win32'") == (sys.platform != "win32")
    assert evaluate_expr(ctx, "process.cwd()") == os.getcwd()

    ctx.provide("dshHomePath", lambda sub="": os.path.join("H", sub) if sub else "H")
    assert evaluate_expr(ctx, "dshHomePath('sessions')") == os.path.join("H", "sessions")

    ctx.provide("webStartup", {"host": None, "port": None, "openBrowser": False, "trustedHosts": []})
    assert evaluate_expr(ctx, "ctx.webStartup.host ?? '127.0.0.1'") == "127.0.0.1"
    assert evaluate_expr(ctx, "ctx.webStartup.port ?? 3080") == 3080
    ctx.provide("webRuntime", {"trustedHosts": ["app.internal"]})
    assert evaluate_expr(ctx, "ctx.webRuntime.trustedHosts") == ["app.internal"]
