"""
Core Tools catalog, Tool execution inputs/results, and ToolsService registry.
"""

import asyncio
import inspect
import json
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.plugin import Plugin


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
        execution_mode: str = "exclusive",  # "parallel" | "exclusive"
        is_concurrency_safe: Optional[Callable[[Any], bool]] = None,
        present_call: Optional[Callable[[Dict[str, Any]], Any]] = None,
        present_result: Optional[Callable[[Any], Any]] = None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.is_concurrency_safe = is_concurrency_safe
        self.execution_mode = execution_mode if execution_mode in ("parallel", "exclusive") else "exclusive"
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
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if "ctx" in sig.parameters or has_var_kw:
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
        elif isinstance(raw, (dict, list)):
            text = json.dumps(raw, ensure_ascii=False, indent=2)
        else:
            text = str(raw)

        return cls(
            content=[{"type": "text", "text": text}],
            is_error=is_error,
            error=error_info,
        )


class ToolsService:
    """
    Core tool catalog and execution orchestration service (`ctx.tools`).
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._tools: Dict[str, Tool] = {}

    def register(
        self,
        tool_or_spec: Union[Tool, Dict[str, Any], str, None] = None,
        description: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        handler: Optional[Callable[..., Any]] = None,
        execution_mode: Optional[str] = None,
        is_concurrency_safe: Optional[Callable[[Any], bool]] = None,
        present_call: Optional[Callable[[Dict[str, Any]], Any]] = None,
        present_result: Optional[Callable[[Any], Any]] = None,
        name: Optional[str] = None,
    ) -> Callable[[], None]:
        """
        Register a tool. Accepts a Tool object, a dictionary specification, or positional/keyword parameters.
        Returns a disposer to unregister the tool.
        """
        spec_name = name or (tool_or_spec if isinstance(tool_or_spec, str) else None)
        if isinstance(tool_or_spec, Tool):
            tool = tool_or_spec
        elif isinstance(tool_or_spec, dict):
            t_name = tool_or_spec.get("name") or spec_name or ""
            t_desc = tool_or_spec.get("description", description or "")
            t_params = tool_or_spec.get("parameters", parameters or {})
            t_handler = tool_or_spec.get("execute") or tool_or_spec.get("handler") or handler
            t_safe = tool_or_spec.get("isConcurrencySafe") or tool_or_spec.get("is_concurrency_safe") or is_concurrency_safe
            t_mode = tool_or_spec.get("execution_mode") or execution_mode or ("parallel" if t_safe else "exclusive")
            t_pres_call = tool_or_spec.get("presentCall") or tool_or_spec.get("present_call") or present_call
            t_pres_res = tool_or_spec.get("presentResult") or tool_or_spec.get("present_result") or present_result
            tool = Tool(
                name=t_name,
                description=t_desc,
                parameters=t_params,
                handler=t_handler,
                execution_mode=t_mode,
                is_concurrency_safe=t_safe,
                present_call=t_pres_call,
                present_result=t_pres_res,
            )
        elif spec_name and (handler is not None or callable(tool_or_spec)):
            actual_handler = handler or (tool_or_spec if callable(tool_or_spec) else None)
            t_mode = execution_mode or ("parallel" if is_concurrency_safe else "exclusive")
            tool = Tool(
                name=spec_name,
                description=description or "",
                parameters=parameters or {},
                handler=actual_handler,
                execution_mode=t_mode,
                is_concurrency_safe=is_concurrency_safe,
                present_call=present_call,
                present_result=present_result,
            )
        else:
            raise ValueError(f"Invalid tool registration spec: {tool_or_spec}, name={name}")

        name_key = tool.name
        self._tools[name_key] = tool

        def disposer():
            if name_key in self._tools and self._tools[name_key] is tool:
                del self._tools[name_key]

        return disposer

    def register_tool(self, *args: Any, **kwargs: Any) -> Callable[[], None]:
        return self.register(*args, **kwargs)


    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def has(self, name: str) -> bool:
        return self.has_tool(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]

    def get_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]

    def execution_mode(self, exec_input: Union[ToolExecutionInput, Dict[str, Any], str], args: Optional[Dict[str, Any]] = None) -> Union[Dict[str, str], str]:
        if isinstance(exec_input, str):
            name = exec_input
            call_args = args or {}
        elif isinstance(exec_input, ToolExecutionInput):
            name = exec_input.name
            call_args = exec_input.arguments if isinstance(exec_input.arguments, dict) else {}
        elif isinstance(exec_input, dict):
            name = exec_input.get("name", "")
            call_args = exec_input.get("arguments", args or {})
        else:
            name = ""
            call_args = {}

        tool = self.get_tool(name)
        if not tool:
            return "exclusive" if isinstance(exec_input, str) else {"kind": "exclusive"}

        if tool.is_concurrency_safe is not None and callable(tool.is_concurrency_safe):
            try:
                res = tool.is_concurrency_safe(call_args)
                if res is True:
                    return "parallel" if isinstance(exec_input, str) else {"kind": "parallel"}
                return "exclusive" if isinstance(exec_input, str) else {"kind": "exclusive"}
            except Exception:
                return "exclusive" if isinstance(exec_input, str) else {"kind": "exclusive"}

        mode = tool.execution_mode if tool.execution_mode in ("parallel", "exclusive") else "exclusive"
        return mode if isinstance(exec_input, str) else {"kind": mode}

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


class ToolsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tools`: Registers core ToolsService on ctx.tools.
    """
    id = "tools"
    name = "@deepseek-ai/dsh-tools"

    def apply(self, ctx: Any) -> None:
        if not ctx.has("tools"):
            svc = ToolsService(ctx)
            ctx.set_service("tools", svc)


ToolRegistry = ToolsService
