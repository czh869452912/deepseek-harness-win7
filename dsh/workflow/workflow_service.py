from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class WorkflowEngine:
    """
    Workflow engine service mounted at ctx.workflowEngine.
    """

    def __init__(self, ctx: Optional[Any] = None):
        self.ctx = ctx

    async def run(self, script_code: str) -> Dict[str, Any]:
        return {
            "status": "completed",
            "output": f"Executed workflow script ({len(script_code)} characters)",
        }
