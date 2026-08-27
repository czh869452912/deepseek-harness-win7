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
        tools = ctx.get("tools", None, strict=False)
        if tools is None:
            return

        wf_engine = ctx.get("workflowEngine", None, strict=False)
        if wf_engine is None:
            wf_engine = WorkflowEngine(ctx)

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

        ctx.effect(lambda: disposer)
