"""
1:1 Test Parity Suite for @deepseek-ai/dsh-session/surface.
Matching packages/core/session/tests/surface.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List, Optional
import pytest

from dsh.core.session import (
    Session,
    SessionId,
    fold_surface,
    foldSurface,
    is_append_surface_event,
    is_replacement_surface_event,
    is_surface_eligible_type,
    is_surface_event,
    isAppendSurfaceEvent,
    isReplacementSurfaceEvent,
    isSurfaceEligibleType,
    isSurfaceEvent,
)
from dsh.core.surface import SurfaceManager
from dsh.llm.message import (
    create_message,
    create_tool_result_message,
    create_user_message,
    createMessage,
    createToolResultMessage,
    createUserMessage,
    freeze_message,
    freezeMessage,
)


def surface_session() -> Session:
    s = Session.create(SessionId("ss"))
    s.append("turn/start", {"turn": 1})
    s.append(
        "user/message",
        create_user_message({
            "content": [{"type": "text", "text": "hello"}],
            "source": {"kind": "user"},
        }),
        surface_op="append",
    )
    s.append(
        "assistant/message",
        {
            "turn": 1,
            "step": 1,
            "message": create_message({
                "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            }),
        },
        surface_op="append",
    )
    s.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
    return s


def provenance_event(seq: int, source_event_seqs: Any) -> Dict[str, Any]:
    ev: Dict[str, Any] = {
        "type": "user/message",
        "seq": seq,
        "time": seq,
        "data": create_user_message({
            "content": [],
            "source": {"kind": "user"},
        }),
        "surfaceOp": "append",
    }
    if source_event_seqs is not None:
        ev["sourceEventSeqs"] = source_event_seqs
    return ev


def tool_result_event(
    seq: int,
    call_id: str,
    surface_op: Any = "append",
    source_event_seqs: Optional[List[int]] = None,
) -> Dict[str, Any]:
    ev: Dict[str, Any] = {
        "type": "tool/result",
        "seq": seq,
        "time": seq,
        "data": {
            "turn": 1,
            "step": 1,
            "message": create_tool_result_message({
                "callId": call_id,
                "content": [{"type": "text", "text": f"result {seq}"}],
                "isError": False,
            }),
        },
        "surfaceOp": surface_op,
    }
    if source_event_seqs is not None:
        ev["sourceEventSeqs"] = source_event_seqs
    return ev


class TestFoldSurfaceSourceEventReferences:
    def test_accepts_absent_or_valid_source_event_references(self):
        events = [
            provenance_event(0, None),
            provenance_event(1, None),
            dict(provenance_event(2, [0, 1]), surfaceOp={"op": "replace", "start": 0, "end": 1}),
        ]
        fold_surface(events)

    def test_rejects_source_event_references_on_a_non_surface_event(self):
        event = {
            "type": "turn/start",
            "seq": 0,
            "time": 1,
            "data": {"turn": 1},
            "sourceEventSeqs": [0],
        }
        with pytest.raises(ValueError, match=r"cannot carry sourceEventSeqs"):
            fold_surface([event])

    def test_accepts_an_explicit_empty_source_event_list_on_an_assistant_message(self):
        event = {
            "type": "assistant/message",
            "seq": 0,
            "time": 0,
            "data": {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            "surfaceOp": "append",
            "sourceEventSeqs": [],
        }
        fold_surface([event])

    @pytest.mark.parametrize(
        "name,events,pattern",
        [
            ("a non-array", [dict(provenance_event(0, None), sourceEventSeqs="invalid")], r"must be an array"),
            ("an empty array", [provenance_event(0, [])], r"must not be empty"),
            ("duplicates", [provenance_event(0, None), provenance_event(1, [0, 0])], r"must not contain duplicates"),
            # A JavaScript sparse-array hole reads as `undefined`; Python's            # closest durable equivalent is a present JSON `null` entry.            ("a sparse array", [dict(provenance_event(0, None), sourceEventSeqs=[None])], r"densely contain"),
            ("a non-number", [dict(provenance_event(0, None), sourceEventSeqs=["0"])], r"non-negative safe integers"),
            ("a fractional number", [provenance_event(0, [0.5])], r"non-negative safe integers"),
            ("a negative number", [provenance_event(0, [-1])], r"non-negative safe integers"),
            ("a self reference", [provenance_event(0, [0])], r"must reference earlier events"),
            ("a non-contiguous event seq", [provenance_event(0, None), provenance_event(2, [1])], r"seq 2 is not contiguous; expected 1"),
            (
                "incomplete replacement coverage",
                [
                    provenance_event(0, None),
                    provenance_event(1, None),
                    dict(provenance_event(2, [0]), surfaceOp={"op": "replace", "start": 0, "end": 1}),
                ],
                r"missing 1",
            ),
        ],
    )
    def test_rejects_invalid_provenance(self, name, events, pattern):
        with pytest.raises(ValueError, match=pattern):
            fold_surface(events)


class TestFoldSurfaceToolResultRewrites:
    def test_rejects_a_replacement_spanning_multiple_current_nodes(self):
        events = [
            provenance_event(0, None),
            provenance_event(1, None),
            tool_result_event(2, "rewrite", {"op": "replace", "start": 0, "end": 1}, [0, 1]),
        ]
        with pytest.raises(ValueError, match=r"must rewrite exactly one current node"):
            fold_surface(events)

    def test_rejects_a_replacement_targeting_a_non_result_node(self):
        events = [
            provenance_event(0, None),
            tool_result_event(1, "rewrite", {"op": "replace", "start": 0, "end": 0}, [0]),
        ]
        with pytest.raises(ValueError, match=r"must target a current tool/result"):
            fold_surface(events)

    def test_rejects_changes_outside_tool_result_content(self):
        events = [
            tool_result_event(0, "original"),
            tool_result_event(1, "changed", {"op": "replace", "start": 0, "end": 0}, [0]),
        ]
        with pytest.raises(ValueError, match=r"may change only content"):
            fold_surface(events)

    @pytest.mark.parametrize(
        "field,patch",
        [
            ("toolCallId", {"toolCallId": "changed"}),
            ("isError", {"isError": True}),
        ],
    )
    def test_rejects_replacement_that_changes_result_block(self, field, patch):
        original = tool_result_event(0, "original")
        data = dict(original["data"])
        msg = dict(data["message"])
        result = dict(msg["content"][0])
        result.update(patch)
        msg["content"] = [result]
        data["message"] = freeze_message(msg)

        replacement = dict(
            original,
            seq=1,
            time=1,
            data=data,
            surfaceOp={"op": "replace", "start": 0, "end": 0},
            sourceEventSeqs=[0],
        )
        with pytest.raises(ValueError, match=r"may change only content"):
            fold_surface([original, replacement])

    def test_compares_array_valued_rest_fields_structurally(self):
        def with_meta(seq: int, meta: Any, surface_op: Any = "append", source_event_seqs: Optional[List[int]] = None) -> Dict[str, Any]:
            event = tool_result_event(seq, "c-meta", surface_op, source_event_seqs)
            data = dict(event["data"])
            msg = dict(data["message"])
            data["message"] = freeze_message(dict(msg, id="meta-message"))
            data["meta"] = meta
            event["data"] = data
            return event

        # Structurally equal arrays pass
        fold_surface([
            with_meta(0, {"tags": ["a", {"n": 1}]}),
            with_meta(1, {"tags": ["a", {"n": 1}]}, {"op": "replace", "start": 0, "end": 0}, [0]),
        ])
        # Same length, drifted element rejects
        with pytest.raises(ValueError, match=r"may change only content"):
            fold_surface([
                with_meta(0, {"tags": ["a"]}),
                with_meta(1, {"tags": ["b"]}, {"op": "replace", "start": 0, "end": 0}, [0]),
            ])
        # Array vs non-array rejects
        with pytest.raises(ValueError, match=r"may change only content"):
            fold_surface([
                with_meta(0, {"tags": ["a"]}),
                with_meta(1, {"tags": "a"}, {"op": "replace", "start": 0, "end": 0}, [0]),
            ])
        # Different key names reject
        with pytest.raises(ValueError, match=r"may change only content"):
            fold_surface([
                with_meta(0, {"left": 1}),
                with_meta(1, {"right": 1}, {"op": "replace", "start": 0, "end": 0}, [0]),
            ])
        # Different key counts reject
        with pytest.raises(ValueError, match=r"may change only content"):
            fold_surface([
                with_meta(0, {"one": 1}),
                with_meta(1, {"one": 1, "two": 2}, {"op": "replace", "start": 0, "end": 0}, [0]),
            ])


class TestSurfaceManager:
    def test_folds_a_contiguous_window_without_materializing_earlier_event_sequences(self):
        base_seq = 400000
        events = [
            provenance_event(base_seq, None),
            provenance_event(base_seq + 1, None),
            dict(provenance_event(base_seq + 2, [base_seq]), surfaceOp={"op": "replace", "start": base_seq, "end": base_seq}),
        ]
        surface = SurfaceManager(events, base_seq)
        assert surface.nodes == [base_seq + 2, base_seq + 1]
        assert surface.replace_generation == 1

    def test_validates_tool_result_rewrites_against_a_nonzero_window_offset(self):
        base_seq = 400000
        original = tool_result_event(base_seq, "call")
        events = [
            original,
            dict(original, seq=base_seq + 1, time=base_seq + 1, surfaceOp={"op": "replace", "start": base_seq, "end": base_seq}, sourceEventSeqs=[base_seq]),
        ]
        assert SurfaceManager(events, base_seq).nodes == [base_seq + 1]

    def test_rejects_a_replacement_that_crosses_a_loaded_window_head(self):
        base_seq = 400000
        events = [
            provenance_event(base_seq, None),
            dict(provenance_event(base_seq + 1, [base_seq - 1, base_seq]), surfaceOp={"op": "replace", "start": base_seq - 1, "end": base_seq}),
        ]
        with pytest.raises(ValueError, match=f"surface replace: start seq {base_seq - 1} not found in surface"):
            _ = SurfaceManager(events, base_seq).nodes

    def test_shares_ordered_entries_and_nested_replacement_ranges_with_fold_surface(self):
        s = Session.create(SessionId("shared-fold"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "b"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("assistant/message", {
            "turn": 1, "step": 1,
            "message": create_message({
                "role": "assistant",
                "content": [{"type": "text", "text": "summary"}],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            }),
        }, surface_op={"op": "replace", "start": 0, "end": 0}, source_event_seqs=[0])
        s.append("assistant/message", {
            "turn": 1, "step": 2,
            "message": create_message({
                "role": "assistant",
                "content": [{"type": "text", "text": "summary 2"}],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            }),
        }, surface_op={"op": "replace", "start": 2, "end": 1}, source_event_seqs=[2, 1])

        folded = fold_surface(s.events)
        assert folded.nodes == s.surface.nodes
        assert folded.replacements == [
            {"seq": 2, "start": 0, "end": 0, "shadowedSeqs": [0]},
            {"seq": 3, "start": 2, "end": 1, "shadowedSeqs": [2, 1]},
        ]
        folded.nodes[0] = 99
        folded.replacements[0].shadowed_seqs.append(99)
        assert s.surface.nodes == [3]
        assert fold_surface(s.events).nodes == [3]
        assert fold_surface(s.events).replacements[0].shadowed_seqs == [0]

    def test_does_not_retain_fold_only_replacement_history_in_incremental_state(self):
        s = Session.create(SessionId("incremental-state"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("assistant/message", {
            "turn": 1, "step": 1,
            "message": create_message({
                "role": "assistant",
                "content": [{"type": "text", "text": "b"}],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            }),
        }, surface_op={"op": "replace", "start": 0, "end": 0}, source_event_seqs=[0])

        assert s.surface.nodes == [1]
        assert not hasattr(s.surface._state, "replacements")
        assert fold_surface(s.events).replacements == [
            {"seq": 1, "start": 0, "end": 0, "shadowedSeqs": [0]},
        ]

    def test_fold_surface_reports_the_same_invalid_replacement_failures_as_incremental_manager(self):
        events = [
            provenance_event(0, None),
            dict(provenance_event(1, [0]), surfaceOp={"op": "replace", "start": 42, "end": 0}),
        ]
        with pytest.raises(ValueError, match=r"start seq 42 not found"):
            fold_surface(events)
        with pytest.raises(ValueError, match=r"start seq 42 not found"):
            Session.create(SessionId("shared-fold-invalid"), events)

    def test_leaves_incremental_state_unchanged_when_candidate_validation_fails(self):
        s = Session.create(SessionId("atomic-validation"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        surface = s.surface
        nodes = surface.nodes

        assert nodes == fold_surface(s.events).nodes
        assert surface.replace_generation == 0

        with pytest.raises(ValueError, match=r"missing 0"):
            s.append(
                "assistant/message",
                {
                    "turn": 1, "step": 1,
                    "message": create_message({
                        "role": "assistant",
                        "content": [{"type": "text", "text": "invalid"}],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
                surface_op={"op": "replace", "start": 0, "end": 0},
            )

        assert len(s.events) == 1
        assert s.surface is surface
        assert surface.nodes == [0]
        assert surface.replace_generation == 0
        assert surface.nodes == fold_surface(s.events).nodes

        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "b"}], "source": {"kind": "user"},
        }), surface_op="append")
        assert surface.nodes == [0, 1]
        assert surface.replace_generation == 0
        assert surface.nodes == fold_surface(s.events).nodes

    def test_fold_surface_rejects_a_surface_eligible_event_without_its_mandatory_marker(self):
        malformed = {
            "type": "user/message",
            "seq": 0,
            "time": 1,
            "data": create_user_message({
                "content": [{"type": "text", "text": "hidden"}], "source": {"kind": "user"},
            }),
        }
        with pytest.raises(ValueError, match=r"surface-eligible and requires a surfaceOp marker"):
            fold_surface([malformed])

    def test_fold_surface_rejects_surface_op_on_a_non_surface_event(self):
        malformed = {
            "type": "turn/start",
            "seq": 0,
            "time": 1,
            "data": {"turn": 1},
            "surfaceOp": "append",
        }
        with pytest.raises(ValueError, match=r"not surface-eligible and cannot carry surfaceOp"):
            fold_surface([malformed])

    def test_folds_an_ordered_sequence_list_from_surface_op_append_markers(self):
        s = surface_session()
        assert s.surface.nodes == [1, 2]

    def test_empty_surface_yields_empty_nodes(self):
        s = Session.create(SessionId("empty"))
        s.append("turn/start", {"turn": 1})
        s.append("step/start", {"turn": 1, "step": 1})
        s.append("step/end", {"turn": 1, "step": 1})
        s.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
        assert len(s.surface.nodes) == 0
        assert s.derive_messages() == []

    def test_picks_up_new_events_incrementally(self):
        s = surface_session()
        assert len(s.surface.nodes) == 2
        s.append("tool/result", {
            "turn": 1, "step": 1,
            "message": create_tool_result_message({
                "callId": "c1",
                "content": [{"type": "text", "text": "ok"}],
                "isError": False,
            }),
        }, surface_op="append")
        assert len(s.surface.nodes) == 3
        assert s.surface.nodes[2] == 4

    def test_replays_identically_from_a_seeded_log_with_surface_markers(self):
        original = surface_session()
        original.append("tool/result", {
            "turn": 1, "step": 1,
            "message": create_tool_result_message({
                "callId": "c1",
                "content": [{"type": "text", "text": "ok"}],
                "isError": False,
            }),
        }, surface_op="append")
        replayed = Session.create(SessionId("replay"), list(original.events))
        assert replayed.surface.nodes == [1, 2, 4]
        assert replayed.derive_messages() == original.derive_messages()

    def test_rebuild_with_replace_operation_splices_out_shadowed_nodes(self):
        s = surface_session()
        s.append(
            "assistant/message",
            {
                "turn": 2, "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "text", "text": "summary"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op={"op": "replace", "start": 1, "end": 2},
            source_event_seqs=[1, 2],
        )
        assert s.surface.nodes == [4]

    def test_replace_with_both_ends_at_real_nodes_splices_only_the_range(self):
        s = Session.create(SessionId("range"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "b"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "c"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append(
            "assistant/message",
            {
                "turn": 1, "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "text", "text": "summary"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op={"op": "replace", "start": 0, "end": 1},
            source_event_seqs=[0, 1],
        )
        assert s.surface.nodes == [3, 2]

    def test_single_node_replacement(self):
        s = Session.create(SessionId("single"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "b"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append(
            "assistant/message",
            {
                "turn": 1, "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "text", "text": "x"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op={"op": "replace", "start": 1, "end": 1},
            source_event_seqs=[1],
        )
        assert s.surface.nodes == [0, 2]

    def test_throws_when_replace_start_is_not_found(self):
        s = Session.create(SessionId("bad-start"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        with pytest.raises(ValueError, match=r"surface replace: start seq 5 not found"):
            s.append(
                "assistant/message",
                {
                    "turn": 1, "step": 1,
                    "message": create_message({
                        "role": "assistant",
                        "content": [{"type": "text", "text": "y"}],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
                surface_op={"op": "replace", "start": 5, "end": 0},
                source_event_seqs=[0],
            )

    def test_throws_when_replace_end_is_not_found(self):
        s = Session.create(SessionId("bad-end"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        with pytest.raises(ValueError, match=r"surface replace: end seq 99 not found"):
            s.append(
                "assistant/message",
                {
                    "turn": 1, "step": 1,
                    "message": create_message({
                        "role": "assistant",
                        "content": [{"type": "text", "text": "y"}],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
                surface_op={"op": "replace", "start": 0, "end": 99},
                source_event_seqs=[0],
            )

    def test_throws_when_start_is_after_end(self):
        s = Session.create(SessionId("reversed"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "b"}], "source": {"kind": "user"},
        }), surface_op="append")
        with pytest.raises(ValueError, match=r"start seq 1.*after end seq 0"):
            s.append(
                "assistant/message",
                {
                    "turn": 1, "step": 1,
                    "message": create_message({
                        "role": "assistant",
                        "content": [{"type": "text", "text": "y"}],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
                surface_op={"op": "replace", "start": 1, "end": 0},
                source_event_seqs=[1, 0],
            )

    def test_source_event_seqs_is_snapshot(self):
        s = Session.create(SessionId("immutable"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "source"}], "source": {"kind": "user"},
        }), surface_op="append")
        sources = [0]
        s.append("assistant/message", {
            "turn": 1, "step": 1,
            "message": create_message({
                "role": "assistant",
                "content": [{"type": "text", "text": "h"}],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            }),
        }, surface_op="append", source_event_seqs=sources)
        sources.append(1)
        sources[0] = 99
        logged = s.events[1]
        assert logged.get("sourceEventSeqs") == [0]

    def test_replace_starting_at_non_head_position_preserves_surrounding_order(self):
        s = Session.create(SessionId("mid-replace"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "b"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "c"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append(
            "assistant/message",
            {
                "turn": 1, "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "text", "text": "x"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op={"op": "replace", "start": 1, "end": 1},
            source_event_seqs=[1],
        )
        assert s.surface.nodes == [0, 3, 2]

    def test_surface_op_replace_object_is_snapshot(self):
        s = Session.create(SessionId("immutable-op"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "a"}], "source": {"kind": "user"},
        }), surface_op="append")
        op = {"op": "replace", "start": 0, "end": 0}
        s.append("assistant/message", {
            "turn": 1, "step": 1,
            "message": create_message({
                "role": "assistant",
                "content": [{"type": "text", "text": "s"}],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            }),
        }, surface_op=op, source_event_seqs=[0])
        op["start"] = 99
        logged = s.events[1]
        assert logged.get("surfaceOp") == {"op": "replace", "start": 0, "end": 0}


class TestDeriveMessagesWithSurface:
    def test_uses_surface_path_when_surface_markers_are_present(self):
        s = surface_session()
        messages = s.derive_messages()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"][0]["text"] == "hello"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"][0]["text"] == "hi"

    def test_surface_path_skips_non_surface_events(self):
        s = Session.create(SessionId("filter"))
        s.append("turn/start", {"turn": 1})
        s.append("assistant/chunk", {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "h"}})
        s.append("assistant/chunk", {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 1, "text": "i"}})
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "hello"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("assistant/message", {
            "turn": 1, "step": 1,
            "message": create_message({
                "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            }),
        }, surface_op="append")
        s.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
        assert len(s.derive_messages()) == 2

    def test_derive_messages_respects_replace(self):
        s = Session.create(SessionId("compacted"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "original"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("assistant/message", {
            "turn": 1, "step": 1,
            "message": create_message({
                "role": "assistant",
                "content": [{"type": "text", "text": "compacted"}],
                "source": {"kind": "model", "provider": "mock", "model": "mock"},
            }),
        }, surface_op={"op": "replace", "start": 0, "end": 0}, source_event_seqs=[0])
        messages = s.derive_messages()
        assert len(messages) == 1
        assert messages[0]["content"][0]["text"] == "compacted"

    def test_injected_context_and_user_messages_appear_on_surface(self):
        s = Session.create(SessionId("ctx"))
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "file changed"}], "source": {"kind": "plugin", "plugin": "watcher"},
        }), surface_op="append")
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "focus"}], "source": {"kind": "user"},
        }), surface_op="append")
        messages = s.derive_messages()
        assert len(messages) == 2
        assert messages[0]["content"] == [{"type": "text", "text": "file changed"}]
        assert messages[1]["content"] == [{"type": "text", "text": "focus"}]

    def test_derive_messages_skips_a_surface_node_that_derives_to_null(self):
        seed = [
            {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}},
            {"type": "step/start", "seq": 1, "time": 2, "data": {"turn": 1, "step": 1}},
            {
                "type": "assistant/message",
                "seq": 2,
                "time": 3,
                "data": {
                    "turn": 1, "step": 1,
                    "message": create_message({
                        "role": "assistant",
                        "content": [],
                        "source": {"kind": "model", "provider": "mock", "model": "mock"},
                    }),
                },
                "surfaceOp": "append",
            },
            {"type": "step/end", "seq": 3, "time": 4, "data": {"turn": 1, "step": 1}},
            {"type": "turn/end", "seq": 4, "time": 5, "data": {"turn": 1, "reason": {"kind": "completed"}}},
        ]
        s = Session.create(SessionId("nomessage"), seed)
        assert len(s.derive_messages()) == 0


class TestSurfaceTypeGuards:
    def test_is_surface_eligible_type(self):
        assert is_surface_eligible_type("user/message") is True
        assert is_surface_eligible_type("assistant/message") is True
        assert is_surface_eligible_type("tool/result") is True
        assert is_surface_eligible_type("turn/start") is False
        assert is_surface_eligible_type("assistant/chunk") is False

    def test_is_surface_event_narrows_fully_formed_surface_event(self):
        s = surface_session()
        user_msg = next(e for e in s.events if e["type"] == "user/message")
        assert is_surface_event(user_msg) is True

    def test_is_surface_event_rejects_non_surface_eligible_type(self):
        s = surface_session()
        turn_start = next(e for e in s.events if e["type"] == "turn/start")
        assert is_surface_event(turn_start) is False

    def test_is_surface_event_rejects_surface_eligible_type_missing_marker(self):
        markerless = {
            "type": "user/message",
            "seq": 0,
            "time": 0,
            "data": create_user_message({
                "content": [{"type": "text", "text": "hi"}], "source": {"kind": "user"},
            }),
        }
        assert is_surface_eligible_type(markerless["type"]) is True
        assert is_surface_event(markerless) is False

    def test_splits_surface_events_into_append_origin_and_replacement(self):
        s = surface_session()
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "checkpoint"}], "source": {"kind": "plugin", "plugin": "compact"},
        }), surface_op={"op": "replace", "start": 1, "end": 2}, source_event_seqs=[1, 2])
        appended = next(e for e in s.events if e["type"] == "user/message")
        replacement = s.events[-1]

        assert is_append_surface_event(appended) is True
        assert is_replacement_surface_event(appended) is False
        assert is_append_surface_event(replacement) is False
        assert is_replacement_surface_event(replacement) is True

    def test_rejects_log_only_and_markerless_events_from_both_marker_guards(self):
        s = surface_session()
        turn_start = next(e for e in s.events if e["type"] == "turn/start")
        markerless = {
            "type": "user/message",
            "seq": 0,
            "time": 0,
            "data": create_user_message({
                "content": [{"type": "text", "text": "hi"}], "source": {"kind": "user"},
            }),
        }
        assert is_append_surface_event(turn_start) is False
        assert is_replacement_surface_event(turn_start) is False
        assert is_append_surface_event(markerless) is False
        assert is_replacement_surface_event(markerless) is False


class TestSurfaceManagerReplaceGeneration:
    def test_folds_pending_log_delta_on_access_and_counts_replaces(self):
        s = Session.create(SessionId("gen"))
        s.append("turn/start", {"turn": 1})
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "one"}], "source": {"kind": "user"},
        }), surface_op="append")
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "two"}], "source": {"kind": "user"},
        }), surface_op="append")

        assert s.surface.replace_generation == 0

        nodes = s.surface.nodes
        s.append("user/message", create_user_message({
            "content": [{"type": "text", "text": "summary"}], "source": {"kind": "plugin", "plugin": "compact"},
        }), surface_op={"op": "replace", "start": nodes[0], "end": nodes[1]}, source_event_seqs=[nodes[0], nodes[1]])
        assert s.surface.replace_generation == 1


class TestSurfaceEventProjectionFields:
    def test_records_source_event_seqs_and_surface_op_on_the_event(self):
        session = Session.create(SessionId("opts"))
        session.append("turn/start", {"turn": 1})
        session.append("step/start", {"turn": 1, "step": 1})
        event = session.append(
            "assistant/message",
            {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [{"type": "text", "text": "h"}],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op="append",
            source_event_seqs=[0, 1],
        )
        assert event["sourceEventSeqs"] == [0, 1]
        assert event["surfaceOp"] == "append"
        # The logged event matches the returned event.
        assert session.events[2]["sourceEventSeqs"] == [0, 1]
        assert session.events[2]["surfaceOp"] == "append"

    def test_a_non_surface_event_carries_no_surface_fields(self):
        session = Session.create(SessionId("noopts"))
        session.append("turn/start", {"turn": 1})
        assert session.events[0].get("sourceEventSeqs") is None
        assert session.events[0].get("surfaceOp") is None

    def test_surface_op_primitives_are_not_cloned(self):
        session = Session.create(SessionId("prim"))
        event = session.append(
            "assistant/message",
            {
                "turn": 1,
                "step": 1,
                "message": create_message({
                    "role": "assistant",
                    "content": [],
                    "source": {"kind": "model", "provider": "mock", "model": "mock"},
                }),
            },
            surface_op="append",
        )
        # `'append'` is an immutable primitive: it is recorded by value, and the
        # recorded marker is the canonical string.
        assert event["surfaceOp"] == "append"
        assert type(event["surfaceOp"]) is str


# ============================================================================
# surface.spec.ts does not isolate these runtime guard shapes with a single
# upstream case each: they pin the reference rules `foldSurface`/`SurfaceManager`
# apply before any fold state mutates (surface.ts:186-246).
# ============================================================================


class TestReferenceSurfaceGuardShapes:
    def test_rejects_a_log_only_event_carrying_a_null_surface_op(self):
        events = [{
            "type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1},
            "surfaceOp": None,
        }]
        with pytest.raises(ValueError, match="not surface-eligible and cannot carry surfaceOp"):
            fold_surface(events)

    def test_rejects_a_surface_eligible_event_carrying_a_null_surface_op(self):
        events = [{
            "type": "user/message", "seq": 0, "time": 1,
            "data": create_user_message({
                "content": [{"type": "text", "text": "x"}], "source": {"kind": "user"},
            }),
            "surfaceOp": None,
        }]
        with pytest.raises(ValueError, match="carries an invalid surfaceOp"):
            fold_surface(events)

    def test_rejects_a_replace_surface_op_with_unknown_keys(self):
        events = [
            provenance_event(0, None),
            dict(
                provenance_event(1, [0]),
                surfaceOp={"op": "replace", "start": 0, "end": 0, "extra": 1},
            ),
        ]
        with pytest.raises(ValueError, match="invalid replace surfaceOp"):
            fold_surface(events)

    def test_rejects_a_present_but_null_source_event_seqs_list(self):
        events = [dict(provenance_event(0, None), sourceEventSeqs=None)]
        with pytest.raises(ValueError, match="must be an array when present"):
            fold_surface(events)

    def test_exposes_the_live_ordered_surface_view(self):
        session = surface_session()
        # `get nodes()` is a readonly view over the fold state, not a copy.
        assert session.surface.nodes is session.surface.nodes
