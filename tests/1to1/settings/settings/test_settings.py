"""
1:1 test parity suite for @deepseek-ai/dsh-settings/src/index.ts.
Matching reference packages/settings/settings/tests/settings.spec.ts.

Language adaptations carried by these cases, each stated at its test:

* JavaScript `undefined` reads as the port's undefined sentinel
  (`dsh.cordis.utils._UNDEFINED`), which is how a sparse patch and an absent
  schema member stay distinct from a stored JSON `null`.
* `Object.freeze` has no Python equivalent, so a handed-out resolved value is
  asserted to be detached instead of frozen.
* `vi.fn()`/`vi.waitFor` become the `Fn` recorder and `wait_for` poller; the
  reference's promise scheduling becomes tasks on the running event loop.
"""

import asyncio
import copy
import datetime
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

import pytest

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _UNDEFINED
from dsh.settings.provider import (
    SettingsConflictError,
    SettingsProvider,
    deep_equal_json,
    install_settings_section,
    settings_namespace,
)

from .memory import MemorySettings


class BareProvider(SettingsProvider):
    """A provider implementing only the three primitives: the Service Definition owns initialization."""

    def __init__(self, ctx: Optional[Any] = None, options: Optional[Dict[str, Any]] = None):
        super().__init__(ctx)
        self.doc: Dict[str, Any] = copy.deepcopy((options or {}).get("doc") or {})

    @property
    def writable(self) -> bool:
        return True

    def load(self) -> Dict[str, Any]:
        return copy.deepcopy(self.doc)

    def _persist_section(self, ns: str, section: Dict[str, Any]) -> None:
        self.doc[ns] = copy.deepcopy(section)


ThemeSchema = Schema.object({
    "theme": Schema.union(["dark", "light"]).default("dark"),
    "fontSize": Schema.number().default(14),
})

NestedSchema = Schema.object({
    "retry": Schema.object({
        "attempts": Schema.number().default(2),
        "delayMs": Schema.number().default(100),
    }),
    "tags": Schema.array(Schema.string()).default(["default"]),
})


class Fn:
    """Stand-in for `vi.fn()`: records every call's positional arguments."""

    def __init__(self) -> None:
        self.calls: List[Any] = []

    def __call__(self, *args: Any) -> None:
        self.calls.append(args)

    def called_with(self, *args: Any) -> bool:
        """`toHaveBeenCalledWith`: whether any recorded call carried exactly these arguments."""
        return any(len(call) == len(args) and all(a == b for a, b in zip(call, args)) for call in self.calls)

    def count(self) -> int:
        return len(self.calls)


async def wait_for(predicate: Callable[[], Any], timeout: float = 1.0) -> None:
    """Stand-in for `vi.waitFor`: poll until `predicate` passes, then re-raise its failure."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            if predicate():
                return
        except AssertionError:
            pass
        if time.monotonic() >= deadline:
            assert predicate()
            return
        await asyncio.sleep(0.01)


async def boot(options: Optional[Dict[str, Any]] = None) -> Any:
    """Boot a `MemorySettings` provider on a fresh context."""
    ctx = Context()
    fiber = ctx.plugin(MemorySettings, options)
    await fiber
    return ctx, ctx.get("settings"), fiber


def register_inline(ctx: Context, ns: str, schema: Any, on_apply: Optional[Callable[[Any], None]] = None) -> Any:
    """
    Mount the reference's inline `ctx.plugin({ inject: ['settings'], apply })` registrant.

    :returns: the mounted fiber and the map carrying the scope it registered.
    """
    captured: Dict[str, Any] = {}

    class _Registrant(Plugin):
        inject = ["settings"]

        def apply(self, child: Context) -> None:
            scope = child.settings.register(ns, schema)
            captured["scope"] = scope
            if on_apply is not None:
                on_apply(scope)

    return ctx.plugin(_Registrant), captured


def record_updates(ctx: Context) -> List[Dict[str, Any]]:
    """Record every settings/updated emission."""
    events: List[Dict[str, Any]] = []

    def _record(ns: str, next_val: Any, prev_val: Any, source: str) -> None:
        events.append({"ns": ns, "next": next_val, "prev": prev_val, "source": source})

    ctx.on("settings/updated", _record)
    return events


class TestProviderMetadata:
    @pytest.mark.asyncio
    async def test_does_not_advertise_a_local_document_unless_the_provider_overrides_it(self):
        ctx, _, _ = await boot()
        assert ctx.get("settings").document_path is None
        assert ctx.get("settings").prepare_document() is None


class TestSettingsNamespace:
    def test_brands_lowercase_kebab_case_names(self):
        assert settings_namespace("ui-theme") == "ui-theme"

    @pytest.mark.parametrize("value", ["", "UI", "9lives", "a_b", "-lead"])
    def test_rejects(self, value):
        with pytest.raises(TypeError):
            settings_namespace(value)


class TestRegistration:
    @pytest.mark.asyncio
    async def test_resolves_schema_defaults_then_composition_base_then_the_user_layer(self):
        ctx, _, _ = await boot({"doc": {"ui-theme": {"theme": "light"}}})
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema, {"base": {"fontSize": 16}})
        # theme: user layer wins; fontSize: base wins over the schema default.
        assert scope.get() == {"theme": "light", "fontSize": 16}

    @pytest.mark.asyncio
    async def test_refuses_a_write_its_owner_could_not_act_on_and_keeps_the_last_good_value_for_a_stored_one(self):
        ctx, _, _ = await boot()
        ns = settings_namespace("ui-theme")

        def _validate(value: Dict[str, Any]) -> None:
            # A constraint the schema cannot express: this owner cannot serve a
            # size it considers unreadable, whatever the schema admits.
            if value["fontSize"] < 10:
                raise ValueError(f"font size {value['fontSize']} is unreadable")

        scope = ctx.get("settings").register(ns, ThemeSchema, {"validate": _validate})
        before = scope.get()

        with pytest.raises(ValueError, match="unreadable"):
            await ctx.get("settings").update(ns, {"fontSize": 4})
        assert scope.get() == before

        # An externally edited document must not strand the owner: the
        # namespace keeps its last good value, exactly as a schema failure would.
        ctx.get("settings").publish({"ui-theme": {"fontSize": 4}})
        assert scope.get() == before

        await ctx.get("settings").update(ns, {"fontSize": 18})
        assert scope.get()["fontSize"] == 18

    @pytest.mark.asyncio
    async def test_fails_the_registration_itself_when_the_already_stored_section_is_unserviceable(self):
        # The other direction of the same contract: `register` resolves inline,
        # so at cold start there is no last good value to keep.
        ctx, _, _ = await boot({"doc": {"ui-theme": {"fontSize": 4}}})

        def _validate(value: Dict[str, Any]) -> None:
            if value["fontSize"] < 10:
                raise ValueError(f"font size {value['fontSize']} is unreadable")

        with pytest.raises(ValueError, match="unreadable"):
            ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema, {"validate": _validate})

    @pytest.mark.asyncio
    async def test_rejects_a_duplicate_namespace_loud(self):
        ctx, _, _ = await boot()
        ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        with pytest.raises(ValueError, match="already registered"):
            ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)

    @pytest.mark.asyncio
    async def test_fails_registration_when_the_stored_section_is_invalid_for_the_schema(self):
        ctx, _, _ = await boot({"doc": {"ui-theme": {"fontSize": "big"}}})
        with pytest.raises(Exception):
            ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)

    @pytest.mark.asyncio
    async def test_fails_registration_when_the_stored_section_is_not_an_object(self):
        ctx, _, _ = await boot({"doc": {"ui-theme": "dark"}})
        with pytest.raises(TypeError, match="must be an object"):
            ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)

    @pytest.mark.asyncio
    async def test_describes_registered_namespaces_with_schema_json_value_and_applies(self):
        ctx, _, _ = await boot()
        ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        ctx.get("settings").register(settings_namespace("workspace"), NestedSchema, {"applies": "restart"})
        descriptors = ctx.get("settings").describe()
        assert [[entry["ns"], entry["applies"]] for entry in descriptors] == [
            ["ui-theme", "live"],
            ["workspace", "restart"],
        ]
        assert descriptors[0]["value"] == {"theme": "dark", "fontSize": 14}
        # schemastery's canonical wire form: a { uid, refs } envelope whose root
        # ref is the object schema, the form schema-driven UIs reconstruct from.
        serialized = descriptors[0]["schema"]
        refs = serialized["refs"]
        assert all(isinstance(key, str) for key in refs)
        assert refs[str(serialized["uid"])]["type"] == "object"

    @pytest.mark.asyncio
    async def test_reads_undefined_for_an_unregistered_namespace(self):
        ctx, _, _ = await boot()
        assert ctx.get("settings").get(settings_namespace("missing")) is None

    @pytest.mark.asyncio
    async def test_hands_out_frozen_resolved_values(self):
        # `Object.isFrozen` has no Python equivalent: the reference freezes the
        # handed-out value so a caller cannot reach the stored one through it,
        # and the port detaches it instead, which is the same guarantee.
        ctx, _, _ = await boot({"doc": {"workspace": {"retry": {"attempts": 5}}}})
        scope = ctx.get("settings").register(settings_namespace("workspace"), NestedSchema)
        value = scope.get()
        assert value == {"retry": {"attempts": 5, "delayMs": 100}, "tags": ["default"]}
        value["retry"]["attempts"] = 0
        assert scope.get()["retry"]["attempts"] == 5

    @pytest.mark.asyncio
    async def test_removes_the_namespace_and_its_observers_when_the_registrant_fiber_disposes(self):
        ctx, provider, _ = await boot()
        seen: List[Any] = []
        fiber, _captured = register_inline(
            ctx,
            "ui-theme",
            ThemeSchema,
            lambda scope: scope.watch(lambda next_val, prev_val: seen.append(next_val)),
        )
        await fiber
        assert ctx.get("settings").get(settings_namespace("ui-theme")) == {"theme": "dark", "fontSize": 14}

        await fiber.dispose()
        assert ctx.get("settings").get(settings_namespace("ui-theme")) is None
        assert ctx.get("settings").describe() == []
        provider.push_external({"ui-theme": {"theme": "light"}})
        assert seen == []

        # The namespace is free again, and re-registration resolves the user
        # layer that kept living in storage while nobody owned the namespace.
        again = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        assert again.get() == {"theme": "light", "fontSize": 14}


class TestUpdate:
    @pytest.mark.asyncio
    async def test_persists_the_merged_user_section_without_baking_in_the_base_layer(self):
        ctx, provider, _ = await boot({"doc": {"ui-theme": {"theme": "light"}}})
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema, {"base": {"fontSize": 16}})
        await scope.update({"theme": "dark"})
        assert provider.persisted == [{"ns": "ui-theme", "section": {"theme": "dark"}}]
        assert scope.get() == {"theme": "dark", "fontSize": 16}

    @pytest.mark.asyncio
    async def test_deep_merges_nested_objects_and_replaces_arrays_wholesale(self):
        ctx, provider, _ = await boot({
            "doc": {"workspace": {"retry": {"attempts": 5, "delayMs": 300}, "tags": ["a", "b"]}},
        })
        scope = ctx.get("settings").register(settings_namespace("workspace"), NestedSchema)
        await scope.update({"retry": {"attempts": 7}, "tags": ["c"]})
        assert provider.persisted[0]["section"] == {
            "retry": {"attempts": 7, "delayMs": 300},
            "tags": ["c"],
        }
        assert scope.get() == {"retry": {"attempts": 7, "delayMs": 300}, "tags": ["c"]}

    @pytest.mark.asyncio
    async def test_commits_notifies_watchers_and_emits_with_source_update(self):
        ctx, _, _ = await boot()
        events = record_updates(ctx)
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        watcher = Fn()
        scope.watch(watcher)
        await scope.update({"theme": "light"})
        await wait_for(lambda: watcher.called_with(
            {"theme": "light", "fontSize": 14},
            {"theme": "dark", "fontSize": 14},
        ))
        assert events == [{
            "ns": "ui-theme",
            "next": {"theme": "light", "fontSize": 14},
            "prev": {"theme": "dark", "fontSize": 14},
            "source": "update",
        }]

    @pytest.mark.asyncio
    async def test_rejects_an_invalid_patch_before_persisting_anything(self):
        ctx, provider, _ = await boot()
        events = record_updates(ctx)
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        with pytest.raises(Exception):
            await scope.update({"fontSize": "big"})
        assert provider.persisted == []
        assert events == []
        assert scope.get() == {"theme": "dark", "fontSize": 14}
        # The failed write must not poison the namespace queue for later writers.
        await scope.update({"fontSize": 18})
        assert scope.get() == {"theme": "dark", "fontSize": 18}

    @pytest.mark.asyncio
    async def test_ignores_explicit_undefined_entries_so_a_sparse_patch_cannot_erase_keys(self):
        ctx, provider, _ = await boot({"doc": {"ui-theme": {"theme": "light"}}})
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        await scope.update({"theme": _UNDEFINED, "fontSize": 18})
        assert provider.persisted[0]["section"] == {"theme": "light", "fontSize": 18}
        assert scope.get() == {"theme": "light", "fontSize": 18}

    @pytest.mark.asyncio
    async def test_rejects_a_non_object_patch(self):
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        with pytest.raises(TypeError):
            await scope.update([1])
        with pytest.raises(TypeError):
            await scope.update(datetime.datetime.fromtimestamp(0))
        with pytest.raises(TypeError, match=r'replace for "ui-theme"'):
            await scope.replace([1])

    @pytest.mark.asyncio
    async def test_accepts_a_null_prototype_patch_object(self):
        # Python has no `Object.create(null)`; a plain dict is the port's
        # mapping with no class prototype behind it, which is what the
        # reference's null-prototype patch keeps admissible.
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        patch: Dict[str, Any] = dict()
        patch["fontSize"] = 18
        await scope.update(patch)
        assert scope.get() == {"theme": "dark", "fontSize": 18}

    @pytest.mark.asyncio
    async def test_rejects_an_unregistered_namespace(self):
        ctx, _, _ = await boot()
        with pytest.raises(ValueError, match="not registered"):
            await ctx.get("settings").update(settings_namespace("missing"), {})

    @pytest.mark.asyncio
    async def test_rejects_on_a_read_only_provider_before_reaching_persist(self):
        ctx, provider, _ = await boot({"writable": False})
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        with pytest.raises(RuntimeError, match="read-only"):
            await scope.update({"theme": "light"})
        assert provider.persisted == []


class TestDeepEqualJson:
    @pytest.mark.parametrize("a,b,equal", [
        ({"a": [1, 2]}, {"a": [1, 2]}, True),
        ({"a": [1, 2]}, {"a": [1]}, False),
        ({"a": [1]}, {"a": {0: 1}}, False),
        ({"a": 1}, {"b": 1}, False),
        ({"a": 1}, {}, False),
        ({"a": None}, {"a": None}, True),
        ({"a": None}, {"a": {}}, False),
    ])
    def test_compares(self, a, b, equal):
        assert deep_equal_json(a, b) is equal


class TestReviewRegressions:
    @pytest.mark.asyncio
    async def test_propagates_an_invariant_coded_listener_failure_instead_of_containing_it(self):
        ctx, provider, _ = await boot()

        def _forged(ns, next_val, prev_val, source):
            raise _invariant_coded("forged relation")

        ctx.on("settings/updated", _forged)
        ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        with pytest.raises(Exception, match="forged relation"):
            provider.push_external({"ui-theme": {"theme": "light"}})

    @pytest.mark.asyncio
    async def test_serializes_concurrent_updates_so_neither_patch_is_lost(self):
        ctx, provider, _ = await boot({"persistDelayMs": 10})
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        await asyncio.gather(
            scope.update({"theme": "light"}),
            scope.update({"fontSize": 20}),
        )
        assert provider.doc["ui-theme"] == {"theme": "light", "fontSize": 20}
        assert scope.get() == {"theme": "light", "fontSize": 20}

    @pytest.mark.asyncio
    async def test_contains_a_throwing_settings_updated_listener_and_keeps_later_commits_alive(self):
        ctx, provider, _ = await boot()

        def _boom(ns, next_val, prev_val, source):
            raise RuntimeError("listener boom")

        ctx.on("settings/updated", _boom)
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        provider.push_external({"ui-theme": {"theme": "light"}})
        assert scope.get()["theme"] == "light"
        provider.push_external({"ui-theme": {"theme": "dark"}})
        assert scope.get()["theme"] == "dark"

    @pytest.mark.asyncio
    async def test_contains_an_async_watcher_rejection(self):
        ctx, provider, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)

        async def _boom(next_val, prev_val):
            raise RuntimeError("async watcher boom")

        scope.watch(_boom)
        provider.push_external({"ui-theme": {"theme": "light"}})
        assert scope.get()["theme"] == "light"
        # Give the rejected watcher awaitable a turn; containment means this
        # suite observes no unhandled exception out of this test.
        await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_loads_the_provider_document_through_the_base_init_without_provider_boilerplate(self):
        ctx = Context()
        await ctx.plugin(BareProvider, {"doc": {"ui-theme": {"fontSize": 7}}})
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        assert scope.get() == {"theme": "dark", "fontSize": 7}

    @pytest.mark.asyncio
    async def test_replaces_the_user_section_wholesale_so_overrides_can_be_removed(self):
        ctx, provider, _ = await boot({"doc": {"ui-theme": {"theme": "light", "fontSize": 20}}})
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema, {"base": {"fontSize": 16}})
        await scope.replace({"theme": "light"})
        # fontSize override is gone: resolution falls back to the base layer.
        assert scope.get() == {"theme": "light", "fontSize": 16}
        assert provider.doc["ui-theme"] == {"theme": "light"}
        await scope.replace({})
        assert scope.get() == {"theme": "dark", "fontSize": 16}
        assert provider.doc["ui-theme"] == {}


class TestSecondReviewRegressions:
    @pytest.mark.asyncio
    async def test_runs_every_settings_updated_listener_even_when_an_earlier_one_throws(self):
        ctx, provider, _ = await boot()

        def _boom(ns, next_val, prev_val, source):
            raise RuntimeError("first listener boom")

        ctx.on("settings/updated", _boom)
        second = Fn()
        ctx.on("settings/updated", second)
        ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        provider.push_external({"ui-theme": {"theme": "light"}})
        assert second.count() == 1

    @pytest.mark.asyncio
    async def test_rejects_an_update_queued_after_the_registrant_fiber_disposed(self):
        ctx, _, _ = await boot()
        fiber, captured = register_inline(ctx, "ui-theme", ThemeSchema)
        await fiber
        await fiber.dispose()
        with pytest.raises(Exception, match="disposed|not registered"):
            await captured["scope"].update({"theme": "light"})

    @pytest.mark.asyncio
    async def test_does_not_notify_a_registrant_disposed_while_its_update_was_in_flight(self):
        ctx, provider, _ = await boot({"persistDelayMs": 30})
        events = record_updates(ctx)
        watcher = Fn()
        fiber, captured = register_inline(
            ctx,
            "ui-theme",
            ThemeSchema,
            lambda scope: scope.watch(watcher),
        )
        await fiber
        pending = captured["scope"].update({"theme": "light"})
        await asyncio.sleep(0.005)
        await fiber.dispose()
        await _contained(pending)
        await asyncio.sleep(0.01)
        assert watcher.count() == 0
        assert events == []
        # The persist was already in flight, so storage keeps the write, but no
        # commit reached the disposed registration.
        assert provider.doc["ui-theme"] == {"theme": "light"}

    @pytest.mark.asyncio
    async def test_drains_in_flight_writes_at_service_dispose_and_rejects_later_ones(self):
        ctx, provider, fiber = await boot({"persistDelayMs": 20})
        service = ctx.get("settings")
        scope = service.register(settings_namespace("ui-theme"), ThemeSchema)
        pending = scope.update({"theme": "light"})
        await asyncio.sleep(0.005)
        await fiber.dispose()
        # The teardown drained the in-flight write before completing.
        await _contained(pending)
        persisted_at_dispose = len(provider.persisted)
        assert persisted_at_dispose == 1
        # ...and afterwards nothing writes and new writes reject.
        with pytest.raises(Exception, match="disposed|not registered"):
            await service.update(settings_namespace("ui-theme"), {"theme": "dark"})
        await asyncio.sleep(0.04)
        assert len(provider.persisted) == persisted_at_dispose

    @pytest.mark.asyncio
    async def test_serializes_invocations_of_one_async_watcher_in_commit_order(self):
        ctx, provider, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        applied: List[Any] = []
        first_call = {"value": True}

        async def _watch(next_val, prev_val):
            # The first (stale) invocation is slow; unserialised it would finish
            # last and clobber the newer applied state.
            delay = 0.03 if first_call["value"] else 0
            first_call["value"] = False
            await asyncio.sleep(delay)
            applied.append(next_val["fontSize"])

        scope.watch(_watch)
        provider.push_external({"ui-theme": {"fontSize": 1}})
        provider.push_external({"ui-theme": {"fontSize": 2}})
        await wait_for(lambda: len(applied) == 2)
        assert applied == [1, 2]

    @pytest.mark.asyncio
    async def test_rejects_a_function_value_as_not_json_compatible(self):
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        with pytest.raises(TypeError, match=r"JSON-compatible.*a function at \$\.theme"):
            await scope.update({"theme": lambda: "dark"})

    @pytest.mark.asyncio
    async def test_rejects_a_write_still_queued_when_the_service_disposes(self):
        ctx, _, fiber = await boot({"persistDelayMs": 20})
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        first = scope.update({"theme": "light"})
        second = scope.update({"fontSize": 20})
        await asyncio.sleep(0.005)
        await fiber.dispose()
        await first
        with pytest.raises(RuntimeError, match="disposed before the queued"):
            await second

    @pytest.mark.asyncio
    async def test_rejects_a_write_still_queued_when_the_registrant_disposes(self):
        ctx, _, _ = await boot({"persistDelayMs": 20})
        fiber, captured = register_inline(ctx, "ui-theme", ThemeSchema)
        await fiber
        first = captured["scope"].update({"theme": "light"})
        second = captured["scope"].update({"fontSize": 20})
        await asyncio.sleep(0.005)
        await fiber.dispose()
        await first
        with pytest.raises(RuntimeError, match="registration was disposed before the queued"):
            await second

    @pytest.mark.asyncio
    async def test_snapshots_the_patch_at_call_time_so_caller_mutation_cannot_leak_in(self):
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        patch = {"fontSize": 18}
        pending = scope.update(patch)
        patch["fontSize"] = 99
        await pending
        assert scope.get()["fontSize"] == 18


class TestPublish:
    @pytest.mark.asyncio
    async def test_notifies_watchers_of_an_external_change_with_source_provider(self):
        ctx, provider, _ = await boot()
        events = record_updates(ctx)
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        watcher = Fn()
        scope.watch(watcher)
        provider.push_external({"ui-theme": {"theme": "light"}})
        await wait_for(lambda: watcher.called_with(
            {"theme": "light", "fontSize": 14},
            {"theme": "dark", "fontSize": 14},
        ))
        assert events[0]["source"] == "provider"

    @pytest.mark.asyncio
    async def test_stays_silent_when_the_resolved_value_is_deep_equal(self):
        ctx, provider, _ = await boot({"doc": {"ui-theme": {"theme": "light"}}})
        events = record_updates(ctx)
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        watcher = Fn()
        scope.watch(watcher)
        provider.push_external({"ui-theme": {"theme": "light"}})
        await asyncio.sleep(0.01)
        assert watcher.count() == 0
        assert events == []

    @pytest.mark.asyncio
    async def test_keeps_the_last_good_value_for_an_invalid_section_while_other_namespaces_commit(self):
        ctx, provider, _ = await boot()
        events = record_updates(ctx)
        theme = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        workspace = ctx.get("settings").register(settings_namespace("workspace"), NestedSchema)
        provider.push_external({
            "ui-theme": {"fontSize": "broken"},
            "workspace": {"retry": {"attempts": 9}},
        })
        assert theme.get() == {"theme": "dark", "fontSize": 14}
        assert workspace.get() == {"retry": {"attempts": 9, "delayMs": 100}, "tags": ["default"]}
        assert [event["ns"] for event in events] == ["workspace"]

    @pytest.mark.asyncio
    async def test_recovers_from_a_bad_section_once_storage_turns_valid_again(self):
        ctx, provider, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        provider.push_external({"ui-theme": {"fontSize": "broken"}})
        assert scope.get() == {"theme": "dark", "fontSize": 14}
        provider.push_external({"ui-theme": {"fontSize": 18}})
        assert scope.get() == {"theme": "dark", "fontSize": 18}


class TestThirdReviewRegressions:
    @pytest.mark.asyncio
    async def test_skips_a_queued_watch_invocation_whose_disposer_ran_before_it_started(self):
        ctx, provider, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        watcher = Fn()
        dispose = scope.watch(watcher)
        # The commit chains the invocation as a task; the disposer runs in the
        # same synchronous frame, before that invocation could start.
        provider.push_external({"ui-theme": {"theme": "light"}})
        dispose()
        await asyncio.sleep(0.01)
        assert watcher.count() == 0

    @pytest.mark.asyncio
    async def test_waits_for_an_in_flight_watch_invocation_at_service_dispose(self):
        ctx, provider, fiber = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        release = asyncio.Event()
        started = asyncio.Event()
        finished = {"value": False}

        async def _watch(next_val, prev_val):
            started.set()
            await release.wait()
            finished["value"] = True

        scope.watch(_watch)
        provider.push_external({"ui-theme": {"theme": "light"}})
        await asyncio.wait_for(started.wait(), 1.0)
        disposed = {"value": False}

        async def _dispose():
            await fiber.dispose()
            disposed["value"] = True

        disposal = asyncio.ensure_future(_dispose())
        await asyncio.sleep(0.015)
        assert disposed["value"] is False
        release.set()
        await disposal
        assert finished["value"] is True

    @pytest.mark.asyncio
    async def test_rejects_a_date_at_its_path_before_anything_persists(self):
        # The reference's `Date` is the port's `datetime`.
        ctx, provider, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({"value": Schema.any()}))
        with pytest.raises(TypeError, match=r"JSON-compatible.*datetime at \$\.value\.at"):
            await scope.update({"value": {"at": datetime.datetime.fromtimestamp(0)}})
        assert provider.persisted == []

    @pytest.mark.asyncio
    async def test_rejects_a_map_that_structuredclone_would_admit(self):
        # The reference's `Map` is the port's closest mapping that is not a
        # plain data object; the label names the Python type.
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({"value": Schema.any()}))
        with pytest.raises(TypeError, match=r"OrderedDict at \$\.value"):
            await scope.update({"value": OrderedDict()})

    @pytest.mark.asyncio
    async def test_rejects_a_symbol_that_structuredclone_would_admit(self):
        # Python 3.8 has no symbol; a bare object instance is the port's
        # non-JSON value with no class of its own, which the reference rejects
        # as `a non-plain object`.
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({"value": Schema.any()}))
        with pytest.raises(TypeError, match=r"non-plain object at \$\.value"):
            await scope.update({"value": object()})

    @pytest.mark.asyncio
    async def test_bigint_maps_to_a_json_number_rather_than_a_rejected_value(self):
        # LANGUAGE ADAPTATION of the reference's `bigint` case: Python has no
        # BigInt, the port maps it to `int`, and lossless JSON represents an
        # arbitrary-precision Python integer, so the case stores, not rejects.
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({"value": Schema.any()}))
        await scope.update({"value": [10 ** 20]})
        assert scope.get() == {"value": [10 ** 20]}

    @pytest.mark.asyncio
    async def test_rejects_a_non_finite_number_that_structuredclone_would_admit(self):
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({"value": Schema.any()}))
        with pytest.raises(TypeError, match=r"non-finite number at \$\.value"):
            await scope.update({"value": float("nan")})

    @pytest.mark.asyncio
    async def test_rejects_an_undefined_array_entry_that_structuredclone_would_admit(self):
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({"value": Schema.any()}))
        with pytest.raises(TypeError, match=r"undefined at \$\.value\[0\]"):
            await scope.update({"value": [_UNDEFINED]})

    @pytest.mark.asyncio
    async def test_rejects_a_class_instance_that_structuredclone_would_admit(self):
        class Marker:
            pass

        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({"value": Schema.any()}))
        with pytest.raises(TypeError, match=r"Marker at \$\.value"):
            await scope.update({"value": Marker()})

    @pytest.mark.asyncio
    async def test_rejects_a_circular_patch_instead_of_storing_an_alias_looped_document(self):
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({"value": Schema.any()}))
        cyclic: Dict[str, Any] = {}
        cyclic["self"] = cyclic
        with pytest.raises(TypeError, match=r"circular reference at \$\.value\.self"):
            await scope.update({"value": cyclic})
        loop: List[Any] = []
        loop.append(loop)
        with pytest.raises(TypeError, match=r"circular reference at \$\.value\[0\]"):
            await scope.update({"value": loop})

    @pytest.mark.asyncio
    async def test_accepts_one_object_referenced_twice_without_a_cycle(self):
        ctx, _, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), Schema.object({"value": Schema.any()}))
        shared = {"leaf": 1}
        await scope.update({"value": {"left": shared, "right": shared}})
        assert scope.get() == {"value": {"left": {"leaf": 1}, "right": {"leaf": 1}}}

    @pytest.mark.asyncio
    async def test_contains_an_async_settings_updated_listener_rejection_and_keeps_other_listeners_running(self):
        ctx, provider, _ = await boot()

        def _boom(*args):
            return _rejecting("async listener boom")

        ctx.on("settings/updated", _boom)
        second = Fn()
        ctx.on("settings/updated", second)
        ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        provider.push_external({"ui-theme": {"theme": "light"}})
        assert second.count() == 1
        # Containment gives the rejection a handler; this suite observes no
        # unhandled exception out of this test.
        await asyncio.sleep(0.01)


class TestWatch:
    @pytest.mark.asyncio
    async def test_stops_after_its_disposer_runs(self):
        ctx, provider, _ = await boot()
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)
        watcher = Fn()
        dispose = scope.watch(watcher)
        dispose()
        provider.push_external({"ui-theme": {"theme": "light"}})
        await asyncio.sleep(0.01)
        assert watcher.count() == 0

    @pytest.mark.asyncio
    async def test_contains_a_throwing_watcher_without_blocking_the_commit_or_other_watchers(self):
        ctx, provider, _ = await boot()
        events = record_updates(ctx)
        scope = ctx.get("settings").register(settings_namespace("ui-theme"), ThemeSchema)

        def _boom(next_val, prev_val):
            raise RuntimeError("watcher boom")

        scope.watch(_boom)
        second = Fn()
        scope.watch(second)
        provider.push_external({"ui-theme": {"theme": "light"}})
        await wait_for(lambda: second.count() == 1)
        assert len(events) == 1
        assert scope.get() == {"theme": "light", "fontSize": 14}


class TestInstallSettingsSection:
    HelperSchema = Schema.object({"theme": Schema.string().default("default")})

    @pytest.mark.asyncio
    async def test_drives_the_source_through_attach_live_commits_and_detach(self):
        ctx = Context()
        entry = {"theme": "entry"}
        state: Dict[str, Any] = {"current": (lambda: entry), "changes": 0}
        install_settings_section(ctx, settings_namespace("helper-ns"), self.HelperSchema, entry, {
            "setSource": lambda source: state.__setitem__("current", source),
            "onChange": lambda: state.__setitem__("changes", state["changes"] + 1),
        })
        # No settings service mounted: nothing ran, the entry stays authoritative.
        assert state["current"]() == {"theme": "entry"}
        assert state["changes"] == 0

        fiber = ctx.plugin(MemorySettings, {"doc": {"helper-ns": {"theme": "user"}}})
        await fiber
        await wait_for(lambda: state["current"]() == {"theme": "user"})
        assert state["changes"] == 1

        await ctx.get("settings").update(settings_namespace("helper-ns"), {"theme": "live"})
        await wait_for(lambda: state["changes"] == 2)
        assert state["current"]() == {"theme": "live"}

        await fiber.dispose()
        await wait_for(lambda: state["changes"] == 3)
        assert state["current"]() == {"theme": "entry"}

    @pytest.mark.asyncio
    async def test_stays_silent_when_the_consumer_itself_unloads(self):
        ctx, _, _ = await boot({"doc": {"helper-ns": {"theme": "user"}}})
        entry = {"theme": "entry"}
        state: Dict[str, Any] = {"current": (lambda: entry)}
        changes: List[str] = []

        class _Consumer(Plugin):
            inject = ["settings"]

            def apply(self, child: Context) -> None:
                install_settings_section(child, settings_namespace("helper-ns"), TestInstallSettingsSection.HelperSchema, entry, {
                    "setSource": lambda source: state.__setitem__("current", source),
                    "onChange": lambda: changes.append(state["current"]()["theme"]),
                })

        consumer = ctx.plugin(_Consumer)
        await consumer
        await wait_for(lambda: changes == ["user"])

        # The consumer's own teardown must not re-derive anything: an onChange
        # here would re-register routes and touch resources being released.
        await consumer.dispose()
        await asyncio.sleep(0.02)
        assert changes == ["user"]

    @pytest.mark.asyncio
    async def test_stays_silent_for_a_stored_change_that_lands_while_the_consumer_unloads(self):
        # The watcher outlives the start of teardown by the width of the unload,
        # so a document change arriving in that window reaches it.
        ctx, provider, _ = await boot({"doc": {"helper-ns": {"theme": "user"}}})
        entry = {"theme": "entry"}
        state: Dict[str, Any] = {"current": (lambda: entry)}
        changes: List[str] = []

        class _Consumer(Plugin):
            inject = ["settings"]

            def apply(self, child: Context) -> None:
                install_settings_section(child, settings_namespace("helper-ns"), TestInstallSettingsSection.HelperSchema, entry, {
                    "setSource": lambda source: state.__setitem__("current", source),
                    "onChange": lambda: changes.append(state["current"]()["theme"]),
                })

        consumer = ctx.plugin(_Consumer)
        await consumer
        await wait_for(lambda: changes == ["user"])

        unloading = asyncio.ensure_future(consumer.dispose())
        provider.push_external({"helper-ns": {"theme": "racing"}})
        await unloading
        assert changes == ["user"]


class TestMutate:
    KeyedSchema = Schema.object({
        "apiKey": Schema.string().role("secret"),
        "baseURL": Schema.string(),
        "reasoning": Schema.string(),
    })
    KEYED = settings_namespace("keyed")
    NESTED = settings_namespace("workspace")

    @staticmethod
    async def mounted(doc: Dict[str, Any]) -> Context:
        ctx = Context()
        await ctx.plugin(BareProvider, {"doc": doc})
        ctx.get("settings").register(TestMutate.KEYED, TestMutate.KeyedSchema)
        return ctx

    @pytest.mark.asyncio
    async def test_removes_one_field_without_touching_a_secret_the_caller_never_saw(self):
        # The data-loss shape this exists to prevent: a configuration UI reads
        # the REDACTED descriptor (no apiKey), the user resets baseURL, and the
        # client rebuilds the section from what it holds. A wholesale replace of
        # that rebuild deletes the stored literal key; a path unset cannot.
        ctx = await self.mounted({"keyed": {"apiKey": "sk-stored", "baseURL": "https://user", "reasoning": "high"}})
        redacted = next(d for d in ctx.get("settings").describe({"redactSecrets": True}) if d["ns"] == self.KEYED)
        assert redacted["user"] == {"baseURL": "https://user", "reasoning": "high"}

        await ctx.get("settings").mutate(self.KEYED, [{"op": "unset", "path": ["baseURL"]}])

        raw = next(d for d in ctx.get("settings").describe() if d["ns"] == self.KEYED)
        assert raw["user"] == {"apiKey": "sk-stored", "reasoning": "high"}

    @pytest.mark.asyncio
    async def test_applies_set_and_unset_in_one_write_in_order(self):
        ctx = await self.mounted({"keyed": {"apiKey": "sk-stored", "baseURL": "https://old"}})
        await ctx.get("settings").mutate(self.KEYED, [
            {"op": "set", "path": ["baseURL"], "value": "https://new"},
            {"op": "set", "path": ["reasoning"], "value": "low"},
            {"op": "unset", "path": ["reasoning"]},
        ])
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.KEYED)["user"] == {
            "apiKey": "sk-stored",
            "baseURL": "https://new",
        }

    @pytest.mark.asyncio
    async def test_reads_the_section_as_it_stands_at_the_front_of_the_queue_not_at_call_time(self):
        # Two concurrent writers: the mutate is issued against the pre-update
        # section but must observe the update that ran before it.
        ctx = await self.mounted({"keyed": {"apiKey": "sk-stored"}})
        first = ctx.get("settings").update(self.KEYED, {"baseURL": "https://first", "reasoning": "high"})
        second = ctx.get("settings").mutate(self.KEYED, [{"op": "unset", "path": ["reasoning"]}])
        await asyncio.gather(first, second)
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.KEYED)["user"] == {
            "apiKey": "sk-stored",
            "baseURL": "https://first",
        }

    @pytest.mark.asyncio
    async def test_creates_intermediate_objects_for_a_nested_set_and_leaves_an_absent_unset_alone(self):
        ctx = Context()
        await ctx.plugin(BareProvider, {"doc": {}})
        ctx.get("settings").register(self.NESTED, NestedSchema)
        await ctx.get("settings").mutate(self.NESTED, [{"op": "set", "path": ["retry", "attempts"], "value": 5}])
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.NESTED)["user"] == {
            "retry": {"attempts": 5},
        }
        await ctx.get("settings").mutate(self.NESTED, [{"op": "unset", "path": ["missing", "deep"]}])
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.NESTED)["user"] == {
            "retry": {"attempts": 5},
        }

    @pytest.mark.asyncio
    async def test_edits_one_leaf_of_an_existing_nested_object_without_replacing_its_siblings(self):
        ctx = Context()
        await ctx.plugin(BareProvider, {"doc": {"workspace": {"retry": {"attempts": 5, "delayMs": 250}}}})
        ctx.get("settings").register(self.NESTED, NestedSchema)
        await ctx.get("settings").mutate(self.NESTED, [{"op": "set", "path": ["retry", "delayMs"], "value": 900}])
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.NESTED)["user"] == {
            "retry": {"attempts": 5, "delayMs": 900},
        }

    @pytest.mark.asyncio
    async def test_addresses_the_section_itself_through_the_empty_path(self):
        ctx = await self.mounted({"keyed": {"apiKey": "sk-stored", "baseURL": "https://user"}})
        await ctx.get("settings").mutate(self.KEYED, [{"op": "set", "path": [], "value": {"reasoning": "low"}}])
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.KEYED)["user"] == {"reasoning": "low"}
        await ctx.get("settings").mutate(self.KEYED, [{"op": "unset", "path": []}])
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.KEYED)["user"] == {}

    @pytest.mark.asyncio
    async def test_refuses_a_non_object_at_the_section_root_leaving_the_stored_section_alone(self):
        ctx = await self.mounted({"keyed": {"apiKey": "sk-stored"}})
        with pytest.raises(TypeError, match="setting the section root requires a plain object"):
            await ctx.get("settings").mutate(self.KEYED, [{"op": "set", "path": [], "value": "a whole section"}])
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.KEYED)["user"] == {
            "apiKey": "sk-stored",
        }

    @pytest.mark.asyncio
    async def test_rejects_ops_that_are_not_an_array_at_all(self):
        ctx = await self.mounted({"keyed": {"apiKey": "sk-stored"}})
        with pytest.raises(TypeError, match="must be a list of path ops"):
            await ctx.get("settings").mutate(self.KEYED, {"op": "unset", "path": ["apiKey"]})
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.KEYED)["user"] == {
            "apiKey": "sk-stored",
        }

    @pytest.mark.asyncio
    async def test_rejects_a_malformed_op_before_anything_is_queued(self):
        ctx = await self.mounted({"keyed": {"apiKey": "sk-stored"}})
        with pytest.raises(TypeError, match=r"must be \{op:'set'\|'unset', path\}"):
            await ctx.get("settings").mutate(self.KEYED, [{"op": "delete"}])
        with pytest.raises(TypeError, match="op paths must be lists of strings"):
            await ctx.get("settings").mutate(self.KEYED, [{"op": "unset", "path": ["a", 1]}])
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.KEYED)["user"] == {
            "apiKey": "sk-stored",
        }

    @pytest.mark.asyncio
    async def test_rejects_a_value_that_lossless_json_cannot_represent(self):
        ctx = await self.mounted({"keyed": {}})
        with pytest.raises(TypeError, match="must contain only JSON-compatible data"):
            await ctx.get("settings").mutate(self.KEYED, [
                {"op": "set", "path": ["baseURL"], "value": datetime.datetime.fromtimestamp(0)},
            ])


class TestRevisionAndConflictDetection:
    REV = settings_namespace("rev")
    RevSchema = Schema.object({"a": Schema.string().default("base-a"), "b": Schema.string()})

    @staticmethod
    async def mounted(doc: Optional[Dict[str, Any]] = None) -> Context:
        ctx = Context()
        await ctx.plugin(BareProvider, {"doc": doc or {}})
        return ctx

    @pytest.mark.asyncio
    async def test_refuses_a_write_whose_expected_revision_is_stale_leaving_the_winner_in_place(self):
        # Two editors open the same namespace, both holding revision 0. The
        # first to land wins; the second must be told rather than overwrite it.
        ctx = await self.mounted()
        ctx.get("settings").register(self.REV, self.RevSchema)
        opened = next(d for d in ctx.get("settings").describe() if d["ns"] == self.REV)["revision"]
        assert opened == 0

        await ctx.get("settings").update(self.REV, {"b": "from-tab-B"}, opened)
        with pytest.raises(Exception, match=r"changed since it was read \(expected revision 0, now 1\)"):
            await ctx.get("settings").update(self.REV, {"a": "from-tab-A"}, opened)
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.REV)["user"] == {
            "b": "from-tab-B",
        }

    @pytest.mark.asyncio
    async def test_carries_the_machine_code_and_both_revisions_on_the_refusal(self):
        ctx = await self.mounted()
        ctx.get("settings").register(self.REV, self.RevSchema)
        await ctx.get("settings").update(self.REV, {"b": "first"})
        error = None
        try:
            await ctx.get("settings").update(self.REV, {"b": "second"}, 0)
        except Exception as caught:
            error = caught
        assert isinstance(error, SettingsConflictError)
        assert error.code == "SETTINGS_CONFLICT"
        assert error.expected == 0
        assert error.actual == 1

    @pytest.mark.asyncio
    async def test_accepts_a_write_that_carries_no_expectation_at_all(self):
        ctx = await self.mounted()
        ctx.get("settings").register(self.REV, self.RevSchema)
        await ctx.get("settings").update(self.REV, {"b": "one"})
        await ctx.get("settings").update(self.REV, {"b": "two"})
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.REV)["revision"] == 2

    @pytest.mark.asyncio
    async def test_announces_a_raw_change_whose_resolved_value_is_unchanged(self):
        # Storing an override equal to the schema default leaves `value` alone
        # but changes what the document says: the field is now overridden, not
        # inherited, and another tab has to learn that.
        ctx = await self.mounted()
        ctx.get("settings").register(self.REV, self.RevSchema)
        documents: List[Any] = []
        resolved: List[str] = []
        ctx.on("settings/document-updated", lambda ns, revision: documents.append([str(ns), revision]))
        ctx.on("settings/updated", lambda *args: resolved.append(str(args[0])))

        await ctx.get("settings").update(self.REV, {"a": "base-a"})

        assert documents == [["rev", 1]]
        assert resolved == []
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.REV)["user"] == {"a": "base-a"}

    @pytest.mark.asyncio
    async def test_does_not_move_the_revision_when_a_write_stores_an_identical_section(self):
        ctx = await self.mounted({"rev": {"b": "same"}})
        ctx.get("settings").register(self.REV, self.RevSchema)
        documents: List[Any] = []
        ctx.on("settings/document-updated", lambda ns, revision: documents.append([str(ns), revision]))
        await ctx.get("settings").update(self.REV, {"b": "same"})
        assert documents == []
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.REV)["revision"] == 0

    @pytest.mark.asyncio
    async def test_moves_the_revision_for_an_external_edit_the_provider_publishes(self):
        ctx = await self.mounted()
        ctx.get("settings").register(self.REV, self.RevSchema)
        documents: List[Any] = []
        ctx.on("settings/document-updated", lambda ns, revision: documents.append([str(ns), revision]))
        ctx.get("settings").publish({"rev": {"b": "edited on disk"}})
        assert documents == [["rev", 1]]
        # An editor that opened before the external edit is now refused.
        with pytest.raises(SettingsConflictError):
            await ctx.get("settings").update(self.REV, {"b": "stale"}, 0)

    @pytest.mark.asyncio
    async def test_moves_the_revision_past_a_stored_section_that_was_not_an_object(self):
        # A hand-edited file can leave a namespace holding a scalar. The
        # resolved value keeps its last good reading, and the repair that
        # follows still has to announce itself.
        ctx = await self.mounted()
        ctx.get("settings").register(self.REV, self.RevSchema)
        ctx.get("settings").publish({"rev": "not a section"})
        documents: List[Any] = []
        ctx.on("settings/document-updated", lambda ns, revision: documents.append([str(ns), revision]))
        ctx.get("settings").publish({"rev": {"b": "repaired by hand"}})
        assert documents == [["rev", 1]]

    @pytest.mark.asyncio
    async def test_contains_a_throwing_document_listener_and_keeps_the_rest_of_the_fan_out_running(self):
        ctx = await self.mounted()
        ctx.get("settings").register(self.REV, self.RevSchema)
        seen: List[int] = []

        def _boom(ns, revision):
            raise RuntimeError("document listener boom")

        ctx.on("settings/document-updated", _boom)
        ctx.on("settings/document-updated", lambda ns, revision: seen.append(revision))
        await ctx.get("settings").update(self.REV, {"b": "one"})
        await ctx.get("settings").update(self.REV, {"b": "two"})
        assert seen == [1, 2]

    @pytest.mark.asyncio
    async def test_contains_an_async_document_listener_rejection(self):
        ctx = await self.mounted()
        ctx.get("settings").register(self.REV, self.RevSchema)

        def _boom(*args):
            return _rejecting("async document boom")

        ctx.on("settings/document-updated", _boom)
        await ctx.get("settings").update(self.REV, {"b": "one"})
        assert next(d for d in ctx.get("settings").describe() if d["ns"] == self.REV)["revision"] == 1
        # Give the rejected listener awaitable a turn; containment means this
        # suite observes no unhandled exception out of this test.
        await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_propagates_an_invariant_coded_document_listener_failure_instead_of_containing_it(self):
        ctx = await self.mounted()
        ctx.get("settings").register(self.REV, self.RevSchema)

        def _forged(ns, revision):
            raise _invariant_coded("forged revision")

        ctx.on("settings/document-updated", _forged)
        with pytest.raises(Exception, match="forged revision"):
            ctx.get("settings").publish({"rev": {"b": "edited on disk"}})


def _invariant_coded(message: str) -> Exception:
    """`Object.assign(new Error(message), { code: 'INVARIANT' })`."""
    error = Exception(message)
    error.code = "INVARIANT"
    return error


async def _rejecting(message: str) -> None:
    """An async listener's rejected promise."""
    raise RuntimeError(message)


async def _contained(awaitable: Any) -> None:
    """Await a write the case does not expect to fail, as `pending.catch(() => undefined)` does."""
    try:
        await awaitable
    except Exception:
        pass
