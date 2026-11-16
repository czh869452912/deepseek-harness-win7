"""
1:1 parity suite for the browser client rows' host halves (`dsh/client/*`,
`dsh/client/rows.py`).

Upstream mounts each browser package's node half over a real Cordis tree; the
per-package spec each case maps is named in its docstring. The rows mount the
way a shipped profile mounts them: through the real Loader under the row's
shipped package name, resolved from the installation table.
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pytest

from dsh.boot.app_boot import mount_root_include
from dsh.boot.plugin_registry import HARNESS_PLUGIN_CLASSES, install_harness_plugin_classes
from dsh.client import locale as locale_row
from dsh.client import rows as client_rows
from dsh.client import ui_chat, ui_conversation, ui_settings_general, ui_theme
from dsh.client.surfaces import EMPTY_HOST_HALVES
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader
from dsh.settings.provider import SettingsProvider
from dsh.settings.types import settings_namespace

NAME = "dsh"


class MemorySettings(SettingsProvider):
    """Settings provider fixture: registers in memory, persists nothing."""

    @property
    def writable(self) -> bool:
        return True

    def _load_document(self) -> Dict[str, Any]:
        return {}

    def _persist_section(self, ns: str, section: Dict[str, Any]) -> None:
        return None


class _EmptySettings:
    """A settings provider whose namespace read comes back empty."""

    def register(self, ns: str, schema: Any = None, **kwargs: Any) -> Any:
        return lambda: None

    def get(self, ns: str) -> Any:
        return None


async def boot_rows(directory: str, row_names: List[str]) -> Context:
    """
    Mount the named shipped rows through the real Loader.

    @param directory: fixture directory the generated config lives in.
    @param row_names: the shipped package names to mount, in order.
    @returns: the booted context; the caller disposes it.
    """
    config_path = os.path.join(directory, "cordis.yml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write("\n".join("- id: row-%d\n  name: '%s'" % (i, name) for i, name in enumerate(row_names)) + "\n")
    ctx = Context()
    await ctx.plugin(Loader)
    install_harness_plugin_classes(ctx.get("loader"))
    await mount_root_include(ctx, config_path)
    await ctx.loader.await_()
    return ctx


def entry_of(ctx: Context, row_index: int) -> Any:
    """The loader entry mounted for row `row_index`."""
    wanted = "row-%d" % row_index
    for entry in ctx.loader.entries():
        if entry.options.get("id") == wanted:
            return entry
    raise AssertionError("row %s did not mount" % wanted)


def index_injections(ctx: Context) -> List[Dict[str, Any]]:
    """Collect the injection table the way an index render or boot payload does."""
    table: List[Dict[str, Any]] = []
    ctx.emit("webserver/index-inject", table)
    return table


def script_text(row: Optional[Dict[str, Any]]) -> str:
    """Narrow the theme row and return its script body."""
    if row is None or row.get("kind") != "script":
        raise AssertionError("expected a script row, got %r" % (row,))
    return row["text"]


def section_named(assembly: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """One assembled prompt section by name."""
    return next((entry for entry in assembly["sections"] if entry["name"] == name), None)


# --- rows whose upstream node half is an empty apply ---------------------------


@pytest.mark.parametrize(
    "package_name",
    sorted(name for _class, (name, _upstream) in EMPTY_HOST_HALVES.items()),
    ids=lambda name: name.replace("@deepseek-ai/dsh-", ""),
)
@pytest.mark.asyncio
async def test_the_empty_host_half_mounts_without_host_behavior(package_name, tmp_path):
    """
    Every browser row whose upstream node half is `export function apply(): void {}`
    mounts as a Loader entry and adds nothing to the host tree.
    """
    ctx = await boot_rows(str(tmp_path), [package_name])
    try:
        entry = entry_of(ctx, 0)
        assert entry.fiber is not None
        assert entry.fiber.state == FiberState.ACTIVE
        # The row is the whole config, so the host gained no service the
        # launcher and Loader do not already own, and no tool at all.
        assert ctx.get("tools") is None
        assert ctx.get("settings") is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ui_jobs_node_half_contributes_no_host_behavior():
    """"ui-job node half" > "contributes no host behavior"."""
    ctx = Context()
    before = (sorted(k for k in ctx._services), ctx.get("tools"))
    fiber = ctx.plugin(EMPTY_HOST_HALVES_CLASS("@deepseek-ai/dsh-client-ui-jobs"))
    await fiber.await_()
    try:
        assert (sorted(k for k in ctx._services), ctx.get("tools")) == before
    finally:
        await ctx.fiber.dispose()


def EMPTY_HOST_HALVES_CLASS(package_name: str) -> Any:
    """The generated host-half class one package resolves to."""
    spec = client_rows.CLIENT_HOST_HALF_ROWS[package_name]
    module_name, _, class_name = spec.partition(":")
    import importlib

    return getattr(importlib.import_module(module_name), class_name)


# --- ui-deliverables -----------------------------------------------------------


@pytest.mark.asyncio
async def test_file_reference_guidance_is_owned_separately_from_deliverables_ui(tmp_path):
    """Current Source separates desktop file guidance from authenticated UI actions."""
    from canonical_web_fixture import close_web_context, web_context
    from dsh.client.file_references_current import CurrentDeliverableFileReferences, FILE_REFERENCE_SECTION
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin

    # rc.3 also injects the native-open providers. Use their actual production
    # composition so this Loader lifecycle check cannot pass with a pending row.
    ctx = await web_context(tmp_path)
    try:
        # This is the prompt ownership unit, while shipped profile inputs are
        # promoted separately. Current Tools requires an explicit executor.
        await ctx.plugin(NativeToolExecutorPlugin)
        mounted = next(entry for entry in ctx.loader.entries()
                       if entry.options.get("name") == "@deepseek-ai/dsh-client-ui-deliverables")
        assert mounted.fiber.state == FiberState.ACTIVE
        before = await ctx.systemPrompt.assemble()
        assert section_named(before, "ui:deliverable-file-references") is None
        guidance = await ctx.plugin(CurrentDeliverableFileReferences)
        assembly = await ctx.systemPrompt.assemble()
        section = section_named(assembly, "ui:deliverable-file-references")
        assert section is not None
        assert section["text"] == FILE_REFERENCE_SECTION['text']

        await mounted.fiber.dispose()
        assert section_named(await ctx.systemPrompt.assemble(), "ui:deliverable-file-references") is not None
        await guidance.dispose()
        after = await ctx.systemPrompt.assemble()
        assert section_named(after, "ui:deliverable-file-references") is None
    finally:
        await close_web_context(ctx)


# --- settings-backed rows ------------------------------------------------------


@pytest.mark.asyncio
async def test_locale_host_registers_an_open_locale_preference():
    """"locale host" > "registers an open locale preference with the Host settings lifecycle"."""
    ctx = Context()
    await ctx.plugin(MemorySettings)
    fiber = ctx.plugin(locale_row.ClientLocalePlugin)
    await fiber.await_()
    try:
        ns = settings_namespace(locale_row.LOCALE_SETTINGS_NAMESPACE)
        assert ctx.settings.get(ns) == {}
        await ctx.settings.update(ns, {"preference": "en"})
        assert ctx.settings.get(ns) == {"preference": "en"}
        await ctx.settings.update(ns, {"preference": "pt-BR"})
        assert ctx.settings.get(ns) == {"preference": "pt-BR"}
        with pytest.raises(Exception):
            await ctx.settings.update(ns, {"preference": "bad locale"})
        with pytest.raises(Exception):
            await ctx.settings.update(ns, {"preference": "123"})
        await fiber.dispose()
        assert ns not in [row["ns"] for row in ctx.settings.describe()]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ui_chat_registers_validates_and_disposes_the_transcript_view_namespace():
    """"ui-chat Host settings" > "registers, validates, and disposes the transcript-view namespace"."""
    ctx = Context()
    await ctx.plugin(MemorySettings)
    fiber = ctx.plugin(ui_chat.ClientUiChatPlugin)
    await fiber.await_()
    ns = settings_namespace(ui_chat.CHAT_SETTINGS_NAMESPACE)

    assert ctx.settings.get(ns) == {"transcriptView": ui_chat.DEFAULT_TRANSCRIPT_VIEW_MODE}
    await ctx.settings.update(ns, {"transcriptView": "normal"})
    assert ctx.settings.get(ns) == {"transcriptView": "normal"}
    with pytest.raises(Exception):
        await ctx.settings.update(ns, {"transcriptView": "dense"})

    await fiber.dispose()
    assert ns not in [row["ns"] for row in ctx.settings.describe()]
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ui_chat_loads_without_a_settings_provider():
    """"ui-chat Host settings" > "loads without a settings provider"."""
    ctx = Context()
    fiber = ctx.plugin(ui_chat.ClientUiChatPlugin)
    try:
        assert await fiber.await_() is fiber.ctx.fiber
        assert ctx.get("settings") is None
        assert fiber.state == FiberState.ACTIVE
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ui_conversation_node_apply_tail_tolerates_a_host_without_settings():
    """"node apply tail" > "tolerates a Host without settings"."""
    ctx = Context()
    fiber = await ctx.plugin(ui_conversation.ClientUiConversationPlugin)
    try:
        assert ctx.get("settings") is None
        assert fiber.state == FiberState.ACTIVE
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ui_settings_general_registers_and_disposes_the_onboarding_namespace():
    """"ui-settings-general host" > "registers and disposes the durable onboarding namespace with its fiber"."""
    ctx = Context()
    await ctx.plugin(MemorySettings)
    fiber = ctx.plugin(ui_settings_general.ClientUiSettingsGeneralPlugin)
    await fiber.await_()
    ns = settings_namespace(ui_settings_general.ONBOARDING_SETTINGS_NAMESPACE)

    assert ns in [row["ns"] for row in ctx.settings.describe()]
    await fiber.dispose()
    assert ns not in [row["ns"] for row in ctx.settings.describe()]
    await ctx.fiber.dispose()


# --- ui-theme ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ui_theme_registers_validates_and_disposes_the_theme_namespace():
    """"ui-theme host" > "registers, validates, and disposes the durable theme namespace with its fiber"."""
    ctx = Context()
    await ctx.plugin(MemorySettings)
    fiber = ctx.plugin(ui_theme.ClientUiThemePlugin)
    await fiber.await_()
    ns = settings_namespace(ui_theme.THEME_SETTINGS_NAMESPACE)

    assert ctx.settings.get(ns) == {"preference": ui_theme.DEFAULT_PREFERENCE, "fontSize": 14}
    await ctx.settings.update(ns, {"preference": "dark", "fontSize": 16})
    assert ctx.settings.get(ns) == {"preference": "dark", "fontSize": 16}
    with pytest.raises(Exception):
        await ctx.settings.update(ns, {"preference": "sepia"})
    with pytest.raises(Exception):
        await ctx.settings.update(ns, {"fontSize": 11})
    with pytest.raises(Exception):
        await ctx.settings.update(ns, {"fontSize": 18})

    await fiber.dispose()
    assert ns not in [row["ns"] for row in ctx.settings.describe()]
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ui_theme_answers_each_collection_with_the_current_durable_preference():
    """"ui-theme host" > "answers each collection with the current durable preference until disposal"."""
    ctx = Context()
    await ctx.plugin(MemorySettings)
    fiber = ctx.plugin(ui_theme.ClientUiThemePlugin)
    await fiber.await_()

    rows = index_injections(ctx)
    assert len(rows) == 1
    assert rows[0]["kind"] == "script"
    assert rows[0]["placement"] == "body"
    assert 'const preference = "system"' in script_text(rows[0])
    assert '"14px"' in script_text(rows[0])

    await ctx.settings.update(
        settings_namespace(ui_theme.THEME_SETTINGS_NAMESPACE), {"preference": "dark", "fontSize": 17}
    )
    assert 'const preference = "dark"' in script_text(index_injections(ctx)[0])
    assert '"17px"' in script_text(index_injections(ctx)[0])

    await fiber.dispose()
    assert index_injections(ctx) == []
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ui_theme_uses_the_system_preference_without_a_settings_provider():
    """"ui-theme host" > "uses the system preference without a settings provider"."""
    ctx = Context()
    fiber = ctx.plugin(ui_theme.ClientUiThemePlugin)
    await fiber.await_()
    try:
        assert 'const preference = "system"' in script_text(index_injections(ctx)[0])
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ui_theme_falls_back_to_the_schema_default_while_the_namespace_holds_no_section():
    """"ui-theme host" > "falls back to the schema default while the theme namespace holds no section"."""
    ctx = Context()
    ctx.provide("settings", _EmptySettings())
    fiber = ctx.plugin(ui_theme.ClientUiThemePlugin)
    await fiber.await_()
    try:
        assert 'const preference = "system"' in script_text(index_injections(ctx)[0])
    finally:
        await ctx.fiber.dispose()


# --- ui-user-questions ---------------------------------------------------------


@pytest.mark.asyncio
async def test_ui_user_questions_node_plugin_mounts_no_model_facing_tool(tmp_path):
    """"ui-user-questions node plugin" > "mounts no model-facing tool"."""
    ctx = await boot_rows(
        str(tmp_path),
        [
            "@deepseek-ai/dsh-system-prompt",
            "@deepseek-ai/dsh-tools",
            "@deepseek-ai/dsh-user-questions",
            "@deepseek-ai/dsh-client-ui-user-questions",
        ],
    )
    try:
        # Selecting the Web question FEATURE must not hand every agent the tool:
        # `tool-ask-user` belongs to the presets that want it. `ctx.tools.register`
        # on a host context files into the global layer every agent merges.
        tools = ctx.get("tools")
        assert tools is not None
        assert tools.get("ask_user_question") is None
    finally:
        await ctx.fiber.dispose()


# --- the row table -------------------------------------------------------------


def test_every_shipped_client_row_has_a_host_half():
    """
    The effective installation registry answers every declared Web client row.
    Current providers override historical surfaces and include transport owners.
    """
    from dsh.boot.plugin_registry_current import CURRENT_HARNESS_PLUGIN_CLASSES

    shipped = web_client_rows()
    assert shipped
    assert set(shipped) <= HARNESS_PLUGIN_CLASSES.keys()
    for name, spec in client_rows.CLIENT_HOST_HALF_ROWS.items():
        assert HARNESS_PLUGIN_CLASSES[name] == CURRENT_HARNESS_PLUGIN_CLASSES.get(name, spec)
    for name, spec in CURRENT_HARNESS_PLUGIN_CLASSES.items():
        assert HARNESS_PLUGIN_CLASSES[name] == spec


def web_client_rows() -> List[str]:
    """Every `dsh-client-*` row the shipped Web bundle patch names."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "packages", "bundle", "web-app", "cordis.patch.yml")
    found = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            match = re.search(r"name: '(@deepseek-ai/dsh-client-[^']+)'", line)
            if match:
                found.append(match.group(1))
    return sorted(set(found))
