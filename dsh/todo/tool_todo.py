"""
Task list tracking tool (`@deepseek-ai/dsh-tool-todo`).
Replaces wholesale on each call and appends `todo/write` event to session.
"""

import json
from typing import Any, Dict, List, Optional, Set
from dsh.cordis.plugin import Plugin
from dsh.core.session import Session, SessionStore


VALID_STATUSES = ("pending", "in_progress", "completed")

DESCRIPTION_HEAD = (
    "Record and update a structured task list for the current work. Send the ENTIRE "
    "list every call — it REPLACES the previous list (there are no partial updates, "
    "no per-item edits). Use it to plan multi-step work and show progress: add one "
    "todo per concrete step before you start. "
)

DESCRIPTION_PARALLEL = (
    "Mark every todo being actively worked "
    "on `in_progress` — several at once when work genuinely runs in parallel (e.g. "
    "concurrent subagents or background commands), one for sequential work; while "
    "work remains, at least one task should be `in_progress`. "
)

DESCRIPTION_SINGLE = (
    "Keep AT MOST ONE todo `in_progress` at a "
    "time; while work remains, exactly one active task should be `in_progress`. "
)

DESCRIPTION_TAIL = (
    "Mark a todo "
    "`completed` the moment it is done (do not batch completions), and allow no "
    "`in_progress` item only once all work is complete. Skip the list for trivial "
    "single-step tasks. Statuses: `pending` (not started), `in_progress` (being "
    "worked on now), `completed` (finished)."
)


def compose_todo_description(allow_parallel: bool) -> str:
    return DESCRIPTION_HEAD + (DESCRIPTION_PARALLEL if allow_parallel else DESCRIPTION_SINGLE) + DESCRIPTION_TAIL


def present_todo_call(args: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "card": "generic",
        "title": "Update todo list",
        "kind": "other",
        "rawInput": args.get("todos"),
    }


class ToolTodoPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-todo`: Defines model-facing todo_write tool.
    """

    id = "tool-todo"
    name = "@deepseek-ai/dsh-tool-todo"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        if "allowParallelInProgress" not in cfg:
            raise ValueError("tool-todo: allowParallelInProgress is required")
        self.allow_parallel_in_progress = bool(cfg.get("allowParallelInProgress"))

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        if not tools:
            return

        # Register session projection if sessionProjections seam exists
        if ctx.has("sessionProjections"):
            projections = ctx.get("sessionProjections")
            if hasattr(projections, "register"):
                def apply_todo_projection(state: Any, event: Any) -> Any:
                    evt_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", "")
                    evt_data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
                    if evt_type == "todo/write":
                        return evt_data.get("todos", [])
                    if evt_type == "turn/start":
                        return None
                    return state

                projections.register(
                    key="todos",
                    schema={"type": "array"},
                    init=lambda: None,
                    apply=apply_todo_projection,
                    view=lambda s: s,
                )

        parameters = {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The COMPLETE task list, replacing any previous list.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "What the task is — a short imperative line.",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "pending (not started) | in_progress (now) | completed (done).",
                            },
                        },
                        "required": ["content", "status"],
                    },
                }
            },
            "required": ["todos"],
        }

        async def exec_todo_write(
            args: Optional[Dict[str, Any]] = None,
            todos: Optional[List[Dict[str, str]]] = None,
            agent: Optional[Any] = None,
            exec_input: Optional[Any] = None,
            **kwargs: Any,
        ) -> Any:
            effective_agent = agent or getattr(exec_input, "agent", None) or kwargs.get("agent")
            if effective_agent is None:
                raise RuntimeError("todo_write requires an owning agent session")

            raw_todos = None
            if isinstance(args, dict):
                raw_todos = args.get("todos")
            elif todos is not None:
                raw_todos = todos
            elif "todos" in kwargs:
                raw_todos = kwargs["todos"]
            else:
                raw_todos = []

            if not isinstance(raw_todos, list):
                raise ValueError("invalid todos: payload must be a list")

            seen_contents: Set[str] = set()
            active_count = 0
            pending_count = 0
            completed_count = 0
            canonical_todos: List[Dict[str, str]] = []

            for item in raw_todos:
                if not isinstance(item, dict):
                    raise ValueError("invalid todo: each item must be an object")
                content = str(item.get("content", "")).strip()
                status = str(item.get("status", "pending")).lower()

                if not content:
                    raise ValueError("invalid todo: `content` must be a non-empty string")
                if content in seen_contents:
                    raise ValueError(f"invalid todos: duplicate content {json.dumps(content)}")
                seen_contents.add(content)

                if status not in VALID_STATUSES:
                    raise ValueError(f'invalid todo status "{status}": must be pending, in_progress, or completed')

                if status == "pending":
                    pending_count += 1
                elif status == "in_progress":
                    active_count += 1
                elif status == "completed":
                    completed_count += 1

                canonical_todos.append({"content": content, "status": status})

            if not self.allow_parallel_in_progress and active_count > 1:
                raise ValueError(f"invalid todos: at most one task may be in_progress (got {active_count})")

            session = getattr(effective_agent, "session", None)
            if session:
                session.append("todo/write", {"todos": canonical_todos})

            return f"Updated todo list: {pending_count} pending, {active_count} in progress, {completed_count} completed."

        disposer = tools.register_tool({
            "name": "todo_write",
            "description": compose_todo_description(self.allow_parallel_in_progress),
            "parameters": parameters,
            "execute": exec_todo_write,
            "presentCall": present_todo_call,
            "present_call": present_todo_call,
        })

        if hasattr(ctx, "effect"):
            ctx.effect(disposer)

