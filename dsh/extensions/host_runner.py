"""Session-owned dynamic Cordis runs and browser activation handshake.

Win7 adaptation: Host bodies are Python and return a Cordis plugin through
``plugin``; Client bodies remain the official JavaScript contract. Host code is
shell-trusted, as upstream's VM is not a security boundary.
"""
import asyncio
import copy
import inspect
import math
import re
import sys
import time
from types import SimpleNamespace

from dsh.extensions.cordis_guard import guarded_plugin, normalize_handler, sandbox_define_tool, sandbox_register_tool
from dsh.extensions.cordis_runner_state import CordisRunnerState, missing_plugin
from dsh.core.session.json import UNDEFINED
from dsh.extensions.inspect_registry import CordisInspectRegistryService, js_trim
from dsh.typert.remote import Remote, TypertRemoteService


def refusal(reason, message):
    return dict(ok=False, reason=reason, message=message)


def half(status):
    return dict(status=status, waitingFor=[])


class DynamicCordisRunner(CordisRunnerState, TypertRemoteService):
    inject = ['tools']

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'dynamicCordisRunner')
        self.timeout = (config or {}).get('vmTimeoutMs', 5000)
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or self.timeout < 1:
            raise ValueError('vmTimeoutMs must be a finite number at least 1')
        self.plugins, self.pending = {}, {}
        self._next_ids = dict(plugin=1, package=1, run=1, approval=1)
        self.inspect_registry = CordisInspectRegistryService(ctx)
        self.starting = {}
        self._transitions, self._ending = {}, {}
        self._closed, self._close_task = False, None
        self.root_ctx = ctx
        self._group = None
        ctx.effect(lambda: self.close)

    async def close(self):
        if self._close_task is None:
            self._closed = True
            for transition in self._transitions.values():
                transition['invalidated'] = True
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self):
        await asyncio.gather(*(self.end_plugin(plugin, True) for plugin in list(self.plugins.values())))
        self.plugins.clear()
        self.pending.clear()
        if self._group is not None:
            await self._group.dispose()
        self.inspect_registry.close()

    def owned(self, agent, plugin_id):
        plugin = self.plugins.get(plugin_id)
        return plugin if plugin is not None and plugin['agentId'] == agent.id else None

    def mint_id(self, kind, prefix):
        # Per-runner monotonic mints, matching the original process-local registry.
        while True:
            value = '{}-{}'.format(prefix, self._next_ids[kind])
            self._next_ids[kind] += 1
            if kind != 'plugin' or value not in self.plugins:
                return value

    def define(self, request):
        if self._closed:
            raise ValueError('dynamic Cordis runner is closed')
        name, purpose, code = js_trim(request['name']), js_trim(request['purpose']), request['code']
        if not name:
            raise ValueError('cordis_define needs a non-empty `name`')
        if not purpose:
            raise ValueError('cordis_define needs a non-empty `purpose`')
        if not any(key in code for key in ('host', 'client')):
            raise ValueError('cordis_define needs `code.host`, `code.client`, or both')
        for value in code.values():
            if not isinstance(value, str) or not value.strip():
                raise ValueError('code halves must be non-empty strings')
        if 'host' in code:
            compile(code['host'], '<cordis-host>', 'exec')
        spec = request['plugin']
        if spec['kind'] == 'new':
            prefix = js_trim(spec['idPrefix'])
            if not re.fullmatch('[a-z]{3,6}', prefix):
                raise ValueError('cordis_define `plugin.idPrefix` must contain 3–6 lowercase English letters')
            pid = self.mint_id('plugin', prefix)
            plugin = dict(pluginId=pid, agentId=request['sessionId'], packages={}, approved=set(), approveFuture=False)
            self.plugins[pid] = plugin
        else:
            plugin = self.plugins.get(spec['pluginId'])
            if plugin is None or plugin['agentId'] != request['sessionId']:
                raise ValueError(missing_plugin(spec['pluginId']))
        package = dict(packageId=self.mint_id('package', 'pkg'), name=name, purpose=purpose, code=copy.deepcopy(code))
        plugin['packages'][package['packageId']] = package
        return dict(pluginId=plugin['pluginId'], **self.package_summary(package))

    @staticmethod
    def package_summary(package):
        return dict(packageId=package['packageId'], name=package['name'], purpose=package['purpose'], hasHostHalf='host' in package['code'], hasClientHalf='client' in package['code'])

    @Remote
    def inventory(self):
        result = []
        for plugin in self.plugins.values():
            row = dict(pluginId=plugin['pluginId'], agentId=plugin['agentId'], packages=[self.package_summary(p) for p in plugin['packages'].values()])
            for key in ('currentPackageId', 'nextPackageId', 'latestRun'):
                if key in plugin:
                    row[key] = copy.deepcopy(plugin[key])
            if 'run' in plugin:
                row['activeRun'] = {key: plugin['run'][key] for key in ('pluginRunId', 'packageId')}
            result.append(row)
        return result

    def snapshot(self, agent):
        rows = []
        for row in self.inventory():
            if row.pop('agentId') != agent.id:
                continue
            run = self.plugins[row['pluginId']].get('run')
            if run is not None:
                row['activeRun']['handlers'] = list(run['handlers'])
                if run.get('fiber') is not None:
                    row['activeRun']['fiber'] = run['fiber']
                if 'renderFailure' in run:
                    row['activeRun']['renderFailure'] = copy.deepcopy(run['renderFailure'])
            rows.append(row)
        return rows

    def listPlugins(self, agent):
        return [self.inspectPlugin(agent, pid) for pid, plugin in self.plugins.items() if plugin['agentId'] == agent.id]

    def inspectPlugin(self, agent, pluginId):
        reference = self.reference(agent, pluginId)
        if reference is None:
            raise ValueError('no dynamic plugin "{}" in this process — it may have been removed or lost on DSH restart'.format(pluginId))
        return dict(reference, packages=[self.package_summary(package) for package in self.plugins[pluginId]['packages'].values()])

    def reference(self, agent, pluginId):
        plugin = self.owned(agent, pluginId)
        if plugin is None:
            return None
        pid = plugin.get('nextPackageId') or plugin.get('currentPackageId') or next(reversed(plugin['packages']), None)
        if pid not in plugin['packages']:
            return None
        package = plugin['packages'][pid]
        result = dict(pluginId=pluginId, packageId=pid, name=package['name'], purpose=package['purpose'])
        return self.inspection_state(plugin, result)

    @staticmethod
    def inspection_state(plugin, result):
        for key in ('currentPackageId', 'nextPackageId', 'latestRun'):
            if key in plugin:
                result[key] = copy.deepcopy(plugin[key])
        if 'run' in plugin:
            result['activeRun'] = {key: plugin['run'][key] for key in ('pluginRunId', 'packageId')}
        return result

    def inspectPackage(self, agent, pluginId, packageId):
        plugin = self.owned(agent, pluginId)
        if plugin is None:
            raise ValueError('no dynamic plugin "{}" in this process — it may have been removed or lost on DSH restart'.format(pluginId))
        if packageId not in plugin['packages']:
            raise ValueError('dynamic package "{}" does not exist on plugin "{}"'.format(packageId, pluginId))
        return self.inspection_state(plugin, dict(pluginId=pluginId, **copy.deepcopy(plugin['packages'][packageId])))

    def plan(self, agent, pid, package_id, mode, attach=False):
        plugin = self.owned(agent, pid)
        if plugin is None:
            return None, refusal('plugin-missing', 'no dynamic plugin "{}" in this process — it may have been removed or lost on DSH restart'.format(pid))
        if self._closed or pid in self._ending:
            return None, refusal('transition-in-flight', 'plugin "{}" is retiring'.format(pid))
        if package_id not in plugin['packages']:
            return None, refusal('package-missing', 'plugin "{}" has no package "{}"'.format(pid, package_id))
        current = plugin.get('currentPackageId')
        if mode not in ('run', 'update'):
            return None, refusal('invalid-mode', 'use run for the current/first version and update to replace a successful version')
        if mode == 'update' and (current is None or current == package_id):
            message = ('plugin "{}" has no successful version yet; start "{}" with mode "run"'.format(pid, package_id)
                       if current is None else 'package "{}" is already current; use mode "run"'.format(package_id))
            return None, refusal('invalid-mode', message)
        if mode == 'run' and current is not None and current != package_id:
            return None, refusal('invalid-mode', 'package "{}" differs from current "{}"; use mode "update"'.format(package_id, current))
        if not attach and pid in self.starting:
            return None, refusal('transition-in-flight', 'plugin "{}" is already starting'.format(pid))
        return plugin, None

    @Remote
    def syncInspectManifest(self, providers):
        self.inspect_registry.sync_client_manifest(providers)
        return None

    @Remote
    def resolveInspectQuery(self, agent, requestId, resolution):
        return self.inspect_registry.resolve_client_query(agent, requestId, resolution)

    async def queryClient(self, agent, provider, method, input=UNDEFINED, signal=None):
        return await self.inspect_registry.query('client', provider, method, input, agent, signal)


    async def start_host(self, plugin, source, run):
        """Evaluate native Python and mount a real child of the dynamic group.

        This evaluator is deliberately not a JavaScript VM or a malicious-code
        sandbox. The guarded native facade checks ordinary API/registration use.
        """
        def handle(method, handler):
            method, normalized = normalize_handler(method, handler)
            run['handlers'][method] = normalized
            def dispose():
                if run['handlers'].get(method) is normalized:
                    del run['handlers'][method]
            run['handlerDisposers'].append(dispose)
            return dispose
        namespace = dict(harness=SimpleNamespace(handle=handle, defineTool=sandbox_define_tool,
            registerTool=sandbox_register_tool))
        fiber = None
        try:
            deadline, previous = time.monotonic() + self.timeout / 1000, sys.gettrace()
            def trace(frame, event, arg):
                if time.monotonic() > deadline:
                    raise TimeoutError('Host evaluation exceeded vmTimeoutMs')
                return trace
            try:
                sys.settrace(trace)
                exec(compile(source, '<cordis-host>', 'exec'), namespace)
            finally:
                sys.settrace(previous)
            native_plugin = namespace.get('plugin')
            if not callable(native_plugin) and not (isinstance(native_plugin, dict) and callable(native_plugin.get('apply'))):
                raise ValueError('Python Host code must expose a callable plugin or a plugin dict with apply(ctx)')
            if self._group is None:
                self._group = self.root_ctx.plugin(dict(name='cordis-dynamic', apply=lambda ctx: None))
            group = await self._group
            fiber = group.ctx.plugin(guarded_plugin(native_plugin,
                lambda error: self.steer_guard_failure(plugin, run, 'Host', self.error_details(error))))
            try:
                await fiber
            except BaseException:
                await fiber.dispose()
                raise
            # Preserve the settled handle, as original startHostHalf does.
            # Native inspectors compare its original identity through ctx.fiber.
            run['fiber'] = fiber.ctx.fiber
            return None
        except Exception as error:
            for dispose in run['handlerDisposers']:
                dispose()
            run['handlerDisposers'].clear()
            return self.error_details(error)

    @staticmethod
    def error_details(error):
        result = dict(message=getattr(error, 'message', str(error)))
        if isinstance(getattr(error, 'stack', None), str):
            result['stack'] = error.stack
        return result

    @Remote
    async def invoke(self, pluginId, pluginRunId, method, args):
        plugin = self.plugins.get(pluginId)
        run = plugin.get('run') if plugin is not None else None
        if run is None:
            return dict(ok=False, code='plugin-not-running', message='dynamic plugin "{}" is not running'.format(pluginId))
        if run['pluginRunId'] != pluginRunId:
            return dict(ok=False, code='stale-run', message='activation "{}" is no longer active'.format(pluginRunId))
        handler = run['handlers'].get(method)
        if handler is None:
            return dict(ok=False, code='method-not-found', message='dynamic plugin "{}" registered no Host method "{}"'.format(pluginId, method))
        try:
            return dict(ok=True, value=await handler(args))
        except Exception as error:
            failure = self.error_details(error)
            self.steer_host_handler_failure(plugin, run, method, failure)
            return dict(ok=False, code='handler-error', **failure)
