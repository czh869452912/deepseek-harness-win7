"""
Interactive user questions tool (`@deepseek-ai/dsh-tool-ask-user`).
Model-facing consumer of `ctx.userQuestions`.
Aligned 1:1 with official `@deepseek-ai/dsh-tool-ask-user`.
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

        async def exec_ask(args: Any = None, agent: Optional[Any] = None, signal: Optional[Any] = None, exec_input: Optional[Any] = None, **kwargs: Any) -> Any:
            if isinstance(args, dict):
                questions_arg = args.get("questions", [])
            elif "questions" in kwargs:
                questions_arg = kwargs["questions"]
            elif isinstance(args, list):
                questions_arg = args
            else:
                questions_arg = []

            effective_agent = agent or getattr(exec_input, "agent", None) or kwargs.get("agent")
            effective_signal = signal or getattr(exec_input, "signal", None) or kwargs.get("signal")

            user_questions_svc = ctx.get("userQuestions")
            if user_questions_svc and hasattr(user_questions_svc, "ask"):
                qs = []
                for q in questions_arg:
                    item = {"id": q["id"], "question": q["question"]}
                    if "header" in q:
                        item["header"] = q["header"]
                    if "options" in q:
                        item["options"] = q["options"]
                    if "multi_select" in q:
                        item["multiSelect"] = q["multi_select"]
                    qs.append(item)

                req: Dict[str, Any] = {"questions": qs}
                if effective_agent is not None:
                    req["agent"] = effective_agent
                if effective_signal is not None:
                    req["signal"] = effective_signal

                res = await user_questions_svc.ask(req)
                answers = res.get("answers", [])
                formatted = []
                for ans in answers:
                    item = {"id": ans["id"], "selected": list(ans.get("selected", []))}
                    if "custom" in ans and ans["custom"] is not None:
                        item["custom"] = ans["custom"]
                    formatted.append(item)
                return json.dumps({"answers": formatted}, ensure_ascii=False)

            if self.handler:
                res = self.handler(questions_arg)
                if hasattr(res, "__await__"):
                    res = await res
                if isinstance(res, str):
                    return res
                return json.dumps(res, ensure_ascii=False)

            answers = []
            for q in questions_arg:
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
            "description": (
                "Ask the user a concise question when you need confirmation, a choice, or missing information before proceeding. "
                "Send one or more questions, each with a stable id that will be echoed in the answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Stable id for this question; echoed in the answer."},
                                "question": {"type": "string", "description": "The specific question to ask the user."},
                                "header": {"type": "string", "description": "Optional short heading for the question."},
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

        if hasattr(ctx, "effect"):
            ctx.effect(disposer)
