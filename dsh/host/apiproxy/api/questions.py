"""
Questions Domain Handler (`@deepseek-ai/dsh-apiproxy/api/questions`).
Aligned 1:1 with reference `api/questions.ts` and `api/questions.schema.ts`.
"""

import asyncio
from typing import Any, Dict, List, Optional


def matches_questions(payload: Dict[str, Any], pending: Dict[str, Any]) -> bool:
    """
    Validate one answer batch against the exact question request it resolves.
    1:1 with reference api-proxy.ts matchesQuestions().
    """
    session_id = payload.get("sessionId")
    if session_id != pending.get("sessionId"):
        return False

    answer_obj = payload.get("answer", {})
    answers = answer_obj.get("answers", []) if isinstance(answer_obj, dict) else []
    pending_questions = pending.get("questions", [])

    if len(answers) != len(pending_questions):
        return False

    for index, answer in enumerate(answers):
        if not isinstance(answer, dict):
            return False
        question = pending_questions[index] if index < len(pending_questions) else {}
        if not isinstance(question, dict):
            return False

        if answer.get("id") != question.get("id"):
            return False

        selected = answer.get("selected", [])
        if not isinstance(selected, list):
            return False
        if len(set(selected)) != len(selected):
            return False

        custom = answer.get("custom")
        if custom is not None:
            if isinstance(custom, str) and custom.strip() == "":
                return False

        multi_select = question.get("multiSelect", False) or question.get("multi_select", False)
        if not multi_select:
            if custom is not None and len(selected) > 0:
                return False
            if len(selected) > 1:
                return False

        options = question.get("options", [])
        labels = set()
        if isinstance(options, list):
            for opt in options:
                if isinstance(opt, dict) and "label" in opt:
                    labels.add(opt["label"])

        if labels:
            if not all(label in labels for label in selected):
                return False

    return True


class QuestionsDomainHandler:
    def __init__(self, ctx: Any, pending_requests: Dict[str, Any], broadcast_mux: Any):
        self.ctx = ctx
        self._pending = pending_requests
        self._broadcast_mux = broadcast_mux

    def request_question(self, question_data: Dict[str, Any]) -> None:
        rpc_id = question_data.get("rpcId") or question_data.get("questionRpcId") or f"q-{id(question_data)}"
        sid = question_data.get("sessionId", "default-session")
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        questions_list = question_data.get("questions") if isinstance(question_data.get("questions"), list) else [question_data]
        self._pending[rpc_id] = {
            "future": fut,
            "sessionId": sid,
            "type": "question",
            "questions": questions_list,
        }

        asyncio.create_task(self._broadcast_mux({
            "type": "question/requested",
            "sessionId": sid,
            "questions": questions_list,
        }, rpc_id=rpc_id))
