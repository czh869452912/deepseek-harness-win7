"""
The one-shot app's command-line provider: it parses the task positional and
`--help`, then provides the resolved task as `headlessStartup`. The runner is an
ordinary consumer whose lazy config waits for that service.

Port of reference/packages/bundle/headless/src/startup.ts.
@module @deepseek-ai/dsh-headless/startup
"""

from typing import Any, Dict, List

from dsh.boot.cmdline import Command, parse_cmdline
from dsh.cordis.plugin import Plugin

__all__ = [
    "HeadlessStartupPlugin",
    "HeadlessStartupValues",
    "NAME",
    "HEADLESS_STARTUP_SERVICE",
    "headless_command",
    "apply",
]

# Stable Cordis plugin name.
NAME = "headless-startup"

# Service provided by this plugin and injected by the one-shot runner.
HEADLESS_STARTUP_SERVICE = "headlessStartup"


class HeadlessStartupValues:
    """
    What the runner row reads from `headlessStartup`.

    The invocation's task text is always present: an invocation without a
    non-whitespace task is a usage error, so nothing is provided at all.
    """

    __slots__ = ("task",)

    def __init__(self, task: str) -> None:
        self.task = task

    def to_dict(self) -> Dict[str, Any]:
        """This invocation's task as the plain object upstream publishes."""
        return {"task": self.task}

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, HeadlessStartupValues):
            return self.to_dict() == other.to_dict()
        if isinstance(other, dict):
            return self.to_dict() == other
        return NotImplemented

    def __ne__(self, other: Any) -> bool:
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __repr__(self) -> str:
        return "HeadlessStartupValues(%r)" % (self.to_dict(),)


def headless_command() -> Command:
    """
    This app's command: the task positional, its description, and its help text.

    @returns: a fresh program, so one process can parse more than once (tests).
    """
    return (
        Command()
        .name("dsh --profile headless")
        .description(
            "Answer one task, stream reasoning to stderr, print the final assistant message, and exit."
        )
        .helpOption("-h, --help", "show this help")
        .argument("[task...]", "the task text; multiple words are joined by spaces")
        .addHelpText(
            "after",
            '\nExamples:\n  dsh --profile headless "run the tests"     answer one task and exit\n',
        )
    )


def apply(ctx: Any) -> None:
    """
    Parse and provide the one-shot task as an ordinary Cordis service. The
    command's action publishes the task; a missing or whitespace-only task is a
    usage error, so on rejection (and on `--help`) nothing is provided.

    @param ctx: plugin context carrying the command line.
    """
    program = headless_command()

    def _action() -> None:
        task = " ".join(program.args)
        if task.strip() == "":
            program.error(
                'error: a task is required, for example: dsh --profile headless "run the tests"'
            )
        ctx.provide(HEADLESS_STARTUP_SERVICE, HeadlessStartupValues(task))

    program.action(_action)
    parse_cmdline(ctx, program)


class HeadlessStartupPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-headless/startup`: the one-shot command-line provider.
    """

    id = "headless-startup"
    name = "@deepseek-ai/dsh-headless/startup"
    inject = ["cmdlineArgs"]
    Config = None

    def apply(self, ctx: Any) -> None:  # type: ignore[override]
        apply(ctx)
