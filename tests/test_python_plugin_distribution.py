"""Actual local/ZIP install, canonical boot and reversible Cordis registrations."""

import asyncio
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import zipfile

import pytest

from apps.cli import plugin as plugin_cli
from dsh.boot.profile import init_profile, read_profile_manifest
from dsh.boot.profile_boot import run_profile
from dsh.boot.profile_lease import ProfileLease
from dsh.boot.python_package import import_package
from dsh.boot import python_plugins as installer
from dsh.core.tools import ToolExecutionInput

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "python-echo"
PACKAGE = "@example/python-echo"


@pytest.fixture
def profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("DSH_HOME", str(home))
    directory = home / "profiles" / "python-test"
    init_profile(str(directory), [], "startup")
    (directory / "cordis.patch.yml").write_text(
        "- insert:\n    - id: system-prompt\n      name: '@deepseek-ai/dsh-system-prompt'\n    - id: tools\n      name: '@deepseek-ai/dsh-tools'\n", encoding="utf-8")
    real_which = shutil.which
    monkeypatch.setattr(plugin_cli.shutil, "which", lambda name, *args, **kwargs:
                        None if name in ("pnpm", "node") else real_which(name, *args, **kwargs))
    return home, directory


def zip_package(path, wrapped=False):
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as archive:
        for file in EXAMPLE.rglob("*"):
            if file.is_file() and "__pycache__" not in file.parts:
                relative = file.relative_to(EXAMPLE).as_posix()
                archive.write(str(file), ("python-echo/" if wrapped else "") + relative)


async def boot(home):
    return await run_profile(dict(profile="python-test", dshHome=str(home), args=[], wait_for_exit=False))


async def close(result):
    await result["ctx"].fiber.dispose()
    await result["ctx"].fiber.await_settled()
    await asyncio.sleep(0)


async def echo(ctx, text="hello"):
    result = await ctx.get("tools").execute(ToolExecutionInput("echo-call", "python_echo", {"text": text}, signal=asyncio.Event()))
    assert not result.is_error
    return result.value


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["directory", "zip", "wrapped-zip"])
async def test_install_boot_execute_unload_remove_reinstall_restart(profile, tmp_path, source_kind):
    home, directory = profile
    source = EXAMPLE
    if source_kind != "directory":
        source = tmp_path / "echo.zip"
        zip_package(source, wrapped=source_kind == "wrapped-zip")
    before_path = list(sys.path)
    assert plugin_cli.run_plugin("python-test", ["add", str(source)]) == 0
    installed = directory / "node_modules" / "@example" / "python-echo"
    assert read_profile_manifest("dsh", str(directory))["dsh"]["profile"]["bundles"] == [PACKAGE]
    assert (installed / "python" / "echo" / "plugin.py").is_file()
    result = await boot(home)
    ctx = result["ctx"]
    try:
        assert await echo(ctx) == "Python echo: hello"
        assert list(sys.path) == before_path
        with pytest.raises(RuntimeError, match="profile is in use"):
            plugin_cli.run_plugin("python-test", ["remove", PACKAGE])
        entry = next(entry for entry in ctx.loader.entries if entry.options.get("id") == "example-python-echo")
        await entry.fiber.dispose()
        await entry.fiber.await_settled()
        missing = await ctx.get("tools").execute(ToolExecutionInput("after-unload", "python_echo", {"text": "gone"}, signal=asyncio.Event()))
        assert missing.is_error and missing.error["info"]["code"] == "UNKNOWN_TOOL"
    finally:
        await close(result)
    assert plugin_cli.run_plugin("python-test", ["remove", PACKAGE]) == 0
    assert not installed.exists()
    assert read_profile_manifest("dsh", str(directory))["dsh"]["profile"]["bundles"] == []
    assert plugin_cli.run_plugin("python-test", ["add", str(source)]) == 0
    restarted = await boot(home)
    try:
        assert await echo(restarted["ctx"], "restart") == "Python echo: restart"
    finally:
        await close(restarted)


@pytest.mark.parametrize("mutation, message", [
    (lambda manifest: manifest["dsh"]["python"].update(apiVersion=2), "API version"),
    (lambda manifest: manifest["dsh"]["python"].update(minPythonVersion=[99, 0, 0]), "Python version"),
    (lambda manifest: manifest["dsh"]["python"].update(minHostVersion=[99, 0, 0]), "host version"),
    (lambda manifest: manifest["dsh"]["python"].update(dependencies=["requests"]), "dependencies"),
    (lambda manifest: manifest["dsh"]["python"].update(sourceRoot="../escape"), "invalid package path"),
    (lambda manifest: manifest["dsh"]["python"].update(entry="echo.missing:Missing"), "entry module"),
    (lambda manifest: manifest["dsh"]["bundle"].update(patch="missing.yml"), "patch is missing"),
    (lambda manifest: manifest.update(name="@deepseek-ai/dsh-tools"), "identities"),
])
def test_validation_failure_preserves_profile(profile, tmp_path, mutation, message):
    _, directory = profile
    source = tmp_path / "source"
    shutil.copytree(str(EXAMPLE), str(source))
    path = source / "package.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutation(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = (directory / "package.json").read_bytes()
    with pytest.raises(ValueError, match=message):
        plugin_cli.run_plugin("python-test", ["add", str(source)])
    assert (directory / "package.json").read_bytes() == before
    assert not (directory / installer.JOURNAL).exists()


@pytest.mark.parametrize("filename", ["../escape.py", "/absolute.py", "C:/escape.py", "CON.py", "bad\\path.py", "bad./file.py"])
def test_zip_paths_cannot_escape_or_alias_windows_files(profile, tmp_path, filename):
    _, directory = profile
    source = tmp_path / "bad.zip"
    with zipfile.ZipFile(str(source), "w") as archive:
        entry = zipfile.ZipInfo("placeholder")
        entry.filename = filename
        archive.writestr(entry, "pass")
    before = (directory / "package.json").read_bytes()
    with pytest.raises(ValueError):
        plugin_cli.run_plugin("python-test", ["add", str(source)])
    assert (directory / "package.json").read_bytes() == before
    assert not (tmp_path / "escape.py").exists()


def test_zip_rejects_links_and_case_collisions(profile, tmp_path):
    for kind in ("link", "duplicate"):
        source = tmp_path / (kind + ".zip")
        with zipfile.ZipFile(str(source), "w") as archive:
            if kind == "link":
                entry = zipfile.ZipInfo("link")
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(entry, "../outside")
            else:
                archive.writestr("A.py", "pass")
                archive.writestr("a.py", "pass")
        with pytest.raises(ValueError, match="duplicate|nonregular"):
            plugin_cli.run_plugin("python-test", ["add", str(source)])


def test_install_never_executes_package_code_and_rejects_syntax(profile, tmp_path):
    _, directory = profile
    source = tmp_path / "source"
    shutil.copytree(str(EXAMPLE), str(source))
    code = source / "python" / "echo" / "plugin.py"
    code.write_text("raise RuntimeError('must not import during installation')\n", encoding="utf-8")
    assert plugin_cli.run_plugin("python-test", ["add", str(source)]) == 0
    plugin_cli.run_plugin("python-test", ["remove", PACKAGE])
    code.write_text("async def broken(:\n", encoding="utf-8")
    before = (directory / "package.json").read_bytes()
    with pytest.raises(ValueError, match="invalid Python syntax"):
        plugin_cli.run_plugin("python-test", ["add", str(source)])
    assert (directory / "package.json").read_bytes() == before


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_manifest_publication_failure_rolls_back_files_and_profile(profile, monkeypatch, operation):
    _, directory = profile
    if operation == "remove":
        plugin_cli.run_plugin("python-test", ["add", str(EXAMPLE)])
    before = (directory / "package.json").read_bytes()
    real = installer.atomic_bytes

    def fail(path, data):
        if path == str(directory / "package.json"):
            raise OSError("injected publication failure")
        return real(path, data)

    monkeypatch.setattr(installer, "atomic_bytes", fail)
    with pytest.raises(OSError, match="publication failure"):
        plugin_cli.run_plugin("python-test", [operation, str(EXAMPLE) if operation == "add" else PACKAGE])
    assert (directory / "package.json").read_bytes() == before
    assert (directory / "node_modules" / "@example" / "python-echo").exists() == (operation == "remove")
    assert not (directory / installer.JOURNAL).exists()


def test_uninstall_preserves_changed_source_and_user_patch(profile):
    _, directory = profile
    patch = (directory / "cordis.patch.yml").read_bytes()
    plugin_cli.run_plugin("python-test", ["add", str(EXAMPLE)])
    source = directory / "node_modules" / "@example" / "python-echo" / "python" / "echo" / "plugin.py"
    source.write_text("# user changes\n", encoding="utf-8")
    before = (directory / "package.json").read_bytes()
    with pytest.raises(ValueError, match="files changed"):
        plugin_cli.run_plugin("python-test", ["remove", PACKAGE])
    assert (directory / "package.json").read_bytes() == before
    assert (directory / "cordis.patch.yml").read_bytes() == patch
    assert source.read_text(encoding="utf-8") == "# user changes\n"


def test_os_lease_blocks_other_process_and_releases_after_close(profile):
    _, directory = profile
    command = [sys.executable, "-c", "from dsh.boot.profile_lease import ProfileLease; import sys; "
               "lease = ProfileLease(sys.argv[1], exclusive=True)", str(directory)]
    with ProfileLease(str(directory)):
        with ProfileLease(str(directory)):
            result = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)
            assert result.returncode != 0 and "profile is in use" in result.stderr
    assert subprocess.run(command, cwd=str(ROOT), capture_output=True).returncode == 0


def test_failed_python_import_cleans_private_namespace(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(str(EXAMPLE), str(source))
    code = source / "python" / "echo" / "plugin.py"
    code.write_text("from . import formatting\nraise RuntimeError('broken plugin')\n", encoding="utf-8")
    before = set(sys.modules)
    with pytest.raises(RuntimeError, match="broken plugin"):
        import_package(str(source))
    assert not any(name.startswith("_dsh_python_") for name in set(sys.modules) - before)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation, committed", [("add", False), ("remove", False), ("add", True), ("remove", True)])
async def test_real_process_interruption_recovers_at_canonical_boot(profile, operation, committed):
    home, directory = profile
    if operation == "remove":
        plugin_cli.run_plugin("python-test", ["add", str(EXAMPLE)])
    code = """
import os, sys
from dsh.boot import python_plugins as installer
from dsh.boot.profile_boot import INSTALL_ANCHOR
real = installer.atomic_bytes
def interrupt(path, data):
    if os.path.basename(path) == 'package.json':
        if sys.argv[3] == 'committed':
            real(path, data)
        os._exit(37)
    real(path, data)
installer.atomic_bytes = interrupt
if sys.argv[2] == 'add':
    installer.install(sys.argv[1], sys.argv[4], INSTALL_ANCHOR)
else:
    installer.uninstall(sys.argv[1], sys.argv[4])
"""
    child = subprocess.run([sys.executable, "-c", code, str(directory), operation,
                            "committed" if committed else "pending",
                            str(EXAMPLE) if operation == "add" else PACKAGE], cwd=str(ROOT), capture_output=True)
    assert child.returncode == 37, child.stderr
    assert (directory / installer.JOURNAL).is_file()
    result = await boot(home)
    installed = (operation == "add") == committed
    try:
        if installed:
            assert await echo(result["ctx"], "recovered") == "Python echo: recovered"
        else:
            missing = await result["ctx"].get("tools").execute(
                ToolExecutionInput("missing", "python_echo", {"text": "gone"}, signal=asyncio.Event()))
            assert missing.is_error and missing.error["info"]["code"] == "UNKNOWN_TOOL"
        assert not (directory / installer.JOURNAL).exists()
    finally:
        await close(result)


@pytest.mark.asyncio
async def test_changed_reinstallation_does_not_reuse_old_module(profile, tmp_path):
    home, directory = profile
    source = tmp_path / "source"
    shutil.copytree(str(EXAMPLE), str(source))
    plugin_cli.run_plugin("python-test", ["add", str(source)])
    first = await boot(home)
    try:
        assert await echo(first["ctx"]) == "Python echo: hello"
    finally:
        await close(first)
    plugin_cli.run_plugin("python-test", ["remove", PACKAGE])
    (source / "python" / "echo" / "formatting.py").write_text(
        'def format_echo(text):\n    return "Changed echo: " + text\n', encoding="utf-8")
    plugin_cli.run_plugin("python-test", ["add", str(source)])
    second = await boot(home)
    try:
        assert await echo(second["ctx"]) == "Changed echo: hello"
    finally:
        await close(second)


@pytest.mark.asyncio
async def test_host_lock_is_retained_while_async_cleanup_drains(profile):
    home, directory = profile
    plugin_cli.run_plugin("python-test", ["add", str(EXAMPLE)])
    result = await boot(home)
    started, finish = asyncio.Event(), asyncio.Event()

    async def dispose():
        started.set()
        await finish.wait()

    result["ctx"].disposable(dispose)
    closing = asyncio.create_task(close(result))
    await started.wait()
    try:
        with pytest.raises(RuntimeError, match="profile is in use"):
            plugin_cli.run_plugin("python-test", ["remove", PACKAGE])
    finally:
        finish.set()
        await closing
    assert plugin_cli.run_plugin("python-test", ["remove", PACKAGE]) == 0


def test_plain_dependency_commands_remain_pnpm_and_hold_profile_lease(profile, monkeypatch):
    _, directory = profile
    called = []
    monkeypatch.setattr(plugin_cli.shutil, "which", lambda _: "pnpm")

    def pnpm(command, cwd):
        called.append((command, cwd))
        with pytest.raises(RuntimeError, match="profile is in use"):
            ProfileLease(cwd, exclusive=True)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(plugin_cli.subprocess, "run", pnpm)
    assert plugin_cli.run_plugin("python-test", ["why", "plain-dependency"]) == 0
    assert called == [(["pnpm", "why", "plain-dependency"], str(directory))]


def test_python_descriptor_failure_never_falls_back_to_js_mock(profile, monkeypatch):
    from dsh.cordis.context import Context
    from dsh.cordis import loader as loader_module

    _, directory = profile
    plugin_cli.run_plugin("python-test", ["add", str(EXAMPLE)])
    package = directory / "node_modules" / "@example" / "python-echo"
    manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
    manifest["main"] = "fallback.js"
    manifest["dsh"]["python"]["entry"] = "missing:Missing"
    (package / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (package / "fallback.js").write_text("export default {}", encoding="utf-8")
    monkeypatch.setattr(loader_module, "create_js_mock_plugin", lambda *args: pytest.fail("JS mock fallback"))
    ctx = Context()
    loader = loader_module.Loader(ctx)
    loader.base_url = str(directory)
    with pytest.raises(ValueError, match="entry module"):
        loader.import_plugin(PACKAGE)


def test_pnpm_cannot_overwrite_managed_python_snapshots(profile):
    plugin_cli.run_plugin("python-test", ["add", str(EXAMPLE)])
    with pytest.raises(ValueError, match="pnpm mutations"):
        plugin_cli.run_plugin("python-test", ["remove", PACKAGE, "--force"])


@pytest.mark.asyncio
async def test_example_installs_and_executes_in_real_web_profile(profile, monkeypatch):
    home, directory = profile
    monkeypatch.setenv("DSH_TELEMETRY_MODE", "DISABLED")
    assert plugin_cli.run_plugin("web", ["add", str(EXAMPLE)]) == 0
    result = await run_profile(dict(profile="web", dshHome=str(home),
                                    args=["--no-open", "--port", "0"], waitForExit=False))
    try:
        assert result["ctx"].get("webServer").port > 0
        assert await echo(result["ctx"], "web") == "Python echo: web"
        assert result["ctx"].get("connection") is not None
    finally:
        await close(result)
    assert plugin_cli.run_plugin("web", ["remove", PACKAGE]) == 0


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_external_profile_edit_during_prepare_is_preserved(profile, monkeypatch, operation):
    _, directory = profile
    if operation == "remove":
        plugin_cli.run_plugin("python-test", ["add", str(EXAMPLE)])
    original = installer.read_profile_manifest

    def edit(bin_name, directory_path):
        value = original(bin_name, directory_path)
        updated = dict(value, userEdit="preserve")
        (Path(directory_path) / "package.json").write_text(json.dumps(updated), encoding="utf-8")
        return value

    monkeypatch.setattr(installer, "read_profile_manifest", edit)
    with pytest.raises(RuntimeError, match="profile changed"):
        plugin_cli.run_plugin("python-test", [operation, str(EXAMPLE) if operation == "add" else PACKAGE])
    assert read_profile_manifest("dsh", str(directory))["userEdit"] == "preserve"
    assert not (directory / installer.JOURNAL).exists()
    assert (directory / "node_modules" / "@example" / "python-echo").exists() == (operation == "remove")
