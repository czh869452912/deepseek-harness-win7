"""
Plugin `@deepseek-ai/dsh-tool-workflow`: Run orchestration workflows.
"""

import asyncio
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.workflow.workflow_service import WorkflowEngine


class ToolWorkflowPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-workflow`: Run orchestration workflows.
    """

    id = "tool-workflow"
    name = "@deepseek-ai/dsh-tool-workflow"
    inject = ["tools"]

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools") if ctx.has("tools") else None
        if not tools:
            return

        if not ctx.has("workflowEngine"):
            ctx.set_service("workflowEngine", WorkflowEngine(ctx))

        wf_engine: WorkflowEngine = ctx.get("workflowEngine")

        async def exec_workflow(script: str, meta: Optional[Dict[str, Any]] = None) -> str:
            res = await wf_engine.run(script, meta=meta)
            return f"Workflow result: {res.get('status', 'done')}\n{res.get('output', '')}"

        disposer = tools.register_tool({
            "name": "run_workflow",
            "description": "Execute a workflow script over the workflow engine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "Workflow script to execute"},
                    "meta": {"type": "object", "description": "Optional workflow metadata"},
                },
                "required": ["script"],
            },
            "execute": exec_workflow,
        })

        ctx.effect(disposer)
