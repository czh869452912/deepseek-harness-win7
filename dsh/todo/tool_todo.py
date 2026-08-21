"""
Task list tracking tool (`@deepseek-ai/dsh-tool-todo`).
Replaces wholesale on each call and appends `todo/write` event to session.
"""

from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.core.session import Session, SessionStore


VALID_STATUSES = {"pending", "in_progress", "completed"}

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


class ToolTodoPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-todo`: Defines model-facing todo_write tool.
    """

    id = "tool-todo"
    name = "@deepseek-ai/dsh-tool-todo"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.allow_parallel_in_progress = bool(self.config.get("allowParallelInProgress", True))

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

        async def exec_todo_write(todos: List[Dict[str, str]]) -> str:
            if not isinstance(todos, list):
                return "Error: invalid todos: payload must be a list"

            seen_contents = set()
            in_progress_count = 0
            pending_count = 0
            completed_count = 0
            canonical_todos: List[Dict[str, str]] = []

            for item in todos:
                if not isinstance(item, dict):
                    return "Error: invalid todo: each item must be an object"
                content = item.get("content", "").strip()
                status = item.get("status", "pending").lower()

                if not content:
                    return "Error: invalid todo: `content` must be a non-empty string"
                if content in seen_contents:
                    return f'Error: invalid todos: duplicate content "{content}"'
                seen_contents.add(content)

                if status not in VALID_STATUSES:
                    return f'Error: invalid todo status "{status}": must be pending, in_progress, or completed'

                if status == "pending":
                    pending_count += 1
                elif status == "in_progress":
                    in_progress_count += 1
                elif status == "completed":
                    completed_count += 1

                canonical_todos.append({"content": content, "status": status})

            if not self.allow_parallel_in_progress and in_progress_count > 1:
                return f"Error: invalid todos: at most one task may be in_progress (got {in_progress_count})"

            # Append todo/write event to session
            target_session = None
            agents_svc = ctx.get("agents")
            if agents_svc and hasattr(agents_svc, "current_initiator"):
                initiator = agents_svc.current_initiator()
                if initiator and hasattr(initiator, "session"):
                    target_session = initiator.session

            if not target_session:
                sessions_svc = ctx.get("sessions")
                if isinstance(sessions_svc, SessionStore):
                    target_session = sessions_svc.get("default-session")
                    if not target_session and sessions_svc._sessions:
                        target_session = next(iter(sessions_svc._sessions.values()))
                elif isinstance(sessions_svc, Session):
                    target_session = sessions_svc

            if target_session:
                target_session.append("todo/write", {"todos": canonical_todos}, ignorable=True)

            return f"Updated todo list: {pending_count} pending, {in_progress_count} in progress, {completed_count} completed."

        disposer = tools.register_tool({
            "name": "todo_write",
            "description": compose_todo_description(self.allow_parallel_in_progress),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string", "description": "The task to be done."},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "The current status of the task.",
                                },
                            },
                            "required": ["content", "status"],
                        },
                        "description": "The whole task list to set.",
                    }
                },
                "required": ["todos"],
            },
            "execute": exec_todo_write,
        })

        ctx.effect(disposer)

