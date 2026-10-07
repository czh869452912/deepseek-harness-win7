"""Model-facing consumer of the injected user-questions service."""

import json
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin


class ToolAskUserPlugin(Plugin):
    id = "tool-ask-user"
    name = "@deepseek-ai/dsh-tool-ask-user"
    inject = ["tools", "userQuestions"]

    def apply(self, ctx: Any) -> None:
        async def execute(arguments: Dict[str, Any], execution: Optional[Any] = None,
                          agent: Optional[Any] = None, signal: Optional[Any] = None) -> Any:
            questions = []
            for question in arguments["questions"]:
                projected = {"id": question["id"], "question": question["question"]}
                for field in ("header", "options"):
                    if field in question:
                        projected[field] = question[field]
                if "multi_select" in question:
                    projected["multiSelect"] = question["multi_select"]
                questions.append(projected)
            request = {"questions": questions,
                       "signal": signal if signal is not None else getattr(execution, "signal", None)}
            caller = agent if agent is not None else getattr(execution, "agent", None)
            if caller is not None:
                request["agent"] = caller
            result = await ctx.userQuestions.ask(request)
            answers = []
            for answer in result["answers"]:
                projected = {"id": answer["id"], "selected": list(answer["selected"])}
                if "custom" in answer:
                    projected["custom"] = answer["custom"]
                answers.append(projected)
            return {"answers": answers}

        definition = {
            "name": "ask_user_question",
            "description": (
                "Ask the user a concise question when you need confirmation, a choice, or missing information before proceeding. "
                "Send one or more questions, each with a stable id that will be echoed in the answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "description": "Questions to ask the user before continuing.",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "id": {"type": "string", "description": "Stable id for this question; echoed in the answer."},
                                "question": {"type": "string", "description": "The specific question to ask the user."},
                                "header": {"type": "string", "description": 'Optional short heading for the question, such as "Confirm" or "Choose Mode".'},
                                "options": {
                                    "type": "array",
                                    "description": "Optional choices to show the user. If you recommend one, put it first and append \"(Recommended)\" to that label.",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": True,
                                        "properties": {
                                            "label": {"type": "string", "description": "Short user-facing option label."},
                                            "description": {"type": "string", "description": "One sentence explaining the tradeoff or impact."},
                                        },
                                        "required": ["label"],
                                    },
                                },
                                "multi_select": {"type": "boolean", "description": "Whether the user may select more than one option. Defaults to false."},
                            },
                            "required": ["id", "question"],
                        },
                    },
                },
                "required": ["questions"],
            },
            "output": {
                "schema": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "answers": {
                            "type": "array",
                            "items": {
                                "type": "object", "additionalProperties": False,
                                "properties": {
                                    "id": {"type": "string"},
                                    "selected": {"type": "array", "items": {"type": "string"}},
                                    "custom": {"type": "string"},
                                },
                                "required": ["id", "selected"],
                            },
                        },
                    },
                    "required": ["answers"],
                },
                "render": lambda _arguments, value: [{"type": "text", "text": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}],
            },
            "execute": execute,
        }
        disposer = ctx.tools.register(definition)
        ctx.disposable(disposer, label="tool_ask_user.unregister")
