"""Loader option comparison against cosmokit helpers and fixed rc022 contracts.

Config uses strict nullish comparison recursively; other options use loose
comparison. Equal inputs retain the raw identity unless force is requested.
"""

from typing import Any, Dict, List, Tuple

from dsh.cordis.context import Context
from dsh.cordis.loader import Entry, Loader
from dsh.cordis.plugin import Plugin
from dsh.cordis.utils import _UNDEFINED
from dsh.cordis.utils import deep_equal as cosmokit_deep_equal
from dsh.cordis.utils import is_nullable as cosmokit_is_nullable

PLUGIN_NAME = "loader-deep-equal-recorder"

#: Config of every `apply` the entry's fiber ran, in order.
applied: List[Any] = []


class RecorderPlugin(Plugin):
    """Plugin whose each apply records the config the entry handed it."""

    name = PLUGIN_NAME

    def apply(self, c: Context) -> None:
        applied.append(dict(self.config) if isinstance(self.config, dict) else self.config)


def _entry(config: Any, disabled: Any = False) -> Tuple[Loader, Context, List[Tuple[Any, Any, Any]]]:
    """Build an initialized entry and its recorded `loader/partial-dispose` emissions."""
    applied.clear()
    ctx = Context()
    loader = Loader(ctx)
    ctx.set_service("loader", loader)
    loader.register_plugin_class(PLUGIN_NAME, RecorderPlugin)
    events: List[Tuple[Any, Any, Any]] = []
    ctx.on("loader/partial-dispose", lambda entry, options, active: events.append((entry, options, active)))
    entry = Entry(loader=loader, name=PLUGIN_NAME, config=config, disabled=disabled, entry_id="target")
    entry.init()
    assert entry.fiber is not None
    return loader, entry, events


def test_entry_ts_2_loader_consumes_the_canonical_cosmokit_helpers():
    """entry.ts:2: the loader module binds cosmokit's own `deepEqual`/`isNullable`.

    The port must not carry a second implementation of either helper: the names
    the loader module resolves have to be the canonical `dsh.cordis.utils`
    function objects that `reference/vendor/cosmokit/src/types.ts:118-142` and
    `misc.ts:20-21` define.
    """
    from dsh.cordis import loader as loader_module

    assert loader_module.deep_equal is cosmokit_deep_equal
    assert loader_module.is_nullable is cosmokit_is_nullable


def test_config_diff_distinguishes_null_from_absent():
    """Fixed rc022 compares config with strict nullish semantics."""
    _, entry, events = _entry({'a': None})
    fiber = entry.fiber
    entry.update({'config': {}})
    assert applied == [{'a': None}, {}]
    assert len(events) == 1
    assert entry.fiber is fiber
    assert entry.options['config'] == {}
    entry.update({'config': {'a': 1}})
    assert applied == [{'a': None}, {}, {'a': 1}]
    assert len(events) == 2
    assert events[1][1]['config'] == {}


def test_entry_ts_159_boolean_and_number_option_values_never_coerce():
    """entry.ts:159: `deepEqual(false, 0)` is false because `typeof` differs.

    Python's `!=` reports `{'flag': False} == {'flag': 0}`, which made the port
    treat the update as a no-op; the reference replaces the config and restarts
    the plugin, emitting `loader/partial-dispose` with the legacy options.
    """
    _, entry, events = _entry({"flag": False})
    assert applied == [{"flag": False}]

    entry.update({"config": {"flag": 0}})

    assert applied == [{"flag": False}, {"flag": 0}]
    assert len(events) == 1
    assert events[0][1]["config"] == {"flag": False}
    assert entry.options["config"] == {"flag": 0}

    # `true` is a boolean too: it never equals `1`.
    entry.update({"config": {"flag": True}})

    assert applied == [{"flag": False}, {"flag": 0}, {"flag": True}]
    assert entry.options["config"] == {"flag": True}


def test_entry_ts_159_nested_option_values_keep_the_typeof_rule():
    """entry.ts:159: the rule holds inside a container, where `==` coerces.

    `deepEqual({n: {v: 1}}, {n: {v: true}})` recurses into the object fallback
    and finds a number against a boolean, so the config counts as changed, while
    two numbers compare equal. Nested null and absent differ in config.
    """
    _, entry, events = _entry({"n": {"v": 1}})

    entry.update({"config": {"n": {"v": 1.0}}})

    assert events == []
    assert entry.options["config"] == {"n": {"v": 1}}

    entry.update({"config": {"n": {"v": True}}})

    assert len(events) == 1
    assert entry.options["config"] == {"n": {"v": True}}

    entry.update({"config": {"n": {"v": 1, "absent": None}}})

    assert len(events) == 2
    assert entry.options["config"] == {"n": {"v": 1, "absent": None}}

    entry.update({"config": {"n": {"v": 1}}})

    assert len(events) == 3
    assert entry.options["config"] == {"n": {"v": 1}}


def test_entry_ts_148_is_nullable_deletes_an_undefined_option_value():
    """entry.ts:148: `isNullable(undefined)` deletes the key, `null` included.

    The port's own `undefined` sentinel is one of the two nullish values, so
    `update({disabled: undefined})` removes `disabled` from the candidate
    instead of storing the sentinel. With the legacy option read as `null`, the
    pair is equal and the reference returns early; `force` commits the removal.
    """
    _, entry, events = _entry({}, disabled=None)
    assert entry.options["disabled"] is None

    entry.update({"disabled": _UNDEFINED})

    assert events == []
    assert entry.options["disabled"] is None

    entry.update({"disabled": _UNDEFINED}, force=True)

    assert "disabled" not in entry.options
    assert len(events) == 1
    assert events[0][1]["disabled"] is None


def test_entry_ts_159_diff_key_set_spans_candidate_and_legacy():
    """entry.ts:158: the key set is `Object.keys({ ...candidate, ...legacy })`.

    A key the update deletes from the candidate stays in the diff through the
    legacy side (`undefined` against the old value), which keeps the update path
    in charge of committing the removal.
    """
    _, entry, events = _entry({})
    fiber = entry.fiber
    assert entry.options["disabled"] is False

    entry.update({"disabled": None})

    assert len(events) == 1
    assert events[0][1]["disabled"] is False
    assert "disabled" not in entry.options
    assert entry.fiber is fiber
    assert applied == [{}]  # a `disabled`-only diff does not restart the fiber


def test_entry_ts_160_empty_diff_returns_before_any_state_change():
    """entry.ts:161: an empty diff returns, and `force` only commits.

    Structurally equal config arrays leave the fiber untouched; the fresh
    caller object is discarded and the entry keeps its original config. With
    `force` the reference commits the caller's object, but the diff it already
    computed stays empty, so the fiber does not restart and no plugin re-applies;
    only a diff that really contains `config` restarts it.
    """
    original = {"k": [{}]}
    _, entry, events = _entry(original)
    fiber = entry.fiber
    updated = {"k": [{}]}

    entry.update({"config": updated})

    assert applied == [{"k": [{}]}]
    assert events == []
    assert entry.fiber is fiber
    assert entry.options["config"] is original

    entry.update({"config": updated}, force=True)

    assert applied == [{"k": [{}]}]
    assert len(events) == 1
    assert events[0][1]["config"] == {"k": [{}]}
    assert events[0][2] is True
    assert entry.fiber is fiber
    assert entry.options["config"] is updated

    entry.update({"config": {"k": [{"a": 1}]}})

    assert applied == [{"k": [{}]}, {"k": [{"a": 1}]}]
    assert len(events) == 2
    assert entry.options["config"] == {"k": [{"a": 1}]}
