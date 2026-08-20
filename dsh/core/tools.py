import inspect
from typing import Any, Callable, Dict, List, Optional


class Tool:
    """
    Defines a tool callable by the LLM.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any]
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    def to_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

    async def execute(self, args: Dict[str, Any], ctx: Optional[Any] = None) -> Any:
        sig = inspect.signature(self.handler)
        if "ctx" in sig.parameters:
            res = self.handler(**args, ctx=ctx)
        else:
            res = self.handler(**args)

        if inspect.isawaitable(res):
            res = await res
        return res


class ToolsService:
    """
    Tools Service registered at `ctx.tools`.
    Manages tool definitions and execution pipeline.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._tools: Dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any]
    ) -> Callable[[], None]:
        """
        Register a tool. Returns disposer function.
        """
        tool = Tool(name, description, parameters, handler)
        self._tools[name] = tool

        def disposer():
            if name in self._tools and self._tools[name] == tool:
                del self._tools[name]

        if hasattr(self.ctx, 'effect'):
            self.ctx.effect(disposer)

    def register_tool(self, tool_def: Dict[str, Any]) -> Callable[[], None]:
        """
        Register a tool using dictionary definition.
        """
        name = tool_def["name"]
        description = tool_def.get("description", "")
        parameters = tool_def.get("parameters", {})
        handler = tool_def.get("execute") or tool_def.get("handler")
        return self.register(name, description, parameters, handler)

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Executes a tool with waterfall lifecycle events:
        tools/pre-execute -> tools/execute -> tools/post-execute
        """
        tool = self.get_tool(tool_name)
        if not tool:
            raise KeyError(f"Tool '{tool_name}' not found in registry")

        call_payload = {
            "name": tool_name,
            "arguments": arguments
        }

        # Event: tools/pre-execute (listeners can modify call_payload or validate arguments)
        call_payload = await self.ctx.waterfall("tools/pre-execute", call_payload)

        try:
            raw_result = await tool.execute(call_payload["arguments"], ctx=self.ctx)
            result_payload = {
                "name": tool_name,
                "arguments": call_payload["arguments"],
                "result": raw_result,
                "error": None
            }
        except Exception as e:
            result_payload = {
                "name": tool_name,
                "arguments": call_payload["arguments"],
                "result": None,
                "error": str(e)
            }

        # Event: tools/post-execute (listeners can format or record result)
        result_payload = await self.ctx.waterfall("tools/post-execute", result_payload)

        if result_payload.get("error"):
            return f"Error executing tool '{tool_name}': {result_payload['error']}"

        return result_payload.get("result")
