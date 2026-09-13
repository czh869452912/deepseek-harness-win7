"""
1:1 parity tests for the unit `vendor/loader-cosmokit-deep-equal`.

reference/vendor/loader/src/config/entry.ts:2 imports `deepEqual` and
`isNullable` from `@deepseek-ai/cosmokit`; the vendored loader ships no test
file of its own, so each case below pins one authoritative line:

- entry.ts:148 - `if (isNullable(value)) delete candidate[key]` removes an
  option whose incoming value is `null` OR `undefined`; every other value is
  assigned, including the falsy `false`, `0` and `''`.
- entry.ts:157-160 - the diff is
  `Object.keys({ ...candidate, ...legacy }).filter(key => !deepEqual(
  candidate[key], legacy[key]))` with no `strict` argument, so a key only one
  operand owns reads as `undefined`, `null` matches it, `false` never matches
  `0`, and containers compare structurally.
- entry.ts:161 - `if (!diff.length && !force) return`: an empty diff leaves
  `this.options`, the fiber and the `loader/partial-dispose` event untouched,
  while `force` enters the update path anyway.

`dsh/cordis/loader.py` compared the option values with Python `!=` and tested
`v is None`, which coerces `false == 0` and `1 == true`, and treats the
`undefined` sentinel as a value distinct from `null`; both the structural
divergences and the observably different update path are asserted here.
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


def test_entry_ts_159_option_diff_compares_containers_with_deep_equal():
    """entry.ts:159: `deepEqual({a: null}, {})` is true, so the diff stays empty.

    A `config` whose only difference is a `null` member against an absent one is
    not a change: the non-strict `deepEqual` reads the missing key as
    `undefined` and its nullish shortcut accepts `null`. The reference returns
    before touching the fiber, so the caller's object is never persisted.
    """
    original = {"a": None}
    _, entry, events = _entry(original)
    assert applied == [{"a": None}]
    fiber = entry.fiber

    entry.update({"config": {}})

    assert applied == [{"a": None}]
    assert events == []
    assert entry.fiber is fiber
    assert entry.options["config"] == {"a": None}
    assert entry.options["config"] is original

    # A member that really differs still takes the update path.
    entry.update({"config": {"a": 1}})

    assert applied == [{"a": None}, {"a": 1}]
    assert len(events) == 1
    assert events[0][1]["config"] == {"a": None}
    assert entry.options["config"] == {"a": 1}


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
    two numbers compare equal. The nested `null`-against-absent pair stays equal
    as well, as in the top-level case.
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

    assert len(events) == 2
    assert entry.options["config"] == {"n": {"v": 1, "absent": None}}


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

    The array branch of `deepEqual` compares elements loosely, so
    `{k: [{a: null}]}` equals `{k: [{}]}`: without `force` the fresh caller
    object is discarded and the entry keeps its original config object. With
    `force` the reference commits the caller's object, but the diff it already
    computed stays empty, so the fiber does not restart and no plugin re-applies;
    only a diff that really contains `config` restarts it.
    """
    original = {"k": [{"a": None}]}
    _, entry, events = _entry(original)
    fiber = entry.fiber
    updated = {"k": [{}]}

    entry.update({"config": updated})

    assert applied == [{"k": [{"a": None}]}]
    assert events == []
    assert entry.fiber is fiber
    assert entry.options["config"] is original

    entry.update({"config": updated}, force=True)

    assert applied == [{"k": [{"a": None}]}]
    assert len(events) == 1
    assert events[0][1]["config"] == {"k": [{"a": None}]}
    assert events[0][2] is True
    assert entry.fiber is fiber
    assert entry.options["config"] is updated

    entry.update({"config": {"k": [{"a": 1}]}})

    assert applied == [{"k": [{"a": None}]}, {"k": [{"a": 1}]}]
    assert len(events) == 2
    assert entry.options["config"] == {"k": [{"a": 1}]}
