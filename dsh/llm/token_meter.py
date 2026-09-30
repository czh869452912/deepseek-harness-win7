"""Replay-aware request pressure and positional surface pricing (Python 3.8)."""
import copy
from weakref import WeakKeyDictionary

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.core.session import canonical_header, header_equals, derive_event_message
from dsh.core.session.json import deep_freeze
from dsh.core.surface import is_surface_event
from dsh.llm.image_content import images
from dsh.llm.token_estimate import (
    CHARS_PER_TOKEN, BLOCK_OVERHEAD, ROLE_OVERHEAD, estimate_content,
    estimate_message, estimate_header, estimate_system_tokens, estimate_tools_tokens,
    estimate_structural_block,
)


def _analyze(event):
    message = derive_event_message(event)
    refs, structural = [], 0
    tokens = 0 if message is None else estimate_message(message)
    if message is not None:
        for block in images(message["content"]):
            refs.append(block["attachment"])
            structural += estimate_structural_block(block)
    return dict(seq=event["seq"], heuristicTokens=tokens,
                imageFreeTokens=tokens - structural, images=refs)


def price_surface(nodes, pricing):
    refs = [ref for node in nodes for ref in node["images"]] if pricing is not None else []
    prices = pricing.priceImages(refs) if refs else []
    if len(prices) != len(refs):
        raise ValueError("token meter: route image pricing answered {} prices for {} occurrences".format(len(prices), len(refs)))
    cursor, result = 0, []
    for node in nodes:
        tokens = node["heuristicTokens"]
        if refs and node["images"]:
            tokens = node["imageFreeTokens"]
            for _ in node["images"]:
                price = prices[cursor]
                cursor += 1
                tokens += price["visualTokens"] + estimate_content([dict(type="text", text=price["text"])])
        result.append(dict(seq=node["seq"], tokens=tokens, heuristicTokens=node["heuristicTokens"]))
    return dict(nodes=result, surfaceTokens=sum(node["tokens"] for node in result))


def usage_tokens(usage):
    return sum(usage.get(key, 0) for key in ("inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens"))


class TokenMeter(Service):
    Config = Schema.object({})

    def __init__(self, ctx=None, config=None):
        for key in config or {}:
            raise ValueError('TokenMeterConfig: unknown key "{}" (no settings are supported)'.format(key))
        self._states = WeakKeyDictionary()
        super().__init__(ctx, "tokenMeter")
        if ctx is not None:
            from dsh.llm.token_projections import DEFINITIONS
            def register(projection_ctx):
                for definition in DEFINITIONS:
                    projection_ctx.get("sessionProjections").register(definition)
            ctx.inject(["sessionProjections"], register)
            ctx.on("session/event", self._observe)

    def _observe(self, session, *_):
        if session in self._states:
            self._sync(session)

    def _sync(self, session):
        state = self._states.get(session)
        if state is None:
            state = dict(consumedEvents=0, header=None, surface=[], stepStart=None, anchor=None)
            self._states[session] = state
        while state["consumedEvents"] < len(session.events):
            self._fold(session, state, session.events[state["consumedEvents"]])
            state["consumedEvents"] += 1
        return state

    def _fold(self, session, state, event):
        kind, data, seq = event["type"], event["data"], event["seq"]
        header, step, anchor = state["header"], state["stepStart"], state["anchor"]
        if kind == "request/header":
            header = canonical_header(data["header"])
        elif kind == "step/start":
            if step is not None:
                raise ValueError("token meter: step/start at seq {} arrived before turn {}/step {} ended".format(seq, step["turn"], step["step"]))
            step = dict(data, nodes=list(state["surface"]), requestStarted=False)
        elif kind == "step/end":
            if step is None or (step["turn"], step["step"]) != (data["turn"], data["step"]):
                raise ValueError("token meter: step/end at seq {} has no matching step/start event".format(seq))
            step = None
        elif kind == "assistant/chunk" and step is not None and not step["requestStarted"]:
            if (step["turn"], step["step"]) == (data["turn"], data["step"]):
                # AgentLoop publishes accepted input after step/start. Freeze its
                # request surface at the first provider chunk, before output rewrites.
                step = dict(step, nodes=list(state["surface"]), requestStarted=True)

        # Plan every fallible transition before committing any replay state.
        node, target = None, None
        if is_surface_event(event):
            node = _analyze(event)
            op = event["surfaceOp"]
            if op == "append":
                target = len(state["surface"]), len(state["surface"])
            else:
                positions = {item["seq"]: index for index, item in enumerate(state["surface"])}
                first, last = positions.get(op["start"]), positions.get(op["end"])
                if first is None or last is None or first > last:
                    raise ValueError("token surface: replace at seq {} has invalid current range {}-{}".format(seq, op["start"], op["end"]))
                target = first, last + 1
        if kind == "assistant/message":
            opening = state["stepStart"]
            if opening is None or (opening["turn"], opening["step"]) != (data["turn"], data["step"]):
                raise ValueError("token meter: assistant/message at seq {} has no matching step/start event".format(seq))
            tokens = node["heuristicTokens"]
            usage = data.get("usage") if header is not None else None
            if usage is not None:
                tokens = self._provider_tokens(session, event, tokens)
            input_nodes = opening["nodes"] if opening["requestStarted"] else list(state["surface"])
            anchor = dict(header=header, nodes=input_nodes, assistantTokens=tokens, usage=usage)
        state["header"], state["stepStart"], state["anchor"] = header, step, anchor
        if node is not None:
            state["surface"][target[0]:target[1]] = [node]

    def _provider_tokens(self, session, event, durable_tokens):
        if "sourceEventSeqs" not in event:
            return durable_tokens
        from dsh.core.agent_loop import BlockAssembler
        assembler, seen = BlockAssembler(), set()
        for seq in event["sourceEventSeqs"]:
            prefix = "token meter: assistant/message at seq {} source seq {}".format(event["seq"], seq)
            if seq >= event["seq"]:
                raise ValueError(prefix + " is not earlier")
            if seq in seen:
                raise ValueError("token meter: assistant/message at seq {} repeats source seq {}".format(event["seq"], seq))
            seen.add(seq)
            source = session.events[seq]
            if source["type"] != "assistant/chunk":
                raise ValueError(prefix + " is not assistant/chunk")
            if (source["data"]["turn"], source["data"]["step"]) != (event["data"]["turn"], event["data"]["step"]):
                raise ValueError(prefix + " belongs to another step")
            assembler.push(source["data"]["chunk"])
        content = assembler.blocks()
        return estimate_content(content) + ROLE_OVERHEAD if content else 0

    def measure(self, session, request_header=None):
        state = self._sync(session)
        header = state["header"] if request_header is None else canonical_header(request_header)
        pricing = None
        llm = self.ctx.get("llm") if self.ctx is not None else None
        if llm is not None and header is not None:
            resolve = getattr(llm, "imageRequestPricing", None) or getattr(llm, "image_request_pricing", None)
            if resolve is not None:
                config = header["config"]
                pricing = resolve(config.get("provider"), config.get("model"))
        surface = price_surface(state["surface"], pricing)
        anchor = state["anchor"]
        matches = (anchor is not None and
                   ((anchor["header"] is None and header is None) or
                    (anchor["header"] is not None and header is not None and header_equals(anchor["header"], header))))
        if matches:
            anchor_tokens = price_surface(anchor["nodes"], pricing)["surfaceTokens"] + anchor["assistantTokens"]
            estimated = estimate_header(header) + anchor_tokens
            usage = anchor["usage"]
            baseline = (dict(kind="usage", tokens=usage_tokens(usage), usage=usage)
                        if usage is not None and usage_tokens(usage) >= estimated
                        else dict(kind="estimated", tokens=estimated))
            delta = surface["surfaceTokens"] - anchor_tokens
        elif header is None and surface["surfaceTokens"] == 0:
            baseline, delta = dict(kind="none", tokens=0), 0
        else:
            baseline, delta = dict(kind="estimated", tokens=estimate_header(header) + surface["surfaceTokens"]), 0
        return deep_freeze(copy.deepcopy(dict(logRevision=state["consumedEvents"], baseline=baseline,
                                             surfaceDeltaTokens=delta, totalTokens=max(0, baseline["tokens"] + delta),
                                             **surface)))

    estimate_content = staticmethod(estimate_content)
    estimate_message = staticmethod(estimate_message)
    estimateMessage = staticmethod(estimate_message)
    estimate_header = staticmethod(estimate_header)


class TokenMeterPlugin(Plugin):
    id = "token-meter"
    name = "@deepseek-ai/dsh-token-meter"
    Config = TokenMeter.Config

    def apply(self, ctx):
        meter = TokenMeter(ctx, self.config)
        ctx.set_service("token_meter", meter)
