"""Loader-owned browser artifacts; no filesystem roster participates in boot."""
import asyncio
import json
import os
from urllib.parse import unquote, urlparse

from dsh.cordis.loader import resolve_module_specifier, split_package_specifier, is_installation_owned_module
from dsh.host.client_modules.registry import (
    ClientModuleRegistry, ClientPackageCompositionError, ABSENT,
    parse_dsh_client, client_export_of, graph_row,
)


class LoaderClientModuleRegistry(ClientModuleRegistry):
    def __init__(self, ctx):
        super().__init__(ctx, roster=set())
        self.loader = ctx.get('loader')
        self.sources, self.metadata, self.dirty = {}, {}, {}
        self.queued, self.closed = False, False
        self.compose()
        ctx.on('internal/plugin', self.changed)
        ctx.effect(lambda: self.close)
        for entry in self.loader.entries():
            self.dirty[entry.options['name']] = None
        self.reconcile(activation=True)

    def close(self):
        self.closed = True
        self.dirty.clear()

    def changed(self, fiber):
        entry = getattr(fiber, 'entry', None)
        if entry is None or self.closed:
            return
        self.dirty[entry.options['name']] = None
        if not self.queued:
            self.queued = True
            asyncio.get_running_loop().call_soon(self.reconcile)

    def locate(self, name, base):
        if name.startswith('cordis:'):
            return None
        path_like = name.startswith(('.', 'file:', '/', '\\')) or os.path.isabs(name)
        package, subpath = split_package_specifier(name)
        if not path_like and (not package or subpath is not None):
            return None
        path = unquote(urlparse(base).path) if base.startswith('file:') else base
        if os.name == 'nt' and path.startswith('/'):
            path = path[1:]
        if os.path.isfile(path):
            path = os.path.dirname(path)
        roots = getattr(self.loader, 'installation_module_roots', [])
        resolved = resolve_module_specifier(name, path, roots)
        if name in getattr(self.loader, 'harness_plugins', {}) and (
                resolved is None or is_installation_owned_module(resolved, roots)):
            from dsh.boot.profile import workspace_package_index
            directory = workspace_package_index(__file__).get(name)
            if directory:
                return os.path.join(directory, 'package.json')
        if resolved is None:
            return None
        directory = resolved if os.path.isdir(resolved) else os.path.dirname(resolved)
        while True:
            manifest = os.path.join(directory, 'package.json')
            try:
                with open(manifest, encoding='utf-8') as stream:
                    value = json.load(stream)
                if isinstance(value.get('name'), str) and (path_like or value['name'] == package):
                    return manifest
            except (OSError, ValueError):
                pass
            parent = os.path.dirname(directory)
            if parent == directory:
                return None
            directory = parent

    def source(self, entry):
        name, base = entry.options['name'], getattr(entry.parent.tree.ctx, 'baseUrl', None)
        if base is None:
            raise ValueError('client-modules: loader entry %s has no resolution base URL' % name)
        key = base + '\0' + name
        if key not in self.metadata:
            manifest = self.locate(name, base)
            meta = None
            if manifest is not None:
                with open(manifest, encoding='utf-8') as stream:
                    package = json.load(stream)
                dsh = package.get('dsh')
                decl = parse_dsh_client(package['name'], dsh.get('client', ABSENT) if isinstance(dsh, dict) else ABSENT)
                if decl is not None and decl['platform'] == 'web':
                    target = client_export_of(package['name'], package.get('exports'))
                    if target is None:
                        raise ValueError('client-modules: %s declares dsh.client but exports no "./client" bundle' % package['name'])
                    meta = dict(name=package['name'], client_path=os.path.normpath(os.path.join(os.path.dirname(manifest), target)),
                                inject=decl.get('inject', []), external=decl.get('external', []),
                                immediately=decl.get('immediately', False), source_key=key)
            self.metadata[key] = meta
        meta = self.metadata[key]
        return None if meta is None else dict(key=key, name=name, base=base, meta=meta)

    def reconcile(self, activation=False):
        self.queued = False
        if self.closed:
            return
        errors, changed = [], False
        for name in list(self.dirty):
            self.dirty.pop(name, None)
            try:
                next_sources = {}
                for entry in self.loader.entries():
                    if entry.options['name'] == name and entry.fiber is not None and not entry.disabled:
                        source = self.source(entry)
                        if source is not None:
                            next_sources[source['key']] = source
                affected = {}
                for key, source in list(self.sources.items()):
                    if source['name'] == name:
                        affected[source['meta']['name']] = None
                        if key not in next_sources:
                            del self.sources[key]
                for key, source in next_sources.items():
                    self.sources[key] = source
                    affected[source['meta']['name']] = None
                for package in affected:
                    try:
                        sources = [source for source in self.sources.values() if source['meta']['name'] == package]
                        if len(sources) > 1:
                            raise ValueError('client-modules: package %s resolves from multiple active Loader sources: %s; remove one entry' %
                                             (package, ', '.join('%s from %s' % (s['name'], s['base']) for s in sources)))
                        old = self._pkg_meta.get(package)
                        new = sources[0]['meta'] if sources else None
                        if old is new:
                            continue
                        if new is None:
                            self._pkg_meta.pop(package, None)
                            self._table.pop(package, None)
                            self._bundle_paths.pop(package, None)
                            self._bundle_cache.pop(package, None)
                        else:
                            # Validate before replacing the previous live generation.
                            baseline, bundle, source_map = self.initial_bundle_snapshot(package, new['client_path'])
                            self._table[package] = dict(id=package, meta=new, baseline=baseline, bundle=bundle,
                                source_map=source_map, entry=graph_row(package, self.allocate_initial_revision(), new))
                            self._pkg_meta[package] = new
                        changed = True
                    except Exception as error:
                        errors.append(error)
            except Exception as error:
                errors.append(error)
        if changed:
            try:
                self.compose()
                self.notify_graph_changed()
            except Exception as error:
                errors.append(error)
        if errors and activation:
            raise ClientPackageCompositionError(errors)
        for error in errors:
            self._log_warn(error)

    def graph(self):
        return self._composed

    def package_order(self):
        return self._pkg_meta
