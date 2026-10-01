"""Session-owned dynamic Cordis runs and browser activation handshake.

Win7 adaptation: Host bodies are Python and return a Cordis plugin through
``plugin``; Client bodies remain the official JavaScript contract. Host code is
shell-trusted, as upstream's VM is not a security boundary.
"""
import asyncio
import copy
import inspect
import re
import sys
import time
from types import SimpleNamespace

from dsh.core.cancellation import aborted
from dsh.core.session.json import UNDEFINED
from dsh.extensions.inspect_registry import CordisInspectRegistryService
from dsh.typert.remote import Remote, TypertRemoteService


def refusal(reason, message):
    return dict(ok=False, reason=reason, message=message)


def half(status):
    return dict(status=status, waitingFor=[])


class DynamicCordisRunner(TypertRemoteService):
    inject = ['tools']

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'dynamicCordisRunner')
        self.timeout = (config or {}).get('vmTimeoutMs', 5000)
        if type(self.timeout) not in (int, float) or self.timeout <= 0:
            raise ValueError('vmTimeoutMs must be positive')
        self.plugins, self.pending = {}, {}
        self._next_ids = dict(plugin=1, package=1, run=1, approval=1)
        self.inspect_registry = CordisInspectRegistryService(ctx)
        self.locks = {}
        ctx.effect(lambda: self.close)

    async def close(self):
        for plugin in list(self.plugins.values()):
            await self.retract(plugin)
        self.plugins.clear()
        self.pending.clear()
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
        name, purpose, code = request['name'].strip(), request['purpose'].strip(), request['code']
        if not name or not purpose or not any(key in code for key in ('host', 'client')):
            raise ValueError('cordis_define needs a name, purpose and at least one code half')
        for value in code.values():
            if not isinstance(value, str) or not value.strip():
                raise ValueError('code halves must be non-empty strings')
        if 'host' in code:
            compile(code['host'], '<cordis-host>', 'exec')
        spec = request['plugin']
        if spec['kind'] == 'new':
            prefix = spec['idPrefix'].strip()
            if not re.fullmatch('[a-z]{3,6}', prefix):
                raise ValueError('idPrefix must contain 3–6 lowercase English letters')
            pid = self.mint_id('plugin', prefix)
            plugin = dict(pluginId=pid, agentId=request['sessionId'], packages={}, approved=set(), approveFuture=False)
            self.plugins[pid] = plugin
        else:
            plugin = self.plugins.get(spec['pluginId'])
            if plugin is None or plugin['agentId'] != request['sessionId']:
                raise ValueError('dynamic plugin is not owned by this session')
        package = dict(packageId=self.mint_id('package', 'pkg'), name=name, purpose=purpose, code=copy.deepcopy(code))
        plugin['packages'][package['packageId']] = package
        plugin['nextPackageId'] = package['packageId']
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
        lock = self.locks.get(pid)
        if not attach and lock is not None and lock.locked():
            return None, refusal('transition-in-flight', 'plugin "{}" is already starting'.format(pid))
        return plugin, None

    def attempt(self, plugin, package_id, mode):
        code = plugin['packages'][package_id]['code']
        attempt = dict(pluginRunId=self.mint_id('run', 'run'), packageId=package_id, mode=mode, status='starting-host', host=half('pending' if 'host' in code else 'absent'), client=half('pending' if 'client' in code else 'absent'))
        plugin.update(latestRun=attempt, nextPackageId=package_id)
        return attempt

    async def run(self, agent, pluginId, packageId, mode, signal=None):
        plugin, error = self.plan(agent, pluginId, packageId, mode)
        if error:
            return error
        if aborted(signal):
            return refusal('cancelled', 'run request cancelled before activation')
        if any(row['pluginId'] == pluginId for row in self.pending.values()):
            return refusal('transition-in-flight', 'plugin already has a pending run request')
        attempt = self.attempt(plugin, packageId, mode)
        package = plugin['packages'][packageId]
        if 'client' not in package['code']:
            result = await self.activate(plugin, attempt)
            return self.run_response(plugin) if result['ok'] else refusal('host-half-failed', result['message'])
        rid = self.mint_id('approval', 'approval')
        required = not plugin['approveFuture'] and packageId not in plugin['approved']
        attempt.update(approvalRequestId=rid, requiresApproval=required, status='awaiting-approval' if required else 'starting-host')
        pending = dict(requestId=rid, agentId=agent.id, pluginId=pluginId, packageId=packageId, mode=mode, name=package['name'], purpose=package['purpose'], requiresApproval=required)
        self.pending[rid] = dict(pending, pluginRunId=attempt['pluginRunId'])
        self.ctx.emit('cordis/request-run', pending)
        return self.run_response(plugin)

    def run_response(self, plugin):
        attempt = plugin['latestRun']
        result = dict(ok=True, status='awaiting-approval' if attempt['status'] == 'awaiting-approval' else 'running' if attempt['status'] in ('running', 'waiting') else 'starting', pluginId=plugin['pluginId'], packageId=attempt['packageId'], pluginRunId=attempt['pluginRunId'], mode=attempt['mode'], waitingFor=attempt['host']['waitingFor'])
        for key in ('currentPackageId', 'nextPackageId'):
            if key in plugin:
                result[key] = plugin[key]
        if 'client' in plugin['packages'][attempt['packageId']]['code']:
            result['clientWaitingFor'] = list(attempt['client']['waitingFor'])
        return result

    async def activate(self, plugin, attempt):
        lock = self.locks.setdefault(plugin['pluginId'], asyncio.Lock())
        async with lock:
            current = plugin.get('run')
            if current and current['pluginRunId'] == attempt['pluginRunId']:
                return dict(ok=True, pluginId=plugin['pluginId'], packageId=attempt['packageId'], pluginRunId=attempt['pluginRunId'], waitingFor=attempt['host']['waitingFor'], startedHere=False)
            await self.retract(plugin)
            handlers, fiber = {}, None
            package = plugin['packages'][attempt['packageId']]
            try:
                if 'host' in package['code']:
                    def handle(method, handler):
                        if not isinstance(method, str) or not method or not callable(handler) or method in handlers:
                            raise ValueError('Host handlers need unique names and callable implementations')
                        handlers[method] = handler
                        return lambda: handlers.pop(method, None)
                    namespace = dict(harness=SimpleNamespace(handle=handle, defineTool=lambda tool: tool, registerTool=lambda ctx, tool: ctx.get('tools').register(tool)))
                    deadline, previous = time.monotonic() + self.timeout / 1000, sys.gettrace()
                    def trace(frame, event, arg):
                        if time.monotonic() > deadline:
                            raise TimeoutError('Host evaluation exceeded vmTimeoutMs')
                        return trace
                    try:
                        sys.settrace(trace)
                        exec(compile(package['code']['host'], '<cordis-host>', 'exec'), namespace)
                    finally:
                        sys.settrace(previous)
                    if not callable(namespace.get('plugin')):
                        raise ValueError('Python Host code must expose a callable named plugin')
                    fiber = self.ctx.plugin(namespace['plugin'])
                    fiber = await fiber
                    waiting = [name for name in getattr(namespace['plugin'], 'inject', []) if self.ctx.get(name) is None]
                    attempt['host'] = dict(status='waiting' if waiting else 'running', waitingFor=waiting)
                plugin['run'] = dict(pluginRunId=attempt['pluginRunId'], packageId=attempt['packageId'], handlers=handlers, fiber=fiber)
                attempt['status'] = 'client-pending' if 'client' in package['code'] else 'waiting' if attempt['host']['waitingFor'] else 'running'
                if 'client' not in package['code']:
                    plugin['currentPackageId'] = attempt['packageId']
                    plugin.pop('nextPackageId', None)
                self.ctx.emit('cordis/advertise', dict(pluginId=plugin['pluginId'], packageId=attempt['packageId'], pluginRunId=attempt['pluginRunId'], name=package['name']))
                return dict(ok=True, pluginId=plugin['pluginId'], packageId=attempt['packageId'], pluginRunId=attempt['pluginRunId'], waitingFor=attempt['host']['waitingFor'], startedHere=True)
            except Exception as error:
                if fiber is not None:
                    await fiber.dispose()
                attempt['status'] = 'failed'
                attempt['host'] = dict(status='failed', waitingFor=[], error=str(error))
                return dict(ok=False, message=str(error))

    @Remote
    async def runHostHalf(self, agent, pluginId, packageId, mode, requestId, approveFutureVersions):
        plugin, error = self.plan(agent, pluginId, packageId, mode, attach=True)
        if error:
            return dict(ok=False, message=error['message'])
        pending = self.pending.get(requestId) if requestId is not None else None
        if requestId is not None:
            if pending is None or (pending['pluginId'], pending['packageId'], pending['mode']) != (pluginId, packageId, mode):
                return dict(ok=False, message='run request does not authorize this package')
            attempt = plugin['latestRun']
            if attempt['pluginRunId'] != pending['pluginRunId']:
                return dict(ok=False, message='run request is stale')
        else:
            if any(row['pluginId'] == pluginId for row in self.pending.values()):
                return dict(ok=False, message='plugin has a pending model run request')
            current = plugin.get('run')
            attempt = plugin['latestRun'] if current and current['packageId'] == packageId else self.attempt(plugin, packageId, mode)
        plugin['approved'].add(packageId)
        if approveFutureVersions:
            plugin['approveFuture'] = True
        return await self.activate(plugin, attempt)

    @Remote
    def getClientCode(self, agent, pluginId, pluginRunId):
        plugin = self.owned(agent, pluginId)
        run = plugin.get('run') if plugin else None
        if run is None or run['pluginRunId'] != pluginRunId:
            raise ValueError('dynamic plugin activation is unavailable')
        package = plugin['packages'][run['packageId']]
        return dict(code=package['code']['client'], name=package['name'], pluginId=pluginId, packageId=package['packageId'], pluginRunId=pluginRunId)

    async def settle(self, plugin, resolution):
        run = plugin.get('run')
        if resolution.get('pluginRunId') is not None and (run is None or run['pluginRunId'] != resolution['pluginRunId']):
            return refusal('cancelled', 'activation is stale')
        attempt = plugin['latestRun']
        if not resolution['ok']:
            await self.retract(plugin)
            attempt['status'] = 'rejected' if resolution['reason'] == 'rejected' else 'failed'
            attempt['client'] = dict(status='failed', waitingFor=[], error=resolution.get('message', resolution['reason']))
            return refusal(resolution['reason'], resolution.get('message', resolution['reason']))
        if run is None:
            return refusal('not-running', 'Host activation is unavailable')
        waiting = resolution.get('waitingFor', [])
        attempt['client'] = dict(status='waiting' if waiting else 'running', waitingFor=waiting)
        attempt['status'] = 'waiting' if waiting or attempt['host']['waitingFor'] else 'running'
        plugin['currentPackageId'] = run['packageId']
        plugin.pop('nextPackageId', None)
        return self.run_response(plugin)

    @Remote
    async def resolveRequestRun(self, requestId, resolution):
        pending = self.pending.get(requestId)
        if pending is None:
            return dict(accepted=False)
        plugin = self.plugins[pending['pluginId']]
        if resolution.get('pluginRunId') is not None and (plugin.get('run') or {}).get('pluginRunId') != resolution['pluginRunId']:
            return dict(accepted=False)
        if resolution['ok'] and not plugin.get('run'):
            return dict(accepted=False)
        self.pending.pop(requestId)
        result = await self.settle(plugin, resolution)
        self.ctx.emit('cordis/request-run-resolved', dict(requestId=requestId, outcome='approved' if result['ok'] else 'rejected' if resolution.get('reason') == 'rejected' else 'failed'))
        return dict(accepted=True)

    @Remote
    async def settleUserRun(self, agent, pluginId, resolution):
        plugin = self.owned(agent, pluginId)
        return await self.settle(plugin, resolution) if plugin is not None else refusal('plugin-missing', 'dynamic plugin is unavailable')

    async def retract(self, plugin):
        run = plugin.pop('run', None)
        if run is not None:
            if run['fiber'] is not None:
                await run['fiber'].dispose()
            self.ctx.emit('cordis/retract', dict(pluginId=plugin['pluginId'], packageId=run['packageId'], pluginRunId=run['pluginRunId']))

    async def stop(self, agent, pluginId):
        plugin = self.owned(agent, pluginId)
        if plugin is None:
            return refusal('plugin-missing', 'dynamic plugin is unavailable')
        pending = [key for key, row in self.pending.items() if row['pluginId'] == pluginId]
        if not pending and 'run' not in plugin:
            return refusal('not-running', 'dynamic plugin is not running')
        for key in pending:
            del self.pending[key]
            self.ctx.emit('cordis/request-run-resolved', dict(requestId=key, outcome='cancelled'))
        await self.retract(plugin)
        plugin['latestRun']['status'] = 'stopped'
        for key in ('host', 'client'):
            if plugin['latestRun'][key]['status'] != 'absent':
                plugin['latestRun'][key] = half('stopped')
        return dict(ok=True)

    @Remote
    async def stopFromPanel(self, agent, pluginId):
        return await self.stop(agent, pluginId)

    async def undefine(self, agent, pluginId):
        plugin = self.owned(agent, pluginId)
        if plugin is None:
            return refusal('plugin-missing', 'dynamic plugin is unavailable')
        running = 'run' in plugin
        await self.stop(agent, pluginId)
        del self.plugins[pluginId]
        self.locks.pop(pluginId, None)
        return dict(ok=True, wasRunning=running)

    @Remote
    async def undefineFromPanel(self, agent, pluginId):
        return await self.undefine(agent, pluginId)

    @Remote
    async def invoke(self, pluginId, pluginRunId, method, args):
        plugin = self.plugins.get(pluginId)
        run = plugin.get('run') if plugin else None
        if run is None:
            return dict(ok=False, code='plugin-not-running', message='dynamic plugin is not running')
        if run['pluginRunId'] != pluginRunId:
            return dict(ok=False, code='stale-run', message='activation is no longer active')
        if method not in run['handlers']:
            return dict(ok=False, code='method-not-found', message='Host method is unavailable')
        try:
            result = run['handlers'][method](args)
            if inspect.isawaitable(result):
                result = await result
            return dict(ok=True, value=result)
        except Exception as error:
            return dict(ok=False, code='handler-error', message=str(error))

    @Remote
    def syncInspectManifest(self, providers):
        self.inspect_registry.sync_client_manifest(providers)
        return None

    @Remote
    def resolveInspectQuery(self, agent, requestId, resolution):
        return self.inspect_registry.resolve_client_query(agent, requestId, resolution)

    async def queryClient(self, agent, provider, method, input=UNDEFINED, signal=None):
        return await self.inspect_registry.query('client', provider, method, input, agent, signal)

    @Remote
    def reportRenderFailure(self, pluginId, pluginRunId, failure):
        plugin = self.plugins.get(pluginId)
        if plugin is not None and plugin.get('run', {}).get('pluginRunId') == pluginRunId:
            plugin['run']['renderFailure'] = copy.deepcopy(failure)
        return None

    @Remote
    def reportClientGuardFailure(self, pluginId, pluginRunId, error):
        plugin = self.plugins.get(pluginId)
        if plugin is not None and plugin.get('run', {}).get('pluginRunId') == pluginRunId:
            plugin['latestRun']['error'] = dict(error, phase='client-apply', pluginId=pluginId, packageId=plugin['run']['packageId'], pluginRunId=pluginRunId)
        return None
