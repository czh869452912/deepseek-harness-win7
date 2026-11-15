"""Native model-call provider; scheduling is shared with existing consumers."""
from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.core.tools import _json_snapshot
from dsh.core.tool_calls import execute_tool_batch


class NativeToolExecutor:
    def __init__(self, ctx: Any, max_parallel: Optional[Callable[[], int]] = None):
        self.ctx = ctx
        self.pipeline = ctx.get('tools')
        self.max_parallel = max_parallel or (lambda: 10)

    def describe(self, tools: List[Any]) -> Dict[str, Any]:
        return dict(schemas=[dict(name=tool.name, description=tool.description,
                                  parameters=_json_snapshot(tool.parameters)) for tool in tools])

    async def execute(self, input: Dict[str, Any]) -> Dict[str, Any]:
        return await execute_tool_batch(self.ctx, input, self.pipeline, self.max_parallel)


class NativeToolExecutorPlugin(Plugin):
    id = 'native-tool-executor'
    inject = ['tools']

    def apply(self, ctx: Any) -> None:
        ctx.tools.setExecutor(NativeToolExecutor(ctx))
