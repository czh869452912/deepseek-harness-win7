"""Execute provider retry policy on the owned Agent request-error waterfall."""
import asyncio
import json
import logging
import math
import random
import uuid

from dsh.cordis.plugin import Plugin
from dsh.core.cancellation import aborted


def policy_key(policy):
    values = [policy["mode"]]
    if policy["mode"] == "normal":
        values.extend([policy["maxRetries"], sorted(policy["retryableCodes"])])
    values.extend(policy[k] for k in ("initialDelayMs", "maxDelayMs", "jitterRatio"))
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


class LLMRetryPlugin(Plugin):
    id = "llm-retry"
    name = "@deepseek-ai/dsh-llm-retry"
    inject = ["agents"]

    def __init__(self, config=None):
        super().__init__(config)
        if self.config:
            raise ValueError("llm-retry takes no config; retryPolicy belongs under each provider")

    def apply(self, ctx):
        lifetime, active = asyncio.Event(), set()

        async def recover(payload, next_fn):
            signal, policy = payload.get("signal"), payload.get("retryPolicy")
            if lifetime.is_set() or aborted(signal):
                return None
            if policy is None:
                return await next_fn()
            if policy["mode"] == "always":
                try:
                    downstream = await next_fn()
                except Exception as error:
                    logging.getLogger("llm-retry").warning("Downstream recovery failed: %s", error)
                    downstream = None
                if lifetime.is_set() or aborted(signal):
                    return None
                if isinstance(downstream, dict) and downstream.get("kind") == "retry":
                    return downstream
            elif payload["failure"]["code"] not in policy["retryableCodes"]:
                return await next_fn()
            agent, key = payload["agent"], policy_key(policy)
            turn, step, provider = payload["turn"], payload["step"], payload["provider"]
            prior = next((e["data"] for e in reversed(agent.session.events)
                          if e["type"] == "llm/retry" and all(e["data"].get(k) == v for k, v in
                              (("turn", turn), ("step", step), ("provider", provider), ("policyKey", key)))), {})
            previous = prior.get("retry", 0)
            if policy["mode"] == "normal" and previous >= policy["maxRetries"]:
                return await next_fn()
            retry = previous + 1
            delay = payload["failure"].get("providerRetryAfterMs")
            if type(delay) in (float, int) and math.isfinite(delay) and delay > 0:
                if delay > policy["maxDelayMs"]:
                    if policy["mode"] == "normal":
                        return await next_fn()
                    delay = None
            else:
                delay = None
            if delay is None:
                exponent = min(retry - 1, 1024)
                cap = policy["maxDelayMs"] / policy["initialDelayMs"]
                base = policy["maxDelayMs"] if exponent >= math.log2(cap) else policy["initialDelayMs"] * 2 ** exponent
                delay = min(base * (1 - policy["jitterRatio"] + 2 * policy["jitterRatio"] * random.random()), policy["maxDelayMs"])
            if lifetime.is_set() or aborted(signal):
                return None
            data = dict(retryId=prior.get("retryId", str(uuid.uuid4())), turn=turn, step=step,
                        provider=provider, mode=policy["mode"], policyKey=key, retry=retry,
                        delayMs=delay, failure=dict(payload["failure"]))
            if policy["mode"] == "normal":
                data["maxRetries"] = policy["maxRetries"]
            agent.session.append("llm/retry", data)
            deadline = asyncio.get_running_loop().time() + delay / 1000
            while not lifetime.is_set() and not aborted(signal):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    agent.session.append("llm/retry-started", {k: data[k] for k in ("retryId", "turn", "step", "retry")})
                    return {"kind": "retry"}
                try:
                    await asyncio.wait_for(lifetime.wait(), min(remaining, 0.02))
                except asyncio.TimeoutError:
                    pass
            return None

        async def listener(payload, next_fn):
            if lifetime.is_set():
                return None
            task = asyncio.current_task()
            active.add(task)
            try:
                return await recover(payload, next_fn)
            finally:
                active.discard(task)

        remove = ctx.on("agent/request-error", listener)

        async def close():
            remove()
            lifetime.set()
            tasks = [task for task in active if task is not asyncio.current_task()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        ctx.effect(lambda: close)
