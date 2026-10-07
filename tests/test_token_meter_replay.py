import copy
import asyncio
import gc
import weakref

import pytest

from dsh.cordis.context import Context
from dsh.core.session import Session, SessionPlugin
from dsh.llm.message import create_user_message, create_assistant_message
from dsh.llm.token_meter import TokenMeter, TokenMeterPlugin, estimate_content, estimate_header, estimate_message
from dsh.llm.token_estimate import estimate_system_tokens, estimate_tools_tokens
from dsh.llm.token_projections import DEFINITIONS, fold_breakdown, fold_pressure, fold_usage
from dsh.session.projections import SessionProjectionsPlugin

HEADER = dict(config=dict(provider="mock", model="mock"), system="system")
USAGE = dict(inputTokens=100, outputTokens=20, cacheReadTokens=40, cacheWriteTokens=10, reasoningTokens=5)


def user(session, text="abcd", op="append"):
    options = {}
    if isinstance(op, dict):
        nodes = session.surface.nodes
        options["source_event_seqs"] = nodes[nodes.index(op["start"]):nodes.index(op["end"]) + 1]
    return session.append("user/message", create_user_message(dict(content=[dict(type='text', text=text)] if isinstance(text, str) else text, source=dict(kind='user'))), surface_op=op, **options)


def call(session, usage=USAGE, text="answer", provider_text=None, provenance="absent", header=HEADER, step=1):
    session.append("step/start", dict(turn=1, step=step))
    if header is not None:
        session.append("request/header", dict(header=header, reason="initial"))
    seqs = []
    if provenance == "exact":
        provider_text = text if provider_text is None else provider_text
        chunks = [dict(type="block-start", index=0, blockType="text"),
                  dict(type="text-delta", index=0, text=provider_text),
                  dict(type="block-end", index=0, block=dict(type="text", text=provider_text)),
                  dict(type="finish", reason=dict(kind="stop"))]
        for chunk in chunks:
            seqs.append(session.append("assistant/chunk", dict(turn=1, step=step, chunk=chunk))["seq"])
    body = dict(turn=1, step=step, message=create_assistant_message(dict(content=[dict(type='text', text=text)] if text else [], source=dict(provider='mock', model='mock'))))
    if usage is not None:
        body["usage"] = usage
    opts = {} if provenance == "absent" else dict(source_event_seqs=seqs)
    event = session.append("assistant/message", body, surface_op="append", **opts)
    session.append("step/end", dict(turn=1, step=step))
    return event


@pytest.mark.parametrize("text,expected", [("", 4), ("abcd", 5), ("abcde", 6),
                                              ("\U0001f600" * 3, 6), ("\ud83d\ude00" * 3, 6), ("\ud800" * 5, 6)])
def test_utf16_text_prices(text, expected):
    assert estimate_content([dict(type="text", text=text)]) == expected
    assert estimate_content([dict(type="reasoning", text=text)]) == expected


def test_json_structural_and_header_prices_use_js_text():
    block = dict(type="future", number=1.0, value="\ud800")
    assert estimate_content([block]) == 4 + (len('{"type":"future","number":1,"value":"\\ud800"}') + 3) // 4
    assert estimate_tools_tokens(dict(tools=[dict(q=1.0)])) == 7
    assert estimate_system_tokens(dict(system="")) == 4
    assert estimate_header(None) == 0
    assert estimate_header(dict(system="", tools=[])) == 4


def test_empty_and_detached_immutable_measurements():
    meter, session = TokenMeter(), Session("empty")
    assert meter.measure(session) == dict(logRevision=0, baseline=dict(kind="none", tokens=0),
                                          surfaceDeltaTokens=0, totalTokens=0, surfaceTokens=0, nodes=[])
    user(session)
    prior = meter.measure(session)
    with pytest.raises(TypeError):
        prior["nodes"][0]["tokens"] = 0
    with pytest.raises(TypeError):
        prior["nodes"].append({})
    user(session)
    assert prior["surfaceTokens"] == 9
    assert meter.measure(session)["surfaceTokens"] == 18


def test_usage_anchor_and_signed_replacement_delta():
    meter, session = TokenMeter(), Session("usage")
    first = user(session, "large" * 100)
    call(session)
    before = meter.measure(session)
    assert before["baseline"] == dict(kind="usage", tokens=170, usage=USAGE)
    user(session, "x", dict(op="replace", start=first["seq"], end=first["seq"]))
    after = meter.measure(session)
    assert after["surfaceDeltaTokens"] == before["surfaceDeltaTokens"] - 124
    assert after["totalTokens"] == 46
    assert [row["seq"] for row in after["nodes"]] == session.surface.nodes


@pytest.mark.parametrize("usage", [None, dict(inputTokens=1, outputTokens=1)])
def test_undercutting_or_missing_usage_uses_full_estimated_anchor(usage):
    meter, session = TokenMeter(), Session("low")
    user(session, "long" * 100)
    call(session, usage=usage)
    measurement = meter.measure(session)
    assert measurement["baseline"]["kind"] == "estimated"
    assert measurement["totalTokens"] == estimate_header(HEADER) + measurement["surfaceTokens"]


def test_effective_header_changes_route_without_mutating_logged_envelope():
    meter, session = TokenMeter(), Session("override")
    user(session)
    call(session)
    alternate = dict(config=dict(provider="mock", model="other"), system="different")
    assert meter.measure(session, alternate)["baseline"]["kind"] == "estimated"
    assert meter.measure(session)["baseline"]["kind"] == "usage"
    assert session.request_header() == HEADER


@pytest.mark.parametrize("provenance,provider_text,expected", [("exact", "abcd", 9), ("empty", None, 0), ("absent", None, 58)])
def test_exact_provider_chunks_price_anchor_before_durable_rewrite(provenance, provider_text, expected):
    meter, session = TokenMeter(), Session("rewritten")
    user(session)
    call(session, text="rewritten" * 22, provider_text=provider_text, provenance=provenance)
    result = meter.measure(session)
    assert result["surfaceDeltaTokens"] == result["surfaceTokens"] - 9 - expected


@pytest.mark.parametrize("kind,data,error", [
    ("step/end", dict(turn=1, step=1), "no matching step/start"),
    ("assistant/message", dict(turn=1, step=1, message=dict(role="assistant", content=[])), "no matching step/start"),
])
def test_invalid_replay_never_advances_failed_event(kind, data, error):
    meter, session = TokenMeter(), Session("corrupt")
    user(session)
    session._log.append(dict(type=kind, seq=1, time=0, data=data, surfaceOp="append"))
    for _ in range(2):
        with pytest.raises(ValueError, match=error):
            meter.measure(session)
        assert meter._states[session]["consumedEvents"] == 1
        assert [node["seq"] for node in meter._states[session]["surface"]] == [0]


def test_failed_provider_provenance_does_not_half_apply_surface_or_anchor():
    meter, session = TokenMeter(), Session("bad-source")
    first = user(session)
    event = call(session)
    raw = copy.deepcopy(dict(event))
    raw["sourceEventSeqs"] = [first["seq"]]
    session._log[event["seq"]] = raw
    for _ in range(2):
        with pytest.raises(ValueError, match="is not assistant/chunk"):
            meter.measure(session)
        assert meter._states[session]["consumedEvents"] == event["seq"]
        assert meter._states[session]["anchor"] is None


def test_sessions_with_equal_ids_are_isolated_and_not_retained():
    meter = TokenMeter()
    left, right = Session("same"), Session("same")
    user(left)
    assert meter.measure(left)["surfaceTokens"] == 9
    assert meter.measure(right)["surfaceTokens"] == 0
    reference = weakref.ref(left)
    del left
    gc.collect()
    assert reference() is None
    assert len(meter._states) == 1


def test_image_pricing_count_mismatch_fails_then_can_be_retried():
    class Pricing:
        def priceImages(self, refs):
            return []
    class Llm:
        def imageRequestPricing(self, *_):
            return Pricing()
    ctx = Context()
    ctx.set_service("llm", Llm())
    meter, session = TokenMeter(ctx), Session("images")
    session.append_request_header(HEADER)
    user(session, [dict(type="image", attachment=dict(attachmentId="sha256:" + "a" * 64,
                                                     bytes=10, width=100, height=100, mediaType="image/png"))])
    with pytest.raises(ValueError, match="answered 0 prices for 1 occurrences"):
        meter.measure(session)
    assert meter._states[session]["consumedEvents"] == len(session.events)


@pytest.mark.parametrize("key", ["models", "contextWindow", "contextWidow"])
def test_meter_rejects_unknown_settings(key):
    with pytest.raises(ValueError, match="unknown key"):
        TokenMeter(config={key: {}})


def test_usage_samples_replace_until_retry_boundary():
    state = dict(totals=dict(uncachedInputTokens=0, outputTokens=0, cacheReadTokens=0, cacheWriteTokens=0), last=None)
    sample = dict(type="assistant/chunk", data=dict(turn=1, step=1, chunk=dict(type="usage", usage=USAGE)))
    state = fold_usage(state, sample)
    assert fold_usage(state, sample) is state
    state = fold_usage(state, dict(type="llm/retry-started", data=dict(turn=1, step=1)))
    state = fold_usage(state, sample)
    assert state["totals"]["uncachedInputTokens"] == 200
    assert state["totals"]["outputTokens"] == 40


def test_projection_shadow_claim_is_adjacent_and_range_checked():
    state = dict(systemTokens=0, toolsTokens=0, messageTokens=100)
    claim = dict(type="compaction/prune", data=dict(shadowedRange=dict(start=1, end=2), shadowedTokenCount=90))
    armed = fold_breakdown(state, claim)
    event = dict(seq=5, type="user/message", surfaceOp=dict(start=1, end=2), data=create_user_message(dict(content=[dict(type='text', text="x")], source=dict(kind='user'))))
    assert fold_breakdown(armed, event)["messageTokens"] == 19
    assert fold_breakdown(state, event) is state
    expired = fold_breakdown(armed, dict(type="session/end-seed", data={}))
    assert fold_breakdown(expired, event) is expired
    bad = dict(event, surfaceOp=dict(start=0, end=2))
    with pytest.raises(ValueError, match="no adjacent shadow price"):
        fold_breakdown(armed, bad)
    assert armed["messageTokens"] == 100


def test_pressure_samples_precede_message_surface_and_window_can_clear():
    session = Session("projection")
    event = user(session)
    state = fold_pressure(dict(surfaceTokens=0), event)
    state = fold_pressure(state, dict(type="request/context", data=dict(contextWindow=1000)))
    state = fold_pressure(state, dict(type="assistant/message", data=dict(usage=USAGE, message=create_assistant_message(dict(content=[dict(type='text', text="abcd")], source=dict(provider='mock', model='mock')))), surfaceOp="append", seq=1))
    from dsh.llm.token_projections import pressure_view
    assert pressure_view(state) == dict(contextWindow=1000, pressureTokens=150, projectedTokens=159)
    state = fold_pressure(state, dict(type="request/context", data={}))
    assert "contextWindow" not in pressure_view(state)


@pytest.mark.parametrize("definition", DEFINITIONS, ids=lambda item: item["key"])
def test_projection_cache_schemas_are_executable_and_strict(definition):
    parser = definition["stateSchema"]
    state = definition["init"]({})
    assert parser(copy.deepcopy(state)) == state
    with pytest.raises(ValueError):
        parser(dict(state, obsolete=True))
    malformed = copy.deepcopy(state)
    key = "totals" if definition["key"] == "tokenUsage" else next(iter(state))
    malformed[key] = -1
    with pytest.raises(ValueError):
        parser(malformed)


@pytest.mark.asyncio
@pytest.mark.parametrize("registry_first", [True, False])
async def test_optional_projection_registration_live_replay_and_unload(registry_first):
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    if registry_first:
        await ctx.plugin(SessionProjectionsPlugin)
    owner = await ctx.plugin(TokenMeterPlugin)
    if not registry_first:
        await ctx.plugin(SessionProjectionsPlugin)
    registry, meter = ctx.get("sessionProjections"), ctx.get("tokenMeter")
    assert all(registry.has(definition["key"]) for definition in DEFINITIONS)
    session = ctx.get("sessions").create("live")
    meter.measure(session)
    user(session)
    assert meter._states[session]["consumedEvents"] == session.seq
    snapshot = registry.snapshot(session)
    assert snapshot["values"]["contextBreakdown"]["messageTokens"] == 9
    checkpoint = registry.checkpoint(session)
    assert registry.restore(checkpoint, [], session.seq, session.header)["snapshot"] == snapshot
    await owner.dispose()
    assert ctx.get("tokenMeter") is None and ctx.get("token_meter") is None
    assert not any(registry.has(definition["key"]) for definition in DEFINITIONS)
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_agent_loop_usage_anchor_projection_dedup_and_cold_replay():
    from dsh.core.agent_loop import AgentLoopPlugin
    from dsh.core.agent import AgentPlugin
    from dsh.core.tools import ToolsPlugin
    from dsh.core.system_prompt import SystemPrompt
    class Model:
        provider, model = "fixture", "fixture"
        async def chat_completion_stream(self, *_args, **_kwargs):
            yield dict(type="block-start", index=0, blockType="text")
            yield dict(type="text-delta", index=0, text="answer")
            yield dict(type="block-end", index=0, block=dict(type="text", text="answer"))
            yield dict(type="usage", usage=dict(inputTokens=1000, outputTokens=20, totalTokens=1020))
            yield dict(type="finish", reason=dict(kind="stop"))
    ctx = Context()
    ctx.set_service("llm", Model())
    for plugin in (SessionPlugin, ToolsPlugin, SystemPrompt, AgentPlugin, AgentLoopPlugin, SessionProjectionsPlugin, TokenMeterPlugin):
        await ctx.plugin(plugin)
    handle = await ctx.get("agent_loop").create("meter-loop")
    try:
        meter, registry, session = ctx.get("tokenMeter"), ctx.get("sessionProjections"), handle.agent.session
        for prompt in ("first", "second"):
            handle.agent.followup(prompt)
            await asyncio.wait_for(handle.agent.when_idle(), 3)
            result = meter.measure(session)
            assert result["baseline"]["kind"] == "usage" and result["baseline"]["tokens"] == 1020
            assert result["surfaceDeltaTokens"] == 0
            assert result["logRevision"] == session.seq
        snapshot = registry.snapshot(session)
        assert snapshot["values"]["tokenUsage"]["uncachedInputTokens"] == 2000
        assert snapshot["values"]["tokenUsage"]["outputTokens"] == 40
        assert snapshot["values"]["contextBreakdown"]["messageTokens"] == sum(row["heuristicTokens"] for row in result["nodes"])
        checkpoint = registry.checkpoint(session)
        cold = Session.from_restore(session.id, copy.deepcopy(session.events), copy.deepcopy(session.header))
        assert cold.events[-1]["type"] == "session/end-seed"
        assert TokenMeter().measure(cold) == dict(result, logRevision=cold.seq)
        assert registry.hydrate(cold, checkpoint, cold.events[session.seq:], session.seq) == dict(snapshot, asOfSeq=cold.seq - 1)
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()


def test_reviewed_input_anchor_gate_rejects_other_changes():
    from scripts.token_meter_oracle import BUG_CASE, BUG_TARGET, reviewed_input_anchor_difference
    baseline = dict(kind="usage", tokens=120, usage=dict(inputTokens=100, outputTokens=20))
    left = dict(mode="late-input-anchor", output=[dict(measurement=dict(baseline=baseline,
        surfaceDeltaTokens=9, totalTokens=129, surfaceTokens=19), projection=dict(values={}))])
    right = copy.deepcopy(left)
    right["output"][0]["measurement"].update(surfaceDeltaTokens=0, totalTokens=120)
    assert reviewed_input_anchor_difference(left, right, BUG_CASE, BUG_TARGET)
    assert not reviewed_input_anchor_difference(left, right, BUG_CASE, "other target")
    assert not reviewed_input_anchor_difference(left, right, dict(BUG_CASE, actions=[]), BUG_TARGET)
    changed = copy.deepcopy(right)
    changed["output"][0]["measurement"]["surfaceTokens"] = 20
    assert not reviewed_input_anchor_difference(left, changed, BUG_CASE, BUG_TARGET)
    changed = copy.deepcopy(right)
    changed["output"][0]["projection"]["values"] = dict(tokenUsage=0)
    assert not reviewed_input_anchor_difference(left, changed, BUG_CASE, BUG_TARGET)


def test_first_chunk_freezes_input_and_later_surface_injection_remains_delta():
    meter, session = TokenMeter(), Session("late-injection")
    session.append("step/start", dict(turn=1, step=1))
    user(session, "abcd")
    session.append_request_header(HEADER)
    chunk = session.append("assistant/chunk", dict(turn=1, step=1,
                                                  chunk=dict(type="text-delta", index=0, text="answer")))
    user(session, "injected")
    session.append("assistant/message", dict(turn=1, step=1, usage=USAGE,
                                            message=create_assistant_message(dict(content=[dict(type='text', text="answer")], source=dict(provider='mock', model='mock')))),
                   surface_op="append", source_event_seqs=[chunk["seq"]])
    session.append("step/end", dict(turn=1, step=1))
    result = meter.measure(session)
    assert result["surfaceDeltaTokens"] == estimate_message(dict(content=[dict(type="text", text="injected")]))
    assert result["baseline"]["tokens"] == 170


def test_header_schema_equivalence_uses_js_numbers_and_enumeration():
    from dsh.core.session import header_equals
    left = dict(config=dict(provider="mock", model="mock"), tools=[dict(name="probe", parameters={"10": 1.0, "2": 2})])
    right = dict(config=dict(provider="mock", model="mock"), tools=[dict(name="probe", parameters={"2": 2.0, "10": 1})])
    assert header_equals(left, right)
