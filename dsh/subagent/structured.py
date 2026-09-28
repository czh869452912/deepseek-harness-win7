"""Child-local structured capture committed by the authoritative tool result."""
import weakref

from dsh.core.tools import ToolArgsError, _schema_violations
from dsh.core.system_prompt import FIRST_PARTY_SECTION_ORDER

INSTRUCTION = ('When you have your final answer, you MUST report it by calling the '
    '`structured_output` tool with arguments matching its parameter schema exactly. '
    'Do not finish with a plain text answer: only the tool call counts as your result.')


def attach_structured(child_ctx, schema):
    staged = weakref.WeakKeyDictionary()
    state = {"captured": None, "pending": None}
    async def execute(args, execution):
        violations = _schema_violations(args, schema, "arguments")
        if violations:
            raise ToolArgsError("structured_output", violations)
        staged[execution] = {"value": args}
        execution.concludeTurn()
        return {"recorded": True}
    child_ctx.get("tools").register({"name": "structured_output",
        "description": "Report your final structured result. Call this exactly once, when your answer is complete; the arguments must match this tool's parameter schema exactly.",
        "parameters": schema, "execute": execute,
        "output": {"schema": {"type": "object", "properties": {"recorded": {"type": "boolean", "const": True}}, "required": ["recorded"], "additionalProperties": False},
                   "render": lambda args, value: [{"type": "text", "text": "Structured output recorded."}]}})
    child_ctx.get("systemPrompt").section({"name": "tool:structured_output", "order": FIRST_PARTY_SECTION_ORDER["STRUCTURED_OUTPUT"], "text": INSTRUCTION})
    child_ctx.get("tools").guard(lambda execution: None if state["captured"] is None and state["pending"] is None
                                 else "structured output already recorded: the run is complete, so `{}` is not executed".format(execution.name))
    def result(execution, outcome):
        if execution.name == "structured_output":
            entry = staged.pop(execution, None)
            if entry is None or outcome.isError:
                return
            if execution.parent is None:
                if state["captured"] is None:
                    state["captured"] = entry
            elif state["captured"] is None and state["pending"] is None:
                state["pending"] = {"parent": execution.parent, "value": entry["value"]}
        elif state["pending"] is not None and state["pending"]["parent"] is execution.token:
            entry, state["pending"] = state["pending"], None
            if not outcome.isError and state["captured"] is None:
                state["captured"] = {"value": entry["value"]}
    child_ctx.on("tools/result", result)
    return state
