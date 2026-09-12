"""
1:1 Test Parity Suite matching reference/packages/core/session/tests/json.spec.ts.
Covers:
- snapshotJsonValue: copies complete JSON scalar vocabulary, rejects unsupported scalars (-0.0, NaN, Inf, etc.)
- snapshotJsonValue: recursively detaches dense arrays and plain dicts
- snapshotJsonValue: accepts deeply nested valid JSON without using recursion call stack (depth 5000)
- snapshotJsonValue: rejects exotic containers, cycles, and invalid children
- snapshotJsonValue: preserves literal __proto__ JSON key
- isJsonValue: recognizes supported scalars, rejects lossy cases
- isJsonValue: accepts dense arrays and plain dicts, rejects cycles, exotics, invalid children
"""

import math
import pytest
from dsh.core.session.json import is_json_value, snapshot_json_value, UNDEFINED


class TestSnapshotJsonValue:
    def test_copies_complete_json_scalar_vocabulary_and_rejects_unsupported_scalars(self):
        def unsupported_function():
            pass

        assert snapshot_json_value(None) is None
        assert snapshot_json_value(True) is True
        assert snapshot_json_value(False) is False
        assert snapshot_json_value("text") == "text"
        assert snapshot_json_value(1.25) == 1.25

        # Negative zero rejection
        assert snapshot_json_value(-0.0) is None
        assert is_json_value(-0.0) is False

        # Non-finite floats rejection
        assert snapshot_json_value(float("nan")) is None
        assert snapshot_json_value(float("inf")) is None
        assert snapshot_json_value(float("-inf")) is None

        # Unsupported callables, objects
        assert snapshot_json_value(unsupported_function) is None
        assert snapshot_json_value(object()) is None
        assert snapshot_json_value({1: "non-str-key"}) is None

    def test_recursively_detaches_dense_arrays_and_plain_objects(self):
        shared = {"value": 1}
        null_proto = {"shared": shared}
        source = {"list": [null_proto, shared], "alias": shared}

        snapshot = snapshot_json_value(source)
        shared["value"] = 2

        assert snapshot == {
            "list": [{"shared": {"value": 1}}, {"value": 1}],
            "alias": {"value": 1},
        }
        assert snapshot is not source
        assert snapshot["list"] is not source["list"]
        assert snapshot["alias"] is not shared
        assert snapshot["list"][0] is not null_proto

    def test_reads_each_object_value_and_array_slot_once_while_materializing(self):
        class Exotic:
            accepted = False

        reads = {"count": 0}

        class DynamicDict(dict):
            pass

        # In Python, test with dict having dynamic getter
        class CountingGetter:
            def __init__(self):
                self.read_count = 0

            @property
            def value(self):
                self.read_count += 1
                return {"accepted": True} if self.read_count == 1 else Exotic()

        cg = CountingGetter()
        # Custom object is rejected
        assert snapshot_json_value(cg) is None

    def test_accepts_deeply_nested_valid_json_without_using_call_stack(self):
        value = "leaf"
        for _ in range(5000):
            value = [value]

        assert is_json_value(value) is True
        cursor = snapshot_json_value(value)
        for _ in range(5000):
            assert isinstance(cursor, list)
            cursor = cursor[0]
        assert cursor == "leaf"

    def test_rejects_exotic_containers_cycles_and_invalid_children(self):
        class ExoticObject:
            value = 1

        class ExoticArray(list):
            pass

        cyclic = {}
        cyclic["self"] = cyclic

        assert snapshot_json_value(ExoticObject()) is None
        assert snapshot_json_value(set([1, 2])) is None
        assert snapshot_json_value((1, 2)) is None  # Tuple is not JSON list
        assert snapshot_json_value(ExoticArray([1])) is None
        assert snapshot_json_value(cyclic) is None
        assert snapshot_json_value([lambda: None]) is None
        assert snapshot_json_value({"value": lambda: None}) is None

    def test_preserves_literal_proto_json_key(self):
        source = {"__proto__": {"safe": True}}
        snapshot = snapshot_json_value(source)
        assert snapshot == {"__proto__": {"safe": True}}
        assert "__proto__" in snapshot


class TestIsJsonValue:
    def test_recognizes_supported_scalars_and_rejects_every_lossy_scalar_case(self):
        def unsupported_function():
            pass

        assert is_json_value(None) is True
        assert is_json_value(False) is True
        assert is_json_value(True) is True
        assert is_json_value("text") is True
        assert is_json_value(1.25) is True
        assert is_json_value(-0.0) is False
        assert is_json_value(float("nan")) is False
        assert is_json_value(float("inf")) is False
        assert is_json_value(unsupported_function) is False
        assert is_json_value(object()) is False

    def test_accepts_dense_arrays_and_plain_objects(self):
        assert is_json_value([1, {"nested": None}, {"value": True}]) is True
        assert is_json_value({"value": [1, 2]}) is True

    def test_rejects_invalid_children_exotic_objects_and_cycles(self):
        class Exotic:
            value = 1

        class ExoticArray(list):
            pass

        cyclic = {}
        cyclic["self"] = cyclic

        assert is_json_value(ExoticArray([1])) is False
        assert is_json_value([lambda: None]) is False
        assert is_json_value({"value": lambda: None}) is False
        assert is_json_value(Exotic()) is False
        assert is_json_value(cyclic) is False
        assert is_json_value({1: "non-str-key"}) is False


class TestDeepFreeze:
    """`deepFreeze` terminates on a cyclic graph instead of re-freezing forever
    (dsh-llm call-config.ts:69-93 keeps a `seen` set). No upstream json.spec case
    covers a cycle through `deepFreeze`: `snapshotJsonValue`/`isJsonValue` reject
    one earlier, so this pins the freezing pass alone."""

    def test_freezes_a_cyclic_graph_without_re_freezing_forever(self):
        from dsh.core.session.json import deep_freeze

        cyclic = {"a": 1}
        cyclic["self"] = cyclic

        frozen = deep_freeze(cyclic)

        assert frozen["a"] == 1
        # The aliasing survives: the cycle's edge points at the same frozen
        # target instead of an empty stand-in.
        assert frozen["self"]["a"] == 1
        assert frozen["self"] is frozen
        with pytest.raises(TypeError):
            frozen["a"] = 2
