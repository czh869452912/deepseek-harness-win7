"""Owned, published one-shot Agent runs for spawn and completed-prefix fork."""
import asyncio
import uuid

from dsh.cordis.plugin import Plugin
from dsh.core.consumed_work import fold_consumed_work
from dsh.llm.message import create_user_message
from dsh.subagent.composition import child_depth, child_options, child_meta, capture_policy, append_policy, apply_composition
from dsh.subagent.descriptor import completed_turn_prefix, final_assistant_output
from dsh.subagent.structured import attach_structured


def read_result(child, boundary, cancelled, structured=None):
    own = child.session.events[boundary:]
    end = fold_consumed_work(own).end
    recorded = end["data"]["reason"]["kind"] if end is not None else None
    reason = {"completed": "completed", "max-tokens": "max-tokens", "aborted": "aborted", "blocked": "refusal"}.get(recorded, "error")
    if cancelled and reason != "completed":
        reason = "aborted"
    result = {"output": final_assistant_output(own) or [], "stopReason": reason}
    if structured is not None:
        if structured["captured"] is not None:
            result["structured"] = structured["captured"]["value"]
        elif reason == "completed":
            result["stopReason"] = "aborted" if cancelled else "error"
    return result


class InProcessRun:
    def __init__(self, handle, signal, prompt, boundary, structured):
        self.id, self.localAgent = handle.agent.id, handle.agent
        self.handle, self.cancelled, self.closing = handle, False, None
        def abort(*_):
            self.cancelled = True
            self.localAgent.cancel({"kind": "parent"})
        self.detach = signal.add_listener("abort", abort)
        if signal.aborted:
            abort()
        async def drive():
            try:
                if not self.cancelled:
                    self.localAgent.followup(create_user_message({"content": prompt, "source": {"kind": "user"}}))
                    await self.localAgent.when_idle()
                return read_result(self.localAgent, boundary, self.cancelled, structured)
            finally:
                self.detach()
        self.result = asyncio.create_task(drive())
        self.result.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)

    async def dispose(self):
        if self.closing is None:
            self.detach()
            self.cancelled = True
            async def close():
                results = await asyncio.gather(self.handle.dispose(), self.result, return_exceptions=True)
                if isinstance(results[0], BaseException):
                    raise results[0]
            self.closing = asyncio.create_task(close())
        await asyncio.shield(self.closing)


async def start_run(request, seed=None):
    signal, parent = request["signal"], request["parent"]
    if signal.aborted:
        raise RuntimeError("subagent request was aborted before child publication")
    depth = child_depth(parent, request.get("maxDepth"))
    boundary, inherited = len(seed or []), capture_policy(parent)
    structured = None
    def setup(child_ctx):
        nonlocal structured
        child = child_ctx.agent
        append_policy(child.session, inherited)
        apply_composition(child_ctx, parent, request)
        if "outputSchema" in request:
            structured = attach_structured(child_ctx, request["outputSchema"])
        appended = False
        async def descriptor(payload, next_fn):
            nonlocal appended
            decision = await next_fn()
            if not appended and decision.get("kind") != "reject":
                appended = True
                payload["agent"].session.append("subagent/descriptor", request["descriptor"])
            return decision
        child_ctx.on("agent/pre-step", descriptor)
    handle = await parent.ctx.get("agents").create({"sessionId": str(uuid.uuid4()), "meta": child_meta(parent, depth, boundary),
        "agentOptions": child_options(parent, request.get("agentOptions"), depth), "signal": signal, "setup": setup,
        **({"seed": seed} if seed else {})})
    return InProcessRun(handle, signal, request["prompt"], boundary, structured)


class InProcessProvider:
    capabilities = {"agentOptions": True, "outputSchema": True, "depthLimit": True, "toolFilter": True, "persona": True}

    def __init__(self, name, fork=False):
        self.name, self.inheritsParentContext = name, fork

    async def start(self, request):
        return await start_run(request, completed_turn_prefix(request["parent"]) if self.inheritsParentContext else None)

    async def prepareContinuable(self, request):
        seed = completed_turn_prefix(request["parent"]) if self.inheritsParentContext else []
        return {"seed": seed} if seed else {}


class SpawnInProcess(Plugin):
    id = "subagent-spawn-in-process"
    inject = ["subagents"]

    def apply(self, ctx):
        ctx.get("subagents").registerProvider(InProcessProvider(self.config.get("providerName", "spawn")))


class ForkInProcess(Plugin):
    id = "subagent-fork-in-process"
    inject = ["subagents"]

    def apply(self, ctx):
        ctx.get("subagents").registerProvider(InProcessProvider(self.config.get("providerName", "fork"), True))
