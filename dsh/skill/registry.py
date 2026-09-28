"""Scoped asynchronous skill discovery with owned provider lifetimes."""
import asyncio
import inspect
import logging
import math
from collections import OrderedDict
from types import SimpleNamespace

from dsh.cordis.service import Service
from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted
from dsh.core.scope import ScopedLayers, scope_of, scope_chain_of
from dsh.skill.skill_service import is_skill_name


def member(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key)


def check(signal):
    if aborted(signal):
        raise RuntimeError("skill lookup aborted")


async def wait_with_abort(value, signal):
    if not inspect.isawaitable(value):
        check(signal)
        return value
    work = asyncio.ensure_future(value)
    if signal is None:
        return await work
    cancel = asyncio.create_task(signal.wait_aborted() if hasattr(signal, "wait_aborted") else signal.wait())
    try:
        await asyncio.wait((work, cancel), return_when=asyncio.FIRST_COMPLETED)
        check(signal)
        return await work
    finally:
        cancel.cancel()
        await asyncio.gather(cancel, return_exceptions=True)
        if not work.done():
            # Provider work is borrowed. Cancellation ends this caller's wait,
            # while a late rejection is consumed without cancelling its owner.
            work.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)


def validate(skill, candidate=False, provider=None):
    if not isinstance(skill, dict) or not is_skill_name(skill.get("name")):
        raise ValueError("skill name must be kebab-case")
    if not isinstance(skill.get("description"), str) or not skill["description"]:
        raise ValueError("skill requires a non-empty description")
    for key in ("source", "provider") + (() if candidate else ("content",)):
        if not isinstance(skill.get(key), str):
            raise TypeError("skill " + key + " must be a string")
    for key in ("whenToUse", "path"):
        if key in skill and not isinstance(skill[key], str):
            raise TypeError("skill " + key + " must be a string")
    policy = skill.get("invocation")
    if policy is not None and (not isinstance(policy, dict) or any(type(policy.get(key)) is not bool for key in ("modelInvocable", "userInvocable"))):
        raise TypeError("skill invocation must contain boolean modelInvocable and userInvocable")
    if candidate and (type(skill.get("rank")) not in (int, float) or not math.isfinite(skill["rank"]) or skill["provider"] != provider):
        raise ValueError("skill candidate has an invalid rank or provider identity")


class SkillLayer:
    def __init__(self):
        self.runtime, self.providers = {}, {}

    def is_empty(self):
        return not self.runtime and not self.providers


class SkillRegistry(Service):
    def __init__(self, ctx, config=None):
        maximum = (config or {}).get("collectCacheMaxEntries", 128)
        if type(maximum) is not int or maximum < 1:
            raise ValueError("collectCacheMaxEntries must be a positive integer")
        super().__init__(ctx, "skills")
        self.maximum, self.cache, self.revision, self.order = maximum, OrderedDict(), 0, 0
        self.layers = ScopedLayers(lambda _: SkillLayer(), self.invalidate)

    def invalidate(self):
        self.revision += 1
        self.cache.clear()
        # Event handlers are notifications, never a veto on committed changes.
        for callback in self.ctx.events.dispatch("emit", ["skills/change"]):
            try:
                value = callback()
                if inspect.isawaitable(value):
                    task = asyncio.ensure_future(value)
                    task.add_done_callback(self._consume)
            except Exception as error:
                logging.getLogger("skills").warning("skills/change failed: %s", error)

    @staticmethod
    def _consume(task):
        if not task.cancelled() and task.exception() is not None:
            logging.getLogger("skills").warning("skills/change rejected: %s", task.exception())

    def register_provider(self, create):
        lifetime, active = AbortController(), {}
        def invalidate():
            if active and active["layer"].providers.get(active["name"], (None,))[0] is active["provider"]:
                self.invalidate()
        try:
            provider = create(SimpleNamespace(signal=lifetime.signal, invalidate=invalidate))
            name = member(provider, "name")
            if not isinstance(name, str) or not name or name == "runtime":
                raise ValueError("skill provider requires a non-reserved name")
            order = self.order
            self.order += 1
            def setup(layer):
                if name in layer.providers:
                    raise ValueError("a skill provider named {!r} is already registered in this scope".format(name))
                layer.providers[name] = (provider, order)
                active.update(layer=layer, name=name, provider=provider)
                def cleanup():
                    active.clear()
                    layer.providers.pop(name, None)
                    lifetime.abort("skill provider disposed")
                return cleanup
            return self.layers.effect(self.ctx, setup, {"label": "skills.registerProvider()"})
        except Exception as error:
            lifetime.abort(error)
            raise

    registerProvider = register_provider

    def register(self, skill):
        definition = dict(skill)
        definition.setdefault("provider", "runtime")
        definition.setdefault("invocation", {"modelInvocable": True, "userInvocable": True})
        validate(definition)
        scope = scope_of(self.ctx)
        layer = self.layers.global_layer if scope is None else self.layers.peek(scope)
        if layer is not None and definition["name"] in layer.runtime:
            logging.getLogger("skills").warning("runtime skill %s ignored because it is already registered", definition["name"])
            return lambda: None
        def setup(layer):
            layer.runtime[definition["name"]] = definition
            return lambda: layer.runtime.pop(definition["name"], None)
        return self.layers.effect(self.ctx, setup, {"label": "skills.register()"})

    async def _collect(self, options):
        signal = options.get("signal")
        check(signal)
        for attempt in range(2):
            revision = self.revision
            chain = tuple(scope_chain_of(options.get("scope")))
            key = (options.get("cwd"), chain, revision)
            if key in self.cache:
                return self.cache[key], True
            merged, complete = {}, True
            for layer in [self.layers.global_layer] + self.layers.chain_layers(options.get("scope")):
                entries = []
                for index, name in enumerate(sorted(layer.runtime)):
                    definition = layer.runtime[name]
                    candidate = dict(definition, rank=250, locator=definition)
                    entries.append((candidate, None, -1, index, layer))
                for provider, order in list(layer.providers.values()):
                    name = member(provider, "name")
                    try:
                        output = await wait_with_abort(member(provider, "list")(options), signal)
                    except Exception as error:
                        check(signal)
                        complete = False
                        logging.getLogger("skills").warning("skill provider %s skipped: %s", name, error)
                        continue
                    if isinstance(output, list):
                        candidates = output
                    elif isinstance(output, dict) and isinstance(output.get("candidates"), list) and type(output.get("complete")) is bool:
                        candidates = output["candidates"]
                        complete = complete and output["complete"]
                    else:
                        raise TypeError("skill provider list() must return an array or {candidates, complete}")
                    for index, candidate in enumerate(candidates):
                        validate(candidate, True, name)
                        entries.append((candidate, provider, order, index, layer))
                winners = {}
                for entry in sorted(entries, key=lambda row: (row[0]["rank"], row[2], row[3])):
                    winners.setdefault(entry[0]["name"], entry)
                merged.update(winners)
            check(signal)
            if revision != self.revision:
                if attempt == 0:
                    continue
                return merged, False
            if complete:
                self.cache[key] = merged
                if len(self.cache) > self.maximum:
                    self.cache.popitem(last=False)
            return merged, complete

    async def snapshot(self, options=None):
        entries, complete = await self._collect(options or {})
        keys = ("name", "description", "whenToUse", "invocation", "source", "provider", "resourceBase")
        return {"skills": [{key: entries[name][0][key] for key in keys if key in entries[name][0]} for name in sorted(entries)], "complete": complete}

    async def list(self, options=None):
        return (await self.snapshot(options))["skills"]

    async def get(self, name, options=None):
        if not is_skill_name(name):
            return None
        options = options or {}
        entries, _ = await self._collect(options)
        check(options.get("signal"))
        if name not in entries:
            return None
        candidate, provider, _, _, layer = entries[name]
        definition = candidate["locator"] if provider is None else await wait_with_abort(member(provider, "get")(candidate, options), options.get("signal"))
        if definition is None:
            return None
        validate(definition)
        if definition["name"] != name:
            if provider is not None and layer.providers.get(member(provider, "name"), (None,))[0] is provider:
                self.invalidate()
            return None
        return definition
