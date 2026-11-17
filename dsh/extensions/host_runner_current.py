"""Current Dynamic Host runner over the Native Python evaluator.

Historical runner code stays pin-bound. The evaluator/process carrier remains
the explicit Python 3.8/Windows 7 adaptation; browser Remote contracts stay
those of the fixed current Source.
"""
import asyncio
import copy

from dsh.cordis import Schema
from dsh.cordis.json_text import stringify_json
from dsh.extensions.host_runner import DynamicCordisRunner
from dsh.extensions.cordis_runner_state import format_error
from dsh.extensions.inspect_registry_current import CurrentCordisInspectRegistryService
from dsh.llm.message import create_user_message
from dsh.typert.remote import Remote, TypertRemoteService


class CurrentDynamicCordisRunner(DynamicCordisRunner):
    Config = Schema.object({
        'vmTimeoutMs': Schema.number().min(1).default(5000),
        'clientInspectTimeoutMs': Schema.number().step(1).min(1).max(2147483647).default(10000),
    })

    def __init__(self, ctx, config=None):
        TypertRemoteService.__init__(self, ctx, 'dynamicCordisRunner')
        self.resolved = self.Config({} if config is None else config)
        self.timeout = self.resolved['vmTimeoutMs']
        self.plugins, self.pending = {}, {}
        self._next_ids = dict(plugin=1, package=1, run=1, approval=1)
        self.inspect_registry = CurrentCordisInspectRegistryService(ctx, self.resolved['clientInspectTimeoutMs'])
        self.starting = {}
        self._transitions, self._ending = {}, {}
        self._closed, self._close_task = False, None
        self.root_ctx = ctx
        self._group = None
        self._spare, self._warming = None, None
        self._host_processes = set()
        self._host_lock = asyncio.Lock()
        ctx.effect(lambda: self.close)

    def _message(self, text):
        return create_user_message(dict(content=[dict(type='text', text=text)], source=dict(kind='cordis-host-runner')))

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
            text = 'Cordis {} {} failed after the runner returned {}: {}\n{}\ncurrentPackageId: {}\nnextPackageId: {}\nReport the failure to the user; the definition can be managed through the Cordis panel.'.format(
                pending['mode'], identity, 'awaiting-approval' if pending['requiresApproval'] else 'starting', settled['reason'],
                format_error(settled), plugin.get('currentPackageId', 'none'), plugin.get('nextPackageId', pending['packageId']))
        agent.steer(self._message(text))

    def inject_user_context(self, agent, text):
        if self.owner_agent(agent.id) is agent:
            agent.inject(self._message(text))

    def steer_guard_failure(self, plugin, run, platform, failure):
        if not self.claim_runtime_failure(plugin, run, platform+'\0guard\0'+failure['message']):
            return
        agent = self.owner_agent(plugin['agentId'])
        if agent is not None:
            text = 'Cordis {} guard rejected runtime code in {}/{} ({}) after activation.\n{}\nThe Plugin remains running. Report the guard rejection to the user; it can be stopped through the Cordis panel.'.format(
                platform, plugin['pluginId'], run['packageId'], run['pluginRunId'], format_error(failure))
            agent.steer(self._message(text))

    def steer_host_handler_failure(self, plugin, run, method, failure):
        if not self.claim_runtime_failure(plugin, run, 'Host\0handler\0'+method+'\0'+failure['message']):
            return
        agent = self.owner_agent(plugin['agentId'])
        if agent is not None:
            text = 'Cordis Host handler {}/{} ({}) failed when the Client called host.call({}).\n{}\nThe Plugin remains running. Report the Host handler failure to the user. If the handler needs a Service, either declare that Service in the returned Plugin inject list or read it with ctx.get(name) and handle undefined.'.format(
                plugin['pluginId'], run['packageId'], run['pluginRunId'], stringify_json(method), format_error(failure))
            agent.steer(self._message(text))

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
                text = 'Cordis Client UI {}/{} ({}) failed while rendering Slot "{}" after activation.\n{}\nentryAbdicated: {}\nReport the Client render failure to the user; the definition can be stopped through the Cordis panel.'.format(
                    pluginId, definition['packageId'], pluginRunId, failure['slot'], format_error(failure), 'true' if failure['abdicated'] else 'false')
                agent.steer(self._message(text))
        return None

    async def start_host(self, plugin, source, run):
        failure = await super().start_host(plugin, source, run)
        if failure is not None and 'already registered' in failure['message']:
            failure = dict(failure, message=failure['message']+' — to REPLACE something an earlier dynamic package registered, first stop that package through its runner or the Cordis panel before running the new version.')
        return failure

    async def _host_lost(self, plugin, run, error):
        if plugin.get('run') is not run:
            return
        failure = self.error_details(error)
        await self.retract(plugin)
        attempt = plugin.get('latestRun')
        if attempt is not None and attempt['pluginRunId'] == run['pluginRunId']:
            self.fail_attempt(plugin, attempt, 'host-runtime', failure)
        agent = self.owner_agent(plugin['agentId'])
        if agent is not None:
            # Native process death has no in-process Source VM equivalent.
            text = 'Cordis Host process for {}/{} ({}) exited. Its registrations were removed. Report the Host process failure to the user.\n{}'.format(
                plugin['pluginId'], run['packageId'], run['pluginRunId'], failure['message'])
            agent.steer(self._message(text))
