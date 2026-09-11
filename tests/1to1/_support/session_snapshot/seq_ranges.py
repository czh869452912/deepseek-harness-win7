"""
Lossless range encoding for JSONL sourceEventSeqs arrays.
Ported 1:1 from reference packages/core/session/src/seq-ranges.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, List, Sequence, Union

MAX_SAFE_INTEGER = 0x1FFFFFFFFFFFFF


def _is_strictly_increasing(values: Sequence[int]) -> bool:
    for i in range(1, len(values)):
        if values[i] <= values[i - 1]:
            return False
    return True


def _assert_seq(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_SAFE_INTEGER:
        raise TypeError("sourceEventSeqs must contain non-negative safe integers")


def encode_seq_ranges(values: Sequence[int]) -> List[Union[int, List[int]]]:
    """
    Replace profitable consecutive runs with inclusive pairs.
    """
    if not _is_strictly_increasing(values):
        return list(values)
    encoded: List[Union[int, List[int]]] = []
    start = 0
    val_len = len(values)
    while start < val_len:
        end = start
        while end + 1 < val_len and values[end + 1] == values[end] + 1:
            end += 1
        if end - start >= 2:
            encoded.append([values[start], values[end]])
        else:
            for idx in range(start, end + 1):
                encoded.append(values[idx])
        start = end + 1
    return encoded


def decode_seq_ranges(value: Any, max_entries: int = MAX_SAFE_INTEGER) -> List[int]:
    """
    Expand a JSON storage-form source sequence array.
    """
    if not isinstance(value, list):
        raise TypeError("sourceEventSeqs must be an array")
    decoded: List[int] = []
    has_range = False
    for entry in value:
        if isinstance(entry, int) and not isinstance(entry, bool):
            _assert_seq(entry)
            if len(decoded) >= max_entries:
                raise TypeError("sourceEventSeqs exceeds its event sequence")
            decoded.append(entry)
            continue
        if not isinstance(entry, list) or len(entry) != 2:
            raise TypeError("sourceEventSeqs range entries must be [start, end] pairs")
        start = entry[0]
        end = entry[1]
        _assert_seq(start)
        _assert_seq(end)
        if end < start:
            raise TypeError("sourceEventSeqs ranges require start <= end")
        length = end - start + 1
        if length > max_entries - len(decoded):
            raise TypeError("sourceEventSeqs range exceeds its event sequence")
        for seq in range(start, end + 1):
            decoded.append(seq)
        has_range = True

    if has_range and not _is_strictly_increasing(decoded):
        raise TypeError("sourceEventSeqs ranges must be strictly increasing")
    return decoded


encodeSeqRanges = encode_seq_ranges
decodeSeqRanges = decode_seq_ranges
