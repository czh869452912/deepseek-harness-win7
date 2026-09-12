"""
The web app's command-line provider: it parses the `dsh --profile web` flag
family (`--host`, `--port`, `--trusted-host`, `--no-open`) and its `--help`
text, then provides the immutable values as `webStartup`. Ordinary rows inject
that service before reading it from lazy config.

Port of reference/packages/bundle/web-app/src/startup.ts.
@module @deepseek-ai/dsh-web-app/startup
"""

import json
import re
from typing import Any, Dict, List, Optional

from dsh.boot.cmdline import Command, parse_cmdline
from dsh.cordis.plugin import Plugin

__all__ = [
    "WebStartupPlugin",
    "WebStartupValues",
    "NAME",
    "WEB_STARTUP_SERVICE",
    "web_command",
    "apply",
]

# Stable Cordis plugin name.
NAME = "web-startup"

# Service provided by this ordinary plugin and injected by flag-configured rows.
WEB_STARTUP_SERVICE = "webStartup"


class WebStartupValues:
    """
    What the web rows read from `webStartup`.

    An invocation publishes only the flags it named: `host` and `port` stay
    absent until an invocation names them, while `openBrowser` and
    `trustedHosts` always carry a value.
    """

    __slots__ = ("openBrowser", "host", "port", "trustedHosts")

    def __init__(
        self,
        open_browser: bool,
        host: Optional[str] = None,
        port: Optional[int] = None,
        trusted_hosts: Optional[List[str]] = None,
    ) -> None:
        self.openBrowser = open_browser
        self.host = host
        self.port = port
        self.trustedHosts = list(trusted_hosts or [])

    def to_dict(self) -> Dict[str, Any]:
        """This invocation's flags as the plain object upstream publishes."""
        values: Dict[str, Any] = {"openBrowser": self.openBrowser}
        if self.host is not None:
            values["host"] = self.host
        if self.port is not None:
            values["port"] = self.port
        values["trustedHosts"] = list(self.trustedHosts)
        return values

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, WebStartupValues):
            return self.to_dict() == other.to_dict()
        if isinstance(other, dict):
            return self.to_dict() == other
        return NotImplemented

    def __ne__(self, other: Any) -> bool:
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __repr__(self) -> str:
        return "WebStartupValues(%r)" % (self.to_dict(),)


def web_command() -> Command:
    """
    This app's command: its flags, its description, and its help text.

    @returns: a fresh program, so one process can parse more than once (tests).
    """
    return (
        Command()
        .name("dsh --profile web")
        .description("Serve the DeepSeek Harness browser UI.")
        .helpOption("-h, --help", "show this help")
        .option("--host <host>", "bind host")
        .option("--no-open", "do not open the Web UI in the default browser")
        .option("--port <port>", "listen port; pass 0 to let the OS pick a free one")
        .option(
            "--trusted-host <authority...>",
            "extra authority the /api browser-trust fence accepts (host or host:port; repeatable)",
        )
        .addHelpText(
            "after",
            "\nExamples:\n"
            "  dsh --profile web                          serve on the composed host and port\n"
            "  dsh --profile web --no-open                serve without opening a browser\n"
            "  dsh --profile web --port 8080              serve on another port\n",
        )
    )


def apply(ctx: Any) -> None:
    """
    Parse and provide the Web invocation as an ordinary Cordis service. The
    command's action publishes the flags this invocation named; `--host 0.0.0.0`
    or a non-numeric `--port` is a usage error, so on rejection (and on `--help`)
    nothing is provided.

    @param ctx: plugin context carrying the command line.
    """
    program = web_command()

    def _action() -> None:
        options = program.opts()
        if options.get("host") == "0.0.0.0":
            program.error(
                "error: --host 0.0.0.0 is intentionally not supported yet for safety: "
                "it would expose remote code execution to the network; use 127.0.0.1 instead"
            )
        port = options.get("port")
        if port is not None and not re.match(r"^\d+$", str(port)):
            program.error("error: --port must be a number, got %s" % json.dumps(port))
        ctx.provide(
            WEB_STARTUP_SERVICE,
            WebStartupValues(
                open_browser=bool(options.get("open")),
                host=options.get("host"),
                port=int(port) if port is not None else None,
                trusted_hosts=options.get("trustedHost") or [],
            ),
        )

    program.action(_action)
    parse_cmdline(ctx, program)


class WebStartupPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-web-app/startup`: the web command-line provider.
    """

    id = "web-startup"
    name = "@deepseek-ai/dsh-web-app/startup"
    inject = ["cmdlineArgs"]
    Config = None

    def apply(self, ctx: Any) -> None:  # type: ignore[override]
        apply(ctx)
