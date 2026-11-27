"""Read-only package management Remote methods; no installation effects."""
import asyncio
import json
import os
import re
import zipfile

from dsh.boot.plugin_bundle_metadata import bundle_selection, update_refusal
from dsh.boot.plugin_compatibility import evaluate_plugin_compatibility
from dsh.boot.plugin_install_spec import parse_install_spec, InvalidInstallSpecError, classify_install_failure, JS_SPACE
from dsh.boot.plugin_package_view import read_profile_registry, view_profile_package
from dsh.boot.plugin_registry_policy import (UNSPECIFIED, VERSION_FIELDS, VERSION_LIST_FIELDS,
    registry_plan, attribute_failure, newer_versions, version_facts)
from dsh.boot.profile import read_profile_manifest
from dsh.boot.profile_compatibility import read_profile_version_exemptions
from dsh.boot.runtime_resolution import _field
from dsh.cordis.utils import js_to_string
from dsh.typert.remote import Remote

INSPECT_FIELDS = ['name', 'version', 'description', 'dsh']
MAX_MANIFEST_BYTES = 1024 * 1024


def _local_manifest(path, native):
    if native and os.path.isfile(path) and path.lower().endswith('.zip'):
        with zipfile.ZipFile(path) as archive:
            manifests = [entry for entry in archive.infolist() if not entry.is_dir()
                         and entry.filename.count('/') <= 1
                         and entry.filename.rsplit('/', 1)[-1].casefold() == 'package.json']
            roots = [entry for entry in manifests if '/' not in entry.filename]
            candidates = roots or manifests
            if len(candidates) != 1:
                raise ValueError('ZIP requires one package.json at its root')
            member = candidates[0]
            if member.file_size > MAX_MANIFEST_BYTES:
                raise ValueError('package.json exceeds the metadata limit')
            return _json(archive.read(member).decode('utf-8'))
    with open(os.path.join(path, 'package.json'), encoding='utf-8', errors='replace') as stream:
        return _json(stream.read())


def _native_abi(manifest):
    version = _field(_field(_field(manifest, 'dsh'), 'python'), 'apiVersion')
    return type(version) is int and version == 1


def _message(error):return getattr(error, 'message', str(error))


def _refused(problem, reason):return dict(status='refused', problem=problem, reason=reason)


def _json(text):
    def reject(value):raise ValueError('Invalid JSON constant '+value)
    return json.loads(text, parse_constant=reject)


def _inspection(kind, manifest, registry):
    dsh = _field(manifest, 'dsh')
    bundle = _field(dsh, 'bundle')
    result = dict(status='accepted', kind=kind, bundle=isinstance(bundle, (dict, list)), registry=registry)
    for key in ('name', 'version', 'description'):
        value = _field(manifest, key)
        if isinstance(value, str) and (key != 'description' or value != ''):result[key] = value
    return result


def _printed_error(printed):
    try:error = _field(_json(printed or 'null'), 'error')
    except ValueError:return ''
    return '  '.join(value for value in [_field(error, 'code'), _field(error, 'message')] if isinstance(value, str))


async def _map_concurrent(items, limit, operation):
    answers = [None]*len(items)
    next_index, stopped = 0, False
    async def worker():
        nonlocal next_index, stopped
        while not stopped and next_index < len(items):
            index = next_index
            next_index += 1
            answer = await operation(items[index])
            answers[index] = answer
            if answer['status'] == 'refused':stopped = True
    await asyncio.gather(*(worker() for _ in range(min(limit, len(items)))))
    return answers


class PluginInspection:
    def _package_backend(self):
        if (_field(self.profile, 'packageManager') is not None
                or getattr(self, 'pnpm_command', 'pnpm') != 'pnpm'):
            return None
        scope = getattr(self, 'package_backend_scope', None)
        held = None if scope is None else scope.get()
        if held is not None:
            return held
        context = getattr(self, 'owner_context', None)
        return None if context is None else context.get('profilePackages')

    def _package_options(self):
        configured = _field(self.profile, 'packageManager')
        if configured is not None:
            return dict(configured)
        backend = self._package_backend()
        if backend is not None:
            return backend.package_options()
        return dict(command=self.pnpm_command)

    @Remote('registries')
    async def registries(self):
        options = dict(self._package_options(), timeoutMs=self.inspect_timeout_ms)
        resolved = await read_profile_registry(_field(self.profile, 'dir'), options)
        return dict(registry=self.registry, fallbackRegistries=list(self.fallback_registries), resolved=resolved)

    def _registry_for(self, name, requested):
        return self.installed_from.get(name, UNSPECIFIED) if requested is UNSPECIFIED else requested

    async def _ask_registries(self, spec, fields, plan, parsed, signal=None):
        attempts = []
        for index, registry in enumerate(plan):
            options = dict(self._package_options(), fields=fields, timeoutMs=self.inspect_timeout_ms, registry=registry)
            if signal is not None:options['signal'] = signal
            view = await view_profile_package(_field(self.profile, 'dir'), spec, options)
            printed = re.sub(r'\x1b\[[0-9;]*m', '', view['stdout']).strip(JS_SPACE)
            if view['exitCode'] != 0 or 'cause' in view or view['timedOut']:
                log = '\n'.join(text for text in [view['stderr'].strip(JS_SPACE), _printed_error(printed),
                    _message(view['cause']) if 'cause' in view else ''] if text)
                kind = classify_install_failure(dict(log=log, timedOut=view['timedOut'], cause=view.get('cause')))
                reason = ('pnpm view timed out after '+str(self.inspect_timeout_ms)+'ms' if view['timedOut']
                    else log or printed or 'pnpm view exited with '+js_to_string(view['exitCode']))
                problem = ('not-found' if kind in ('not-found', 'no-matching-version')
                    else 'network' if kind in ('network', 'timeout') else 'unknown')
                attempts.append(dict(registry=registry, problem=problem, reason=reason))
                if index < len(plan)-1 and not (signal is not None and signal.aborted) and attribute_failure(kind, log, parsed) == 'registry':continue
                return dict(_refused(problem, reason), attempts=attempts)
            try:answer = _json(printed or 'null')
            except ValueError as error:
                reason = 'unreadable pnpm view output: '+_message(error)
                attempts.append(dict(registry=registry, problem='unknown', reason=reason))
                return dict(_refused('unknown', reason), attempts=attempts)
            attempts.append(dict(registry=registry))
            return dict(status='answered', answer=answer, registry=registry, attempts=attempts)
        raise RuntimeError('no registry was asked')

    @Remote('inspect')
    async def inspect(self, spec, options=None, signal=None):
        try:parsed = parse_install_spec(spec)
        except InvalidInstallSpecError as error:return _refused('invalid-spec', error.reason)
        native = self._package_backend() is not None
        manifest = read_profile_manifest('dsh', _field(self.profile, 'dir'))
        with open(_field(self.profile, 'installAnchor'), encoding='utf-8') as stream:installation = json.load(stream)
        known = set(bundle_selection(manifest)) | set(manifest.get('dependencies') or {}) | set(installation.get('dependencies') or {})
        plan = registry_plan((options or {}).get('registry', UNSPECIFIED), await self.registries())
        registry = plan[0]
        if parsed['kind'] == 'git':return dict(status='accepted', kind='git', bundle=None, registry=registry, host=parsed['host'])
        if parsed['kind'] == 'tarball':
            if 'path' in parsed and not os.path.exists(parsed['path']):return _refused('not-a-package', 'the tarball does not exist')
            result = dict(status='accepted', kind='tarball', bundle=None, registry=registry)
            if 'host' in parsed:result['host'] = parsed['host']
            return result
        if parsed['kind'] == 'path':
            if not os.path.exists(parsed['path']):return _refused('not-a-package', 'the path does not exist')
            try:
                read = await asyncio.get_running_loop().run_in_executor(None, _local_manifest, parsed['path'], native)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
                return _refused('not-a-package', 'no readable package.json at the path: '+_message(error))
            inspection = _inspection('path', read, registry)
            if 'name' not in inspection:return _refused('not-a-package', 'the package.json names no package')
            if inspection['name'] in known:return _refused('already-installed', inspection['name']+' is already installed')
            if not inspection['bundle']:return _refused('not-a-bundle', inspection['name']+' declares no dsh.bundle')
            if native and not _native_abi(read):return _refused('not-a-package', inspection['name']+' requires a Win7 Python plugin build')
            return inspection
        if parsed['name'] in known:return _refused('already-installed', parsed['name']+' is already installed')
        asked = await self._ask_registries(spec.strip(JS_SPACE), INSPECT_FIELDS, plan, parsed, signal)
        registries = [attempt['registry'] for attempt in asked['attempts']]
        if asked['status'] == 'refused':return dict(_refused(asked['problem'], asked['reason']), registries=registries)
        latest = (asked['answer'][-1] if asked['answer'] else None) if isinstance(asked['answer'], list) else asked['answer']
        if not isinstance(latest, (dict, list)):return dict(_refused('unknown', 'pnpm view answered no package'), registries=registries)
        inspection = _inspection('registry', latest, asked['registry'])
        inspection.setdefault('name', parsed['name'])
        if not inspection['bundle']:return dict(_refused('not-a-bundle', inspection['name']+' declares no dsh.bundle'), registries=registries)
        if native and not _native_abi(latest):
            return dict(_refused('not-a-package', inspection['name']+' requires a Win7 Python plugin build'), registries=registries)
        return inspection

    @Remote('listVersions')
    async def listVersions(self, name, options=None, signal=None):
        target = update_refusal(next((row for row in await self.listBundles() if row['name'] == name), None), name)
        if isinstance(target, str):return dict(_refused('not-updatable', target), attempts=[])
        if target['kind'] == 'git':return dict(_refused('not-updatable', name+' is installed from Git, which lists no versions'), attempts=[])
        requested = self._registry_for(name, (options or {}).get('registry', UNSPECIFIED))
        plan = registry_plan(requested, await self.registries())
        listing = await self._ask_registries(name, VERSION_LIST_FIELDS, plan, target['parsed'], signal)
        if listing['status'] == 'refused':return listing
        try:newer = newer_versions(listing['answer'], target['installed'])
        except Exception as error:return dict(_refused('unknown', _message(error)), attempts=listing['attempts'])
        listed = newer[:self.version_list_limit]
        exemptions = read_profile_version_exemptions(_field(self.profile, 'dir'))
        async def read(published):
            spec = name+'@'+published['version']
            answer = await self._ask_registries(spec, VERSION_FIELDS, [listing['registry']], dict(kind='registry', spec=spec, name=name), signal)
            if answer['status'] == 'refused':return answer
            facts = version_facts(answer['answer'], name, published['version'])
            try:compatibility = evaluate_plugin_compatibility(facts['manifest'], exemptions)
            except Exception as error:return dict(_refused('unknown', _message(error)), attempts=answer['attempts'])
            version = dict(published, bundle=facts['bundle'])
            if 'deprecated' in facts:version['deprecated'] = facts['deprecated']
            if compatibility is not None and not compatibility['exempted']:
                version['incompatible'] = {key:value for key, value in compatibility.items() if key != 'exempted'}
            return dict(status='read', version=version)
        looked = await _map_concurrent(listed, self.version_lookup_concurrency, read)
        versions = []
        for answer in looked:
            if answer is None:continue
            if answer['status'] == 'refused':return dict(answer, attempts=listing['attempts'][:-1]+answer['attempts'])
            versions.append(answer['version'])
        return dict(status='listed', installed=target['installed'], registry=listing['registry'],
                    attempts=listing['attempts'], versions=versions, omitted=len(newer)-len(listed))
