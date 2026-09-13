"""
1:1 Parity Tests for App Boot, Env Loading, Fail Loud, Activation Audits, and Harness Source Section.
Port of reference/packages/boot/app-boot/tests/app-boot.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import gc
import inspect
import json
import os
import sys
import tempfile
import time
import warnings
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from dsh.boot.app_boot import (
    FAIL_LOUD_RELEASE_TIMEOUT_MS,
    HARNESS_SOURCE_SECTION,
    addHarnessSourceSection,
    assertEntriesActivated,
    assertEntriesLoaded,
    boot,
    file_url_to_path,
    installFailLoud,
    loadEnv,
    loadLayeredEnv,
    loadOverlayPatches,
    path_to_file_url,
    resolveConfigPath,
)
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.core.system_prompt import SystemPrompt, render_prompt

NAME = "dsh-test-bin"


def tmp() -> str:
    return tempfile.mkdtemp(prefix="dsh-app-boot-")


class FakeProc:
    """Mock process object for installFailLoud tests."""

    def __init__(self):
        self.handlers: List[Callable[[Any], None]] = []
        self.written: List[str] = []
        self.exits: List[int] = []

        class Stderr:
            def __init__(self, outer):
                self.outer = outer

            def write(self, chunk: str):
                self.outer.written.append(chunk)

        self.stderr = Stderr(self)

    def on(self, event: str, handler: Callable[[Any], None]):
        self.handlers.append(handler)

    def off(self, event: str, handler: Callable[[Any], None]):
        if handler in self.handlers:
            self.handlers.remove(handler)

    def exit(self, code: int):
        self.exits.append(code)


# ---------------------------------------------------------------------------
# resolveConfigPath
# ---------------------------------------------------------------------------


def test_resolve_config_path_relative_to_given_cwd_outside_replay_mode():
    base = os.path.abspath(os.path.join(os.path.sep, "base"))
    assert resolveConfigPath("./cordis.yml", None, base) == os.path.join(base, "cordis.yml")
    assert resolveConfigPath("conf/app.yaml", "record", base) == os.path.join(base, "conf", "app.yaml")


def test_resolve_config_path_swaps_cordis_basename_in_replay_mode():
    base = os.path.abspath(os.path.join(os.path.sep, "base"))
    assert resolveConfigPath("./cordis.yml", "replay", base) == os.path.join(base, "cordis.snapshot.yml")
    assert resolveConfigPath("deep/cordis.yaml", "replay", base) == os.path.join(base, "deep", "cordis.snapshot.yml")


def test_resolve_config_path_leaves_non_cordis_alone_in_replay_and_defaults_cwd():
    base = os.path.abspath(os.path.join(os.path.sep, "base"))
    assert resolveConfigPath("custom.yml", "replay", base) == os.path.join(base, "custom.yml")
    assert resolveConfigPath("./x.yml", None) == os.path.abspath(os.path.join(os.getcwd(), "x.yml"))


# ---------------------------------------------------------------------------
# loadEnv
# ---------------------------------------------------------------------------


def test_load_env_loads_variables_from_dotenv_in_given_dir(monkeypatch):
    d = tmp()
    with open(os.path.join(d, ".env"), "w", encoding="utf-8") as f:
        f.write("DSH_APP_BOOT_SPEC_VAR=loaded\n")
    warn = MagicMock()
    monkeypatch.delenv("DSH_APP_BOOT_SPEC_VAR", raising=False)
    loadEnv(NAME, d, warn)
    assert os.environ.get("DSH_APP_BOOT_SPEC_VAR") == "loaded"
    warn.assert_not_called()
    monkeypatch.delenv("DSH_APP_BOOT_SPEC_VAR", raising=False)


def test_load_env_stays_silent_when_no_dotenv_exists():
    warn = MagicMock()
    loadEnv(NAME, tmp(), warn)
    warn.assert_not_called()


def test_load_env_warns_when_dotenv_is_directory():
    d = tmp()
    os.makedirs(os.path.join(d, ".env"), exist_ok=True)
    warn = MagicMock()
    loadEnv(NAME, d, warn)
    warn.assert_called_once()
    msg = warn.call_args[0][0]
    assert msg.startswith(f"{NAME}: failed to load .env: ")


def test_load_env_defaults_dir_to_process_cwd_and_warn_to_stderr(monkeypatch):
    d = tmp()
    with open(os.path.join(d, ".env"), "w", encoding="utf-8") as f:
        f.write("DSH_APP_BOOT_SPEC_DEFAULTS=yes\n")
    previous = os.getcwd()
    monkeypatch.delenv("DSH_APP_BOOT_SPEC_DEFAULTS", raising=False)
    try:
        os.chdir(d)
        loadEnv(NAME)
    finally:
        os.chdir(previous)
    assert os.environ.get("DSH_APP_BOOT_SPEC_DEFAULTS") == "yes"
    monkeypatch.delenv("DSH_APP_BOOT_SPEC_DEFAULTS", raising=False)

    broken = tmp()
    os.makedirs(os.path.join(broken, ".env"), exist_ok=True)
    captured = []
    monkeypatch.setattr(sys.stderr, "write", lambda s: captured.append(s))
    loadEnv(NAME, broken)
    assert len(captured) >= 1
    assert any(f"{NAME}: failed to load .env: " in s for s in captured)


# ---------------------------------------------------------------------------
# loadLayeredEnv
# ---------------------------------------------------------------------------


NAMES = ["APP_BOOT_LAYERED_SHARED", "APP_BOOT_LAYERED_USER", "APP_BOOT_LAYERED_PROJECT"]


def clear_layered_env(monkeypatch):
    for n in NAMES:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.delenv("APP_BOOT_LAYERED_INHERITED", raising=False)


def test_load_layered_env_layers_user_under_project_under_inherited_environment(monkeypatch):
    home = tmp()
    project = tmp()
    with open(os.path.join(home, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[0]}=user\n{NAMES[1]}=user-only\nAPP_BOOT_LAYERED_INHERITED=user-loses\n")
    with open(os.path.join(project, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[0]}=project\n{NAMES[2]}=project-only\nAPP_BOOT_LAYERED_INHERITED=project-loses\n")

    clear_layered_env(monkeypatch)
    monkeypatch.setenv("DSH_HOME", home)
    monkeypatch.setenv("APP_BOOT_LAYERED_INHERITED", "inherited")
    warn = MagicMock()
    try:
        loadLayeredEnv(NAME, project, warn)
        assert os.environ.get(NAMES[0]) == "project"
        assert os.environ.get(NAMES[1]) == "user-only"
        assert os.environ.get(NAMES[2]) == "project-only"
        assert os.environ.get("APP_BOOT_LAYERED_INHERITED") == "inherited"
        warn.assert_not_called()
    finally:
        clear_layered_env(monkeypatch)


@pytest.mark.parametrize("case_name,content", [
    ("a harness switch", "DSH_PERMISSION_MODE=danger-full-access\n"),
    ("the executable search path", "PATH=/tmp/evil\n"),
    ("a module preload", "NODE_OPTIONS=--require /tmp/evil.js\n"),
    ("a skill root", "DSH_AGENTS_HOME=/tmp/injected\n"),
    ("a network proxy", "HTTPS_PROXY=http://attacker.example\n"),
    ("a lowercase network proxy", "https_proxy=http://attacker.example\n"),
    ("a browser command", "BROWSER=./script\n"),
])
def test_load_layered_env_refuses_to_launch_when_dotenv_sets_bootstrap_only(monkeypatch, case_name, content):
    home = tmp()
    project = tmp()
    with open(os.path.join(project, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[1]}=applied-anyway\n{content}")
    clear_layered_env(monkeypatch)
    monkeypatch.setenv("DSH_HOME", home)
    try:
        with pytest.raises(RuntimeError, match="only the launching environment may set"):
            loadLayeredEnv(NAME, project, MagicMock())
        assert os.environ.get(NAMES[1]) is None
    finally:
        clear_layered_env(monkeypatch)


def test_load_layered_env_reports_each_file_value_with_its_absolute_path(monkeypatch):
    home = tmp()
    project = tmp()
    with open(os.path.join(home, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[1]}=u\n")
    with open(os.path.join(project, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[2]}=p\n")
    clear_layered_env(monkeypatch)
    monkeypatch.setenv("DSH_HOME", home)
    try:
        snapshot = loadLayeredEnv(NAME, project, MagicMock())
        assert snapshot.get(NAMES[1]) == {"value": "u", "source": "user-env", "path": os.path.join(home, ".env")}
        assert snapshot.get(NAMES[2]) == {"value": "p", "source": "project-env", "path": os.path.join(project, ".env")}
        assert snapshot.get_from(NAMES[2], ["process", "user-env"]) is None
    finally:
        clear_layered_env(monkeypatch)


def test_load_layered_env_resolves_harness_home_from_inherited_environment_never_from_file(monkeypatch):
    home = tmp()
    project = tmp()
    with open(os.path.join(home, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[1]}=real-home\n")
    with open(os.path.join(project, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[2]}=set-by-project\n")
    clear_layered_env(monkeypatch)
    monkeypatch.setenv("DSH_HOME", home)
    try:
        loadLayeredEnv(NAME, project, MagicMock())
        assert os.environ.get(NAMES[1]) == "real-home"
        assert os.environ.get(NAMES[2]) == "set-by-project"
    finally:
        clear_layered_env(monkeypatch)


def test_load_layered_env_warns_and_continues_when_layer_exists_but_cannot_be_read(monkeypatch):
    home = tmp()
    project = tmp()
    os.makedirs(os.path.join(home, ".env"), exist_ok=True)
    with open(os.path.join(project, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[2]}=project-only\n")
    clear_layered_env(monkeypatch)
    monkeypatch.setenv("DSH_HOME", home)
    warn = MagicMock()
    try:
        snapshot = loadLayeredEnv(NAME, project, warn)
        warn.assert_called_once()
        assert f"{NAME}: failed to load .env" in warn.call_args[0][0]
        assert snapshot.get(NAMES[1]) is None
        assert snapshot.get(NAMES[2]) == {"value": "project-only", "source": "project-env", "path": os.path.join(project, ".env")}
        assert os.environ.get(NAMES[2]) == "project-only"
    finally:
        clear_layered_env(monkeypatch)


def test_load_layered_env_reports_to_stderr_when_caller_supplies_no_reporter(monkeypatch):
    home = tmp()
    project = tmp()
    os.makedirs(os.path.join(home, ".env"), exist_ok=True)
    with open(os.path.join(project, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[2]}=project-only\n")
    clear_layered_env(monkeypatch)
    monkeypatch.setenv("DSH_HOME", home)
    captured = []
    monkeypatch.setattr(sys.stderr, "write", lambda s: captured.append(s))
    try:
        snapshot = loadLayeredEnv(NAME, project)
        assert any(f"{NAME}: failed to load .env" in s for s in captured)
        assert snapshot.get(NAMES[2]) == {"value": "project-only", "source": "project-env", "path": os.path.join(project, ".env")}
        assert os.environ.get(NAMES[2]) == "project-only"
    finally:
        clear_layered_env(monkeypatch)


def test_load_layered_env_passes_over_absent_layer_without_reporting_it(monkeypatch):
    home = tmp()
    project = tmp()
    with open(os.path.join(project, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[2]}=project-only\n")
    clear_layered_env(monkeypatch)
    monkeypatch.setenv("DSH_HOME", home)
    warn = MagicMock()
    try:
        snapshot = loadLayeredEnv(NAME, project, warn)
        warn.assert_not_called()
        assert snapshot.get(NAMES[2]) == {"value": "project-only", "source": "project-env", "path": os.path.join(project, ".env")}
    finally:
        clear_layered_env(monkeypatch)


def test_load_layered_env_carries_only_inherited_environment_when_neither_file_exists(monkeypatch):
    home = tmp()
    project = tmp()
    clear_layered_env(monkeypatch)
    monkeypatch.setenv("DSH_HOME", home)
    monkeypatch.setenv("APP_BOOT_LAYERED_INHERITED", "inherited")
    try:
        snapshot = loadLayeredEnv(NAME, project, MagicMock())
        assert snapshot.get("APP_BOOT_LAYERED_INHERITED") == {"value": "inherited", "source": "process"}
    finally:
        clear_layered_env(monkeypatch)


def test_load_layered_env_reads_harness_home_that_is_also_invocation_directory_once(monkeypatch):
    both = tmp()
    with open(os.path.join(both, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{NAMES[2]}=one-file\n")
    clear_layered_env(monkeypatch)
    monkeypatch.setenv("DSH_HOME", both)
    try:
        snapshot = loadLayeredEnv(NAME, both, MagicMock())
        assert snapshot.get(NAMES[2]) == {"value": "one-file", "source": "project-env", "path": os.path.join(both, ".env")}
    finally:
        clear_layered_env(monkeypatch)


# ---------------------------------------------------------------------------
# installFailLoud
# ---------------------------------------------------------------------------


def test_install_fail_loud_writes_one_labelled_line_with_stack_and_exits_1():
    proc = FakeProc()
    installFailLoud(NAME, proc)
    error = RuntimeError("boom")
    error.stack = "RuntimeError: boom\n    at spec_frame"
    proc.handlers[0](error)
    assert f"{NAME}: fatal load failure: " in proc.written[0]
    assert "RuntimeError: boom\n    at spec_frame" in proc.written[0]
    assert proc.exits == [1]


def test_install_fail_loud_stringifies_non_error_and_error_without_stack():
    plain = FakeProc()
    installFailLoud(NAME, plain)
    plain.handlers[0]("plain failure")
    assert "plain failure" in plain.written[0]
    assert plain.exits == [1]

    bare = FakeProc()
    installFailLoud(NAME, bare)
    bare.handlers[0](Exception("no stack"))
    assert "no stack" in bare.written[0]
    assert bare.exits == [1]


def test_install_fail_loud_returns_uninstaller_that_removes_handler():
    proc = FakeProc()
    uninstall = installFailLoud(NAME, proc)
    assert len(proc.handlers) == 1
    uninstall()
    assert len(proc.handlers) == 0

    # Default proc doesn't throw
    uninstall_real = installFailLoud(NAME)
    uninstall_real()


@pytest.mark.asyncio
async def test_install_fail_loud_default_proc_restores_loop_handler():
    loop = asyncio.get_running_loop()
    dummy_handler = lambda l, c: None
    loop.set_exception_handler(dummy_handler)
    try:
        uninstall_real = installFailLoud(NAME)
        assert loop.get_exception_handler() is not dummy_handler
        uninstall_real()
        assert loop.get_exception_handler() is dummy_handler
    finally:
        loop.set_exception_handler(None)


@pytest.mark.asyncio
async def test_install_fail_loud_does_not_report_assembled_rejection_shared_by_boot_audit():
    proc = FakeProc()
    installFailLoud(NAME, proc)
    error = RuntimeError("assembled activation failure")

    class FakeFiber:
        state = FiberState.FAILED
        inject = {}
        ctx = type("Ctx", (), {"get": lambda s, n: None})()

        async def await_(self):
            raise error

    class FakeEntry:
        def __init__(self, name):
            self.options = {"name": name}
            self.fiber = FakeFiber()

    class FakeLoader:
        def entries(self):
            return [FakeEntry("broken-a"), FakeEntry("broken-b")]

    ctx = Context()
    ctx.set_service("loader", FakeLoader())

    audit_task = asyncio.create_task(assertEntriesActivated(ctx, NAME))
    await asyncio.sleep(0)
    proc.handlers[0](error)
    assert proc.written == []
    assert proc.exits == []
    with pytest.raises(RuntimeError, match="assembled activation failure"):
        await audit_task
    proc.handlers[0](error)
    assert proc.exits == [1]


@pytest.mark.asyncio
async def test_install_fail_loud_awaits_release_hook_before_exiting():
    proc = FakeProc()
    order = []

    async def release():
        await asyncio.sleep(0.01)
        order.append("released")

    installFailLoud(NAME, proc, release)
    proc.handlers[0](RuntimeError("sibling entry rejected"))
    assert f"{NAME}: fatal load failure: " in proc.written[0]
    # Allow async release task to run
    for _ in range(10):
        if proc.exits:
            break
        await asyncio.sleep(0.02)
    assert proc.exits == [1]
    assert order == ["released"]


@pytest.mark.asyncio
async def test_install_fail_loud_still_exits_when_release_hook_rejects():
    proc = FakeProc()

    async def release():
        raise RuntimeError("terminal stop failed")

    installFailLoud(NAME, proc, release)
    proc.handlers[0](RuntimeError("boom"))
    for _ in range(10):
        if proc.exits:
            break
        await asyncio.sleep(0.02)
    assert proc.exits == [1]


@pytest.mark.asyncio
async def test_install_fail_loud_exits_without_waiting_when_release_hook_never_settles(monkeypatch):
    import dsh.boot.app_boot as boot_mod
    monkeypatch.setattr(boot_mod, "FAIL_LOUD_RELEASE_TIMEOUT_MS", 50)
    proc = FakeProc()

    async def release():
        await asyncio.sleep(10)

    installFailLoud(NAME, proc, release)
    proc.handlers[0](RuntimeError("boom"))
    for _ in range(15):
        if proc.exits:
            break
        await asyncio.sleep(0.02)
    assert proc.exits == [1]


@pytest.mark.asyncio
async def test_install_fail_loud_reports_only_first_rejection_and_keeps_handling_later():
    proc = FakeProc()
    released = False

    async def release():
        nonlocal released
        await asyncio.sleep(0.02)
        released = True

    installFailLoud(NAME, proc, release)
    proc.handlers[0](RuntimeError("first rejection"))
    proc.handlers[0](RuntimeError("second rejection"))
    assert len(proc.handlers) == 1
    assert len(proc.written) == 1
    assert "first rejection" in proc.written[0]
    for _ in range(10):
        if proc.exits:
            break
        await asyncio.sleep(0.02)
    assert proc.exits == [1]
    assert released is True


# ---------------------------------------------------------------------------
# assertEntriesLoaded
# ---------------------------------------------------------------------------


def test_assert_entries_loaded_passes_when_every_enabled_entry_has_fiber():
    class EntryOk:
        options = {"name": "a"}
        fiber = object()
        disabled = False

    class EntryOff:
        options = {"name": "off"}
        fiber = None
        disabled = True

    class FakeLoader:
        def entries(self):
            return [EntryOk(), EntryOff()]

    ctx = Context()
    ctx.set_service("loader", FakeLoader())
    assertEntriesLoaded(ctx, NAME)


def test_assert_entries_loaded_throws_naming_every_enabled_fiber_less_entry():
    class EntryOk:
        options = {"name": "ok"}
        fiber = object()
        disabled = False

    class EntryBrokenA:
        options = {"name": "broken-a"}
        fiber = None
        disabled = False

    class EntryBrokenB:
        options = {"name": "broken-b"}
        fiber = None
        disabled = False

    class FakeLoader:
        def entries(self):
            return [EntryOk(), EntryBrokenA(), EntryBrokenB()]

    ctx = Context()
    ctx.set_service("loader", FakeLoader())
    with pytest.raises(RuntimeError, match=f"{NAME}: plugin\\(s\\) failed to load: broken-a, broken-b"):
        assertEntriesLoaded(ctx, NAME)


# ---------------------------------------------------------------------------
# assertEntriesActivated
# ---------------------------------------------------------------------------


class MockFiber:
    def __init__(self, state, error=None, inject=None, services=None):
        self.state = state
        self.error = error
        self.inject = inject or {}
        self.services = services or []

        class Ctx:
            def __init__(self, s):
                self.s = s

            def get(self, name):
                return {} if name in self.s else None

        self.ctx = Ctx(self.services)

    async def await_(self):
        if self.error is not None:
            if isinstance(self.error, BaseException):
                raise self.error
            raise RuntimeError(str(self.error))


@pytest.mark.asyncio
async def test_assert_entries_activated_passes_active_entries_and_ignores_disabled():
    class ActiveEntry:
        options = {"name": "active"}
        disabled = False
        fiber = MockFiber(FiberState.ACTIVE)

    class DisabledEntry:
        options = {"name": "disabled"}
        disabled = True
        fiber = MockFiber(FiberState.FAILED, RuntimeError("disabled failure"))

    class FakeLoader:
        def entries(self):
            return [ActiveEntry(), DisabledEntry()]

    ctx = Context()
    ctx.set_service("loader", FakeLoader())
    await assertEntriesActivated(ctx, NAME)


@pytest.mark.asyncio
async def test_assert_entries_activated_reports_plugin_name_and_original_activation_stack():
    class BrokenEntry:
        options = {"name": "broken-plugin"}
        disabled = False
        err = RuntimeError("actual plugin failure")
        fiber = MockFiber(FiberState.FAILED, err)

    class FakeLoader:
        def entries(self):
            return [BrokenEntry()]

    ctx = Context()
    ctx.set_service("loader", FakeLoader())
    with pytest.raises(RuntimeError, match=f"{NAME}: 1 entry did not activate\nbroken-plugin: actual plugin failure"):
        await assertEntriesActivated(ctx, NAME)


@pytest.mark.asyncio
async def test_assert_entries_activated_formats_stackless_and_non_error_failures():
    class Entry1:
        options = {"name": "stackless"}
        disabled = False
        fiber = MockFiber(FiberState.FAILED, Exception("stackless failure"))

    class Entry2:
        options = {"name": "plain"}
        disabled = False
        fiber = MockFiber(FiberState.FAILED, "plain failure")

    class FakeLoader:
        def entries(self):
            return [Entry1(), Entry2()]

    ctx = Context()
    ctx.set_service("loader", FakeLoader())
    with pytest.raises(RuntimeError) as exc_info:
        await assertEntriesActivated(ctx, NAME)
    msg = str(exc_info.value)
    assert f"{NAME}: 2 entries did not activate" in msg
    assert "stackless: stackless failure" in msg
    assert "plain: plain failure" in msg


@pytest.mark.asyncio
async def test_assert_entries_activated_reports_unresolved_services_for_pending_entries():
    class WaitingEntry:
        options = {"name": "waiting"}
        disabled = False
        fiber = MockFiber(FiberState.PENDING, inject={"ready": {}, "missingA": {}, "missingB": {}}, services=["ready"])

    class SingleWaitEntry:
        options = {"name": "single-wait"}
        disabled = False
        fiber = MockFiber(FiberState.PENDING, inject={"missing": {}})

    class UnknownWaitEntry:
        options = {"name": "unknown-wait"}
        disabled = False
        fiber = MockFiber(FiberState.PENDING)

    class FakeLoader:
        def entries(self):
            return [WaitingEntry(), SingleWaitEntry(), UnknownWaitEntry()]

    ctx = Context()
    ctx.set_service("loader", FakeLoader())
    with pytest.raises(RuntimeError) as exc_info:
        await assertEntriesActivated(ctx, NAME)
    msg = str(exc_info.value)
    assert f"{NAME}: 3 entries did not activate" in msg
    assert "waiting: pending (waiting for services: missingA, missingB)" in msg
    assert "single-wait: pending (waiting for service: missing)" in msg
    assert "unknown-wait: pending (waiting for services: unknown)" in msg


@pytest.mark.asyncio
async def test_assert_entries_activated_retains_numeric_diagnostic_for_settled_unexpected_state():
    class DisposedEntry:
        options = {"name": "disposed"}
        disabled = False
        fiber = MockFiber(FiberState.DISPOSED)

    class FakeLoader:
        def entries(self):
            return [DisposedEntry()]

    ctx = Context()
    ctx.set_service("loader", FakeLoader())
    with pytest.raises(RuntimeError, match="disposed: fiber state 4"):
        await assertEntriesActivated(ctx, NAME)


# ---------------------------------------------------------------------------
# loadOverlayPatches
# ---------------------------------------------------------------------------


def test_load_overlay_patches_loads_expressions_and_rejects_malformed():
    d = tmp()
    valid = os.path.join(d, "valid.yml")
    with open(valid, "w", encoding="utf-8") as f:
        f.write("- id: target\n  config:\n    value: !!js process.env.VALUE\n")
    res = loadOverlayPatches(NAME, valid)
    assert res == [{"id": "target", "config": {"value": {"__jsExpr": "process.env.VALUE"}}}]

    with pytest.raises(RuntimeError, match=f"{NAME}: failed to read overlay"):
        loadOverlayPatches(NAME, os.path.join(d, "missing.yml"))

    malformed = os.path.join(d, "malformed.yml")
    with open(malformed, "w", encoding="utf-8") as f:
        f.write(": bad")
    with pytest.raises(RuntimeError, match=f"{NAME}: failed to parse overlay"):
        loadOverlayPatches(NAME, malformed)

    mapping = os.path.join(d, "mapping.yml")
    with open(mapping, "w", encoding="utf-8") as f:
        f.write("id: target\n")
    with pytest.raises(RuntimeError, match="must be a top-level YAML array"):
        loadOverlayPatches(NAME, mapping)

    scalar = os.path.join(d, "scalar.yml")
    with open(scalar, "w", encoding="utf-8") as f:
        f.write("- scalar\n")
    with pytest.raises(RuntimeError, match="entry 1"):
        loadOverlayPatches(NAME, scalar)


# ---------------------------------------------------------------------------
# boot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boot_boots_leaf_config_through_real_loader_and_settles_tree():
    d = tmp()
    with open(os.path.join(d, "noop.mjs"), "w", encoding="utf-8") as f:
        f.write('export const name = "noop"\nexport function apply() {}\n')
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: noop\n  name: ./noop.mjs\n")
    ctx = await boot(NAME, os.path.join(d, "cordis.yml"))
    try:
        entries = list(ctx.loader.entries())
        assert any(entry.options.get("name") == "./noop.mjs" and entry.fiber is not None for entry in entries)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_boot_can_resolve_bare_plugins_from_harness_when_config_shadows_name():
    d = tmp()
    harness = tmp()
    absolute_plugin = os.path.join(d, "absolute.mjs")
    shadow = os.path.join(d, "node_modules", "@deepseek-ai", "dsh-system-prompt")
    harness_plugin = os.path.join(harness, "node_modules", "@deepseek-ai", "dsh-system-prompt")
    os.makedirs(shadow, exist_ok=True)
    os.makedirs(harness_plugin, exist_ok=True)

    with open(os.path.join(shadow, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "@deepseek-ai/dsh-system-prompt", "type": "module", "exports": "./index.mjs"}, f)
    with open(os.path.join(shadow, "index.mjs"), "w", encoding="utf-8") as f:
        f.write('export function apply(ctx) { ctx.provide("shadowPluginLoaded", true) }\n')

    with open(os.path.join(harness_plugin, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "@deepseek-ai/dsh-system-prompt", "type": "module", "exports": "./index.mjs"}, f)
    with open(os.path.join(harness_plugin, "index.mjs"), "w", encoding="utf-8") as f:
        f.write('export function apply(ctx) { ctx.provide("harnessPluginLoaded", true) }\n')

    with open(os.path.join(d, "relative.mjs"), "w", encoding="utf-8") as f:
        f.write('export function apply(ctx) { ctx.provide("relativePluginLoaded", true) }\n')
    with open(absolute_plugin, "w", encoding="utf-8") as f:
        f.write('export function apply(ctx) { ctx.provide("absolutePluginLoaded", true) }\n')

    entries = [
        "- id: prompt",
        "  name: '@deepseek-ai/dsh-system-prompt'",
        "- id: relative",
        "  name: './relative.mjs'",
    ]
    config_owned_path = os.path.join(d, "config-owned.cordis.yml")
    with open(config_owned_path, "w", encoding="utf-8") as f:
        f.write("\n".join(entries) + "\n")

    host_owned_path = os.path.join(d, "host-owned.cordis.yml")
    with open(host_owned_path, "w", encoding="utf-8") as f:
        f.write("\n".join(entries + ["- id: absolute", f"  name: {json.dumps(absolute_plugin)}", ""]))

    config_owned = await boot(NAME, config_owned_path)
    try:
        assert config_owned.get("shadowPluginLoaded") is True
        assert config_owned.get("systemPrompt") is None
        assert config_owned.get("relativePluginLoaded") is True
    finally:
        await config_owned.fiber.dispose()

    harness_base_url = path_to_file_url(os.path.join(harness, "entry.mjs"))
    ctx = await boot(NAME, host_owned_path, None, None, harness_base_url)
    try:
        assert ctx.get("harnessPluginLoaded") is True
        assert ctx.get("shadowPluginLoaded") is None
        assert ctx.get("relativePluginLoaded") is True
        assert ctx.get("absolutePluginLoaded") is True
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_boot_runs_host_preparation_before_loader_tree_mounts():
    d = tmp()
    with open(os.path.join(d, "noop.mjs"), "w", encoding="utf-8") as f:
        f.write('export const name = "noop"\nexport function apply() {}\n')
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: noop\n  name: ./noop.mjs\n")

    prepared: List[Context] = []

    def prepare(host_ctx: Context):
        assert host_ctx.loader is not None
        assert list(host_ctx.loader.entries()) == []
        prepared.append(host_ctx)

    ctx = await boot(NAME, os.path.join(d, "cordis.yml"), None, prepare)
    try:
        assert prepared == [ctx]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_boot_disposes_partial_host_setup_and_labels_non_error_preparation_failures():
    d = tmp()
    failure = 42
    disposed = False

    def prepare(ctx: Context):
        nonlocal disposed

        def _cleanup():
            nonlocal disposed
            disposed = True

        ctx.effect(lambda: _cleanup)
        raise RuntimeError(str(failure))

    with pytest.raises(RuntimeError, match=f"{NAME}: host preparation failed: {failure}"):
        await boot(NAME, os.path.join(d, "cordis.yml"), None, prepare)
    assert disposed is True


@pytest.mark.asyncio
async def test_boot_exposes_dsh_home_path_to_loader_config_expressions(monkeypatch):
    d = tmp()
    dsh_home = os.path.join(d, "home")
    monkeypatch.setenv("DSH_HOME", dsh_home)
    with open(os.path.join(d, "capture.mjs"), "w", encoding="utf-8") as f:
        f.write('export const name = "capture"\nexport function apply(ctx, config) { ctx.provide("capturedPath", config.path) }\n')
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: capture\n  name: ./capture.mjs\n  config:\n    path: !!js dshHomePath('sessions')\n")

    ctx = None
    try:
        ctx = await boot(NAME, os.path.join(d, "cordis.yml"))
        assert ctx.get("capturedPath") == os.path.join(dsh_home, "sessions")
    finally:
        if ctx:
            await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_boot_returns_instead_of_asserting_over_tree_disposed_mid_startup():
    d = tmp()
    with open(os.path.join(d, "exiting.mjs"), "w", encoding="utf-8") as f:
        f.write('export const name = "exiting"\nexport function apply(ctx) { void ctx.root.fiber.dispose() }\n')
    with open(os.path.join(d, "delayed.mjs"), "w", encoding="utf-8") as f:
        f.write('export function apply() {}\n')
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: exiting\n  name: ./exiting.mjs\n- id: delayed\n  name: ./delayed.mjs\n")

    ctx = await boot(NAME, os.path.join(d, "cordis.yml"))
    assert ctx.get("loader") is None


@pytest.mark.asyncio
async def test_boot_settles_the_root_fiber_teardown_a_script_bridge_starts_mid_startup():
    """Boot joins the teardown a dropped `void ctx.root.fiber.dispose()` started.

    Reference: reference/packages/boot/app-boot/tests/app-boot.spec.ts
    'returns instead of asserting over a tree a surface disposed mid-startup'.
    The reference drops the promise the plugin body returns and only the
    microtask queue keeps the teardown alive. The port owns that settlement on
    the root fiber and joins it, with the dependent fiber inertia, so boot
    returns with no scheduled task and no unawaited coroutine left behind.
    """
    d = tmp()
    with open(os.path.join(d, "exiting.mjs"), "w", encoding="utf-8") as f:
        f.write('export const name = "exiting"\nexport function apply(ctx) { void ctx.root.fiber.dispose() }\n')
    with open(os.path.join(d, "delayed.mjs"), "w", encoding="utf-8") as f:
        f.write("export function apply() {}\n")
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: exiting\n  name: ./exiting.mjs\n- id: delayed\n  name: ./delayed.mjs\n")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ctx = await boot(NAME, os.path.join(d, "cordis.yml"))
        pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        settlements = ctx.fiber.settlement_tasks()
        gc.collect()

    assert ctx.get("loader") is None
    assert pending == []
    assert settlements == []
    assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []


@pytest.mark.asyncio
async def test_boot_rejects_when_config_names_plugin_that_cannot_be_imported():
    d = tmp()
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: ghost\n  name: ./missing.mjs\n")
    with pytest.raises(RuntimeError, match=f"{NAME}: plugin tree failed to load: failed to apply loader entry"):
        await boot(NAME, os.path.join(d, "cordis.yml"))


@pytest.mark.asyncio
async def test_boot_labels_deferred_config_failure_with_its_row_and_leaves_file_unchanged():
    d = tmp()
    config_path = os.path.join(d, "cordis.yml")
    config = (
        "- id: invalid-config\n"
        "  name: ./noop.mjs\n"
        "  config:\n"
        "    value: !!js \"JSON.parse('invalid')\"\n"
    )
    with open(os.path.join(d, "noop.mjs"), "w", encoding="utf-8") as f:
        f.write("export function apply() {}\n")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config)

    with pytest.raises(RuntimeError, match="failed to apply loader entry invalid-config \\(\\./noop\\.mjs\\)"):
        await boot(NAME, config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        assert f.read() == config


@pytest.mark.asyncio
async def test_boot_appends_deepest_cause_with_original_stack():
    d = tmp()
    with open(os.path.join(d, "failing.mjs"), "w", encoding="utf-8") as f:
        f.write(
            "export function apply() {\n"
            "  const failure = new Error('pinned activation failure')\n"
            "  throw failure\n"
            "}\n"
        )
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: failing\n  name: ./failing.mjs\n")

    with pytest.raises(RuntimeError, match="pinned activation failure"):
        await boot(NAME, os.path.join(d, "cordis.yml"))


@pytest.mark.asyncio
async def test_boot_falls_back_to_deepest_cause_message_when_stack_was_erased():
    d = tmp()
    deepest = RuntimeError("stackless deep failure")

    def prepare(ctx):
        wrapper = RuntimeError("wrapped setup failure")
        wrapper.__cause__ = deepest
        raise wrapper

    with pytest.raises(RuntimeError) as exc_info:
        await boot(NAME, os.path.join(d, "cordis.yml"), None, prepare)
    msg = str(exc_info.value)
    assert f"{NAME}: host preparation failed: wrapped setup failure" in msg
    assert "stackless deep failure" in msg


@pytest.mark.asyncio
async def test_boot_expands_stackless_aggregate_at_deepest_activation_cause():
    d = tmp()

    class FakeAggregateError(Exception):
        def __init__(self, errors, message=""):
            super().__init__(message)
            self.errors = errors
            self.message = message

    aggregate = FakeAggregateError([
        RuntimeError("first aggregate member"),
        "second aggregate member",
    ], "aggregate activation failure")

    def prepare(ctx):
        wrapper = RuntimeError("wrapped aggregate failure")
        wrapper.__cause__ = aggregate
        raise wrapper

    with pytest.raises(RuntimeError) as exc_info:
        await boot(NAME, os.path.join(d, "cordis.yml"), None, prepare)
    msg = str(exc_info.value)
    assert f"{NAME}: host preparation failed: wrapped aggregate failure" in msg
    assert "aggregate activation failure" in msg
    assert "first aggregate member" in msg
    assert "second aggregate member" in msg


@pytest.mark.asyncio
async def test_boot_reports_pending_real_loader_fiber_and_service_unresolved():
    d = tmp()
    with open(os.path.join(d, "waiting.mjs"), "w", encoding="utf-8") as f:
        f.write('export const inject = ["neverProvided"]\nexport function apply() {}\n')
    with open(os.path.join(d, "cordis.yml"), "w", encoding="utf-8") as f:
        f.write("- id: waiting\n  name: ./waiting.mjs\n")

    with pytest.raises(RuntimeError) as exc_info:
        await boot(NAME, os.path.join(d, "cordis.yml"))
    msg = str(exc_info.value)
    assert f"{NAME}: 1 entry did not activate" in msg
    assert "./waiting.mjs: pending (waiting for service: neverProvided)" in msg


# ---------------------------------------------------------------------------
# addHarnessSourceSection
# ---------------------------------------------------------------------------


SOURCE_ROOT = os.path.join(os.path.sep, "opt", "harness-src")
EXPECTED_SOURCE = (
    f"The DeepSeek Harness implementation checkout is at {SOURCE_ROOT}. "
    f"The checkout location and current working directory are separate values and may differ; "
    f"never infer the working directory from this path. Use pwd to determine the current working directory. "
    f"Use this checkout only to inspect or extend DSH itself."
)


@pytest.mark.asyncio
async def test_add_harness_source_section_distinguishes_source_path_from_workdir():
    ctx = Context()
    try:
        await ctx.plugin(SystemPrompt, {"persona": "You are a coding agent."})
        dispose = addHarnessSourceSection(ctx, SOURCE_ROOT)
        assert callable(dispose)

        system_prompt = ctx.get("systemPrompt")
        rendered = render_prompt(await system_prompt.assemble())
        assert EXPECTED_SOURCE in rendered

        identity_at = rendered.find("You are an AI agent powered by DeepSeek Harness.")
        source_at = rendered.find(EXPECTED_SOURCE)
        persona_at = rendered.find("You are a coding agent.")

        assert identity_at >= 0
        assert persona_at >= 0
        assert identity_at < source_at
        assert source_at < persona_at
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_add_harness_source_section_is_noop_when_no_system_prompt():
    ctx = Context()
    try:
        assert addHarnessSourceSection(ctx, SOURCE_ROOT) is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_add_harness_source_section_disposes_section_it_added():
    ctx = Context()
    try:
        await ctx.plugin(SystemPrompt, {})
        system_prompt = ctx.get("systemPrompt")
        dispose = addHarnessSourceSection(ctx, SOURCE_ROOT)
        assert callable(dispose)

        present = await system_prompt.assemble()
        assert any(section.get("name") == HARNESS_SOURCE_SECTION for section in present.get("sections", []))

        dispose()
        gone = await system_prompt.assemble()
        assert not any(section.get("name") == HARNESS_SOURCE_SECTION for section in gone.get("sections", []))
    finally:
        await ctx.fiber.dispose()
