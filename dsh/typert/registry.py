"""Cordis-owned Typert reflection, invocation, lookup and Context registry."""
import copy

from dsh.cordis.service import Service
from dsh.typert.protocol import TypertDisposer, TypertLookupProvider
from dsh.typert.stores import (
    DescriptorStore, DescriptorView, LookupStore, LookupView, ContextStore,
    ContextView, segment,
)


class LookupRegistry(LookupView):
    """Standalone registry facade; registrations require an owning Context."""
    def __init__(self, ctx):
        super().__init__(ctx, LookupStore())


class TypertRegistry(Service):
    id = "typert"
    name = "@deepseek-ai/dsh-typert-registry"

    def __init__(self, ctx):
        super().__init__(ctx, "typert")
        self.schemas, self.packages, self.remote_packages = {}, {}, {}
        self.local_store, self.remote_store = DescriptorStore("local"), DescriptorStore("remote")
        self.lookup_store, self.context_store = LookupStore(), ContextStore()
        self.__dict__.update(self._views(ctx))

    def _views(self, ctx):
        return {"local": DescriptorView(ctx, self.local_store),
                "remotes": DescriptorView(ctx, self.remote_store, self.remote_packages),
                "lookups": LookupView(ctx, self.lookup_store),
                "contexts": ContextView(ctx, self.context_store)}

    def _extend(self, props=None):
        # Service getters in JS execute with the calling receiver. Python's
        # proxy eagerly evaluates properties, so bind the nested views here.
        props = dict(props or {})
        props.update(self._views(props.get("ctx", self.ctx)))
        return super()._extend(props)

    def register(self, contribution):
        package, face = contribution["package"], contribution["face"]
        segment("package name", package)
        if face not in ("host", "client"):
            raise ValueError("typert: face must be host or client")
        key = package + "#" + face
        if key in self.packages:
            raise ValueError("typert: package face already registered: " + key)
        package_record = {"package": package, "face": face, "key": key, "model": contribution["model"]}
        records, batch = [], set()
        for schema in contribution["schemas"]:
            segment("schema name", schema["name"])
            schema_key = package + "#" + schema["name"]
            if schema_key in batch or schema_key in self.schemas:
                raise ValueError("typert: schema already registered: " + schema_key)
            batch.add(schema_key)
            records.append(dict(schema, package=package, face=face, key=schema_key))
        descriptors = contribution["invocations"]
        self.local_store.validate(descriptors)
        owner = object()
        def setup():
            self.packages[key] = package_record
            for record in records:
                self.schemas[record["key"]] = record
            self.local_store.commit(owner, descriptors)
            def dispose():
                if self.packages.get(key) is package_record:
                    del self.packages[key]
                for record in records:
                    if self.schemas.get(record["key"]) is record:
                        del self.schemas[record["key"]]
                self.local_store.withdraw(owner, descriptors)
            return dispose
        return self.ctx.effect(setup, "typert.register()")

    def get(self, key):
        return self.schemas.get(key)

    def resolve(self, key):
        record = self.schemas.get(key)
        if record is not None:
            return record
        package, separator, name = key.partition("#")
        if not package or not separator or not name:
            raise ValueError("typert: invalid schema key; expected <package>#<name>")
        if any(row["package"] == package for row in self.packages.values()):
            raise ValueError("typert: package registered but contributes no schema named " + name)
        raise ValueError("typert: package has no registered contribution: " + package)

    def list(self, filter=None):
        return self._filtered(self.schemas, filter)

    @staticmethod
    def _filtered(table, filter):
        selected = filter or {}
        return [row for row in table.values() if all(key not in selected or row[key] == selected[key] for key in ("package", "face"))]

    def getPackage(self, package, face="host"):
        return self.packages.get(package + "#" + face)

    def listPackages(self, filter=None):
        return self._filtered(self.packages, filter)

    def toJSONSchema(self, key, params=None):
        schema = self.resolve(key)["schema"]
        project = getattr(schema, "to_json_schema", None) or getattr(schema, "toJSONSchema", None)
        if project is None:
            raise ValueError("typert: schema has no JSON Schema projector")
        return copy.deepcopy(project(params) if params is not None else project())


default = TypertRegistry
__all__ = ["LookupRegistry", "TypertRegistry", "default", "TypertDisposer", "TypertLookupProvider"]
