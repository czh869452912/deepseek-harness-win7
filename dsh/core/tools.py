import asyncio
import inspect
import json
from typing import Any, Callable, Dict, List, Optional, Union


TOOL_ABORTED_BEFORE_DISPATCH = "TOOL_ABORTED_BEFORE_DISPATCH"
TOOL_RUNTIME_SCHEDULER = "TOOL_RUNTIME_SCHEDULER"
TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
TOOL_ARGS_INVALID = "TOOL_ARGS_INVALID"


class Tool:
    """
    Defines a tool callable by the LLM with execution mode and presentation hooks.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
        execution_mode: str = "parallel",  # "parallel" | "exclusive"
        present_call: Optional[Callable[[Dict[str, Any]], Any]] = None,
        present_result: Optional[Callable[[Any], Any]] = None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.execution_mode = execution_mode if execution_mode in ("parallel", "exclusive") else "parallel"
        self.present_call = present_call
        self.present_result = present_result

    def to_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
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


class ToolExecutionInput:
    """Represents a single tool invocation prepared for scheduling."""

    def __init__(
        self,
        call_id: str,
        name: str,
        arguments: Any,
        agent: Optional[Any] = None,
        signal: Optional[asyncio.Event] = None,
    ):
        self.call_id = call_id
        self.name = name
        self.arguments = arguments
        self.agent = agent
        self.signal = signal


class ToolExecutionResult:
    """Normalized result returned after tool execution."""

    def __init__(
        self,
        content: List[Dict[str, Any]],
        is_error: bool = False,
        error: Optional[Dict[str, Any]] = None,
        meta: Optional[Dict[str, Any]] = None,
        concludes_turn: bool = False,
        additional_contexts: Optional[List[Any]] = None,
    ):
        self.content = content
        self.is_error = is_error
        self.error = error
        self.meta = meta
        self.concludes_turn = concludes_turn
        self.additional_contexts = additional_contexts or []

    @classmethod
    def from_raw(cls, raw: Any, is_error: bool = False, error_info: Optional[Dict[str, Any]] = None) -> "ToolExecutionResult":
        if isinstance(raw, ToolExecutionResult):
            return raw
        if isinstance(raw, str):
            text = raw
        elif raw is None:
            text = ""
        else:
            try:
                text = json.dumps(raw, ensure_ascii=False, indent=2)
            except Exception:
                text = str(raw)
        return cls(
            content=[{"type": "text", "text": text}],
            is_error=is_error,
            error=error_info,
        )


class ToolsService:
    """
    Tool Registry & Execution Pipeline Service mounted at `ctx.tools`.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._tools: Dict[str, Tool] = {}
        self.presentation_mode: str = "native"  # "native" | "code" | "both"

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
        execution_mode: str = "parallel",
        present_call: Optional[Callable[[Dict[str, Any]], Any]] = None,
        present_result: Optional[Callable[[Any], Any]] = None,
    ) -> Callable[[], None]:
        """
        Register a tool. Returns disposer function.
        """
        tool = Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            execution_mode=execution_mode,
            present_call=present_call,
            present_result=present_result,
        )
        self._tools[name] = tool

        def disposer():
            if name in self._tools and self._tools[name] == tool:
                del self._tools[name]

        if hasattr(self.ctx, "effect"):
            self.ctx.effect(disposer)
        return disposer

    def register_tool(self, tool_def: Dict[str, Any]) -> Callable[[], None]:
        name = tool_def["name"]
        description = tool_def.get("description", "")
        parameters = tool_def.get("parameters", {})
        handler = tool_def.get("execute") or tool_def.get("handler")
        execution_mode = tool_def.get("execution_mode", tool_def.get("executionMode", "parallel"))
        present_call = tool_def.get("present_call")
        present_result = tool_def.get("present_result")
        return self.register(
            name,
            description,
            parameters,
            handler,
            execution_mode=execution_mode,
            present_call=present_call,
            present_result=present_result,
        )

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]

    def execution_mode(self, exec_input: Union[ToolExecutionInput, Dict[str, Any]]) -> Dict[str, str]:
        name = exec_input.name if isinstance(exec_input, ToolExecutionInput) else exec_input.get("name", "")
        tool = self.get_tool(name)
        mode = tool.execution_mode if tool else "parallel"
        return {"kind": mode}

    # Scheduler lifecycle hooks (1:1 with TOOL_RUNTIME_SCHEDULER)
    async def prepare(self, exec_input: ToolExecutionInput) -> Dict[str, Any]:
        """Runs pre-execute waterfall."""
        call_payload = {
            "call_id": exec_input.call_id,
            "name": exec_input.name,
            "arguments": exec_input.arguments,
            "agent": exec_input.agent,
        }
        modified = await self.ctx.waterfall("tools/pre-execute", call_payload)
        exec_input.name = modified.get("name", exec_input.name)
        exec_input.arguments = modified.get("arguments", exec_input.arguments)
        return {"kind": "dispatch", "exec": exec_input}

    async def dispatch(self, exec_input: ToolExecutionInput) -> Dict[str, Any]:
        """Invokes the underlying tool handler."""
        tool = self.get_tool(exec_input.name)
        if not tool:
            err_result = ToolExecutionResult.from_raw(
                f"Error: Tool '{exec_input.name}' not found in catalog",
                is_error=True,
                error_info={"name": "NotFoundError", "code": TOOL_NOT_FOUND},
            )
            return {"kind": "post-result", "result": err_result}

        args = exec_input.arguments if isinstance(exec_input.arguments, dict) else {}
        try:
            raw = await tool.execute(args, ctx=self.ctx)
            result = ToolExecutionResult.from_raw(raw)
            return {"kind": "post-result", "result": result}
        except Exception as e:
            err_result = ToolExecutionResult.from_raw(
                f"Error executing tool '{exec_input.name}': {str(e)}",
                is_error=True,
                error_info={"name": type(e).__name__, "message": str(e), "code": "TOOL_EXECUTION_ERROR"},
            )
            return {"kind": "post-result", "result": err_result}

    async def finalize(self, exec_input: ToolExecutionInput, result: ToolExecutionResult) -> ToolExecutionResult:
        """Runs post-execute waterfall."""
        payload = {
            "call_id": exec_input.call_id,
            "name": exec_input.name,
            "arguments": exec_input.arguments,
            "result": result,
        }
        res = await self.ctx.waterfall("tools/post-execute", payload)
        fin = res.get("result", result)
        return fin if isinstance(fin, ToolExecutionResult) else ToolExecutionResult.from_raw(fin)

    def finish(self, exec_input: ToolExecutionInput, result: ToolExecutionResult) -> ToolExecutionResult:
        return result

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Sequential single-tool helper with pre/post waterfall."""
        exec_input = ToolExecutionInput(
            call_id=f"call-{tool_name}",
            name=tool_name,
            arguments=arguments,
        )
        prep = await self.prepare(exec_input)
        disp = await self.dispatch(prep["exec"])
        final = await self.finalize(prep["exec"], disp["result"])
        if final.is_error:
            text = "".join(b.get("text", "") for b in final.content if b.get("type") == "text")
            return text or "Tool execution failed"
        text = "".join(b.get("text", "") for b in final.content if b.get("type") == "text")
        return text


ToolRegistry = ToolsService
