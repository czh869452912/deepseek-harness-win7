"""
1:1 Test Parity Suite matching reference/packages/core/session/tests/seq-ranges.spec.ts.
Covers:
- sourceEventSeqs ranges round-trips
- encodes only profitable increasing runs
- does not impose a persistence-only provenance length limit (1_000_001 items)
- rejects malformed or impossible expansions
"""

import pytest
from dsh.core.session.seq_ranges import (
    decode_seq_ranges,
    encode_seq_ranges,
    decodeSeqRanges,
    encodeSeqRanges,
    MAX_SAFE_INTEGER,
)


class TestSourceEventSeqsRanges:
    @pytest.mark.parametrize(
        "values",
        [
            [],
            [5],
            [10, 11, 12, 13, 14],
            [16, 17, 100, 200, 201, 202, 203],
            [3, 2],
            [MAX_SAFE_INTEGER - 1, 0, MAX_SAFE_INTEGER - 2],
        ],
    )
    def test_round_trips(self, values):
        assert decode_seq_ranges(encode_seq_ranges(values)) == values
        assert decodeSeqRanges(encodeSeqRanges(values)) == values

    def test_encodes_only_profitable_increasing_runs(self):
        assert encode_seq_ranges([1, 3, 4, 5, 7]) == [1, [3, 5], 7]
        assert encode_seq_ranges([1, 3, 4, 7]) == [1, 3, 4, 7]
        assert encode_seq_ranges([3, 2]) == [3, 2]

    def test_does_not_impose_persistence_only_provenance_length_limit(self):
        values = list(range(1_000_001))
        assert encode_seq_ranges(values) == [[0, 1_000_000]]

    def test_rejects_malformed_or_impossible_expansions(self):
        with pytest.raises(TypeError, match=r"must be an array"):
            decode_seq_ranges("nope")
        with pytest.raises(TypeError, match=r"non-negative safe integers"):
            decode_seq_ranges([-1])
        with pytest.raises(TypeError, match=r"\[start, end\] pairs"):
            decode_seq_ranges([[1]])
        with pytest.raises(TypeError, match=r"start <= end"):
            decode_seq_ranges([[4, 2]])
        with pytest.raises(TypeError, match=r"strictly increasing"):
            decode_seq_ranges([[2, 5], [4, 7]])
        with pytest.raises(TypeError, match=r"exceeds its event sequence"):
            decode_seq_ranges([0], 0)
        with pytest.raises(TypeError, match=r"exceeds its event sequence"):
            decode_seq_ranges([[0, 10]], 10)
