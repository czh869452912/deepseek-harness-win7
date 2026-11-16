"""Native package service: prepare in a child, commit in the owning host."""
import asyncio
import json
import os
import subprocess
import tempfile

from dsh.boot import python_plugins as store
from dsh.boot.app_boot import load_overlay_patches
from dsh.boot.config_editor import flatten
from dsh.boot.plugin_package_operations import active_recorded_run
from dsh.boot.plugin_install_spec import parse_install_spec
from dsh.boot.profile import read_profile_manifest, compose_entries, bundle_patch_paths
from dsh.boot.python_package_cli import package_command
from dsh.boot.python_package_prepare import prepared_registry_package, prepared_local_package, prepared_git_package, prepared_url_package
from dsh.boot.python_plugin_snapshot import retained_installed_package
from dsh.boot.runtime_resolution import _field
from dsh.cordis.plugin import Plugin
from dsh.cordis.file_lock import with_file_lock
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.core.cleanup import CleanupPromise


class PythonPackageBackend(Plugin):
    inject = ['profileContext', 'pythonProfileLease', 'pythonDependencies', 'loader']

    def apply(self, ctx, config=None):
        self.ctx = ctx
        self.config = config or {}
        self.profile = ctx.get('profileContext')
        self.directory = os.path.normcase(os.path.realpath(_field(self.profile, 'dir')))
        self.lease = ctx.get('pythonProfileLease')
        self.dependencies = ctx.get('pythonDependencies')
        self.abort, self.operations, self.updates = AbortController(), set(), {}
        def close():
            self.abort.abort()
            async def drain():
                await asyncio.gather(*list(self.operations), return_exceptions=True)
            return drain()
        ctx.effect(lambda: close)
        ctx.provide('profilePackages', self)

    def package_options(self):
        return package_command(self.config.get('env'))

    def update(self, name, operation, lock_wait_ms):
        async def owned():
            task = asyncio.current_task()
            self.operations.add(task)
            scope, snapshot = None, None
            try:
                self.abort.signal.throwIfAborted()
                async def capture():
                    nonlocal scope, snapshot
                    if name in self.updates:
                        raise RuntimeError('another native update owns this package')
                    manifest = read_profile_manifest('dsh', self.directory)
                    if name in manifest.get('dsh', {}).get('pythonPlugins', {}):
                        scope = retained_installed_package(self.directory, name)
                        snapshot = scope.__enter__()
                        self.updates[name] = snapshot
                await with_file_lock(os.path.join(self.directory, 'package.json'), capture, waitMs=lock_wait_ms)
                result = await operation()
                restore = result.get('restore', {})
                if snapshot is not None and restore.get('application') in ('failed', 'cancelled'):
                    path = snapshot.preserve('update-restoration-failed')
                    command = ['dsh', 'plugin', '--profile', _field(self.profile, 'name'), 'recover', path]
                    result['recovery'] = dict(path=path, reason='update-restoration-failed', command=command)
                    error = restore.get('error')
                    if isinstance(error, dict):
                        error['diagnostic'] = (error.get('diagnostic') or error.get('code') or 'Restoration failed') + '\nPrevious version retained. Stop the profile and run:\n' + subprocess.list2cmdline(command)
                return result
            except BaseException:
                if snapshot is not None:
                    current = read_profile_manifest('dsh', self.directory).get('dsh', {}).get('pythonPlugins', {}).get(name)
                    if current is None or current['version'] != snapshot.manifest['version']:
                        snapshot.preserve('update-interrupted-after-removal')
                raise
            finally:
                try:
                    if snapshot is not None:
                        self.updates.pop(name, None)
                        scope.__exit__(None, None, None)
                finally:
                    self.operations.discard(task)
        return CleanupPromise(owned())

    def _result(self):
        root = os.path.join(self.directory, '.plugin-manager', 'logs')
        os.makedirs(root, mode=0o700, exist_ok=True)
        path = os.path.join(tempfile.mkdtemp(prefix='native-', dir=root), 'pnpm.log')
        with open(path, 'xb'):
            pass
        return dict(exitCode=1, output='', truncated=False, logPath=path)

    def _append(self, result, text, options, stream='stderr'):
        data = text.encode('utf-8')
        with open(result['logPath'], 'ab') as log:
            log.write(data)
        tail = result['output'].encode('utf-8') + data
        limit = options.get('outputBytes', 16384)
        result['truncated'] = result['truncated'] or len(tail) > limit
        result['output'] = tail[-limit:].decode('utf-8', errors='replace')
        if options.get('onOutput'):
            options['onOutput'](text, stream)

    async def _exclusive(self, operation, signal):
        async def apply():
            signal.throwIfAborted()
            with self.lease.exclusive_window():
                signal.throwIfAborted()
                # No await between the final cancellation check and commit.
                return operation()
        hmr = self.ctx.get('hmr')
        return await apply() if hmr is None else await hmr.runExclusive(apply)

    def _assert_unloaded(self, name):
        manifest = read_profile_manifest('dsh', self.directory)
        if name in manifest.get('dsh', {}).get('profile', {}).get('bundles', []):
            raise RuntimeError('native package must be disabled and unloaded before removal')
        package = os.path.join(self.directory, 'node_modules', name)
        metadata = read_profile_manifest('dsh', package)
        patches = []
        for path in bundle_patch_paths(package, metadata['dsh']['bundle']):
            patches.extend(load_overlay_patches('dsh', path))
        rows = flatten(compose_entries([patches]))
        for entry in self.ctx.get('loader').entries():
            if entry.fiber is not None and any(entry.options.get('id') == row.get('id')
                    and entry.options.get('name') == row.get('name') for row in rows):
                raise RuntimeError('native package still has a live plugin entry')

    def run(self, context, args, options):
        async def owned():
            task = asyncio.current_task()
            self.operations.add(task)
            controller = AbortController()
            detach = [signal.add_listener('abort', controller.abort)
                for signal in (self.abort.signal, options.get('signal') or NEVER_ABORTED)]
            try:
                return await self._execute(context, args, dict(options, signal=controller.signal))
            finally:
                for dispose in detach:
                    dispose()
                self.operations.discard(task)
        return CleanupPromise(owned())

    async def _execute(self, context, args, options):
        if os.path.normcase(os.path.realpath(context['dir'])) != self.directory:
            raise RuntimeError('native package service belongs to another profile')
        options = dict(options)
        signal = options.get('signal') or NEVER_ABORTED
        result = None
        try:
            signal.throwIfAborted()
            active = await active_recorded_run(self.directory)
            if active is not None:
                result = self._result()
                self._append(result, active, options)
                return result
            if len(args) < 2 or args[0] not in ('add', 'remove'):
                raise ValueError('native package service requires one add or remove target')
            registry = None
            for flag in args[2:]:
                if flag.startswith(('--registry=', '--config.registry=')):
                    registry = flag.split('=', 1)[1]
                elif flag != '--save-exact':
                    raise ValueError('unsupported native package operation option')
            if args[0] == 'remove':
                result = self._result()
                def remove():
                    self._assert_unloaded(args[1])
                    prepared = self.dependencies.prepare_change(removing=args[1])
                    try:
                        store.uninstall(self.directory, args[1], lease=self.lease)
                        self.dependencies.commit_change(prepared)
                    finally:
                        prepared.close()
                await self._exclusive(remove, signal)
                result.update(exitCode=0, nativeCommitted=True)
                self._append(result, 'Removed ' + args[1] + '\n', options, 'stdout')
                return result
            parsed = parse_install_spec(args[1])
            snapshot = self.updates.get(parsed.get('name')) if parsed['kind'] == 'registry' else None
            if parsed['kind']=='git':
                snapshot=next((value for value in self.updates.values()
                    if value.record_for(self.directory,value.source).get('acquisition',{}).get('kind')=='git-tgz'
                    and store.dependency_reference(value.manifest['name'],value.record_for(self.directory,value.source))==args[1]),None)
                if snapshot is not None:
                    result=self._result()
                    return await self._install(snapshot,result,options,snapshot)
            if snapshot is not None and parsed.get('range') == snapshot.manifest['version']:
                result = self._result()
                return await self._install(snapshot, result, options, snapshot)
            prepare_options = dict(options, registry=registry)
            local = parsed['kind'] in ('path', 'tarball') and 'path' in parsed
            preparation = (prepared_local_package(self.directory, parsed['path'], prepare_options) if local
                else prepared_git_package(self.directory,args[1],prepare_options) if parsed['kind']=='git'
                else prepared_url_package(self.directory,args[1],prepare_options) if parsed['kind']=='tarball'
                else prepared_registry_package(self.directory, args[1], prepare_options))
            async with preparation as prepared:
                result = prepared.result
                if prepared.candidate is None:
                    for line in result['output'].splitlines():
                        try:
                            issue = json.loads(line).get('error', {}).get('incompatible')
                            if issue is not None:
                                result['incompatible'] = issue
                        except (ValueError, AttributeError):
                            pass
                    return result
                return await self._install(prepared.candidate, result, options)
        except Exception as error:
            if result is None:
                result = self._result()
            result['exitCode'] = 1
            self._append(result, str(error) + '\n', options)
            return result

    async def _install(self, candidate, result, options, snapshot=None):
        expected = options.get('expected')
        if expected is not None and any(candidate.manifest.get(key) != expected[key] for key in ('name', 'version')):
            result.update(exitCode=1, unmet='unexpected-package')
            self._append(result, 'Prepared package differs from the expected identity\n', options)
            return result
        with tempfile.TemporaryDirectory(prefix='dependencies-', dir=os.path.dirname(candidate.source)) as stage:
            store.copy_source(candidate.source, stage)
            retained = self.dependencies.prepare_change(candidate=stage)
            try:
                def install():
                    if options.get('onCommit'):
                        options['onCommit']()
                    store.install(self.directory, candidate.source, _field(self.profile, 'installAnchor'),
                        candidate.acquisition if snapshot is None else None, lease=self.lease, enabled=False, _snapshot=snapshot)
                    self.dependencies.commit_change(retained)
                await self._exclusive(install, options.get('signal') or NEVER_ABORTED)
                result.update(exitCode=0, nativeCommitted=True)
            finally:
                retained.close()
        self._append(result, ('Restored ' if snapshot is not None else 'Installed ') + candidate.manifest['name'] + '\n', options, 'stdout')
        return result
