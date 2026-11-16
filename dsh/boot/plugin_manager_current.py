"""Current profile management Remote, extended in verified contract batches."""
import asyncio
import datetime
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from dsh.boot.bundle_platform import UnsupportedBundlePlatformError
from dsh.boot.plugin_switch import flatten, write_plugin_enabled
from dsh.boot.plugin_bundle_metadata import (OFFICIAL_DATA, OFFICIAL_CATALOG, OPTIONAL_BUNDLES,
    bundle_directory, bundle_manifest, bundle_selection, official_bundle_install_target, update_refusal)
from dsh.boot.plugin_install_spec import dependency_spec, parse_install_spec, InvalidInstallSpecError
from dsh.boot.plugin_bundle_detail import read_bundle_document, read_bundle_image
from dsh.boot.plugin_inspection import PluginInspection
from dsh.boot.plugin_registry_policy import normalize_registry, NPMMIRROR_REGISTRY
from dsh.boot.plugin_compatibility import evaluate_plugin_compatibility, get_dsh_runtime_version
from dsh.boot.package_meta import read_plugin_meta
from dsh.boot.plugin_packages import ResolutionRestartRequired
from dsh.boot.profile import compose_entries, read_profile_manifest, bundle_patch_paths
from dsh.boot.app_boot import load_overlay_patches
from dsh.boot.profile_compatibility import (PROFILE_COMPATIBILITY_FILENAME, read_profile_version_exemptions,
    read_profile_compatibility, set_profile_version_exemption, validate_plugin_version_exemption)
from dsh.boot.profile_context import read_profile_patches
from dsh.boot.runtime_resolution import _field
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.errors import ThrownValueError
from dsh.cordis.file_lock import with_file_lock
from dsh.cordis.schema import Schema
from dsh.cordis.utils import js_to_string, _js_own_enumerable_keys
from dsh.core.abort import AbortController
from dsh.host.plugin_inventory.current import read_plugin_inventory
from dsh.typert.remote import Remote, TypertRemoteService, RemoteError, remote_error_of
from dsh.util.atomic_write import write_file_atomic
from dsh.util.plugin_detail import NPM_FILE_SOURCES, detail_image_response


PROTECTED_PLUGINS = frozenset(OFFICIAL_DATA['protectedPlugins'])


class ManagementFailure(RuntimeError):
    def __init__(self, code, incompatible=None):
        super().__init__(code)
        self.code, self.incompatible = code, incompatible


class InstallCancelledError(RuntimeError):
    def __init__(self):
        super().__init__('Installation cancelled')


def management_error(error):
    if isinstance(error, UnsupportedBundlePlatformError):
        return dict(code='unsupported-platform')
    if isinstance(error, ManagementFailure):
        result = dict(code=error.code)
        if error.incompatible is not None:
            result['incompatible'] = error.incompatible
        return result
    return dict(code='operation-error', diagnostic=js_to_string(error.value)
                if isinstance(error, ThrownValueError) else getattr(error, 'message', str(error)))


def _bounded(value, limit):
    return isinstance(value, str) and len(value.encode('utf-16-le', errors='surrogatepass')) // 2 <= limit


def diagnostic_version(value):
    return value if _bounded(value, 128) else None


class CurrentPluginManager(PluginInspection, TypertRemoteService):
    inject = ['loader', 'profileContext']
    Config = Schema.object(dict(lockWaitMs=Schema.number().step(1).min(0).default(120000),
        pnpmCommand=Schema.string().default('pnpm'),
        inspectTimeoutMs=Schema.number().step(1).min(1000).default(20000),
        registry=Schema.string().pattern(r'^https?://\S+$'),
        fallbackRegistries=Schema.array(Schema.string().pattern(r'^https?://\S+$')).default([NPMMIRROR_REGISTRY]),
        versionListLimit=Schema.number().step(1).min(1).default(20),
        versionLookupConcurrency=Schema.number().step(1).min(1).default(4),
        detailMaxBytes=Schema.natural().min(1).default(1024*1024),
        detailImageMaxBytes=Schema.natural().min(1).default(5*1024*1024),
        detailFetchTimeoutMs=Schema.natural().min(1).max(2147483647).default(15000),
        detailNpmFileSources=Schema.array(Schema.union(NPM_FILE_SOURCES)).min(1).default(list(NPM_FILE_SOURCES))))

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'pluginManager')
        self.profile = ctx.profileContext
        self.owner_context = ctx
        self.owner_entry_id = _field(getattr(ctx.fiber, 'entry', None), 'id')
        self.management_bundles = set()
        for name in _field(self.profile, 'startedBundles', []):
            self._protects_manager(name)
        self.lock_wait_ms = (config or {}).get('lockWaitMs', 120000)
        config = config or {}
        self.pnpm_command = config.get('pnpmCommand', 'pnpm')
        self.inspect_timeout_ms = config.get('inspectTimeoutMs', 20000)
        self.registry = normalize_registry(config['registry']) if 'registry' in config else None
        self.fallback_registries = [normalize_registry(url) for url in config.get('fallbackRegistries', [NPMMIRROR_REGISTRY])]
        self.version_list_limit = config.get('versionListLimit', 20)
        self.version_lookup_concurrency = config.get('versionLookupConcurrency', 4)
        self.installed_from = {}
        self.abort = AbortController()
        values = dict(detailMaxBytes=1024*1024, detailImageMaxBytes=5*1024*1024,
            detailFetchTimeoutMs=15000, detailNpmFileSources=list(NPM_FILE_SOURCES))
        values.update(config or {})
        self.detail = dict(profile=self.profile, maxDocumentBytes=values['detailMaxBytes'],
            maxImageBytes=values['detailImageMaxBytes'], npmFileSources=values['detailNpmFileSources'],
            timeoutMs=values['detailFetchTimeoutMs'], lifetime=self.abort.signal)
        self.package_operations = set()
        self.diagnostics = set()
        def close():
            self.abort.abort()
            async def drain():
                await asyncio.gather(*list(self.package_operations), return_exceptions=True)
            return drain()
        ctx.effect(lambda: close)
        def register(scope):
            scope.effect(lambda: scope.get('connection').fetch.register(dict(
                path='/api/plugin-manager/detail-file', methods=['GET'], requestBody='buffered',
                fetch=self._serve_detail_file)), 'plugin-manager: detail-file')
        ctx.inject(['connection'], register)

    async def _listed_bundle(self, name):
        bundle = next((row for row in await self.listBundles() if row['name'] == name), None)
        if bundle is None:raise RemoteError('plugin-manager/unknown-bundle', 'No such bundle: '+name, dict(name=name))
        return bundle

    @Remote('readBundleDetail')
    async def readBundleDetail(self, name, language, options=None):
        return await read_bundle_document(await self._listed_bundle(name), language, (options or {}).get('npmFileSources') or [], self.detail)

    async def _serve_detail_file(self, request):
        params = parse_qs(urlsplit(_field(request, 'url')).query, keep_blank_values=True)
        if any(key not in params for key in ('bundle', 'document', 'path')):
            return detail_image_response('invalid', 'no-store')
        bundle, document, path = [params[key][0] for key in ('bundle', 'document', 'path')]
        sources = params.get('sources', [''])[0].split(',')
        try:
            image = await read_bundle_image(await self._listed_bundle(bundle), document, path, sources, self.detail)
            return detail_image_response(image, 'no-store')
        except Exception as error:
            failure = remote_error_of(error)
            if failure is not None:
                if failure['code'] == 'plugin-manager/unknown-bundle':return detail_image_response(None, 'no-store')
                if failure['code'] == 'plugin-manager/detail-unavailable':return detail_image_response(failure['details']['reason'], 'no-store')
            raise

    @Remote('listPlugins')
    async def listPlugins(self):
        rows = flatten(compose_entries([read_profile_patches('dsh', self.profile)]))
        snapshot = await read_plugin_inventory(self.ctx)
        result = []
        for source in snapshot['entries']:
            entry = next((row for row in self.ctx.loader.entries() if row.id == source['entryId']), None)
            candidates = [row for row in rows if row.get('id') == _field(_field(entry, 'options'), 'id')]
            row = dict(source)
            if source['moduleName'] in PROTECTED_PLUGINS or source['entryId'] == self.owner_entry_id:
                row['readOnlyReason'] = 'management-required'
            elif (not candidates or len(candidates) > 1 or candidates[0].get('name') != source['moduleName']
                  or _field(getattr(entry.parent.tree.ctx.fiber, 'entry', None), 'id') != 'include'):
                row['readOnlyReason'] = 'unaddressable'
            else:
                row['patchId'] = candidates[0]['id']
            result.append(row)
        return result

    def _bundle_directory(self, name):
        return bundle_directory(name, _field(self.profile, 'dir'), _field(self.profile, 'installAnchor'))

    def _bundle_manifest(self, name):
        return bundle_manifest(name, _field(self.profile, 'dir'), _field(self.profile, 'installAnchor'))

    def _bundle_patches(self, name, manifest):
        result = []
        for filename in bundle_patch_paths(self._bundle_directory(name), manifest['dsh']['bundle']):
            result.extend(load_overlay_patches('dsh', filename))
        return result

    def _bundle_rows(self, name):
        manifest = self._bundle_manifest(name)
        return [] if manifest is None else flatten(compose_entries([self._bundle_patches(name, manifest)]))

    def _protects_manager(self, name):
        if name in self.management_bundles:
            return True
        try:
            rows = self._bundle_rows(name)
        except Exception:
            return False
        protected = any(row.get('name') in PROTECTED_PLUGINS or 'include:'+str(row.get('id')) == self.owner_entry_id for row in rows)
        if protected:
            self.management_bundles.add(name)
        return protected

    @staticmethod
    def _assert_platform(bundle):
        from dsh.boot.bundle_platform import assert_bundle_platform
        if isinstance(bundle, dict) and 'platforms' in bundle:
            assert_bundle_platform(bundle['platforms'])

    def _assert_compatibility(self, manifest, exemptions):
        issue = evaluate_plugin_compatibility(manifest, exemptions)
        if issue is not None and not issue['exempted']:
            raise ManagementFailure('incompatible-version', [{key:issue[key] for key in ('name', 'version', 'runtimeVersion', 'requirements')}])

    def _declared_rows(self, name, manifest):
        patches = self._bundle_patches(name, manifest)
        directory = self._bundle_directory(name)
        live = {entry.options['id']:entry for entry in self.ctx.loader.entries() if isinstance(entry.options.get('id'), str)}
        rows = []
        packages = self.ctx.get('pluginPackages')
        for row in flatten(compose_entries([[patch for patch in patches if 'insert' in patch]])):
            if not isinstance(row.get('id'), str) or not isinstance(row.get('name'), str) or row.get('group') is True:
                continue
            active = live.get(row['id'])
            base = _field(active.parent.tree.ctx, 'baseUrl') if active is not None else None
            if base is None:
                base = Path(directory, 'package.json').as_uri()
            meta = None if packages is None else packages.metaOf(row['name'], base)
            item = dict(rowId=row['id'], moduleName=row['name'])
            if active is not None:
                item['entryId'] = active.id
            if meta is not None:
                item['meta'] = meta
            rows.append(item)
        declared = {row['rowId'] for row in rows}
        overrides = list(dict.fromkeys(patch['id'] for patch in patches
            if 'insert' not in patch and isinstance(patch.get('id'), str) and patch['id'] not in declared))
        return dict(rows=rows, overrides=overrides)

    def _read_bundles(self):
        manifest = read_profile_manifest('dsh', _field(self.profile, 'dir'))
        exemptions = read_profile_version_exemptions(_field(self.profile, 'dir'))
        selected, recorded = bundle_selection(manifest), manifest.get('dependencies') or {}
        dependencies = _js_own_enumerable_keys(recorded)
        with open(_field(self.profile, 'installAnchor'), 'r', encoding='utf-8', errors='replace') as stream:
            installation = json.load(stream)
        catalog = {entry['packageName']:entry for entry in OFFICIAL_CATALOG}
        shipped_names = _js_own_enumerable_keys(installation.get('dependencies') or {})
        names = list(dict.fromkeys([*selected, *dependencies, *shipped_names, *catalog]))
        bundles = []
        runtime = get_dsh_runtime_version()
        for name in names:
            installed, enabled, shipped = name in dependencies, name in selected, name in shipped_names
            optional, offered = name in OPTIONAL_BUNDLES, catalog.get(name)
            official = optional or offered is not None
            target, target_error = {}, None
            if offered is not None:
                try:
                    target['installTarget'] = official_bundle_install_target(name, _field(self.profile, 'installAnchor'), runtime)
                except Exception as error:
                    target_error = management_error(error)
            catalog_meta = {} if offered is None else dict(meta=offered['meta'])
            if offered is not None and not installed and not shipped:
                platform_error = None
                try:
                    self._assert_platform(offered)
                except Exception as error:
                    platform_error = management_error(error)
                error = platform_error or target_error or (dict(code='not-bundle') if enabled else None)
                item = dict(name=name, official=official, availability='missing', enabled=enabled,
                            installed=installed, optional=optional, removable=enabled, rows=[], overrides=[], **catalog_meta, **target)
                if platform_error is not None and platform_error['code'] == 'unsupported-platform':
                    item['listedByDefault'] = False
                if error is not None:
                    item['error'] = error
                bundles.append(item)
                continue
            owned = installed and not shipped
            removable = owned or (enabled and not installed and not shipped)
            def source_of(package_name=None):
                return dict(source=dependency_spec(name, recorded[name], _field(self.profile, 'dir'), package_name)) if owned else {}
            read_only = 'management-required' if self._protects_manager(name) else None
            availability, version, version_present, listing = 'missing', None, False, {}
            def basic():
                item = dict(name=name, official=official, availability=availability, enabled=enabled,
                            installed=installed, optional=optional, removable=removable and read_only is None,
                            **catalog_meta, **target, **listing)
                if read_only is not None:
                    item['readOnlyReason'] = read_only
                if version_present:
                    item['version'] = version
                return item
            try:
                info = self._bundle_manifest(name)
                availability = 'installation' if shipped else 'profile'
                if info is None:
                    if enabled or offered is not None:
                        bundles.append(dict(basic(), **source_of(), error=target_error or dict(code='not-bundle'), rows=[], overrides=[]))
                    continue
                version = info.get('version')
                version_present = 'version' in info
                bundle = info['dsh']['bundle']
                listed = bundle.get('listedByDefault')
                listing_diagnostic = None if 'listedByDefault' not in bundle or type(listed) is bool else 'dsh.bundle.listedByDefault must be a boolean'
                if type(listed) is bool:
                    listing['listedByDefault'] = listed
                self._assert_compatibility(info, exemptions)
                directory = self._bundle_directory(name)
                meta = offered['meta'] if offered is not None else read_plugin_meta(info.get('name') if info.get('name') is not None else name, Path(directory, 'package.json').as_uri())
                if listing_diagnostic is not None:
                    meta = dict(meta or {})
                    meta['error'] = listing_diagnostic if 'error' not in meta else meta['error']+'; '+listing_diagnostic
                platform_error = None
                try:
                    self._assert_platform(bundle)
                except Exception as error:
                    platform_error = management_error(error)
                if platform_error is not None and platform_error['code'] == 'unsupported-platform':
                    listing['listedByDefault'] = False
                error = platform_error or target_error
                item = dict(basic(), **source_of(info.get('name')), **self._declared_rows(name, info))
                if 'description' in info and info['description'] != '':
                    item['description'] = info['description']
                if meta is not None:
                    item['meta'] = meta
                else:
                    item.pop('meta', None)
                if error is not None:
                    item['error'] = error
                bundles.append(item)
            except Exception as error:
                if enabled or installed or optional or offered is not None:
                    bundles.append(dict(basic(), **source_of(), error=target_error or management_error(error), rows=[], overrides=[]))
        return bundles

    @Remote('listBundles')
    async def listBundles(self):
        bundles = self._read_bundles()
        for bundle in bundles:
            target = update_refusal(bundle, bundle['name'])
            if not isinstance(target, str):
                bundle['update'] = target['kind']
        return bundles

    async def _select_bundle(self, name, enabled):
        import json
        manifest = read_profile_manifest('dsh', _field(self.profile, 'dir'))
        previous = bundle_selection(manifest)
        if enabled or name not in previous:
            metadata = self._bundle_manifest(name)
            if metadata is None:
                raise ManagementFailure('not-bundle')
            if enabled:
                self._assert_platform(metadata['dsh']['bundle'])
                self._assert_compatibility(metadata, read_profile_version_exemptions(_field(self.profile, 'dir')))
                self._bundle_rows(name)
        if not enabled and name in previous and self._protects_manager(name):
            raise ManagementFailure('management-required')
        selected = previous + ([] if name in previous else [name]) if enabled else [item for item in previous if item != name]
        if previous == selected:
            return
        dsh = dict(manifest.get('dsh') or {})
        dsh['profile'] = dict(dsh.get('profile') or {}, bundles=selected)
        manifest['dsh'] = dsh
        await write_file_atomic(os.path.join(_field(self.profile, 'dir'), 'package.json'), json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', mode=0o600)
        if enabled:
            self._protects_manager(name)

    async def _refresh_packages(self):
        selected = bundle_selection(read_profile_manifest('dsh', _field(self.profile, 'dir')))
        if any(name not in selected for name in _field(self.profile, 'startedBundles', [])):
            return
        packages = self.owner_context.get('pluginPackages')
        if packages is not None and _field(packages, 'resolution') is not None:
            try:
                await await_callback_result(packages.refresh())
            except ResolutionRestartRequired:
                pass

    async def _publish_and_reload(self, required_ids=()):
        if self.owner_context.get('hmr') is None:
            await self._refresh_packages()
        return await self._reload(required_ids)

    @Remote('setBundleEnabled')
    async def setBundleEnabled(self, name, enabled):
        async def operation(result):
            async def apply():
                await self._select_bundle(name, enabled)
                result.update(await self._publish_and_reload([row['id'] for row in self._bundle_rows(name)]) if enabled else await self._reload())
            await self._configure(apply)
        return await self._change(operation, dict(stage='enable', target=name, enabled=enabled), 'bundle')

    async def _configure(self, operation):
        async def apply():
            self.abort.signal.throwIfAborted()
            return await await_callback_result(operation())
        hmr = self.owner_context.get('hmr')
        return await apply() if hmr is None else await hmr.runExclusive(apply)

    @Remote('listVersionExemptions')
    def listVersionExemptions(self):
        record = read_profile_compatibility(_field(self.profile, 'dir'))
        return dict(exemptions=record['exemptions'], warnings=record['warnings'])

    @Remote('setVersionExemption')
    async def setVersionExemption(self, package_version, runtime_version, enabled, acceptRisk=None):
        identity = dict(target=None)
        try:
            validate_plugin_version_exemption(package_version, runtime_version)
        except (ValueError, TypeError):
            pass
        else:
            name, _, version = package_version.rpartition('@')
            identity = dict(target=self._operation_target('install', name), version=diagnostic_version(version))
        async def operation(result):
            async def apply():
                await set_profile_version_exemption(_field(self.profile, 'dir'), package_version,
                    runtime_version, enabled, acceptRisk is True)
                result.update(await self._reload())
            await self._configure(apply)
        return await self._change(operation, dict(stage='enable', target=package_version, enabled=enabled), 'bundle', identity)

    async def _reload(self, required_ids=()):
        hmr = self.owner_context.get('hmr')
        if hmr is None:
            compose_entries([read_profile_patches('dsh', self.profile)])
            return dict(warnings=[])
        result = await hmr.reconcileProfile(required_ids)
        restart = result.get('restartReason')
        if restart is None and result.get('pending'):
            restart = result['pending'][0]['reason']
        return dict(warnings=result['warnings'], **({} if restart is None else dict(restartReason=restart)))

    @Remote('setPluginEnabled')
    async def setPluginEnabled(self, identity, enabled):
        async def operation(result):
            async def apply():
                row = next((item for item in await self.listPlugins() if item['entryId'] == identity), None)
                if row is None:
                    raise ManagementFailure('unknown-plugin')
                if 'readOnlyReason' in row:
                    raise ManagementFailure(row['readOnlyReason'])
                await write_plugin_enabled(self.profile, row['patchId'], row['moduleName'], enabled)
                result.update(await self._reload([row['patchId']] if enabled else []))
                current = next((item for item in await self.listPlugins() if item['entryId'] == identity), None)
                if _field(current, 'enabled') != enabled and self.owner_context.get('hmr') is not None:
                    return 'overridden'
            return await self._configure(apply)
        return await self._change(operation, dict(stage='enable', target=identity, enabled=enabled), 'plugin')

    def _operation_target(self, reason, target):
        if reason == 'plugin':
            return target if _bounded(target, 256) and any(entry.id == target for entry in self.ctx.loader.entries()) else None
        try:
            parsed = parse_install_spec(target)
        except InvalidInstallSpecError:
            return None
        name = parsed['name'] if parsed['kind'] == 'registry' else None
        return name if reason == 'install' or name == target else None

    def _operation_version(self, reason, target):
        if reason == 'install' or target is None:
            return None
        try:
            if reason != 'plugin':
                return diagnostic_version(_field(self._bundle_manifest(target), 'version'))
            entry = next((row for row in self.ctx.loader.entries() if row.id == target), None)
            base = _field(entry.parent.tree.ctx, 'baseUrl') if entry is not None else None
            packages = self.owner_context.get('pluginPackages')
            if base is None or packages is None:
                return None
            return diagnostic_version(_field(packages.packageOf(entry.options['name'], base), 'version'))
        except Exception:
            return None

    def _disk_state(self):
        result = []
        for filename in ('package.json', 'cordis.patch.yml', 'pnpm-workspace.yaml', PROFILE_COMPATIBILITY_FILENAME):
            try:
                with open(os.path.join(_field(self.profile, 'dir'), filename), 'r', encoding='utf-8', errors='replace', newline='') as stream:
                    result.append(stream.read())
            except FileNotFoundError:
                result.append('')
        return '\0'.join(result)

    def _report_operation(self, facts):
        async def report():
            try:
                await self.owner_context.parallel('plugin-manager/operation', facts)
            except Exception:
                sys.stderr.write('dsh plugin-manager: operation diagnostic delivery failed\n')
        task = asyncio.create_task(report())
        self.diagnostics.add(task)
        task.add_done_callback(self.diagnostics.discard)

    async def _change(self, operation, request, reason, identity=None):
        target = self._operation_target(reason, request['target']) if identity is None else identity['target']
        version = self._operation_version(reason, request['target'] if reason == 'plugin' else target) if identity is None else identity.get('version')
        facts = dict(id=str(uuid.uuid4()), reason=reason, stage=request['stage'], target=target)
        if version is not None:
            facts['version'] = version
        if 'enabled' in request:
            facts['enabled'] = request['enabled']
        def report(phase, **extra):
            event = dict(facts, time=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'), phase=phase)
            event.update(extra)
            self._report_operation(event)
        report('started')
        async def change():
            self.abort.signal.throwIfAborted()
            before = self._disk_state()
            result = dict(request, changed=False, application='applied' if self.owner_context.get('hmr') is not None else 'restart-required')
            if result['application'] == 'restart-required':
                result['restartReason'] = 'no-hmr'
            try:
                outcome = await operation(result)
                if outcome is not None:
                    result['application'] = outcome
                elif result['application'] == 'applied' and result.get('restartReason') is not None:
                    result['application'] = 'restart-required'
            except InstallCancelledError:
                result['application'] = 'cancelled'
            except Exception as error:
                result.update(application='failed', error=management_error(error))
            if result['application'] != 'restart-required':
                result.pop('restartReason', None)
            result['changed'] = before != self._disk_state()
            self.owner_context.emit('plugin-manager/changed', dict(reason=reason))
            return result
        try:
            settled = await with_file_lock(os.path.join(_field(self.profile, 'dir'), 'package.json'), change, waitMs=self.lock_wait_ms)
        except BaseException:
            report('unknown')
            raise
        extra = {key:settled[key] for key in ('stage', 'application', 'changed')}
        if settled.get('error') is not None:
            extra['errorCode'] = settled['error']['code']
        if 'restartReason' in settled:
            extra['restartReason'] = settled['restartReason']
        if diagnostic_version(settled.get('version')) is not None:
            extra['version'] = settled['version']
        report('settled', **extra)
        return settled
