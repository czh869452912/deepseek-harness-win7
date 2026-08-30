import pytest
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionStore
from dsh.session.projections import SessionProjectionsPlugin, SessionProjectionRegistry
from dsh.session.stats import (
    SessionStatsPlugin,
    apply_session_stats,
    init_session_stats,
    sessionStatsProjectionDefinition,
    view_session_stats,
)


def totals(**kwargs):
    base = {
        'turns': 0,
        'steps': 0,
        'llmMs': 0,
        'toolMs': 0,
        'ttftMs': 0,
        'ttftSteps': 0,
        'decodeMs': 0,
        'decodeTokens': 0,
    }
    base.update(kwargs)
    return base


def fold(events):
    state = init_session_stats()
    for ev in events:
        state = apply_session_stats(state, ev)
    return view_session_stats(state)


def at(time_ms, event_type, data):
    return {'seq': time_ms, 'time': time_ms, 'type': event_type, 'data': data}


def test_zero_figures_on_empty_log():
    assert fold([]) == totals()


def test_counts_distinct_turns_and_closed_steps():
    events = [
        at(100, 'turn/start', {'turn': 1}),
        at(110, 'step/start', {'turn': 1, 'step': 1}),
        at(120, 'step/end', {'turn': 1, 'step': 1}),
        at(130, 'step/start', {'turn': 1, 'step': 2}),
        at(140, 'step/end', {'turn': 1, 'step': 2}),
        at(150, 'turn/end', {'turn': 1, 'reason': {'kind': 'completed'}}),
        at(200, 'turn/start', {'turn': 2}),
        at(210, 'step/start', {'turn': 2, 'step': 1}),
        at(220, 'step/end', {'turn': 2, 'step': 1}),
        at(230, 'turn/end', {'turn': 2, 'reason': {'kind': 'completed'}}),
    ]
    assert fold(events) == totals(turns=2, steps=3)


def test_does_not_count_rejected_or_empty_turn():
    events = [
        at(100, 'turn/start', {'turn': 1}),
        at(150, 'turn/end', {'turn': 1, 'reason': {'kind': 'blocked'}}),
    ]
    assert fold(events) == totals()


def test_accrues_model_first_token_and_decode_time():
    msg = {'role': 'assistant', 'content': [{'type': 'text', 'text': 'answer'}]}
    events = [
        at(1000, 'step/start', {'turn': 1, 'step': 1}),
        at(1800, 'assistant/chunk', {'turn': 1, 'step': 1, 'chunk': {'type': 'text-delta', 'index': 0, 'text': 'a'}}),
        at(4800, 'assistant/message', {'turn': 1, 'step': 1, 'message': msg, 'usage': {'inputTokens': 10, 'outputTokens': 60}}),
        at(4900, 'step/end', {'turn': 1, 'step': 1}),
    ]
    assert fold(events) == totals(
        turns=1,
        steps=1,
        llmMs=3800,
        ttftMs=800,
        ttftSteps=1,
        decodeMs=3000,
        decodeTokens=60,
    )


def test_pairs_tool_wall_time_by_call_id():
    events = [
        at(1000, 'step/start', {'turn': 1, 'step': 1}),
        at(1100, 'tool/call', {'turn': 1, 'step': 1, 'callId': 'a', 'name': 'read'}),
        at(1200, 'tool/call', {'turn': 1, 'step': 1, 'callId': 'b', 'name': 'read'}),
        at(4200, 'tool/result', {'turn': 1, 'step': 1, 'message': {'source': {'kind': 'tool', 'callId': 'b'}}}),
        at(1600, 'tool/result', {'turn': 1, 'step': 1, 'message': {'source': {'kind': 'tool', 'callId': 'a'}}}),
        at(5000, 'tool/result', {'turn': 1, 'step': 1, 'message': {'source': {'kind': 'tool', 'callId': 'ghost'}}}),
        at(5100, 'step/end', {'turn': 1, 'step': 1}),
    ]
    assert fold(events) == totals(turns=1, steps=1, toolMs=3500)