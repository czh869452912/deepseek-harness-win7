"""Dynamic Cordis activation/approval state machine from the pinned Host runner.

The source-language evaluator is supplied by the Python Host. Wire identities,
version commits, request ownership, page attachment and model notifications
remain the original protocol. No browser program is rewritten here.
"""
import asyncio
import copy

from dsh.core.cancellation import aborted
from dsh.llm.message import create_user_message
from dsh.typert.remote import Remote


def missing_plugin(pid):
    return 'no dynamic plugin "{}" in this process — it may have been removed or lost on DSH restart'.format(pid)


def refusal(reason, message, **fields):
    return dict(ok=False, reason=reason, message=message, **fields)


def format_error(failure):
    return 'message: ' + failure['message'] + ('\nstack:\n' + failure['stack'] if 'stack' in failure else '')


class CordisRunnerState:
    def attempt(self, plugin, package_id, mode):
        code = plugin['packages'][package_id]['code']
        attempt = dict(pluginRunId=self.mint_id('run', 'run'), packageId=package_id, mode=mode, status='starting-host',
            host=dict(status='pending' if 'host' in code else 'absent', waitingFor=[]),
            client=dict(status='pending' if 'client' in code else 'absent', waitingFor=[]))
        plugin.update(nextPackageId=package_id, latestRun=attempt)
        return attempt

    def pending_for(self, pid):
        return next((rid for rid, pending in self.pending.items() if pending['pluginId'] == pid), None)

    async def run(self, agent, pluginId, packageId, mode, signal=None):
        plugin, error = self.plan(agent, pluginId, packageId, mode)
        if error is not None:
            return error
        if aborted(signal):
            return refusal('cancelled', 'the run request for dynamic plugin "{}" was cancelled before activation'.format(pluginId))
        if self.pending_for(pluginId) is not None:
            return refusal('transition-in-flight', 'dynamic plugin "{}" already has a pending run request'.format(pluginId))
        attempt = self.attempt(plugin, packageId, mode)
        package = plugin['packages'][packageId]
        if 'client' not in package['code']:
            started = await self.activate(plugin, attempt)
            if started['ok']:
                return self.run_response(plugin, started)
            if self.activation_retired(plugin, attempt):
                return dict(started, reason='cancelled')
            self.fail_attempt(plugin, attempt, 'host-load', started)
            return dict(started, reason='host-half-failed')
        rid = self.mint_id('approval', 'approval')
        required = not plugin['approveFuture'] and packageId not in plugin['approved']
        attempt.update(approvalRequestId=rid, requiresApproval=required, status='awaiting-approval' if required else 'starting-host')
        self.pending[rid] = dict(agentId=agent.id, pluginId=pluginId, packageId=packageId,
            pluginRunId=attempt['pluginRunId'], mode=mode, requiresApproval=required)
        self.ctx.emit('cordis/request-run', dict(requestId=rid, agentId=agent.id, pluginId=pluginId, packageId=packageId,
            mode=mode, name=package['name'], purpose=package['purpose'], requiresApproval=required))
        result = dict(ok=True, status='awaiting-approval' if required else 'starting', pluginId=pluginId,
            packageId=packageId, pluginRunId=attempt['pluginRunId'], mode=mode, waitingFor=[])
        if 'currentPackageId' in plugin:
            result['currentPackageId'] = plugin['currentPackageId']
        result['nextPackageId'] = packageId
        return result

    @Remote
    async def runHostHalf(self, agent, pluginId, packageId, mode, requestId, approveFutureVersions):
        plugin, error = self.plan(agent, pluginId, packageId, mode, attach=requestId is None)
        if error is not None:
            return dict(ok=False, message=error['message'])
        if requestId is not None:
            pending = self.pending.get(requestId)
            if pending is None or (pending['pluginId'], pending['packageId'], pending['mode']) != (pluginId, packageId, mode):
                return dict(ok=False, message='run request "{}" does not authorize {}/{}'.format(requestId, pluginId, packageId))
            latest = plugin.get('latestRun')
            status = 'awaiting-approval' if pending['requiresApproval'] else 'starting-host'
            if latest is None or latest['pluginRunId'] != pending['pluginRunId'] or (
                    latest['status'] != status and (pending['requiresApproval'] or latest['status'] != 'client-pending')):
                return dict(ok=False, message='run request "{}" no longer identifies the latest run of {}'.format(requestId, pluginId))
            attempt = latest
            if pending['requiresApproval']:
                plugin['approved'].add(packageId)
                if approveFutureVersions:
                    plugin['approveFuture'] = True
        else:
            pending_id = self.pending_for(pluginId)
            if pending_id is not None:
                return dict(ok=False, message='dynamic plugin "{}" has pending run request {}'.format(pluginId, pending_id))
            active, latest = plugin.get('run', {}), plugin.get('latestRun', {})
            attached = active.get('packageId') == packageId and latest.get('pluginRunId') == active.get('pluginRunId')
            attempt = latest if attached else self.attempt(plugin, packageId, mode)
            if 'client' in plugin['packages'][packageId]['code']:
                plugin['approved'].add(packageId)
        attaching = attempt['pluginRunId'] == plugin.get('run', {}).get('pluginRunId')
        if not attaching:
            attempt['status'] = 'starting-host'
            if attempt['host']['status'] != 'absent':
                attempt['host'] = dict(status='pending', waitingFor=[])
        started = await self.activate(plugin, attempt, requestId, attaching)
        if not started['ok'] and not self.activation_retired(plugin, attempt):
            self.fail_attempt(plugin, attempt, 'host-load', started)
        return started

    def _missing_for(self, run):
        fiber = run.get('fiber')
        return [] if fiber is None else [name for name in fiber.inject if self.ctx.get(name) is None]

    async def activate(self, plugin, attempt, request_id=None, attach=False):
        pid = plugin['pluginId']
        task = self.starting.get(pid)
        if task is None:
            transition = dict(plugin=plugin, attempt=attempt, invalidated=False)
            self._transitions[pid] = transition
            task = asyncio.create_task(self.start_fresh(plugin, attempt, request_id, attach, transition))
            transition['task'] = task
            self.starting[pid] = task
            def finished(completed):
                if self.starting.get(pid) is completed:
                    del self.starting[pid]
                if self._transitions.get(pid) is transition:
                    del self._transitions[pid]
                # Observe a failure even when all callers abandoned their waits.
                if not completed.cancelled():
                    completed.exception()
            task.add_done_callback(finished)
        # A caller owns its wait, not the shared activation transaction.
        return await asyncio.shield(task)

    def activation_retired(self, plugin, attempt):
        return (self._closed or self.ctx.fiber.uid is None or self.plugins.get(plugin['pluginId']) is not plugin
                or attempt['status'] in ('cancelled', 'stopped'))

    async def start_fresh(self, plugin, attempt, request_id, attach, transition):
        package_id, rid = attempt['packageId'], attempt['pluginRunId']
        current = plugin.get('run')
        if attach and current is not None and current['packageId'] == package_id and current['pluginRunId'] == rid:
            return dict(ok=True, pluginId=plugin['pluginId'], packageId=package_id, pluginRunId=rid,
                waitingFor=self._missing_for(current), startedHere=False)
        if current is not None:
            await self.retract(plugin)
        if transition['invalidated'] or self.activation_retired(plugin, attempt):
            return dict(ok=False, message='activation of dynamic plugin "{}" was cancelled during retirement'.format(plugin['pluginId']))
        if attempt['mode'] == 'update' or 'currentPackageId' not in plugin:
            plugin['nextPackageId'] = package_id
        run = dict(pluginRunId=rid, packageId=package_id, handlers={}, handlerDisposers=[], reportedRuntimeErrors=set())
        if request_id is not None:
            run['startedForRequest'] = request_id
        package = plugin['packages'][package_id]
        if 'host' in package['code']:
            failure = await self.start_host(plugin, package['code']['host'], run)
            if transition['invalidated'] or self.activation_retired(plugin, attempt):
                await self.discard_run(run)
                return dict(ok=False, message='activation of dynamic plugin "{}" was cancelled during retirement'.format(plugin['pluginId']))
            if failure is not None:
                return dict(ok=False, **failure)
        elif transition['invalidated'] or self.activation_retired(plugin, attempt):
            return dict(ok=False, message='activation of dynamic plugin "{}" was cancelled during retirement'.format(plugin['pluginId']))
        plugin['run'] = run
        self.ctx.emit('cordis/dynamic-package', dict(pluginId=plugin['pluginId'], packageId=package_id, pluginRunId=rid, name=package['name']))
        waiting = self._missing_for(run)
        attempt['host'] = dict(status='absent' if 'fiber' not in run else 'waiting' if waiting else 'running', waitingFor=waiting)
        if 'client' not in package['code']:
            self.commit_activation(plugin, run)
        else:
            attempt['status'] = 'client-pending'
            attempt['client'] = dict(status='pending', waitingFor=[])
        return dict(ok=True, pluginId=plugin['pluginId'], packageId=package_id, pluginRunId=rid,
            waitingFor=self._missing_for(run), startedHere=True)

    @Remote
    def getClientCode(self, agent, pluginId, pluginRunId):
        plugin = self.owned(agent, pluginId)
        if plugin is None:
            raise ValueError(missing_plugin(pluginId))
        run = plugin.get('run')
        if run is None or run['pluginRunId'] != pluginRunId:
            raise ValueError('dynamic plugin "{}" is not running activation "{}"'.format(pluginId, pluginRunId))
        package = plugin['packages'][run['packageId']]
        if 'client' not in package['code']:
            raise ValueError('package "{}" has no Client half'.format(run['packageId']))
        return dict(code=package['code']['client'], name=package['name'], pluginId=pluginId, packageId=run['packageId'], pluginRunId=pluginRunId)

    async def settle(self, plugin, resolution, request_id=None):
        if plugin is None:
            return refusal('plugin-missing', 'the dynamic plugin was removed during activation')
        attempt = plugin.get('latestRun')
        if not resolution['ok']:
            reason = resolution['reason']
            if reason == 'rejected':
                message = resolution.get('message', 'the run request was declined')
                if attempt is not None:
                    attempt['status'] = 'rejected'
                    attempt['error'] = self.diagnostic(plugin, attempt, 'approval', dict(message=message))
                    attempt['client'] = dict(status='stopped', waitingFor=[])
                return refusal(reason, message)
            run = plugin.get('run')
            owns = run is not None and resolution.get('pluginRunId') == run['pluginRunId'] and (
                request_id is None or run.get('startedForRequest') == request_id) and resolution.get('startedHere') is not False
            if owns:
                await self.retract(plugin)
            details = dict(message=resolution.get('message', reason))
            if 'stack' in resolution:
                details['stack'] = resolution['stack']
            if attempt is not None and ('pluginRunId' not in resolution or attempt['pluginRunId'] == resolution['pluginRunId']):
                self.fail_attempt(plugin, attempt, 'host-apply' if reason == 'host-half-failed' else 'client-apply', details)
            return dict(ok=False, reason=reason, **details)
        run = plugin.get('run')
        if run is None or run['pluginRunId'] != resolution['pluginRunId']:
            return refusal('client-half-failed', 'activation "{}" is no longer active'.format(resolution['pluginRunId']))
        if attempt is not None and attempt['pluginRunId'] == run['pluginRunId']:
            waiting = resolution.get('waitingFor', [])
            attempt['client'] = dict(status='waiting' if waiting else 'running', waitingFor=list(waiting))
        self.commit_activation(plugin, run)
        result = self.run_response(plugin, dict(pluginRunId=run['pluginRunId'], packageId=run['packageId'], waitingFor=self._missing_for(run)))
        if 'waitingFor' in resolution:
            result['clientWaitingFor'] = list(resolution['waitingFor'])
        return result

    def commit_activation(self, plugin, run):
        plugin['currentPackageId'] = run['packageId']
        plugin.pop('nextPackageId', None)
        run.pop('startedForRequest', None)
        attempt = plugin.get('latestRun')
        if attempt is not None and attempt['pluginRunId'] == run['pluginRunId']:
            attempt['status'] = 'waiting' if attempt['host']['status'] == 'waiting' or attempt['client']['status'] == 'waiting' else 'running'
            for key in ('approvalRequestId', 'requiresApproval', 'error'):
                attempt.pop(key, None)

    def run_response(self, plugin, started):
        attempt = plugin.get('latestRun', {})
        return dict(ok=True, status='running', pluginId=plugin['pluginId'], packageId=started['packageId'],
            pluginRunId=started['pluginRunId'], waitingFor=list(started['waitingFor']), currentPackageId=started['packageId'],
            mode=attempt.get('mode', 'run') if attempt.get('pluginRunId') == started['pluginRunId'] else 'run')

    @Remote
    async def resolveRequestRun(self, requestId, resolution):
        pending = self.pending.get(requestId)
        if pending is None:
            return dict(accepted=False)
        plugin = self.plugins.get(pending['pluginId'])
        run = plugin.get('run', {}) if plugin is not None else {}
        if resolution['ok'] and run.get('pluginRunId') != resolution.get('pluginRunId'):
            return dict(accepted=False)
        if not resolution['ok'] and 'pluginRunId' in resolution and run.get('pluginRunId') != resolution['pluginRunId']:
            return dict(accepted=False)
        del self.pending[requestId]
        settled = await self.settle(plugin, resolution, requestId)
        self.announce_resolved(requestId, resolution, None if pending['requiresApproval'] else 'completed')
        self.steer_run_outcome(pending, settled)
        return dict(accepted=True)

    @Remote
    async def settleUserRun(self, agent, pluginId, resolution):
        plugin = self.owned(agent, pluginId)
        if plugin is None:
            return refusal('plugin-missing', missing_plugin(pluginId))
        settled = await self.settle(plugin, resolution)
        self.inject_user_run_outcome(agent, pluginId, settled)
        return settled

    async def stop(self, agent, pluginId):
        plugin = self.owned(agent, pluginId)
        if plugin is None:
            return refusal('plugin-missing', missing_plugin(pluginId))
        if 'run' not in plugin and self.pending_for(pluginId) is None and pluginId not in self.starting and pluginId not in self._ending:
            return refusal('not-running', 'dynamic plugin "{}" is not running'.format(pluginId))
        await self.end_plugin(plugin, False)
        return dict(ok=True)

    @Remote
    async def stopFromPanel(self, agent, pluginId):
        result = await self.stop(agent, pluginId)
        if result['ok']:
            plugin = self.owned(agent, pluginId)
            self.inject_user_context(agent, 'The user stopped Cordis Plugin {}. Its Packages remain defined; currentPackageId is {}.'.format(
                pluginId, plugin.get('currentPackageId', 'none') if plugin is not None else 'none'))
        return result

    async def undefine(self, agent, pluginId):
        plugin = self.owned(agent, pluginId)
        if plugin is None:
            return refusal('plugin-missing', missing_plugin(pluginId))
        was_running = 'run' in plugin
        await self.end_plugin(plugin, True)
        return dict(ok=True, wasRunning=was_running)

    async def end_plugin(self, plugin, remove):
        """Own retirement independently of any Remote/tool caller's wait."""
        pid = plugin['pluginId']
        ending = self._ending.get(pid)
        if ending is None:
            transition = self._transitions.get(pid)
            if transition is not None:
                transition['invalidated'] = True
                transition['attempt']['status'] = 'cancelled'
            self.cancel_pending(pid, 'dynamic plugin "{}" was {} before approval'.format(pid, 'removed' if remove else 'stopped'))
            ending = dict(remove=remove)
            self._ending[pid] = ending
            task = ending['task'] = asyncio.create_task(self._end_plugin(plugin, ending, transition))
            def finished(completed):
                if self._ending.get(pid) is ending:
                    del self._ending[pid]
                if not completed.cancelled():
                    completed.exception()
            task.add_done_callback(finished)
        else:
            ending['remove'] = ending['remove'] or remove
        await asyncio.shield(ending['task'])

    async def _end_plugin(self, plugin, ending, transition):
        if transition is not None:
            await asyncio.gather(asyncio.shield(transition['task']), return_exceptions=True)
        await self.retract(plugin)
        attempt = plugin.get('latestRun')
        if attempt is not None:
            attempt['status'] = 'stopped'
            for name in ('host', 'client'):
                if attempt[name]['status'] != 'absent':
                    attempt[name] = dict(status='stopped', waitingFor=[])
        if ending['remove'] and self.plugins.get(plugin['pluginId']) is plugin:
            del self.plugins[plugin['pluginId']]

    @Remote
    async def undefineFromPanel(self, agent, pluginId):
        result = await self.undefine(agent, pluginId)
        if result['ok']:
            self.inject_user_context(agent, 'The user removed Cordis Plugin {} and all of its Packages. The Plugin no longer exists.'.format(pluginId))
        return result

    def announce_resolved(self, rid, resolution, override=None):
        outcome = override or ('approved' if resolution['ok'] else 'rejected' if resolution['reason'] == 'rejected' else 'failed')
        self.ctx.emit('cordis/request-run-resolved', dict(requestId=rid, outcome=outcome))

    def cancel_pending(self, pid, message):
        rid = self.pending_for(pid)
        if rid is None:
            return
        pending = self.pending.pop(rid)
        plugin = self.plugins.get(pid)
        if plugin is not None and plugin.get('latestRun', {}).get('pluginRunId') == pending['pluginRunId']:
            attempt = plugin['latestRun']
            attempt['status'] = 'cancelled'
            attempt['error'] = self.diagnostic(plugin, attempt, 'approval', dict(message=message))
            attempt.pop('approvalRequestId', None)
            attempt.pop('requiresApproval', None)
        self.announce_resolved(rid, dict(ok=False, reason='rejected'), 'cancelled')

    @staticmethod
    def diagnostic(plugin, attempt, phase, failure):
        return dict(phase=phase, **failure, pluginId=plugin['pluginId'], packageId=attempt['packageId'], pluginRunId=attempt['pluginRunId'])

    def fail_attempt(self, plugin, attempt, phase, failure):
        attempt['status'] = 'failed'
        attempt['error'] = self.diagnostic(plugin, attempt, phase, failure)
        attempt['host' if phase.startswith('host') else 'client'] = dict(status='failed', waitingFor=[], error=failure['message'])

    async def retract(self, plugin):
        run = plugin.pop('run', None)
        if run is None:
            return
        await self.discard_run(run)
        self.ctx.emit('cordis/dynamic-retract', dict(pluginId=plugin['pluginId'], packageId=run['packageId'], pluginRunId=run['pluginRunId']))

    @staticmethod
    async def discard_run(run):
        disposers, run['handlerDisposers'] = run.get('handlerDisposers', []), []
        for dispose in disposers:
            dispose()
        if run.get('fiber') is not None:
            await run['fiber'].dispose()

    def owner_agent(self, sid):
        agents = self.root_ctx.get('agents')
        return agents.get(sid) if agents is not None else None

    def steer_run_outcome(self, pending, settled):
        agent = self.owner_agent(pending['agentId'])
        if agent is None:
            return
        plugin = self.plugins.get(pending['pluginId'], {})
        identity = '{pluginId}/{packageId} ({pluginRunId})'.format(**pending)
        if settled['ok']:
            text = 'Cordis {} {} completed successfully. currentPackageId is {}. Continue using the running Plugin.'.format(
                pending['mode'], identity, settled.get('currentPackageId', pending['packageId']))
        elif settled['reason'] == 'rejected':
            text = 'The user rejected Cordis {} {}. Do not request the same activation again unless the user asks.'.format(pending['mode'], identity)
        else:
            text = 'Cordis {} {} failed after cordis_run returned {}: {}\n{}\ncurrentPackageId: {}\nnextPackageId: {}\nInspect the failed Package, correct it on the same Plugin when needed, and retry the activation autonomously.'.format(
                pending['mode'], identity, 'awaiting-approval' if pending['requiresApproval'] else 'starting', settled['reason'],
                format_error(settled), plugin.get('currentPackageId', 'none'), plugin.get('nextPackageId', pending['packageId']))
        agent.steer(create_user_message(dict(content=[dict(type='text', text=text)], source=dict(kind='plugin', plugin='cordis-host-runner'))))

    def inject_user_context(self, agent, text):
        if self.owner_agent(agent.id) is not agent:
            return
        agent.inject(create_user_message(dict(content=[dict(type='text', text=text)], source=dict(kind='plugin', plugin='cordis-host-runner'))))

    def inject_user_run_outcome(self, agent, pid, settled):
        plugin = self.owned(agent, pid) or {}
        if settled['ok']:
            text = 'The user manually ran Cordis Plugin {}, Package {}, as {}. The activation succeeded; currentPackageId is {}.'.format(
                pid, settled['packageId'], settled['pluginRunId'], settled['currentPackageId'])
        else:
            latest = plugin.get('latestRun')
            version = '' if latest is None else ', Package {}, as {}'.format(latest['packageId'], latest['pluginRunId'])
            text = 'The user manually ran Cordis Plugin {}{}, but it failed: {}\n{}\ncurrentPackageId: {}\nnextPackageId: {}'.format(
                pid, version, settled['reason'], format_error(settled), plugin.get('currentPackageId', 'none'), plugin.get('nextPackageId', 'none'))
        self.inject_user_context(agent, text)

    def claim_runtime_failure(self, plugin, run, key):
        attempt = plugin.get('latestRun', {})
        if plugin.get('run') is not run or attempt.get('pluginRunId') != run['pluginRunId'] or attempt.get('status') not in ('running', 'waiting'):
            return False
        if key in run['reportedRuntimeErrors']:
            return False
        run['reportedRuntimeErrors'].add(key)
        return True

    def steer_guard_failure(self, plugin, run, platform, failure):
        if not self.claim_runtime_failure(plugin, run, (platform, 'guard', failure['message'])):
            return
        agent = self.owner_agent(plugin['agentId'])
        if agent is not None:
            text = 'Cordis {} guard rejected runtime code in {}/{} ({}) after activation.\n{}\nThe Plugin remains running. Inspect this Package, define a corrected Package on the same Plugin, and activate it autonomously with cordis_run mode:"update".'.format(
                platform, plugin['pluginId'], run['packageId'], run['pluginRunId'], format_error(failure))
            agent.steer(create_user_message(dict(content=[dict(type='text', text=text)], source=dict(kind='plugin', plugin='cordis-host-runner'))))

    def steer_host_handler_failure(self, plugin, run, method, failure):
        from dsh.core.json_schema import _dump
        if not self.claim_runtime_failure(plugin, run, ('Host', 'handler', method, failure['message'])):
            return
        agent = self.owner_agent(plugin['agentId'])
        if agent is not None:
            text = 'Cordis Host handler {}/{} ({}) failed when the Client called host.call({}).\n{}\nThe Plugin remains running. Inspect this Package, correct the Host code on the same Plugin, and activate the new Package autonomously with cordis_run mode:"update". If the handler needs a Service, either declare that Service in the plugin.inject list or read it with ctx.get(name) and handle None in Python Host code.'.format(
                plugin['pluginId'], run['packageId'], run['pluginRunId'], _dump(method), format_error(failure))
            agent.steer(create_user_message(dict(content=[dict(type='text', text=text)], source=dict(kind='plugin', plugin='cordis-host-runner'))))

    @Remote
    async def reportClientGuardFailure(self, agent, pluginId, pluginRunId, failure):
        plugin = self.owned(agent, pluginId)
        if plugin is not None and plugin.get('run', {}).get('pluginRunId') == pluginRunId:
            self.steer_guard_failure(plugin, plugin['run'], 'Client', failure)
        return None

    @Remote
    async def reportRenderFailure(self, agent, pluginId, pluginRunId, failure):
        plugin = self.owned(agent, pluginId)
        if plugin is not None and plugin.get('run', {}).get('pluginRunId') == pluginRunId:
            run = plugin['run']
            should_steer = 'renderFailure' not in run
            run['renderFailure'] = copy.deepcopy(failure)
            attempt = plugin.get('latestRun')
            if attempt is not None and attempt['pluginRunId'] == pluginRunId:
                attempt['error'] = self.diagnostic(plugin, attempt, 'client-render', failure)
                attempt['client'] = dict(status='failed', waitingFor=attempt['client']['waitingFor'], error=failure['message'])
                attempt['status'] = 'failed'
            definition = plugin['packages'].get(run['packageId'])
            if definition is not None and should_steer:
                text = 'Cordis Client UI {}/{} ({}) failed while rendering Slot "{}" after activation.\n{}\nentryAbdicated: {}\nInspect the failed Package, fix the Client code by defining a new Package on the same Plugin, and activate that Package autonomously with cordis_run mode:"update".'.format(
                    pluginId, definition['packageId'], pluginRunId, failure['slot'], format_error(failure), 'true' if failure['abdicated'] else 'false')
                agent.steer(create_user_message(dict(content=[dict(type='text', text=text)], source=dict(kind='plugin', plugin='cordis-host-runner'))))
        return None
