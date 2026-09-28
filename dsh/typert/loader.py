"""Incremental Loader-owned Typert artifact registration."""
import asyncio
import importlib.util
import inspect
import json
import logging
import os
from urllib.parse import unquote, urlparse

from dsh.cordis.loader import module_search_dirs, split_package_specifier, is_installation_owned_module
from dsh.cordis.plugin import Plugin
from dsh.typert.artifact import read_generated_artifact
from dsh.typert.stores import field, validate_invocation


def validate_manifest(package, manifest):
    def fail(message):
        raise ValueError("typert-loader: " + package + " " + message)
    def obj(value, subject):
        if not isinstance(value, dict):
            fail(subject + " must be an object")
        return value
    def array(value, subject):
        if not isinstance(value, list):
            fail(subject + " must be an array")
        return value
    def string(value, key, subject):
        if not isinstance(value.get(key), str) or not value[key]:
            fail(subject + " has missing or empty " + key)
    def strict(codec):
        obj(codec, "codec")
        if codec.get("mode") != "strict" or not callable(field(codec.get("schema"), "parse")):
            fail("codec must use an executable strict schema")
        string(codec, "typeSymbol", "codec")
    obj(manifest, "TYPERT")
    if manifest.get("package") != package or manifest.get("face") != "host":
        fail("TYPERT must name its owning package and host face")
    for schema in array(manifest.get("schemas"), "schemas"):
        obj(schema, "schema")
        string(schema, "name", "schema")
        if not callable(field(schema.get("schema"), "parse")):
            fail("schema is not executable")
    model = obj(manifest.get("model"), "model")
    for kind in ("services", "events", "objects"):
        for row in array(model.get(kind), kind):
            obj(row, kind + " entry")
            array(row.get("tags"), "tags")
            for key in ("description", "summary", "jsDoc"):
                if key in row and not isinstance(row[key], str):
                    fail(key + " must be a string")
            if kind == "events":
                string(row, "name", "event")
                string(row, "signature", "event")
                if "mode" in row and not isinstance(row["mode"], str):
                    fail("event mode must be a string")
                continue
            string(row, "key" if kind == "services" else "name", kind)
            string(row, "exportName", kind)
            for member in array(row.get("members"), "members"):
                obj(member, "member")
                for key in ("name", "signature"):
                    string(member, key, "member")
                if member.get("kind") not in ("property", "method", "getter", "setter", "call", "construct", "index"):
                    fail("member has invalid kind")
            for value in array(row.get("types"), "types"):
                obj(value, "type")
                for key in ("name", "declaration"):
                    string(value, key, "type")
    for row in array(manifest.get("invocations"), "invocations"):
        obj(row, "invocation")
        receiver = obj(row.get("invocation"), "invocation receiver")
        if receiver.get("kind") not in ("direct", "context"):
            fail("receiver kind must be direct or context")
        if receiver["kind"] == "context":
            strict(receiver.get("codec"))
        for parameter in array(row.get("parameters"), "parameters"):
            obj(parameter, "parameter")
            if parameter.get("source") not in ("lookup", "json"):
                fail("parameter source must be lookup or json")
            strict(parameter.get("codec"))
        strict(row.get("result"))
        validate_invocation(row)
        if "sourceLocation" in row:
            location = obj(row["sourceLocation"], "sourceLocation")
            string(location, "file", "sourceLocation")
            if any(type(location.get(key)) is not int or location[key] < 1 for key in ("line", "column")):
                fail("sourceLocation line and column must be positive integers")
    return manifest


class TypertLoader(Plugin):
    id = "typert-loader"
    inject = ["typert", "loader"]

    async def apply(self, ctx):
        configured = self.config.get("packages", [])
        if not isinstance(configured, list) or any(not isinstance(name, str) or not name for name in configured):
            raise ValueError("typert-loader: packages must be non-empty strings")
        configured = set(configured)
        base = getattr(ctx, "baseUrl", None)
        if not base:
            raise ValueError("typert-loader: ctx.baseUrl is unset")
        if base.startswith("file:"):
            base = unquote(urlparse(base).path)
            if os.name == "nt" and base.startswith("/"):
                base = base[1:]
        base = os.path.abspath(base)
        if os.path.isfile(base):
            base = os.path.dirname(base)
        loader, registry = ctx.get("loader"), ctx.get("typert")
        paths, manifests, registered, pending, dirty = {}, {}, {}, {}, set()
        state = {"active": True, "queued": False}
        tasks = set()

        def artifact(name):
            if name in paths:
                return paths[name]
            manifest_path = None
            package, subpath = split_package_specifier(name)
            if not subpath and not name.startswith((".", "/", "cordis:")):
                for root in module_search_dirs(base, getattr(loader, "installation_module_roots", [])):
                    candidate = os.path.join(root, package, "package.json")
                    if os.path.isfile(candidate):
                        manifest_path = candidate
                        break
                if manifest_path is None and name in getattr(loader, "harness_plugins", {}):
                    from dsh.boot.profile import workspace_package_index
                    directory = workspace_package_index(__file__).get(name)
                    if directory:
                        manifest_path = os.path.join(directory, "package.json")
            if manifest_path is None:
                if name in configured:
                    raise ValueError("typert-loader: configured package cannot be resolved: " + name)
                paths[name] = None
                return None
            # The Python installation uses vendored generated artifacts while
            # healed development links may point at unbuilt reference sources.
            # Apply the same installation ownership rule as plugin resolution;
            # project-local packages always retain their own artifacts.
            if name in getattr(loader, "harness_plugins", {}) and is_installation_owned_module(
                    manifest_path, getattr(loader, "installation_module_roots", [])):
                from dsh.boot.profile import workspace_package_index
                directory = workspace_package_index(__file__).get(name)
                if directory:
                    manifest_path = os.path.join(directory, "package.json")
            with open(manifest_path, "r", encoding="utf-8") as stream:
                package_json = json.load(stream)
            exports = package_json.get("exports")
            target = exports.get("./typert") if isinstance(exports, dict) else None
            if isinstance(target, dict):
                target = target.get("default")
                if not isinstance(target, str):
                    raise ValueError("typert-loader: typert export needs a string default: " + name)
            elif target is not None and not isinstance(target, str):
                raise ValueError("typert-loader: typert export must be a string: " + name)
            if target is None and name in configured:
                raise ValueError("typert-loader: configured package does not export ./typert: " + name)
            paths[name] = os.path.join(os.path.dirname(manifest_path), target) if target is not None else None
            return paths[name]

        def qualifies(name):
            return name in configured or any(entry.options.get("name") == name and entry.fiber is not None and not entry.disabled for entry in loader.entries())

        async def reconcile(name):
            if not qualifies(name):
                dispose = registered.pop(name, None)
                if dispose is not None:
                    result = dispose()
                    if inspect.isawaitable(result):
                        await result
                return
            if name in registered or name in pending:
                return
            path = artifact(name)
            if path is None:
                return
            pending[name] = True
            try:
                if name not in manifests:
                    try:
                        if path.endswith(".py"):
                            spec = importlib.util.spec_from_file_location("_dsh_typert_" + str(id(paths)) + "_" + str(len(manifests)), path)
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)
                            value = getattr(module, "TYPERT", None)
                        else:
                            value = read_generated_artifact(path)
                        manifests[name] = validate_manifest(name, value)
                    except Exception as error:
                        manifests[name] = error
                value = manifests[name]
                if isinstance(value, Exception):
                    raise ValueError("typert-loader: cannot import " + name + ": " + str(value)) from value
                if state["active"] and qualifies(name) and name not in registered:
                    registered[name] = registry.register(value)
            finally:
                pending.pop(name, None)

        async def flush(activation=False):
            errors = []
            for name in list(dirty):
                dirty.discard(name)
                try:
                    await reconcile(name)
                except Exception as error:
                    errors.append(error)
                    if not activation:
                        logging.getLogger("typert-loader").error("%s", error)
            if activation and errors:
                raise ValueError("typert-loader: {} contributor(s) failed: {}".format(len(errors), "; ".join(map(str, errors))))

        def queued():
            state["queued"] = False
            if state["active"]:
                task = asyncio.create_task(flush())
                tasks.add(task)
                task.add_done_callback(tasks.discard)

        def changed(fiber):
            entry = getattr(fiber, "entry", None)
            name = entry.options.get("name") if entry is not None else None
            if name is None:
                return
            dirty.add(name)
            if not state["queued"]:
                state["queued"] = True
                asyncio.get_running_loop().call_soon(queued)

        async def close():
            state["active"] = False
            dirty.clear()
            if tasks:
                await asyncio.gather(*list(tasks), return_exceptions=True)
        ctx.effect(lambda: close, "typert loader lifetime")
        ctx.on("internal/plugin", changed)
        dirty.update(configured)
        dirty.update(entry.options["name"] for entry in loader.entries())
        await flush(activation=True)
