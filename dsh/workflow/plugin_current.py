"""Own the private Win7 JavaScript carrier for the current Workflow service."""
from dsh.cordis.plugin import Plugin
from dsh.javascript.runtime import JavaScriptRuntime
from dsh.workflow.ptc_engine import PtcWorkflowEngine


class CurrentWorkflowPtcPlugin(Plugin):
    inject = ['subagents', 'sandboxPolicy', 'workingDirectory']
    Config = PtcWorkflowEngine.Config

    def apply(self, ctx):
        if ctx.get('jsRuntime') is None:
            ctx.plugin(JavaScriptRuntime)
        ctx.plugin(PtcWorkflowEngine, self.config)
