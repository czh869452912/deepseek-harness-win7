"""Model-facing whole-list todo replacement tool."""

import json
from typing import Any, Dict, List, Optional, Set

from dsh.cordis.plugin import Plugin


name = "tool-todo"
inject = ["tools"]
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
    return DESCRIPTION_HEAD + (
        DESCRIPTION_PARALLEL if allow_parallel else DESCRIPTION_SINGLE
    ) + DESCRIPTION_TAIL


class Config:
    """Cordis config schema for the required deployment policy."""

    @staticmethod
    def validate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict) or "allowParallelInProgress" not in value:
            return {"issues": [{
                "path": ["allowParallelInProgress"],
                "message": "allowParallelInProgress missing required value",
            }]}
        policy = value["allowParallelInProgress"]
        if not isinstance(policy, bool):
            return {"issues": [{
                "path": ["allowParallelInProgress"],
                "message": "allowParallelInProgress expected boolean",
            }]}
        return {"value": {"allowParallelInProgress": policy}}


def _validate_config(value: Any) -> Dict[str, Any]:
    result = Config.validate(value)
    issues = result.get("issues")
    if issues:
        raise TypeError(issues[0]["message"])
    return result["value"]


def _todo_item_schema(with_descriptions: bool = False) -> Dict[str, Any]:
    content: Dict[str, Any] = {"type": "string"}
    status: Dict[str, Any] = {"type": "string", "enum": list(VALID_STATUSES)}
    if with_descriptions:
        content["description"] = "What the task is — a short imperative line."
        status["description"] = (
            "pending (not started) | in_progress (now) | completed (done)."
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"content": content, "status": status},
        "required": ["content", "status"],
    }


def _to_todo_list(raw: List[Dict[str, str]],
                  allow_parallel: bool) -> List[Dict[str, str]]:
    todos: List[Dict[str, str]] = []
    seen: Set[str] = set()
    active = 0
    for item in raw:
        content = item["content"].strip()
        if not content:
            raise ValueError("invalid todo: `content` must be a non-empty string")
        if content in seen:
            encoded = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
            raise ValueError("invalid todos: duplicate content %s" % encoded)
        seen.add(content)
        if item["status"] == "in_progress":
            active += 1
        todos.append({"content": content, "status": item["status"]})
    if not allow_parallel and active > 1:
        raise ValueError(
            "invalid todos: at most one task may be in_progress (got %d)" % active
        )
    return todos


def _projection_apply(state: Any, event: Any) -> Any:
    event_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
    if event_type == "todo/write":
        return data["todos"]
    if event_type == "turn/start":
        return None
    return state


def _install_projection(ctx: Any) -> None:
    projections = ctx.sessionProjections
    schema = {
        "anyOf": [
            {"type": "array", "items": _todo_item_schema()},
            {"type": "null"},
        ],
    }

    def setup() -> Any:
        return projections.register(
            key="todos",
            schema=schema,
            init=lambda: None,
            apply=_projection_apply,
            view=lambda state: state,
            state_version=2,
        )

    ctx.effect(setup, label="sessionProjections.register(todos)")


def _definition(allow_parallel: bool) -> Dict[str, Any]:
    parameters = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "todos": {
                "type": "array",
                "description": "The COMPLETE task list, replacing any previous list.",
                "items": _todo_item_schema(with_descriptions=True),
            },
        },
        "required": ["todos"],
    }
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "todos": {"type": "array", "items": _todo_item_schema()},
            "counts": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "pending": {"type": "integer"},
                    "inProgress": {"type": "integer"},
                    "completed": {"type": "integer"},
                },
                "required": ["pending", "inProgress", "completed"],
            },
        },
        "required": ["todos", "counts"],
    }

    async def execute(args: Dict[str, Any], execution: Any) -> Dict[str, Any]:
        todos = _to_todo_list(args["todos"], allow_parallel)
        agent = execution.agent
        session = getattr(agent, "session", None) if agent is not None else None
        if session is None or not hasattr(session, "append"):
            raise ValueError("todo_write requires an owning agent session")
        session.append("todo/write", {"todos": todos})

        def count(status: str) -> int:
            return sum(1 for todo in todos if todo["status"] == status)

        return {
            "todos": [dict(todo) for todo in todos],
            "counts": {
                "pending": count("pending"),
                "inProgress": count("in_progress"),
                "completed": count("completed"),
            },
        }

    def render(_args: Dict[str, Any], value: Dict[str, Any]) -> List[Dict[str, str]]:
        counts = value["counts"]
        return [{
            "type": "text",
            "text": (
                "Updated todo list: %d pending, %d in progress, %d completed."
                % (counts["pending"], counts["inProgress"], counts["completed"])
            ),
        }]

    return {
        "name": "todo_write",
        "description": compose_todo_description(allow_parallel),
        "parameters": parameters,
        "output": {"schema": output_schema, "render": render},
        "execute": execute,
        "presentCall": lambda args: {
            "card": "generic", "title": "Update todo list", "kind": "other",
            "rawInput": args["todos"],
        },
    }


def apply(ctx: Any, config: Dict[str, Any]) -> None:
    allow_parallel = _validate_config(config)["allowParallelInProgress"]
    ctx.inject(["sessionProjections"], _install_projection)
    ctx.tools.register(_definition(allow_parallel))


class ToolTodoPlugin(Plugin):
    """Compatibility class for the package's namespace-style plugin export."""

    id = "tool-todo"
    name = "@deepseek-ai/dsh-tool-todo"
    inject = inject
    Config = Config

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    def apply(self, ctx: Any) -> None:
        apply(ctx, self.config)


__all__ = [
    "Config", "ToolTodoPlugin", "apply", "compose_todo_description", "inject",
    "name",
]
