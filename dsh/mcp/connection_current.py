"""Current generation supervisor, credential refresh and bounded replacement fence."""
import asyncio
import time
from types import SimpleNamespace

from dsh.core.abort import AbortController
from dsh.mcp.client_current import CurrentSdkClient
from dsh.mcp.credentials_current import McpTemplateBinding
from dsh.mcp.deadline_current import with_deadline
from dsh.mcp.diagnostic_current import McpLocalError
from dsh.mcp.generation_current import McpGeneration
from dsh.mcp.templates_current import MissingTemplateValue
from dsh.mcp.tools import _same_json
from dsh.mcp.tools_current import McpToolRegistrationError, sync_tools
from dsh.mcp.signals_current import combined_signals
from dsh.host.http_proxy_policy import JS_SPACE


def now_ms():
    return int(time.time()*1000)


class SupervisedMcpConnection:
    def __init__(self, ctx, config, policy, status):
        self.ctx, self.config, self.policy, self.status = ctx, config, policy, status
        self._label = 'mcp-client('+config['serverName']+')'
        self.binding = McpTemplateBinding(ctx,config)
        self.lifetime = AbortController()
        self.ready = asyncio.get_running_loop().create_future()
        self.current = None
        self.disposed = False
        self.disposers = {}
        self._instructions = ''
        self._binding_value = None
        self._failed_attempts = 0
        self._closure_failure = None
        self._sync_tail = None
        self._retry_timer = None
        self._checking_credentials = None
        self._credentials_dirty = False
        self._resource_operations = set()
        self._transport_config = config
        self._opts = dict(serverName=config['serverName'],toolCallTimeoutMs=config.get('toolCallTimeoutMs',60000),currentContract=True)
        self.resources = SimpleNamespace(request=self.request_resource)
        if self.binding.refs:
            ctx.on('credentials/reference-updated',self._credential_updated)
        self._settling = self._task(self._connect_generation())

    @property
    def client(self):
        return self.current.wire.client._wire if self.current is not None else None

    @property
    def _connected_at(self):
        return self.current.connected_at if self.current is not None else None

    def instructions(self):
        return self._instructions

    def _create_transport(self):
        from dsh.mcp.transport_current import create_current_transport
        return create_current_transport(self._transport_config)

    def _task(self, operation):
        task = asyncio.ensure_future(operation)
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        return task

    def _resolve_ready(self, error=None):
        if not self.ready.done():
            self.ready.set_result({} if error is None else dict(error=error))

    def _log(self, level, message):
        getattr(self.ctx.logger,level)(self._label+': '+message)

    def _diagnostic(self, error, operation):
        return self.binding.diagnostic(error,operation)

    def _is_current(self, record):
        return not self.disposed and self.current is record and not record.wire.lifetime.signal.aborted

    def _stopped(self):
        return self.disposed or self._closure_failure is not None

    def _stop_timers(self):
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None

    def _clear_tools(self):
        for dispose in self.disposers.values():
            try:dispose()
            except Exception as error:
                self._closure_failure = dict(self.status.closure(),cleanupError=self._diagnostic(error,'tool cleanup'))
                self.status.recordClosure(self._closure_failure)
                self._log('error','tool cleanup failed: '+self._diagnostic(error,'tool cleanup'))
        self.disposers = {}
        self._instructions = ''

    async def _close(self, record):
        result = await record.wire.close()
        if (not result['closeConfirmed'] or 'cleanupError' in result) and self._closure_failure is None:
            self._closure_failure = result
        self.status.recordClosure(self._closure_failure if self._closure_failure is not None else result)
        if self._closure_failure is not None and not self.disposed:
            error = McpLocalError(self._closure_failure.get('cleanupError',''))
            self.status.update(dict(state='failed',reason='unclosed-generation',lastError=str(error)))
            self._resolve_ready(error)
        return self._closure_failure is None

    def _enqueue(self, action):
        previous = self._sync_tail
        async def run():
            if previous is not None:
                await asyncio.gather(asyncio.shield(previous),return_exceptions=True)
            return await action()
        task = self._task(run())
        async def settled():
            await asyncio.gather(asyncio.shield(task),return_exceptions=True)
        self._sync_tail = self._task(settled())
        return task

    def _enqueue_sync(self, record):
        async def run():
            if not self._is_current(record):return
            async def sync(signal):
                opts = dict(self._opts,signal=signal)
                if self.config.get('expandTemplates'):
                    opts['redact'] = self.binding.redact
                self.disposers = await sync_tools(record.wire.client,self.ctx,opts,self.disposers,lambda: self._is_current(record))
            await record.wire.run(sync)
        return self._enqueue(run)

    def _schedule_reconnect(self, error, connected_at=None):
        if self._stopped():return
        policy = self.policy
        if not policy['enabled']:
            self.status.update(dict(state='failed',reason='reconnect-disabled',lastError=error))
            self._log('error','connection lost and reconnect is disabled — registered tools will fail until an HMR reload or Host restart' if connected_at is not None else 'connection failed and reconnect is disabled — no tools were registered; reload the plugin or restart the Host to connect')
            return
        if connected_at is not None and now_ms()-connected_at >= policy['maxDelayMs']:
            self._failed_attempts = 0
        self._failed_attempts += 1
        if self._failed_attempts > policy['maxAttempts']:
            async def clear():self._clear_tools()
            self._enqueue(clear)
            self.status.update(dict(state='failed',reason='gave-up',lastError=error))
            self._log('error','giving up after %s consecutive failed reconnect attempts — tools unregistered; reload the plugin or restart the Host to reconnect' % policy['maxAttempts'])
            return
        exponent = self._failed_attempts-1
        delay = policy['maxDelayMs'] if exponent>1023 else min(policy['maxDelayMs'],policy['initialDelayMs']*2.0**exponent)
        action = 'connection lost; reconnecting' if connected_at is not None else 'connection failed; retrying'
        self._log('warn','%s in %sms (attempt %s/%s)' % (action,format(delay,'.15g'),self._failed_attempts,policy['maxAttempts']))
        self.status.update(dict(state='reconnecting',attempt=self._failed_attempts,maxAttempts=policy['maxAttempts'],nextRetryAtMs=now_ms()+delay,lastError=error))
        if self._stopped():return
        def retry():
            self._retry_timer = None
            self._settling = self._task(self._connect_generation())
        self._retry_timer = asyncio.get_running_loop().call_later(int(delay)/1000,retry)

    def _lost(self, record, error):
        if not self._is_current(record):return
        self.current = None
        async def finish():
            confirmed = await self._close(record)
            self._resolve_ready(McpLocalError(error))
            if confirmed:self._schedule_reconnect(error,record.connected_at)
        self._settling = self._task(finish())

    def _credential_updated(self, ref, *_):
        from dsh.cordis.utils import js_to_string
        if js_to_string(ref) in self.binding.refs:
            self._request_credential_refresh()

    def _request_credential_refresh(self):
        if self._stopped():return
        self._credentials_dirty = True
        if self._checking_credentials is None:
            self._checking_credentials = self._task(self._check_credentials())

    async def _check_credentials(self):
        try:
            while self._credentials_dirty and not self._stopped():
                self._credentials_dirty = False
                try:next_config = await self.binding.resolve(self.lifetime.signal)
                except MissingTemplateValue:next_config = None
                if self.disposed or self._binding_value is not None and _same_json(next_config,self._binding_value.get('config')):
                    continue
                self._stop_timers()
                record, attempt = self.current, self._settling
                self.current = None
                if record is not None:await self._close(record)
                if attempt is not None:await asyncio.shield(attempt)
                if self._sync_tail is not None:await asyncio.shield(self._sync_tail)
                self._stop_timers()
                self._clear_tools()
                if self._stopped():
                    self._resolve_ready(McpLocalError('MCP credential refresh cleanup is incomplete'))
                    return
                self._failed_attempts = 0
                self._binding_value = {} if next_config is None else dict(config=next_config)
                self._settling = self._task(self._connect_generation())
        except Exception as error:
            if not self.disposed:self._log('error','credential refresh failed: '+self._diagnostic(error,'credential refresh'))
        finally:
            self._checking_credentials = None
            if self._credentials_dirty:self._request_credential_refresh()

    async def _refresh_tools(self, record, packet):
        if packet.get('method')!='notifications/tools/list_changed' or not self._is_current(record):return
        self._log('info','tool list changed, re-syncing')
        try:
            await asyncio.shield(self._enqueue_sync(record))
            if self._is_current(record) and record.connected_at is not None:
                self.status.update(dict(state='connected',toolCount=len(self.disposers),connectedAt=record.connected_at))
        except Exception as error:
            if isinstance(error,McpToolRegistrationError):self._lost(record,self._diagnostic(error,'tool synchronization'))
            elif self._is_current(record):self._log('error','tool re-sync failed: '+self._diagnostic(error,'tool synchronization'))

    async def _connect_generation(self):
        if self._stopped():return
        client = CurrentSdkClient()
        record = SimpleNamespace(wire=McpGeneration(client,self.config.get('closeTimeoutMs',5000),lambda error: self._diagnostic(error,'cleanup'),transport_factory=lambda _: self._create_transport()),connected_at=None)
        self.current = record
        self.status.opened()
        self.status.update(dict(state='connecting',attempt=self._failed_attempts))
        client.onclose = lambda: self._lost(record,'connection closed') if record.connected_at is not None else None
        client.on_notification = lambda packet: self._refresh_tools(record,packet)
        try:
            started = now_ms()
            remaining = lambda: None if self.config.get('startupTimeoutMs') is None else self.config['startupTimeoutMs']-(now_ms()-started)
            resolved = await record.wire.run(self.binding.resolve,remaining())
            self._binding_value = dict(config=resolved)
            self._transport_config = resolved
            await record.wire.connect(resolved,remaining())
            if not self._is_current(record):return
            text = (client.getInstructions() or '').rstrip(JS_SPACE)
            instructions = '### MCP server: '+self.config['serverName']+'\n\n'+text if text else ''
            maximum = self.config.get('maxInstructionBytes',32768)
            encoded = instructions.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace').encode('utf-8')
            if len(encoded)>maximum:
                raise McpLocalError(self._label+': server instructions exceed maxInstructionBytes ('+str(maximum)+')')
            sync, budget = self._enqueue_sync(record), remaining()
            await (asyncio.shield(sync) if budget is None else with_deadline(sync,budget,self._label+': startup timed out'))
            if not self._is_current(record):return
            record.wire.assertOpen()
            self._instructions, record.connected_at = instructions, now_ms()
            self.status.update(dict(state='connected',toolCount=len(self.disposers),connectedAt=record.connected_at))
            self._resolve_ready()
            if self._failed_attempts>0:self._log('info','reconnected and re-synced tools (attempt %s/%s)' % (self._failed_attempts,self.policy['maxAttempts']))
        except Exception as error:
            if self.current is not record:return
            self.current = None
            confirmed = await self._close(record)
            self._resolve_ready(McpLocalError(self._diagnostic(error,'startup')) if self.config.get('expandTemplates') else error)
            if self.disposed or not confirmed:return
            if isinstance(error,MissingTemplateValue):
                self._binding_value = {}
                self.status.update(dict(state='waiting-credentials',lastError=self._diagnostic(error,'credential resolution')))
                return
            self._log('warn','connection attempt failed: '+self._diagnostic(error,'startup'))
            self._schedule_reconnect(self._diagnostic(error,'startup'))

    async def request_resource(self, request, execution):
        record = self.current
        if record is None or record.connected_at is None:
            raise McpLocalError(self._label+': server is disconnected')
        task = asyncio.current_task()
        self._resource_operations.add(task)
        async def operation(signal):
            async with combined_signals(signal,execution.signal) as combined:
                options = dict(signal=combined,timeout=self.config.get('toolCallTimeoutMs',60000))
                client = record.wire.client
                method = request['method']
                if method in ('resources/list','resources/templates/list'):
                    if 'resources' not in (client.getServerCapabilities() or {}):
                        return {'resources' if method=='resources/list' else 'resourceTemplates':[]}
                    params = dict(cursor=request['cursor']) if 'cursor' in request else None
                    return await (client.listResources(params,options) if method=='resources/list' else client.listResourceTemplates(params,options))
                if method=='resources/read':return await client.readResource(dict(uri=request['uri']),options)
                raise McpLocalError('unsupported MCP resource method: '+method)
        try:return await record.wire.run(operation)
        except Exception as error:
            if self.config.get('expandTemplates'):raise McpLocalError(self._diagnostic(error,request['method'])) from None
            raise
        finally:self._resource_operations.discard(task)

    async def dispose(self):
        await self._dispose()

    async def _dispose(self):
        self.disposed = True
        self._resolve_ready(McpLocalError('MCP client disposed'))
        self.lifetime.abort(McpLocalError('MCP client disposed'))
        self._stop_timers()
        record, self.current = self.current, None
        if record is not None:await self._close(record)
        try:
            await with_deadline(asyncio.gather(*[asyncio.shield(task) for task in (self._settling,self._sync_tail,self._checking_credentials) if task is not None]),self.config.get('closeTimeoutMs',5000),'MCP cleanup did not settle')
        except Exception as error:
            if self._closure_failure is None:self._closure_failure = dict(self.status.closure(),cleanupError=self._diagnostic(error,'cleanup'))
        self._clear_tools()
        result = self._closure_failure if self._closure_failure is not None else self.status.closure()
        self.status.recordClosure(result)
        self.status.update(dict(state='closed',result=result))
        if not result['closeConfirmed'] or 'cleanupError' in result:self._log('error','cleanup incomplete')
