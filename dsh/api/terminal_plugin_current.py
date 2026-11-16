"""Own the Win7 screen carrier alongside the current browser controller."""
from dsh.api.terminal_controller_authorized import AuthorizedTerminalController
from dsh.cordis.plugin import Plugin
from dsh.javascript.runtime import JavaScriptRuntime
from dsh.terminal.screen_runtime import TerminalScreenRuntime


class CurrentTerminalControllerPlugin(Plugin):
    inject = ['subprocess', 'sandboxPolicy', 'workingDirectory', 'typert']
    Config = AuthorizedTerminalController.Config

    def apply(self, ctx):
        if ctx.get('jsRuntime') is None:
            ctx.plugin(JavaScriptRuntime)
        if ctx.get('terminalScreens') is None:
            ctx.plugin(TerminalScreenRuntime)
        ctx.plugin(AuthorizedTerminalController, self.config)
