"""Model-facing consumer of the injected user-questions service."""

import json
import math
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.json_text import stringify_json
from dsh.jobs.pump import field


SKIPPED_GUIDANCE = ('An answer item with empty selected and no custom means the user skipped that question: '
    'continue without it, do not ask it again, and do not treat the skip as permission.')
PENDING_NOTICE = ('No answer batch arrived before the timeout. This is pending, not a skipped answer. '
    'Continue useful independent work. The user can still answer; their reply will be a user message '
    'identified as answer_to_pending_question with this callId and the original questions. '
    'Do not treat this as permission.')


def validate_timeout(timeout):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout != -1 and (timeout < 1 or timeout > 2147483 or int(timeout) != timeout):
        raise ValueError('timeout must be -1 or a positive integer up to 2147483 seconds')
    return timeout


class CurrentToolAskUserPlugin(Plugin):
    id = "tool-ask-user"
    name = "@deepseek-ai/dsh-tool-ask-user"
    inject = ["tools", "userQuestions"]

    Config = Schema.object(dict(mode=Schema.union('legacy', 'timed').default('legacy'),
        timeout=Schema.union(-1, Schema.number().step(1).min(1).max(2147483)).default(120)))

    def apply(self, ctx: Any, config=None) -> None:
        config = self.config if config is None else config
        timed = config.get('mode', 'legacy') == 'timed'
        default_timeout = validate_timeout(config.get('timeout', 120)) if timed else 120
        async def execute(arguments: Dict[str, Any], execution: Optional[Any] = None,
                          agent: Optional[Any] = None, signal: Optional[Any] = None) -> Any:
            timeout = validate_timeout(arguments.get('timeout') if arguments.get('timeout') is not None else default_timeout) if timed else None
            if timed:
                seen = set()
                for item in arguments['questions']:
                    if item['id'] in seen:
                        raise ValueError('question id '+stringify_json(item['id'])+' must be unique within this call')
                    seen.add(item['id'])
            questions = []
            for question in arguments["questions"]:
                projected = {"id": question["id"], "question": question["question"]}
                for key in ("header", "options"):
                    if key in question:
                        projected[key] = [dict(option) for option in question[key]] if timed and key == 'options' else question[key]
                if "multi_select" in question:
                    projected["multiSelect"] = question["multi_select"]
                questions.append(projected)
            request = {"questions": questions,
                       "signal": signal if signal is not None else field(execution, "signal")}
            caller = agent if agent is not None else field(execution, "agent")
            if caller is not None:
                request["agent"] = caller
            if timed:
                call_id = field(execution, 'callId')
                if timeout != -1:
                    if caller is None:
                        raise ValueError('timed questions require a live agent')
                    result = await ctx.userQuestions.askTimed(request, call_id, timeout * 1000)
                    if 'pending' in result:
                        return dict(result, message=PENDING_NOTICE)
                else:
                    result = await ctx.userQuestions.ask(dict(request, wait=dict(callId=call_id)))
            else:
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
                + SKIPPED_GUIDANCE
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
        if timed:
            definition['description'] = ('Ask brief, direct, self-contained questions about missing information, preferences, or decisions. '
                'Use user-facing terms; assume no knowledge of background work or internal names. '
                'Use distinct stable question IDs. '+SKIPPED_GUIDANCE+' '
                'A pending result instead means no answer batch arrived before the timeout and the user can still answer.')
            properties = definition['parameters']['properties']
            properties['questions']['description'] = 'Questions to ask the user.'
            properties['timeout'] = dict(type='integer', description='Wait seconds for the entire batch (default %s); omit unless the user specifies a duration. Use -1 only when an answer is required before proceeding.' % default_timeout)
            answers_schema = definition['output']['schema']
            answers_schema['properties']['answers']['description'] = 'Submitted answer batch with one item per question. A skipped question has empty selected and no custom; unlike pending, the user has completed the batch.'
            answer_properties = answers_schema['properties']['answers']['items']['properties']
            answer_properties['id']['description'] = 'Stable question id echoed from the request.'
            answer_properties['selected']['description'] = 'Selected option labels. Empty with no custom means the user explicitly skipped this question.'
            answer_properties['custom']['description'] = 'Optional free-form answer; omitted for a skipped question.'
            definition['output']['schema'] = dict(oneOf=[dict(type='object', additionalProperties=False,
                properties=dict(pending=dict(type='boolean', enum=[True], description='True when the foreground wait expired before the user submitted an answer batch. The questions remain answerable; this is not a skipped answer.'),
                    callId=dict(type='string', description='Tool call whose unanswered questions remain pending.'),
                    message=dict(type='string', description='How to continue while the questions stay answerable.')),
                required=['pending', 'callId', 'message']), answers_schema])
        disposer = ctx.tools.register(definition)
        ctx.disposable(disposer, label="tool_ask_user.unregister")
