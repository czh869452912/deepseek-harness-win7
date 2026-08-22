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
    "EMPTY_RESPONSE", "RATE_LIMIT", "SERVER", "TIMEOUT", "TRANSPORT",
    "SERVER_ERROR", "CONNECTION_ERROR", "429", "500", "502", "503", "504"
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
        self.initial_delay_ms = float(self.config.get("initialDelayMs", 500.0))
        self.max_delay_ms = float(self.config.get("maxDelayMs", 10000.0))
        self.jitter_ratio = float(self.config.get("jitterRatio", 0.1))
        self._retry_counts: Dict[str, int] = {}

    def apply(self, ctx: Any) -> None:
        async def on_request_error(payload: Dict[str, Any]) -> Dict[str, Any]:
            agent = payload.get("agent")
            error_val = payload.get("error", "")
            error_str = str(error_val)
            turn = payload.get("turn", 0)
            step = payload.get("step", 0)
            provider = payload.get("provider", "default")
            failure = payload.get("failure") or (error_val.failure if hasattr(error_val, "failure") else None)

            code = None
            provider_retry_after_ms = None
            if isinstance(failure, dict):
                code = failure.get("code")
                provider_retry_after_ms = failure.get("providerRetryAfterMs")
            elif hasattr(error_val, "code"):
                code = getattr(error_val, "code")
                provider_retry_after_ms = getattr(error_val, "providerRetryAfterMs", None)

            # Check if error is retryable
            is_retryable = False
            if code and str(code) in RETRYABLE_ERROR_CODES:
                is_retryable = True
            elif any(c in error_str for c in RETRYABLE_ERROR_CODES):
                is_retryable = True
            elif "429" in error_str or "50" in error_str or "timed out" in error_str.lower():
                is_retryable = True

            if not is_retryable:
                return {"kind": "reject", "error": error_str}

            agent_id = getattr(agent, "id", "default")
            key = f"{agent_id}:{turn}:{step}"
            curr_try = self._retry_counts.get(key, 0) + 1
            self._retry_counts[key] = curr_try

            if curr_try > self.max_retries:
                # Exceeded max retries
                return {"kind": "reject", "error": f"Exceeded max retries ({self.max_retries}): {error_str}"}

            # Calculate delay
            if provider_retry_after_ms is not None and provider_retry_after_ms > 0:
                if provider_retry_after_ms > self.max_delay_ms:
                    return {"kind": "reject", "error": f"Provider retry-after ({provider_retry_after_ms}ms) exceeds maxDelayMs ({self.max_delay_ms}ms)"}
                delay_ms = float(provider_retry_after_ms)
            else:
                # Exponential backoff with symmetric jitter around local delay
                exponent = min(curr_try - 1, 1024)
                exponential = min(self.initial_delay_ms * (2 ** exponent), self.max_delay_ms)
                jitter = 1.0 - self.jitter_ratio + (2.0 * self.jitter_ratio * random.random())
                delay_ms = min(exponential * jitter, self.max_delay_ms)

            actual_delay_s = delay_ms / 1000.0

            ctx.emit("llm/retry", {
                "agentId": agent_id,
                "provider": provider,
                "turn": turn,
                "step": step,
                "attempt": curr_try,
                "retry": curr_try,
                "delayMs": delay_ms,
                "error": error_str,
            })

            await asyncio.sleep(actual_delay_s)
            return {"kind": "retry"}

        ctx.on("agent/request-error", on_request_error)
