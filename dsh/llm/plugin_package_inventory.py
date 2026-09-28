"""Active Loader package provenance for the official DeepSeek request field.

The Python installation table replaces Node's installed module closure. Only
active Loader entries are looked up in that closure; installed dependencies and
anonymous plugin fibers never become request inventory merely by existing.
"""
import json
import os
from urllib.parse import unquote, urlparse

from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import module_search_dirs, split_package_specifier
from dsh.cordis.plugin import Plugin


def _directory(value):
    if value.startswith("file:"):
        value = unquote(urlparse(value).path)
        if os.name == "nt" and value.startswith("/"):
            value = value[1:]
    value = os.path.abspath(value)
    return os.path.dirname(value) if os.path.isfile(value) else value


def _identity(path, anonymous=False):
    with open(path, "r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if anonymous and isinstance(manifest, dict) and "name" not in manifest:
        return None
    if not isinstance(manifest, dict) or any(
            not isinstance(manifest.get(key), str) or not manifest[key] for key in ("name", "version")):
        raise ValueError("plugin-package-inventory-deepseek: {} must declare non-empty name and version".format(path))
    return {key: manifest[key] for key in ("name", "version")}


class PackageIdentityResolver:
    def __init__(self, host_base, loader):
        self.host_base, self.loader, self.cache = host_base, loader, {}

    def resolve(self, entry, bare_base=None):
        tree = entry.parent.tree
        tree_base = getattr(tree.ctx, "baseUrl", None) or self.host_base
        anchors = tuple(dict.fromkeys([bare_base or tree_base, tree_base, self.host_base]))
        name = entry.options["name"]
        key = anchors + (name,)
        if key in self.cache:
            return self.cache[key]
        bare = not (name.startswith((".", "/", "\\")) or ":" in name or os.path.isabs(name))
        manifest = None
        if bare:
            package, _ = split_package_specifier(name)
            for anchor in anchors:
                for root in module_search_dirs(_directory(anchor), getattr(self.loader, "installation_module_roots", [])):
                    candidate = os.path.join(root, package, "package.json")
                    if os.path.isfile(candidate):
                        manifest = candidate
                        break
                if manifest is not None:
                    break
            if manifest is None and name in getattr(self.loader, "harness_plugins", {}):
                from dsh.boot.profile import workspace_package_index
                directory = workspace_package_index(__file__).get(package)
                if directory is not None:
                    manifest = os.path.join(directory, "package.json")
            if manifest is None:
                raise ValueError("plugin-package-inventory-deepseek: cannot resolve active package {!r}".format(package))
        elif not name.startswith("cordis:"):
            module = name
            if module.startswith("file:"):
                module = unquote(urlparse(module).path)
                if os.name == "nt" and module.startswith("/"):
                    module = module[1:]
            # Local Python rows can explicitly select the exported class.
            if ".py:" in module:
                module = module.rsplit(":", 1)[0]
            current = os.path.dirname(os.path.abspath(os.path.join(_directory(tree_base), module)))
            while True:
                candidate = os.path.join(current, "package.json")
                if os.path.isfile(candidate):
                    manifest = candidate
                    break
                parent = os.path.dirname(current)
                if parent == current:
                    break
                current = parent
        value = _identity(manifest, anonymous=not bare) if manifest else None
        self.cache[key] = value
        return value


def _active(tree, root_base=None):
    for entry in tree.entries():
        if not entry.options.get("group") and not entry.disabled and getattr(entry.fiber, "state", None) == FiberState.ACTIVE:
            yield entry, root_base if entry.parent.tree is tree else None


class PluginPackageInventoryDeepSeek(Plugin):
    id = "plugin-package-inventory-deepseek"
    inject = ["agents", "deepseekLlmApiExtensions", "loader"]

    def apply(self, ctx):
        enabled = self.config.get("enabled", True)
        if type(enabled) is not bool:
            raise ValueError("plugin-package-inventory-deepseek: enabled must be boolean")
        if not enabled:
            return
        host_base = getattr(ctx, "baseUrl", None) or os.path.dirname(__file__)
        loader = ctx.get("loader")
        resolver = PackageIdentityResolver(host_base, loader)

        async def prepare(request):
            entries = list(_active(loader))
            session_id = request.get("sessionId")
            if session_id is not None and ctx.get("agentPresets") is not None:
                agent = ctx.get("agents").get(session_id)
                if agent is not None:
                    from dsh.presets.mount import standing_mount_for
                    mount = standing_mount_for(agent.ctx)
                    if mount is not None:
                        entries.extend(_active(mount.tree, host_base))
            unique = {}
            for entry, base in entries:
                identity = resolver.resolve(entry, base)
                if identity is not None:
                    unique[(identity["name"], identity["version"])] = identity
            return {"value": {"version": 1, "packages": [unique[key] for key in sorted(unique)]}}

        ctx.get("deepseekLlmApiExtensions").register("dsh_plugin_packages", {"prepare": prepare})
