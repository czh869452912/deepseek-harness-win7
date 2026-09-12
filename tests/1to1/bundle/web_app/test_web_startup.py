"""
1:1 parity suite for the Web command-line provider
(`dsh/bundle/web_app/startup.py`), the port of
`reference/packages/bundle/web-app/src/startup.ts`.

Upstream is `packages/bundle/web-app/tests/startup.spec.ts`: it mounts the REAL
provider over a real Loader tree plus a consumer whose row config reads
`ctx.webStartup` directly, then observes the provider's service value, the
config the consumer was released with, the process output, and the exit codes
the launcher received. The fixture mounts the tree through the same
`cordis:include` entry and `parseCmdline` contract the shipped profiles use,
without the profile-level activation audit (upstream's fixture has none either).
"""

import os
import shutil
import tempfile
from typing import Any, List, Optional, Tuple

import pytest

from dsh.boot.app_boot import mount_root_include
from dsh.boot.cmdline import internals, provide_cmdline
from dsh.boot.plugin_registry import install_harness_plugin_classes
from dsh.bundle.web_app.startup import WEB_STARTUP_SERVICE, WebStartupValues
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader

NAME = "dsh"

READER_PLUGIN_SOURCE = '''"""Consumer fixture: the row config the Loader resolves is its whole input."""

from dsh.cordis.plugin import Plugin


class ReaderPlugin(Plugin):
    """Records the config expressions resolved once the provider released it."""

    id = "reader"
    inject = ["webStartup"]

    def apply(self, ctx):
        self.released = dict(self.config or {})
'''

CONFIG_ROWS = [
    "- id: reader",
    "  name: {reader}:ReaderPlugin",
    f"  inject: [{WEB_STARTUP_SERVICE}]",
    "  config:",
    "    host: !!js ctx.webStartup.host ?? '127.0.0.1'",
    "    openBrowser: !!js ctx.webStartup.openBrowser",
    "    port: !!js ctx.webStartup.port ?? 3080",
    "    trustedHosts: !!js ctx.webStartup.trustedHosts",
    "- id: provider",
    "  name: '@deepseek-ai/dsh-web-app/startup'",
    "",
]


class Observed:
    """What one fixture boot observed."""

    def __init__(self, args: List[str]) -> None:
        self.args = args
        self.exits: List[int] = []
        self.out = ""

    def write(self, chunk: str) -> bool:
        """Capture a process write the way the upstream suite captures streams."""
        self.out += chunk
        return True


async def boot_provider(args: List[str]) -> Tuple[Optional[Any], Observed, Context, str]:
    """
    Mount the real provider and a consumer using injection-ordered config.

    @param args: the invocation's inner arguments.
    @returns: the provider's service value, the observed consumer/process
        effects, the booted context, and the fixture directory to remove.
    """
    directory = tempfile.mkdtemp(prefix="dsh-web-startup-")
    reader = os.path.join(directory, "reader.py")
    with open(reader, "w", encoding="utf-8") as f:
        f.write(READER_PLUGIN_SOURCE)
    config_path = os.path.join(directory, "cordis.yml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write("\n".join(row.replace("{reader}", reader.replace("\\", "/")) for row in CONFIG_ROWS))

    observed = Observed(args)
    internals.stdout = observed
    internals.stderr = observed
    ctx = Context()
    await ctx.plugin(Loader)
    install_harness_plugin_classes(ctx.get("loader"))
    provide_cmdline(ctx, {"args": args, "exit": lambda code: observed.exits.append(code)})
    await mount_root_include(ctx, config_path)
    await ctx.loader.await_()
    return ctx.get(WEB_STARTUP_SERVICE), observed, ctx, directory


def reader_fiber(ctx: Context) -> Any:
    """The consumer entry's fiber, so a case can assert it never activated."""
    for entry in ctx.loader.entries():
        if entry.options.get("id") == "reader":
            assert entry.fiber is not None
            return entry.fiber
    raise AssertionError("the reader entry did not mount")


def reader_config(ctx: Context) -> Optional[Any]:
    """The config the Loader released the consumer with, or None while pending."""
    fiber = reader_fiber(ctx)
    plugin = fiber.plugin
    return getattr(plugin, "released", None) if plugin is not None else None


@pytest.fixture(autouse=True)
def _restore_streams():
    out, err = internals.stdout, internals.stderr
    try:
        yield
    finally:
        internals.stdout, internals.stderr = out, err


# --- web command-line provider -------------------------------------------------


@pytest.mark.asyncio
async def test_publishes_each_flag_and_releases_direct_service_expressions():
    """"publishes each flag and releases direct service expressions"."""
    values, observed, ctx, directory = await boot_provider(
        [
            "--host", "127.0.0.1",
            "--no-open",
            "--port", "8080",
            "--trusted-host", "lab.internal", "lab-2.internal",
            "--trusted-host", "10.0.0.9",
        ]
    )
    try:
        assert values == WebStartupValues(
            open_browser=False,
            host="127.0.0.1",
            port=8080,
            trusted_hosts=["lab.internal", "lab-2.internal", "10.0.0.9"],
        )
        assert reader_config(ctx) == {
            "host": "127.0.0.1",
            "openBrowser": False,
            "port": 8080,
            "trustedHosts": ["lab.internal", "lab-2.internal", "10.0.0.9"],
        }
        assert observed.exits == []
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.asyncio
async def test_leaves_deployment_values_to_each_consumer_when_flags_omit_them():
    """"leaves deployment values to each consumer when flags omit them"."""
    values, observed, ctx, directory = await boot_provider([])
    try:
        assert values == WebStartupValues(open_browser=True, host=None, port=None, trusted_hosts=[])
        assert reader_config(ctx) == {
            "host": "127.0.0.1",
            "openBrowser": True,
            "port": 3080,
            "trustedHosts": [],
        }
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.asyncio
async def test_prints_its_own_help_and_leaves_the_consumer_pending():
    """"prints its own help and leaves the consumer pending"."""
    values, observed, ctx, directory = await boot_provider(["--help"])
    try:
        assert "dsh --profile web" in observed.out
        assert "--no-open" in observed.out
        assert "--trusted-host" in observed.out
        assert values is None
        assert reader_config(ctx) is None
        assert reader_fiber(ctx).state == FiberState.PENDING
        assert observed.exits == [0]
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.asyncio
async def test_rejects_a_non_numeric_port_before_the_consumer_activates():
    """"rejects a non-numeric port before the consumer activates"."""
    values, observed, ctx, directory = await boot_provider(["--port", "abc"])
    try:
        assert "--port must be a number" in observed.out
        assert values is None
        assert reader_config(ctx) is None
        assert observed.exits == [1]
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.asyncio
async def test_rejects_the_unsupported_all_interfaces_host_before_the_consumer_activates():
    """"rejects the intentionally unsupported all-interfaces host before the consumer activates"."""
    values, observed, ctx, directory = await boot_provider(["--host", "0.0.0.0"])
    try:
        assert (
            "--host 0.0.0.0 is intentionally not supported yet for safety: it would expose "
            "remote code execution to the network; use 127.0.0.1 instead"
        ) in observed.out
        assert values is None
        assert reader_config(ctx) is None
        assert observed.exits == [1]
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory, ignore_errors=True)
