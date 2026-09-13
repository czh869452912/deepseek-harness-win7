"""
1:1 parity suite for the one-shot app's command-line provider
(`dsh/bundle/headless/startup.py`), the port of
`reference/packages/bundle/headless/src/startup.ts`.

Upstream is `packages/bundle/headless/tests/startup.spec.ts`: it mounts the REAL
provider over a real Loader tree plus a runner stand-in whose row config reads
`ctx.headlessStartup.task`, then observes the provider's service value, the
config the runner was released with, the process output, and the exit codes the
launcher received. The fixture mounts the tree through the same
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
from dsh.bundle.headless.startup import HEADLESS_STARTUP_SERVICE, HeadlessStartupValues
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader

NAME = "dsh"

RUNNER_PLUGIN_SOURCE = '''"""Runner stand-in: the row config the Loader resolves is its whole input."""

from dsh.cordis.plugin import Plugin


class RunnerPlugin(Plugin):
    """Records the config expressions resolved once the provider released it."""

    id = "headless-runner"
    inject = ["headlessStartup"]

    def apply(self, ctx):
        self.released = dict(self.config or {})
'''

CONFIG_ROWS = [
    "- id: headless-runner",
    "  name: {runner}:RunnerPlugin",
    f"  inject: [{HEADLESS_STARTUP_SERVICE}]",
    "  config:",
    "    task: !!js ctx.headlessStartup.task",
    "- id: headless-startup",
    "  name: '@deepseek-ai/dsh-headless/startup'",
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


async def boot_startup(
    args: List[str],
) -> Tuple[Optional[Any], Observed, Context, str]:
    """
    Mount the real provider and a runner stand-in using injection-ordered config.

    @param args: the invocation's inner arguments.
    @returns: the provider's service value, the observed runner/process
        effects, the booted context, and the fixture directory to remove.
    """
    directory = tempfile.mkdtemp(prefix="dsh-headless-startup-")
    runner = os.path.join(directory, "runner.py")
    with open(runner, "w", encoding="utf-8") as f:
        f.write(RUNNER_PLUGIN_SOURCE)
    config_path = os.path.join(directory, "cordis.yml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write("\n".join(row.replace("{runner}", runner.replace("\\", "/")) for row in CONFIG_ROWS))

    observed = Observed(args)
    internals.stdout = observed
    internals.stderr = observed
    ctx = Context()
    await ctx.plugin(Loader)
    install_harness_plugin_classes(ctx.get("loader"))
    provide_cmdline(ctx, {"args": args, "exit": lambda code: observed.exits.append(code)})
    await mount_root_include(ctx, config_path)
    await ctx.loader.await_()
    return ctx.get(HEADLESS_STARTUP_SERVICE), observed, ctx, directory


def runner_fiber(ctx: Context) -> Any:
    """The runner entry's fiber, so a case can assert it never activated."""
    for entry in ctx.loader.entries():
        if entry.options.get("id") == "headless-runner":
            assert entry.fiber is not None
            return entry.fiber
    raise AssertionError("the runner entry did not mount")


def runner_config(ctx: Context) -> Optional[Any]:
    """The config the Loader released the runner with, or None while pending."""
    fiber = runner_fiber(ctx)
    plugin = fiber.plugin
    return getattr(plugin, "released", None) if plugin is not None else None


@pytest.fixture(autouse=True)
def _restore_streams():
    out, err = internals.stdout, internals.stderr
    try:
        yield
    finally:
        internals.stdout, internals.stderr = out, err


# --- headless command-line provider --------------------------------------------


@pytest.mark.asyncio
async def test_joins_the_task_positional_into_the_runner_config():
    """"joins the task positional into the runner config"."""
    values, observed, ctx, directory = await boot_startup(["run", "the", "tests"])
    try:
        assert values == HeadlessStartupValues(task="run the tests")
        assert set(values.to_dict()) == {"task"}
        assert runner_config(ctx) == {"task": "run the tests"}
        assert observed.exits == []
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [[], ["   "]], ids=["no-arguments", "whitespace-only"])
async def test_rejects_an_invocation_with_no_non_whitespace_task(args):
    """"rejects an invocation with no non-whitespace task ($args)"."""
    values, observed, ctx, directory = await boot_startup(args)
    try:
        assert "a task is required" in observed.out
        assert values is None
        assert runner_config(ctx) is None
        assert runner_fiber(ctx).state == FiberState.PENDING
        assert observed.exits == [1]
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.asyncio
async def test_prints_its_own_help_and_leaves_the_runner_pending():
    """"prints its own help and leaves the runner pending"."""
    values, observed, ctx, directory = await boot_startup(["--help"])
    try:
        assert "dsh --profile headless" in observed.out
        assert "stream reasoning to stderr" in observed.out
        assert values is None
        assert runner_config(ctx) is None
        assert runner_fiber(ctx).state == FiberState.PENDING
        assert observed.exits == [0]
    finally:
        await ctx.fiber.dispose()
        shutil.rmtree(directory, ignore_errors=True)
