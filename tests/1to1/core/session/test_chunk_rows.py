"""
1:1 Test Parity Suite matching reference/packages/core/session/tests/chunk-rows.spec.ts.
Covers:
- packChunkRuns text-delta, reasoning-delta, tool-call-delta runs
- name-less tool-call runs
- runs shorter than 3 left verbatim
- non-delta chunks and non-chunk events left verbatim
- run breaking rules (seq gap, kind switch, block-index switch, step switch, id/name switch)
- off-whitelist delta stored verbatim
- decodeStorageRecord pass-through, clock step-back negative dt, and malformed row exceptions
- property: pack -> decode reproduces batches exactly
"""

import copy
import json
import random
import pytest
from typing import Any, Dict, List

from dsh.core.session.chunk_rows import (
    chunkRowLength,
    chunk_row_length,
    decodeStorageRecord,
    decode_storage_record,
    isChunkRow,
    is_chunk_row,
    packChunkRuns,
    pack_chunk_runs,
    MAX_SAFE_INTEGER,
)


def chunk_event(seq: int, ev_time: int, chunk: Dict[str, Any], turn: int = 1, step: int = 1) -> Dict[str, Any]:
    return {"type": "assistant/chunk", "seq": seq, "time": ev_time, "data": {"turn": turn, "step": step, "chunk": chunk}}


def delta_run(kind: str, count: int, seq0: int = 0, index: int = 0) -> List[Dict[str, Any]]:
    return [
        chunk_event(seq0 + k, 1000 + 10 * k, {"type": kind, "index": index, "text": f"t{k}"})
        for k in range(count)
    ]


def decode_all(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in records:
        parsed = json.loads(json.dumps(r))
        out.extend(decode_storage_record(parsed))
    return out


class TestPackChunkRuns:
    def test_packs_text_delta_run_into_one_text_chunks_row_and_round_trips_it(self):
        events = delta_run("text-delta", 5)
        packed = pack_chunk_runs(events)
        assert len(packed) == 1
        row = packed[0]
        assert row["type"] == "text-chunks"
        assert row["seq0"] == 0
        assert row["time0"] == 1000
        assert row["data"]["turn"] == 1
        assert row["data"]["step"] == 1
        assert row["data"]["index"] == 0
        assert row["data"]["dt"] == [10, 10, 10, 10]
        assert row["data"]["texts"] == ["t0", "t1", "t2", "t3", "t4"]

        assert is_chunk_row(row) is True
        assert isChunkRow(row) is True
        assert chunk_row_length(row) == 5
        assert chunkRowLength(row) == 5
        assert is_chunk_row(events[0]) is False
        assert decode_all(packed) == events

    def test_packs_reasoning_and_tool_call_runs_under_their_own_tags(self):
        reasoning = delta_run("reasoning-delta", 3)
        tool_call = [
            chunk_event(
                seq,
                1000 + seq,
                {"type": "tool-call-delta", "index": 1, "id": "c1", "name": "write", "argumentsDelta": f"a{seq}"},
            )
            for seq in [4, 5, 6]
        ]
        packed = pack_chunk_runs(reasoning + tool_call)
        assert [r["type"] for r in packed] == ["reasoning-chunks", "tool-call-chunks"]
        row = packed[1]
        assert row["data"]["id"] == "c1"
        assert row["data"]["name"] == "write"
        assert row["data"]["args"] == ["a4", "a5", "a6"]
        assert chunk_row_length(row) == 3
        assert decode_all(packed) == (reasoning + tool_call)

    def test_packs_name_less_tool_call_run_and_round_trips_field_absence(self):
        events = [
            chunk_event(seq, 1000, {"type": "tool-call-delta", "index": 0, "id": "c1", "argumentsDelta": f"a{seq}"})
            for seq in [0, 1, 2]
        ]
        packed = pack_chunk_runs(events)
        assert len(packed) == 1
        assert "name" not in packed[0]["data"]
        decoded = decode_all(packed)
        assert decoded == events
        assert all("name" not in e["data"]["chunk"] for e in decoded)

    def test_leaves_runs_shorter_than_three_events_verbatim(self):
        events = delta_run("text-delta", 2)
        assert pack_chunk_runs(events) == events

    def test_leaves_non_delta_chunks_and_non_chunk_events_verbatim_between_runs(self):
        events = [
            chunk_event(0, 1000, {"type": "block-start", "index": 0, "blockType": "text"}),
            *delta_run("text-delta", 3, 1),
            chunk_event(4, 1040, {"type": "block-end", "index": 0, "block": {"type": "text", "text": "t0t1t2"}}),
            {"type": "step/end", "seq": 5, "time": 1050, "data": {"turn": 1, "step": 1}},
        ]
        packed = pack_chunk_runs(events)
        assert len(packed) == 4
        assert packed[1]["type"] == "text-chunks"
        assert decode_all(packed) == events

    @pytest.mark.parametrize(
        "label,events",
        [
            ("a seq gap", [e if k != 2 else dict(e, seq=9) for k, e in enumerate(delta_run("text-delta", 3))]),
            ("a kind switch", delta_run("text-delta", 2) + delta_run("reasoning-delta", 1, 2)),
            ("a block-index switch", delta_run("text-delta", 2) + delta_run("text-delta", 1, 2, 7)),
            (
                "a step switch",
                [
                    chunk_event(e["seq"], e["time"], e["data"]["chunk"], 1, 2) if k == 2 else e
                    for k, e in enumerate(delta_run("text-delta", 3))
                ],
            ),
        ],
    )
    def test_breaks_a_run_on_switch(self, label, events):
        assert pack_chunk_runs(events) == events

    def test_breaks_a_tool_call_run_on_call_id_or_name_change(self):
        def call(seq: int, cid: str, name: str = None) -> Dict[str, Any]:
            c = {"type": "tool-call-delta", "index": 0, "id": cid, "argumentsDelta": "a"}
            if name is not None:
                c["name"] = name
            return chunk_event(seq, 1000, c)

        id_switch = [call(0, "c1", "w"), call(1, "c1", "w"), call(2, "c2", "w")]
        assert pack_chunk_runs(id_switch) == id_switch

        name_presence = [call(0, "c1", "w"), call(1, "c1", "w"), call(2, "c1")]
        assert pack_chunk_runs(name_presence) == name_presence

    def test_stores_an_off_whitelist_delta_verbatim(self):
        extra_field = dict(chunk_event(0, 1000, {"type": "text-delta", "index": 0, "text": "x"}), surfaceOp="append")
        bad_text = chunk_event(1, 1001, {"type": "text-delta", "index": 0, "text": 7})
        events = [extra_field, bad_text]
        assert pack_chunk_runs(events) == events

    def test_stores_delta_with_off_whitelist_data_envelope_verbatim(self):
        def mk(seq: int, data: Any) -> Dict[str, Any]:
            return {"type": "assistant/chunk", "seq": seq, "time": 1000, "data": data}

        events = [
            mk(0, "not-an-object"),
            mk(1, {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "a"}, "extra": 1}),
            mk(2, {"turn": "x", "step": 1, "chunk": {"type": "text-delta", "index": 0, "text": "a"}}),
            mk(3, {"turn": 1, "step": 1, "chunk": "not-an-object"}),
            mk(4, {"turn": 1, "step": 1, "chunk": {"type": "text-delta", "index": "x", "text": "a"}}),
            mk(5, {"turn": 1, "step": 1, "chunk": {"type": "tool-call-delta", "index": 0, "id": 7, "argumentsDelta": "a"}}),
        ]
        assert pack_chunk_runs(events) == events


class TestDecodeStorageRecord:
    def test_passes_non_row_values_through_unvalidated(self):
        event = {"type": "turn/start", "seq": 0, "time": 1, "data": {"turn": 1}}
        assert decode_storage_record(event) == [event]
        assert decode_storage_record("junk") == ["junk"]
        assert decode_storage_record(None) == [None]

    def test_reconstructs_timestamps_through_negative_dt_gaps(self):
        events = [
            chunk_event(0, 1000, {"type": "text-delta", "index": 0, "text": "a"}),
            chunk_event(1, 990, {"type": "text-delta", "index": 0, "text": "b"}),
            chunk_event(2, 995, {"type": "text-delta", "index": 0, "text": "c"}),
        ]
        assert decode_all(pack_chunk_runs(events)) == events

    @pytest.mark.parametrize(
        "label,row",
        [
            ("a non-object data", {"type": "text-chunks", "seq0": 0, "time0": 1, "data": "x"}),
            ("an envelope with extra keys", {"type": "text-chunks", "seq0": 0, "time0": 1, "data": {"turn": 1, "step": 1, "index": 0, "dt": [], "texts": ["a"]}, "extra": 1}),
            ("a negative seq0", {"type": "text-chunks", "seq0": -1, "time0": 1, "data": {"turn": 1, "step": 1, "index": 0, "dt": [], "texts": ["a"]}}),
            ("a data shape mismatch", {"type": "text-chunks", "seq0": 0, "time0": 1, "data": {"turn": 1, "step": 1, "index": 0, "dt": [], "args": ["a"]}}),
            ("a non-string member", {"type": "text-chunks", "seq0": 0, "time0": 1, "data": {"turn": 1, "step": 1, "index": 0, "dt": [], "texts": [7]}}),
            ("an empty member list", {"type": "text-chunks", "seq0": 0, "time0": 1, "data": {"turn": 1, "step": 1, "index": 0, "dt": [], "texts": []}}),
            ("a dt arity mismatch", {"type": "text-chunks", "seq0": 0, "time0": 1, "data": {"turn": 1, "step": 1, "index": 0, "dt": [1, 2], "texts": ["a", "b"]}}),
            ("a non-numeric turn", {"type": "text-chunks", "seq0": 0, "time0": 1, "data": {"turn": "x", "step": 1, "index": 0, "dt": [], "texts": ["a"]}}),
            ("a tool-call row without id", {"type": "tool-call-chunks", "seq0": 0, "time0": 1, "data": {"turn": 1, "step": 1, "index": 0, "dt": [], "args": ["a"]}}),
            ("a tool-call row with non-string id", {"type": "tool-call-chunks", "seq0": 0, "time0": 1, "data": {"turn": 1, "step": 1, "index": 0, "id": 7, "dt": [], "args": ["a"]}}),
        ],
    )
    def test_throws_on_malformed_row(self, label, row):
        with pytest.raises(ValueError, match=r"malformed .* storage row"):
            decode_storage_record(row)

    def test_property_random_batches_reproduce_identically(self):
        rng = random.Random(42)
        chunk_kinds = ["text-delta", "reasoning-delta", "tool-call-delta", "block-start"]

        for _ in range(50):
            batch_len = rng.randint(0, 30)
            events = []
            cur_time = 1000
            for seq in range(batch_len):
                kind = rng.choice(chunk_kinds)
                cur_time += rng.randint(-10, 50)
                if kind in ("text-delta", "reasoning-delta"):
                    chunk = {"type": kind, "index": 0, "text": f"text_{seq}"}
                elif kind == "tool-call-delta":
                    chunk = {"type": kind, "index": 0, "id": "call_1", "argumentsDelta": f"arg_{seq}"}
                else:
                    chunk = {"type": kind, "index": 0, "blockType": "text"}
                events.append(chunk_event(seq, cur_time, chunk, turn=1, step=1))

            assert decode_all(pack_chunk_runs(events)) == events
