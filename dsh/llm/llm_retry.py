"""
Provider-routed model-request retry policy on the agent loop's request recovery extension point.
Aligned 1:1 with official `@deepseek-ai/dsh-llm-retry`.
"""

import asyncio
import random
import time
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


RETRYABLE_ERROR_CODES = {
    "429", "500", "502", "503", "504",
    "RATE_LIMIT", "SERVER_ERROR", "TIMEOUT", "CONNECTION_ERROR"
}


class LLMRetryPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-llm-retry`: Catches LLM request errors and schedules exponential backoff retries.
    """

    id = "llm-retry"
    name = "@deepseek-ai/dsh-llm-retry"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.max_retries = int(self.config.get("maxRetries", 5))
        self.initial_delay_ms = float(self.config.get("initialDelayMs", 1000.0))
        self.max_delay_ms = float(self.config.get("maxDelayMs", 30000.0))
        self.jitter_ratio = float(self.config.get("jitterRatio", 0.2))
        self._retry_counts: Dict[str, int] = {}

    def apply(self, ctx: Any) -> None:
        async def on_request_error(payload: Dict[str, Any]) -> Dict[str, Any]:
            agent = payload.get("agent")
            error_str = str(payload.get("error", ""))
            turn = payload.get("turn", 0)
            step = payload.get("step", 0)

            # Check if error is retryable
            is_retryable = any(code in error_str for code in RETRYABLE_ERROR_CODES)
            if not is_retryable and "429" not in error_str and "50" not in error_str and "timed out" not in error_str.lower():
                return {"kind": "reject", "error": error_str}

            agent_id = getattr(agent, "id", "default")
            key = f"{agent_id}:{turn}:{step}"
            curr_try = self._retry_counts.get(key, 0) + 1
            self._retry_counts[key] = curr_try

            if curr_try > self.max_retries:
                # Exceeded max retries
                return {"kind": "reject", "error": f"Exceeded max retries ({self.max_retries}): {error_str}"}

            # Exponential backoff with jitter
            exponent = min(curr_try - 1, 10)
            delay_ms = min(self.initial_delay_ms * (2 ** exponent), self.max_delay_ms)
            jitter = 1.0 - self.jitter_ratio + (2.0 * self.jitter_ratio * random.random())
            actual_delay_s = (delay_ms * jitter) / 1000.0

            ctx.emit("llm/retry", {
                "agentId": agent_id,
                "turn": turn,
                "step": step,
                "attempt": curr_try,
                "delayMs": actual_delay_s * 1000.0,
                "error": error_str,
            })

            await asyncio.sleep(actual_delay_s)
            return {"kind": "retry"}

        ctx.on("agent/request-error", on_request_error)
