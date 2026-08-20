"""
Interactive user questions tool (`@deepseek-ai/dsh-tool-ask-user`).
"""

import json
from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class ToolAskUserPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-ask-user`: Defines model-facing ask_user_question tool.
    """

    id = "tool-ask-user"
    name = "@deepseek-ai/dsh-tool-ask-user"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.handler: Optional[Callable[[List[Dict[str, Any]]], Any]] = None

    def apply(self, ctx: Any) -> None:
        tools = ctx.get("tools")
        if not tools:
            return

        async def exec_ask(questions: List[Dict[str, Any]]) -> str:
            if self.handler:
                res = self.handler(questions)
                if hasattr(res, "__await__"):
                    res = await res
                if isinstance(res, str):
                    return res
                return json.dumps(res, ensure_ascii=False)

            answers = []
            for q in questions:
                qid = q.get("id", "q1")
                opts = q.get("options", [])
                selected = [opts[0]["label"]] if opts else []
                answers.append({
                    "id": qid,
                    "selected": selected,
                    "custom": None,
                })

            return json.dumps({"answers": answers}, ensure_ascii=False)

        disposer = tools.register_tool({
            "name": "ask_user_question",
            "description": "Ask the user one or more clarifying or design questions when ambiguous intent or critical decisions arise.",
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Stable unique ID for the question"},
                                "question": {"type": "string", "description": "Question text"},
                                "header": {"type": "string", "description": "Optional short header title"},
                                "options": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {"type": "string"},
                                            "description": {"type": "string"},
                                        },
                                        "required": ["label"],
                                    },
                                },
                                "multi_select": {"type": "boolean"},
                            },
                            "required": ["id", "question"],
                        },
                    }
                },
                "required": ["questions"],
            },
            "execute": exec_ask,
        })

        ctx.effect(disposer)
