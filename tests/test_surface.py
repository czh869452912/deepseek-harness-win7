import pytest
from dsh.core.surface import (
    SurfaceManager,
    derive_event_message,
    fold_surface,
    is_surface_eligible_type,
    tool_pairing_balanced_after,
    tool_pairing_balanced_before,
)


def test_surface_eligibility():
    assert is_surface_eligible_type("user/message") is True
    assert is_surface_eligible_type("assistant/message") is True
    assert is_surface_eligible_type("tool/result") is True
    assert is_surface_eligible_type("turn/start") is False
    assert is_surface_eligible_type("step/start") is False
    assert is_surface_eligible_type("compaction/start") is False


def test_surface_append_and_derivation():
    events = [
        {"seq": 0, "type": "turn/start", "data": {"turn": 1}},
        {
            "seq": 1,
            "type": "user/message",
            "surfaceOp": "append",
            "data": {"id": "u1", "role": "user", "content": "Hello", "source": None},
        },
        {"seq": 2, "type": "step/start", "data": {"turn": 1, "step": 1}},
        {
            "seq": 3,
            "type": "assistant/message",
            "surfaceOp": "append",
            "data": {
                "message": {
                    "role": "assistant",
                    "content": "Hi there!",
                    "tool_calls": [
                        {"id": "call_1", "function": {"name": "read_file", "arguments": "{}"}}
                    ],
                }
            },
        },
        {
            "seq": 4,
            "type": "tool/result",
            "surfaceOp": "append",
            "data": {
                "tool_call_id": "call_1",
                "result": "File content",
                "message": {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "name": "read_file",
                    "content": "File content",
                },
            },
        },
    ]

    manager = SurfaceManager(events)
    assert manager.nodes == [1, 3, 4]
    assert manager.replace_generation == 0

    # Test derive messages
    m1 = derive_event_message(events[1])
    assert m1 == {"id": "u1", "role": "user", "content": "Hello", "source": None}

    m3 = derive_event_message(events[3])
    assert m3["role"] == "assistant"
    assert m3["content"] == "Hi there!"

    m4 = derive_event_message(events[4])
    assert m4["role"] == "tool"
    assert m4["content"] == "File content"

    # Non-surface event derives to None
    assert derive_event_message(events[0]) is None
    assert derive_event_message(events[2]) is None


def test_surface_replacement():
    events = [
        {
            "seq": 0,
            "type": "user/message",
            "surfaceOp": "append",
            "data": {"content": "Prompt 1"},
        },
        {
            "seq": 1,
            "type": "assistant/message",
            "surfaceOp": "append",
            "data": {"message": {"role": "assistant", "content": "Answer 1"}},
        },
        {
            "seq": 2,
            "type": "user/message",
            "surfaceOp": "append",
            "data": {"content": "Prompt 2"},
        },
    ]

    manager = SurfaceManager(events)
    assert manager.nodes == [0, 1, 2]
    assert manager.replace_generation == 0

    # Replace range [0, 1] with a summary at seq 3
    summary_event = {
        "seq": 3,
        "type": "user/message",
        "surfaceOp": {"op": "replace", "start": 0, "end": 1},
        "sourceEventSeqs": [0, 1],
        "data": {"content": "<summary>Summary of 0 and 1</summary>"},
    }
    events.append(summary_event)

    assert manager.nodes == [3, 2]
    assert manager.replace_generation == 1


def test_surface_validation_failures():
    events = [
        {
            "seq": 0,
            "type": "user/message",
            "surfaceOp": "append",
            "data": {"content": "Prompt 1"},
        }
    ]
    manager = SurfaceManager(events)

    # Missing surfaceOp for surface eligible event
    with pytest.raises(ValueError, match="requires a surfaceOp marker"):
        manager.validate_next({"seq": 1, "type": "user/message", "data": {"content": "x"}})

    # Non-surface event carrying surfaceOp
    with pytest.raises(ValueError, match="cannot carry surfaceOp"):
        manager.validate_next({
            "seq": 1,
            "type": "turn/start",
            "surfaceOp": "append",
            "data": {"turn": 1},
        })

    # Start seq not in surface
    with pytest.raises(ValueError, match="start seq 99 not found"):
        manager.validate_next({
            "seq": 1,
            "type": "user/message",
            "surfaceOp": {"op": "replace", "start": 99, "end": 0},
            "sourceEventSeqs": [99, 0],
            "data": {"content": "rep"},
        })

    # Empty sourceEventSeqs on user/message
    with pytest.raises(ValueError, match="sourceEventSeqs must not be empty"):
        manager.validate_next({
            "seq": 1,
            "type": "user/message",
            "surfaceOp": {"op": "replace", "start": 0, "end": 0},
            "sourceEventSeqs": [],
            "data": {"content": "rep"},
        })

    # Missing sourceEventSeqs coverage when replacing multiple nodes [0, 1] but citing only [0]
    events_multi = [
        {"seq": 0, "type": "user/message", "surfaceOp": "append", "data": {"content": "0"}},
        {"seq": 1, "type": "user/message", "surfaceOp": "append", "data": {"content": "1"}},
    ]
    manager_multi = SurfaceManager(events_multi)
    with pytest.raises(ValueError, match="must include every shadowed surface node"):
        manager_multi.validate_next({
            "seq": 2,
            "type": "user/message",
            "surfaceOp": {"op": "replace", "start": 0, "end": 1},
            "sourceEventSeqs": [0],
            "data": {"content": "rep"},
        })


def test_tool_pairing_balance():
    events = [
        {"seq": 0, "type": "user/message", "surfaceOp": "append", "data": {"content": "Do task"}},
        {
            "seq": 1,
            "type": "assistant/message",
            "surfaceOp": "append",
            "data": {
                "message": {
                    "role": "assistant",
                    "content": "Calling tool",
                    "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}],
                }
            },
        },
        {
            "seq": 2,
            "type": "tool/result",
            "surfaceOp": "append",
            "data": {"tool_call_id": "c1", "result": "res"},
        },
        {"seq": 3, "type": "user/message", "surfaceOp": "append", "data": {"content": "Next"}},
    ]
    surface = [0, 1, 2, 3]

    assert tool_pairing_balanced_before(events, surface, 0) is True
    assert tool_pairing_balanced_before(events, surface, 1) is True

    # Cutting before seq 2 (the tool result) would leave seq 1 (tool call) unanswered!
    assert tool_pairing_balanced_before(events, surface, 2) is False

    # Cutting after seq 2 is balanced (both call and result are included)
    assert tool_pairing_balanced_after(events, surface, 2) is True
    assert tool_pairing_balanced_before(events, surface, 3) is True
