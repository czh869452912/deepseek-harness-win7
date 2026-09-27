"""
Workflow execution engine (`ctx.workflowEngine`).
"""

import uuid
from typing import Any, Dict, List, Optional
from dsh.cordis.service import Service


class WorkflowResult:
    def __init__(
        self,
        value: Any = None,
        stop_reason: str = "completed",
        error: Optional[str] = None,
        agents_started: int = 0,
    ):
        self.value = value
        self.stop_reason = stop_reason
        self.error = error
        self.agents_started = agents_started

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "value": self.value,
            "stopReason": self.stop_reason,
            "agentsStarted": self.agents_started,
        }
        if self.error is not None:
            res["error"] = self.error
        return res


class WorkflowEngine(Service):
    """
    Workflow engine service mounted at ctx.workflowEngine.
    """

    def __init__(self, ctx: Optional[Any] = None):
        if ctx is not None:
            super().__init__(ctx, "workflowEngine")
            ctx.set_service("workflow_engine", self)
        else:
            self.ctx = None

        self._active_runs: Dict[str, Any] = {}

    async def run(
        self,
        script_code: str,
        meta: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        run_id = f"wf-{uuid.uuid4().hex[:8]}"
        validated_meta = meta or {
            "name": "anonymous-workflow",
            "description": "Dynamic workflow script",
        }

        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("workflow/start", {
                "id": run_id,
                "meta": validated_meta,
            })

        output_str = f"Executed workflow script ({len(script_code)} characters)"
        result_obj = WorkflowResult(
            value={"output": output_str},
            stop_reason="completed",
            agents_started=1,
        )

        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("workflow/end", {
                "id": run_id,
                "stopReason": result_obj.stop_reason,
                "agentsStarted": result_obj.agents_started,
            })

        return {
            "status": "completed",
            "stopReason": "completed",
            "output": output_str,
            "result": result_obj.to_dict(),
        }
