"""
Questions Domain Handler (`@deepseek-ai/dsh-apiproxy/api/questions`).
Aligned 1:1 with reference `api/questions.ts`.
"""

import asyncio
import time
from typing import Any, Dict


class QuestionsDomainHandler:
    def __init__(self, ctx: Any, pending_requests: Dict[str, Any], broadcast_mux: Any):
        self.ctx = ctx
        self._pending = pending_requests
        self._broadcast_mux = broadcast_mux

    def request_question(self, question_data: Dict[str, Any]) -> None:
        rpc_id = question_data.get("rpcId") or f"q-{time.time()}"
        sid = question_data.get("sessionId", "default-session")
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending[rpc_id] = fut

        questions_list = question_data.get("questions") if isinstance(question_data.get("questions"), list) else [question_data]
        asyncio.create_task(self._broadcast_mux({
            "type": "question/requested",
            "sessionId": sid,
            "questions": questions_list,
        }, rpc_id=rpc_id))
