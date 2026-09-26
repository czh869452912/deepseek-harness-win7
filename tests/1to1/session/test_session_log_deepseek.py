"""
1:1 parity suite for `@deepseek-ai/dsh-session-log-deepseek`
(`dsh/session/session_log_deepseek.py`).

Upstream is reference/packages/session/session-log-deepseek/tests/upload.spec.ts.
Every case keeps the upstream setup, action, and assertions: the opt-in default,
the incremental prefix/suffix contribution and its acceptance watermark, restart
rebuild and inherited fork watermarks, out-of-order acceptance, the incremental
fold, direct/stale requests, model-invisible completeness, the fail-closed
malformed watermark, and HMR withdrawal.

The reference keys the acceptance fold with a `WeakMap<Session, fold>`; the port
uses a `WeakKeyDictionary`, so the incremental-fold case counts event reads on a
list subclass instead of a `Proxy` on an array (LEGAL_ADAPTATION: the platform's
property-read count has no Python analogue).
"""

from typing import Any, Dict, List, Optional

import pytest

from dsh.core.abort import AbortSignal
from dsh.core.session import Session, SessionStore
from dsh.cordis.context import Context
from dsh.llm.deepseek_api_extensions import DeepSeekLlmApiExtensionRegistry
from dsh.session.session_log_deepseek import (
    ACCEPTED_EVENT_TYPE,
    SessionLogDeepSeekPlugin,
    accepted_through,
)

SIGNAL = AbortSignal()


def body(text: str = "x" * 300) -> Dict[str, Any]:
    return {"messages": [{"role": "user", "content": text}]}


async def harness(
    session_id: str,
    seed: Optional[List[Dict[str, Any]]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    upload = await ctx.plugin(SessionLogDeepSeekPlugin, {"enabled": True})
    options: Optional[Dict[str, Any]] = None
    if seed is not None:
        options = {"seed": seed}
        if meta is not None:
            options["meta"] = meta
    session = ctx.get("sessions").create(session_id, options)
    return {"ctx": ctx, "session": session, "disposeUpload": upload.dispose}


async def prepare(test: Dict[str, Any], **overrides: Any) -> Any:
    request: Dict[str, Any] = {"body": body(), "signal": SIGNAL}
    request.update(overrides)
    return await test["ctx"].deepseekLlmApiExtensions.prepare(request)


@pytest.mark.asyncio
async def test_does_not_contribute_the_session_log_under_its_default_configuration():
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    await ctx.plugin(SessionLogDeepSeekPlugin)
    session = ctx.get("sessions").create("default-off")
    session.append("turn/start", {"turn": 1})

    prepared = await ctx.deepseekLlmApiExtensions.prepare(
        {"body": body(), "signal": SIGNAL, "sessionId": session.id}
    )
    assert "dsh_session_log" not in prepared.fields


@pytest.mark.asyncio
async def test_uploads_the_full_first_prefix_records_acceptance_then_sends_only_the_appended_suffix():
    test = await harness("incremental")
    session = test["session"]
    session.append("turn/start", {"turn": 1})
    session.append("step/start", {"turn": 1, "step": 1})

    first = await prepare(test, sessionId=session.id)
    first_payload = first.fields["dsh_session_log"]
    assert first_payload["afterSeq"] == -1
    assert first_payload["throughSeq"] == 1
    assert len(first_payload["events"]) == 2
    await first.accept()
    assert accepted_through(session) == 1

    session.append("step/end", {"turn": 1, "step": 1})
    second = await prepare(test, sessionId=session.id)
    payload = second.fields["dsh_session_log"]
    assert payload["afterSeq"] == 1
    assert payload["throughSeq"] == 3
    assert len(payload["events"]) == 2
    assert payload["events"][0]["type"] == ACCEPTED_EVENT_TYPE
    assert payload["events"][0]["seq"] == 2


@pytest.mark.asyncio
async def test_reconstructs_a_persisted_cursor_and_ignores_an_inherited_parent_watermark_in_a_fork():
    first = await harness("parent")
    first["session"].append("turn/start", {"turn": 1})
    prepared = await prepare(first, sessionId=first["session"].id)
    await prepared.accept()
    seed = list(first["session"].events)

    resumed = await harness("parent", seed)
    assert accepted_through(resumed["session"]) == 0
    resumed_payload = await prepare(resumed, sessionId=resumed["session"].id)
    assert resumed_payload.fields["dsh_session_log"]["afterSeq"] == 0

    fork = await harness(
        "child", seed, {"parentSession": first["session"].id, "seedLength": len(seed)}
    )
    assert accepted_through(fork["session"]) == -1
    fork_payload = await prepare(fork, sessionId=fork["session"].id)
    assert fork_payload.fields["dsh_session_log"]["afterSeq"] == -1
    assert fork_payload.fields["dsh_session_log"]["throughSeq"] == fork["session"].seq - 1


@pytest.mark.asyncio
async def test_takes_the_maximum_watermark_when_concurrent_acceptances_settle_out_of_order():
    test = await harness("concurrent")
    session = test["session"]
    session.append("turn/start", {"turn": 1})
    earlier = await prepare(test, sessionId=session.id)
    session.append("step/start", {"turn": 1, "step": 1})
    later = await prepare(test, sessionId=session.id)

    await later.accept()
    await earlier.accept()
    assert accepted_through(session) == 1


def test_folds_only_events_appended_after_the_cached_acceptance_scan():
    reads = [0]

    class CountingEvents(list):
        """One event list counting indexed reads (the reference's Proxy)."""

        def __getitem__(self, index: Any) -> Any:
            if isinstance(index, int):
                reads[0] += 1
            return list.__getitem__(self, index)

    class FakeSession:
        def __init__(self, session_id: str, events: CountingEvents) -> None:
            self._id = session_id
            self._events = events

        @property
        def id(self) -> str:
            return self._id

        @property
        def events(self) -> CountingEvents:
            return self._events

    events = CountingEvents(
        [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
            {
                "type": ACCEPTED_EVENT_TYPE,
                "seq": 1,
                "time": 2,
                "data": {"sessionId": "incremental-fold", "throughSeq": 0},
            },
        ]
    )
    session = FakeSession("incremental-fold", events)

    assert accepted_through(session) == 0
    assert reads[0] == 2
    reads[0] = 0
    assert accepted_through(session) == 0
    assert reads[0] == 0

    events.append({"type": "step/start", "seq": 2, "time": 3, "data": {"turn": 1, "step": 1}})
    events.append(
        {
            "type": ACCEPTED_EVENT_TYPE,
            "seq": 3,
            "time": 4,
            "data": {"sessionId": "incremental-fold", "throughSeq": 2},
        }
    )
    assert accepted_through(session) == 2
    assert reads[0] == 2


@pytest.mark.asyncio
async def test_omits_the_field_for_direct_or_stale_requests_and_uploads_the_prior_marker_next():
    test = await harness("edges")
    session = test["session"]
    assert dict((await prepare(test)).fields) == {}
    assert dict((await prepare(test, sessionId="missing")).fields) == {}
    assert dict((await prepare(test, sessionId=session.id)).fields) == {}

    session.append("turn/start", {"turn": 1})
    first = await prepare(test, sessionId=session.id)
    await first.accept()
    current = await prepare(test, sessionId=session.id)
    payload = current.fields["dsh_session_log"]
    assert payload["afterSeq"] == 0
    assert payload["throughSeq"] == 1
    assert [event["type"] for event in payload["events"]] == [ACCEPTED_EVENT_TYPE]


@pytest.mark.asyncio
async def test_contributes_complete_events_without_reading_request_messages():
    test = await harness("direct-events")
    session = test["session"]
    session.append("turn/start", {"turn": 1})
    prepared = await test["ctx"].deepseekLlmApiExtensions.prepare(
        {"body": {}, "signal": SIGNAL, "sessionId": session.id}
    )
    assert list(prepared.fields["dsh_session_log"]["events"]) == list(session.events)


def test_fails_closed_on_a_malformed_persisted_acceptance_watermark():
    malformed = [
        {
            "type": ACCEPTED_EVENT_TYPE,
            "seq": 0,
            "time": 1,
            "data": {"sessionId": "malformed", "throughSeq": 0},
        }
    ]
    session = Session.create("malformed", malformed)
    with pytest.raises(ValueError, match="malformed acceptance watermark"):
        accepted_through(session)


@pytest.mark.asyncio
async def test_withdraws_its_request_field_when_the_contributing_plugin_reloads():
    test = await harness("hmr")
    session = test["session"]
    session.append("turn/start", {"turn": 1})
    assert "dsh_session_log" in (await prepare(test, sessionId=session.id)).fields
    await test["disposeUpload"]()
    assert "dsh_session_log" not in (await prepare(test, sessionId=session.id)).fields
