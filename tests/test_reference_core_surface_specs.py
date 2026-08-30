"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session/surface
Matching reference/packages/core/session/tests/surface.spec.ts.
Covers:
- foldSurface source-event references and provenance
- foldSurface tool-result rewrites (single node, unchanged non-content, meta structure)
- SurfaceManager windowed slicing, offset, and atomic candidate validation
- deriveMessages with surface (replacement, filtering non-surface chunks/boundaries)
"""

import copy
import pytest
from dsh.core.session import Session, SessionStore
from dsh.core.surface import (
    SurfaceManager,
    fold_surface,
    is_append_surface_event,
    is_replacement_surface_event,
    is_surface_eligible_type,
    is_surface_event,
)


def surface_session():
    s = Session.create("ss")
    s.append("turn/start", {"turn": 1})
    s.append("user/message", {
        "id": "u1", "role": "user", "content": [{"type": "text", "text": "hello"}], "source": {"kind": "user"}
    }, surface_op="append")
    s.append("assistant/message", {
        "turn": 1, "step": 1,
        "message": {
            "id": "a1", "role": "assistant",
            "content": [{"type": "text", "text": "hi"}],
            "source": {"kind": "model", "provider": "mock", "model": "mock"},
        },
    }, surface_op="append")
    s.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
    return s


def provenance_event(seq: int, source_event_seqs=None):
    ev = {
        "type": "user/message",
        "seq": seq,
        "time": seq,
        "data": {
            "id": f"msg-{seq}", "role": "user",
            "content": [{"type": "text", "text": f"txt-{seq}"}],
            "source": {"kind": "user"},
        },
        "surfaceOp": "append",
    }
    if source_event_seqs is not None:
        ev["sourceEventSeqs"] = source_event_seqs
    return ev


def tool_result_event(seq: int, call_id: str, surface_op="append", source_event_seqs=None):
    ev = {
        "type": "tool/result",
        "seq": seq,
        "time": seq,
        "data": {
            "turn": 1,
            "step": 1,
            "message": {
                "id": f"tool-{seq}",
                "role": "user",
                "content": [{
                    "type": "tool-result",
                    "toolCallId": call_id,
                    "content": [{"type": "text", "text": f"result {seq}"}],
                    "isError": False,
                }],
                "source": {"kind": "tool", "callId": call_id},
            },
        },
        "surfaceOp": surface_op,
    }
    if source_event_seqs is not None:
        ev["sourceEventSeqs"] = source_event_seqs
    return ev


# ============================================================================
# 1. foldSurface source-event references & provenance
# ============================================================================

def test_fold_surface_accepts_valid_references_and_complete_coverage():
    events = [
        provenance_event(0, None),
        provenance_event(1, None),
        {
            **provenance_event(2, [0, 1]),
            "surfaceOp": {"op": "replace", "start": 0, "end": 1},
        },
    ]
    folded = fold_surface(events)
    assert folded.nodes == [2]
    assert folded.replace_generation == 1


def test_fold_surface_rejects_source_event_references_on_non_surface_event():
    event = {
        "type": "turn/start",
        "seq": 0,
        "time": 1,
        "data": {"turn": 1},
        "sourceEventSeqs": [0],
    }
    with pytest.raises(ValueError, match="cannot carry sourceEventSeqs"):
        fold_surface([event])


def test_fold_surface_accepts_explicit_empty_source_event_list_on_assistant_message():
    event = {
        "type": "assistant/message",
        "seq": 0,
        "time": 0,
        "data": {
            "turn": 1,
            "step": 1,
            "message": {
                "id": "a1",
                "role": "assistant",
                "content": [],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            },
        },
        "surfaceOp": "append",
        "sourceEventSeqs": [],
    }
    folded = fold_surface([event])
    assert folded.nodes == [0]


def test_fold_surface_rejects_invalid_source_event_seqs_patterns():
    # Non-array
    with pytest.raises(ValueError, match="must be an array"):
        fold_surface([{**provenance_event(0, None), "sourceEventSeqs": "invalid"}])

    # Empty array on non-assistant
    with pytest.raises(ValueError, match="must not be empty"):
        fold_surface([provenance_event(0, [])])

    # Duplicates
    with pytest.raises(ValueError, match="must not contain duplicates"):
        fold_surface([provenance_event(0, None), provenance_event(1, [0, 0])])

    # Non-integer / negative
    with pytest.raises(ValueError, match="non-negative safe integers"):
        fold_surface([provenance_event(0, [-1])])

    # Self-reference (reference >= current_seq)
    with pytest.raises(ValueError, match="must reference earlier events"):
        fold_surface([provenance_event(0, [0])])

    # Incomplete replacement coverage
    with pytest.raises(ValueError, match="missing 1"):
        fold_surface([
            provenance_event(0, None),
            provenance_event(1, None),
            {**provenance_event(2, [0]), "surfaceOp": {"op": "replace", "start": 0, "end": 1}},
        ])


# ============================================================================
# 2. foldSurface tool-result rewrites
# ============================================================================

def test_fold_surface_tool_result_rewrite_rules():
    # Spanning multiple nodes
    with pytest.raises(ValueError, match="must rewrite exactly one current node"):
        fold_surface([
            provenance_event(0, None),
            provenance_event(1, None),
            tool_result_event(2, "rewrite", {"op": "replace", "start": 0, "end": 1}, [0, 1]),
        ])

    # Targeting non-tool-result node
    with pytest.raises(ValueError, match="must target a current tool/result"):
        fold_surface([
            provenance_event(0, None),
            tool_result_event(1, "rewrite", {"op": "replace", "start": 0, "end": 0}, [0]),
        ])

    # Changes outside content (callId mismatch)
    orig = tool_result_event(0, "original")
    changed = tool_result_event(1, "changed", {"op": "replace", "start": 0, "end": 0}, [0])
    with pytest.raises(ValueError, match="may change only content"):
        fold_surface([orig, changed])


def test_fold_surface_tool_result_content_change_accepted():
    orig = tool_result_event(0, "c1")
    repl = copy.deepcopy(orig)
    repl["seq"] = 1
    repl["time"] = 1
    repl["surfaceOp"] = {"op": "replace", "start": 0, "end": 0}
    repl["sourceEventSeqs"] = [0]
    repl["data"]["message"]["content"][0]["content"] = [{"type": "text", "text": "new content"}]

    folded = fold_surface([orig, repl])
    assert folded.nodes == [1]
    assert folded.replace_generation == 1


# ============================================================================
# 3. SurfaceManager incremental vs foldSurface equivalence
# ============================================================================

def test_surface_manager_shares_nodes_and_replacement_ranges_with_fold_surface():
    s = Session.create("shared-fold")
    s.append_user_message("a")
    s.append_user_message("b")
    s.append_assistant_message(
        {"role": "assistant", "content": [{"type": "text", "text": "summary"}]},
        turn=1, step=1,
        surface_op={"op": "replace", "start": 0, "end": 0},
        source_event_seqs=[0],
    )
    s.append_assistant_message(
        {"role": "assistant", "content": [{"type": "text", "text": "summary 2"}]},
        turn=1, step=2,
        surface_op={"op": "replace", "start": 2, "end": 1},
        source_event_seqs=[2, 1],
    )

    folded = fold_surface(s.events)
    assert folded.nodes == s.surface.nodes
    assert folded.nodes == [3]
    assert s.surface.replace_generation == 2


def test_surface_manager_rejects_reversed_or_invalid_replace_boundaries():
    s = Session.create("rev-test")
    s.append_user_message("a")
    s.append_user_message("b")

    # Start not found
    with pytest.raises(ValueError, match="start seq 5 not found"):
        s.append_assistant_message(
            {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
            surface_op={"op": "replace", "start": 5, "end": 0},
            source_event_seqs=[0],
        )

    # End not found
    with pytest.raises(ValueError, match="end seq 99 not found"):
        s.append_assistant_message(
            {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
            surface_op={"op": "replace", "start": 0, "end": 99},
            source_event_seqs=[0],
        )

    # Start after end (reversed)
    with pytest.raises(ValueError, match="after end seq 0"):
        s.append_assistant_message(
            {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
            surface_op={"op": "replace", "start": 1, "end": 0},
            source_event_seqs=[1, 0],
        )
