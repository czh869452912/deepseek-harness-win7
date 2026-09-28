"""Runtime invocation and dependency stores for the canonical Typert registry.

Python schemas expose parse()/to_json_schema() instead of JavaScript Zod
instances. No TypeScript analysis is performed by the runtime registry.
"""
import inspect
import logging
import re
from types import SimpleNamespace


def field(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def nonempty(subject, value):
    if not isinstance(value, str) or not value:
        raise ValueError("typert: invalid " + subject + " — must be nonempty")


def segment(subject, value):
    nonempty(subject, value)
    if "#" in value:
        raise ValueError("typert: invalid " + subject + " — must not contain #")


def wire_name(subject, value):
    if not isinstance(value, str) or value in (".", "..") or not re.fullmatch(r"[A-Za-z0-9_$.-]+", value):
        raise ValueError("typert: invalid " + subject + " — invalid RPC segment")


def validate_codec(codec, subject):
    if field(codec, "mode") == "src-json":
        return
    nonempty(subject + " type symbol", field(codec, "typeSymbol"))
    if not callable(field(field(codec, "schema"), "parse")):
        raise ValueError("typert: " + subject + " strict codec has no parse() method")


def endpoint(descriptor):
    return descriptor["namespace"] + "/" + descriptor["method"]


def validate_invocation(row):
    nonempty("invocation id", row.get("id"))
    segment("invocation service key", row.get("service"))
    for key in ("namespace", "method"):
        wire_name("invocation " + key, row.get(key))
    if "implementation" in row:
        wire_name("invocation implementation", row["implementation"])
    validate_codec(row.get("result"), row["id"] + " result")
    wires, lookups = set(), []
    for parameter in row["parameters"]:
        wire_name("parameter name", parameter.get("name"))
        wire_name("parameter wire field", parameter.get("wire"))
        if parameter["wire"] in wires:
            raise ValueError("typert: invocation repeats wire field " + parameter["wire"])
        wires.add(parameter["wire"])
        if parameter.get("source") == "lookup":
            if "acceptsUndefined" in parameter:
                raise ValueError("typert: lookup parameter cannot accept undefined")
            segment("lookup key", parameter.get("lookup"))
            lookups.append(parameter)
        elif "lookup" in parameter:
            raise ValueError("typert: JSON parameter declares a lookup key")
        validate_codec(parameter.get("codec"), row["id"] + " parameter " + parameter["name"])
    if "cancellation" in row and row["cancellation"].get("parameter") != "signal":
        raise ValueError("typert: cancellation parameter must be signal")
    receiver = row["invocation"]
    if "scope" in row:
        scope = row["scope"]
        if receiver["kind"] != "direct":
            raise ValueError("typert: Context receiver cannot declare a direct scope projection")
        segment("scope Context key", scope.get("context"))
        wire_name("scope wire field", scope.get("wire"))
        if len(lookups) != 1 or lookups[0]["wire"] != scope["wire"] or lookups[0]["lookup"] != scope["context"]:
            raise ValueError("typert: scope must select its only lookup parameter")
    if receiver["kind"] == "context":
        segment("Context key", receiver.get("context"))
        wire_name("Context wire field", receiver.get("wire"))
        if receiver["wire"] in wires:
            raise ValueError("typert: invocation repeats Context wire field")
        validate_codec(receiver.get("codec"), row["id"] + " Context")


class ChangeSource:
    def __init__(self):
        self.listeners = []

    def subscribe(self, ctx, listener):
        # Identity and registration order are preserved, including reentrancy.
        def setup():
            if listener not in self.listeners:
                self.listeners.append(listener)
            def dispose():
                if listener in self.listeners:
                    self.listeners.remove(listener)
            return dispose
        return ctx.effect(setup, "typert registry subscription")

    def emit(self, kind, key):
        for listener in list(self.listeners):
            try:
                listener({"kind": kind, "key": key})
            except Exception:
                logging.getLogger("typert").warning("%s observer for %s failed", kind, key, exc_info=True)


class DescriptorStore:
    def __init__(self, kind):
        self.kind, self.entries, self.ids, self.history = kind, {}, {}, set()
        self.changes = ChangeSource()

    def validate(self, descriptors):
        endpoints, ids = set(), set()
        for row in descriptors:
            validate_invocation(row)
            key = endpoint(row)
            if key in endpoints or key in self.entries:
                raise ValueError("typert: " + self.kind + " endpoint already registered: " + key)
            if row["id"] in ids or row["id"] in self.ids:
                raise ValueError("typert: " + self.kind + " invocation id already registered: " + row["id"])
            endpoints.add(key)
            ids.add(row["id"])

    def commit(self, owner, descriptors):
        for row in descriptors:
            entry = {"descriptor": row, "owner": owner}
            self.entries[endpoint(row)] = self.ids[row["id"]] = entry
            self.history.add(endpoint(row))
        for row in descriptors:
            self.changes.emit(self.kind, endpoint(row))

    def withdraw(self, owner, descriptors):
        removed = []
        for row in descriptors:
            key = endpoint(row)
            entry = self.entries.get(key)
            if entry is None or entry["owner"] is not owner:
                continue
            del self.entries[key]
            if self.ids.get(row["id"]) is entry:
                del self.ids[row["id"]]
            removed.append(key)
        for key in removed:
            self.changes.emit(self.kind, key)

    def get(self, key):
        entry = self.entries.get(key)
        return entry["descriptor"] if entry else None

    def list(self):
        return [entry["descriptor"] for entry in self.entries.values()]


class DescriptorView:
    def __init__(self, ctx, store, packages=None):
        self.ctx, self.store, self.packages = ctx, store, packages

    def get(self, key):
        return self.store.get(key)

    def list(self):
        return self.store.list()

    def hasSeen(self, key):
        return key in self.store.history

    def subscribe(self, listener):
        return self.store.changes.subscribe(self.ctx, listener)

    def register(self, contribution):
        if self.packages is None:
            raise ValueError("typert: local invocations are owned by package contributions")
        package = contribution["package"]
        segment("Remote package name", package)
        if package in self.packages:
            raise ValueError("typert: Remote package already registered: " + package)
        descriptors = contribution["descriptors"]
        self.store.validate(descriptors)
        owner = object()
        def setup():
            self.packages[package] = owner
            self.store.commit(owner, descriptors)
            def dispose():
                if self.packages.get(package) is owner:
                    del self.packages[package]
                self.store.withdraw(owner, descriptors)
            return dispose
        return self.ctx.effect(setup, "typert.remotes.register()")


def register_provider(ctx, table, changes, kind, key, provider):
    if key in table:
        raise ValueError("typert: " + kind + " provider already registered: " + key)
    entry = {"provider": provider}
    def setup():
        table[key] = entry
        changes.emit(kind, key)
        def dispose():
            if table.get(key) is entry:
                del table[key]
                changes.emit(kind, key)
        return dispose
    return ctx.effect(setup, "typert " + kind + " registration")


async def resolve_async(resolver, identity):
    value = resolver(identity)
    return await value if inspect.isawaitable(value) else value


class LookupStore:
    def __init__(self):
        self.providers, self.resolvers, self.definitions = {}, {}, {}
        self.changes = ChangeSource()


class LookupView:
    def __init__(self, ctx, store):
        self.ctx, self.store = ctx, store

    def register(self, key, provider):
        from dsh.typert.protocol import TypertLookupDefinition
        segment("lookup key", key)
        segment("lookup parameter", field(provider, "parameter"))
        wire_name("lookup wire field", field(provider, "wire"))
        for name in ("hostTypeSymbol", "wireTypeSymbol"):
            nonempty("lookup " + name, field(provider, name))
        declaration = {name: field(provider, name) for name in ("parameter", "wire", "hostTypeSymbol", "wireTypeSymbol")}
        definition = TypertLookupDefinition(key, declaration["parameter"], declaration["wire"],
                                            declaration["hostTypeSymbol"], declaration["wireTypeSymbol"])
        known = self.store.definitions.get(key)
        if known is not None and known.to_dict() != definition.to_dict():
            raise ValueError("typert: lookup changed its wire declaration: " + key)
        if key in self.store.providers:
            raise ValueError("typert: lookup provider already registered: " + key)
        entry = {"provider": provider}
        def setup():
            # Definitions survive withdrawal, but failed effects cannot publish them.
            self.store.definitions[key] = definition
            self.store.providers[key] = entry
            self.store.changes.emit("lookup", key)
            def dispose():
                if self.store.providers.get(key) is entry:
                    del self.store.providers[key]
                    self.store.changes.emit("lookup", key)
            return dispose
        return self.ctx.effect(setup, "typert.lookups.register()")

    def configure(self, key, resolver):
        segment("lookup key", key)
        return register_provider(self.ctx, self.store.resolvers, self.store.changes, "lookup", key, resolver)

    def get(self, key):
        entry = self.store.providers.get(key)
        if entry is None:
            return None
        provider, resolver = entry["provider"], self.store.resolvers.get(key)
        if resolver is None:
            return provider
        return SimpleNamespace(**{name: field(provider, name) for name in ("parameter", "wire", "hostTypeSymbol", "wireTypeSymbol")},
                               resolve=lambda identity: resolve_async(resolver["provider"], identity))

    def has(self, key):
        return key in self.store.providers

    def keys(self):
        return list(self.store.providers)

    def definitions(self):
        return list(self.store.definitions.values())

    def subscribe(self, listener):
        return self.store.changes.subscribe(self.ctx, listener)


class ContextStore:
    def __init__(self):
        self.hosts, self.clients, self.resolvers = {}, {}, {}
        self.changes = ChangeSource()


class ContextView:
    def __init__(self, ctx, store):
        self.ctx, self.store = ctx, store

    def registerHost(self, key, adapter):
        segment("Context key", key)
        wire_name("Context wire field", field(adapter, "wire"))
        nonempty("Context wire type symbol", field(adapter, "wireTypeSymbol"))
        return register_provider(self.ctx, self.store.hosts, self.store.changes, "host-context", key, adapter)

    def registerClient(self, key, adapter):
        segment("Context key", key)
        return register_provider(self.ctx, self.store.clients, self.store.changes, "client-context", key, adapter)

    def configureHost(self, key, resolver):
        segment("Context key", key)
        return register_provider(self.ctx, self.store.resolvers, self.store.changes, "host-context", key, resolver)

    def getHost(self, key):
        entry = self.store.hosts.get(key)
        if entry is None:
            return None
        adapter, resolver = entry["provider"], self.store.resolvers.get(key)
        if resolver is None:
            return adapter
        return SimpleNamespace(**{name: field(adapter, name) for name in ("wire", "wireTypeSymbol", "identity")},
                               resolve=lambda identity: resolve_async(resolver["provider"], identity))

    def getClient(self, key):
        entry = self.store.clients.get(key)
        return entry["provider"] if entry else None

    def identifyHost(self, ctx):
        match = None
        for key in self.store.hosts:
            identity = field(self.getHost(key), "identity")(ctx)
            if identity is None:
                continue
            if match is not None:
                raise ValueError("typert: Host Context recognized by both " + match["kind"] + " and " + key)
            match = {"kind": key, "identity": identity}
        return match

    def subscribe(self, listener):
        return self.store.changes.subscribe(self.ctx, listener)
