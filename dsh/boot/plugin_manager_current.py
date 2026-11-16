"""Current profile management Remote, extended in verified contract batches."""
import asyncio
import datetime
import os
import sys
import uuid

from dsh.boot.bundle_platform import UnsupportedBundlePlatformError
from dsh.boot.plugin_switch import flatten, write_plugin_enabled
from dsh.boot.profile import compose_entries
from dsh.boot.profile_compatibility import PROFILE_COMPATIBILITY_FILENAME
from dsh.boot.profile_context import read_profile_patches
from dsh.boot.runtime_resolution import _field
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.errors import ThrownValueError
from dsh.cordis.file_lock import with_file_lock
from dsh.cordis.schema import Schema
from dsh.cordis.utils import js_to_string
from dsh.core.abort import AbortController
from dsh.host.plugin_inventory.current import read_plugin_inventory
from dsh.typert.remote import Remote, TypertRemoteService


PROTECTED_PLUGINS = frozenset((
    '@deepseek-ai/dsh-plugin-manager', '@deepseek-ai/cordis-plugin-loader',
    '@deepseek-ai/cordis-plugin-include', '@deepseek-ai/dsh-api-gateway',
    '@deepseek-ai/dsh-host-webserver', '@deepseek-ai/dsh-client-modules',
    '@deepseek-ai/dsh-client-ui-settings-plugin-inventory', '@deepseek-ai/dsh-client-ui-plugin-manager',
    '@deepseek-ai/dsh-host-plugin-inventory', '@deepseek-ai/dsh-typert-registry',
    '@deepseek-ai/dsh-api-remotes', '@deepseek-ai/dsh-api-remote-access',
    '@deepseek-ai/cordis-plugin-timer', '@deepseek-ai/dsh-client-connection',
    '@deepseek-ai/dsh-host-frontend-static', '@deepseek-ai/dsh-tools', '@deepseek-ai/dsh-hmr'))


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


class CurrentPluginManager(TypertRemoteService):
    inject = ['loader', 'profileContext']
    Config = Schema.object(dict(lockWaitMs=Schema.number().step(1).min(0).default(120000)))

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'pluginManager')
        self.profile = ctx.profileContext
        self.owner_context = ctx
        self.owner_entry_id = _field(getattr(ctx.fiber, 'entry', None), 'id')
        self.lock_wait_ms = (config or {}).get('lockWaitMs', 120000)
        self.abort = AbortController()
        self.package_operations = set()
        self.diagnostics = set()
        def close():
            self.abort.abort()
            async def drain():
                await asyncio.gather(*list(self.package_operations), return_exceptions=True)
            return drain()
        ctx.effect(lambda: close)

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

    async def _configure(self, operation):
        async def apply():
            self.abort.signal.throwIfAborted()
            return await await_callback_result(operation())
        hmr = self.owner_context.get('hmr')
        return await apply() if hmr is None else await hmr.runExclusive(apply)

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
        # Package operations supply their canonical package identity explicitly.
        return None

    def _operation_version(self, reason, target):
        if reason == 'install' or target is None:
            return None
        try:
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
