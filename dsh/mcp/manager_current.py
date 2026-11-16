"""MCP fleet ownership, serialized replacement and management Remote surface."""
import asyncio
from types import SimpleNamespace
from dsh.core.abort import AbortController
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.utils import _js_own_enumerable_keys
from dsh.mcp.current import CurrentMcpClient
from dsh.mcp.manager_entries_current import MANAGER_CONFIG, SERVER_ENTRY_SCHEMA, validate_entries, to_client_config
from dsh.mcp.server_probe_current import probe_server
from dsh.mcp.signals_current import combined_signals
from dsh.mcp.status_current import connection_status_in
from dsh.mcp.tools import _same_json
from dsh.mcp.content import error_string
from dsh.typert.remote import TypertRemoteService, Remote


class CurrentMcpManager(TypertRemoteService):
    Config = MANAGER_CONFIG
    inject = ['tools']

    def __init__(self, ctx, config):
        super().__init__(ctx,'mcpManager')
        self.config = config
        self._owner_context = ctx
        self._instances, self._statuses, self._registrations = {}, {}, {}
        self._watchers = set()
        self._lifetime = AbortController()
        self._tail = None
        self._stopped = False
        validate_entries(config['servers'].get())

    def apply(self, ctx=None):
        ctx = self.ctx
        ctx.effect(lambda: self._dispose,label='mcp-manager.instances')
        owner = ctx.fiber
        def validate(fiber,next_fn):
            raw = next_fn()
            if fiber is not owner:return raw
            entries = MANAGER_CONFIG(raw)['servers'].get()
            validate_entries(entries)
            for name in _js_own_enumerable_keys(entries):
                if name in self._registrations:
                    raise RuntimeError('servers.'+name+': a plugin already registers this server name — rename the entry key')
            return raw
        ctx.on('internal/config',validate)
        ctx.on('internal/plugin',lambda fiber: self._stop() if fiber is owner and fiber.uid is None else None,global_listener=True)
        ctx.on('loader/volatile-update',lambda *_:self._entries_changed('config reconcile'))
        async def activated():
            try:await owner.await_settled()
            except Exception:return
            await self._schedule(self._reconcile,'initial reconcile')
        self._activation = self._task(activated())

    def _task(self, operation):
        task = asyncio.ensure_future(operation)
        task.add_done_callback(lambda done:done.exception() if not done.cancelled() else None)
        return task

    def _entries(self):
        return dict(self.config['servers'].get(),**self._registrations)

    def list(self):
        entries = self._entries()
        names = dict.fromkeys([*_js_own_enumerable_keys(entries),*self._instances])
        return [dict(name=name,configured=name in entries,status=self._statuses.get(name,
            dict(state='connecting',attempt=0) if entries.get(name,{}).get('enabled') else dict(state='disabled'))) for name in names]

    def register(self, name, entry):
        resolved = SERVER_ENTRY_SCHEMA(dict(entry,enabled=True))
        validate_entries({name:resolved})
        def own():
            if self._stopped:raise RuntimeError('mcp-manager: the manager is disposed')
            if name in self.config['servers'].get() or name in self._registrations:
                raise RuntimeError('mcp-manager: server "'+name+'" is already configured or registered')
            self._registrations[name] = resolved
            self._entries_changed('registration of "'+name+'"')
            def remove():
                self._registrations.pop(name,None)
                if not self._stopped:return self._entries_changed('removal of "'+name+'"')
            return remove
        dispose = self.ctx.effect(own,label='mcpManager.register()')
        return lambda:dispose()

    @Remote(dict(mode='stream'))
    async def watch(self, signal):
        wake = asyncio.Event();wake.set()
        self._watchers.add(wake.set)
        async with combined_signals(signal,self._lifetime.signal) as ended:
            detach = ended.add_listener('abort',lambda _:wake.set())
            try:
                while not ended.aborted:
                    await wake.wait()
                    if ended.aborted:break
                    wake.clear()
                    yield self.list()
            finally:
                self._watchers.discard(wake.set)
                detach()

    @Remote
    async def restart(self, name):
        async def operation():
            if name not in self._entries():
                raise RuntimeError('mcp-manager: unknown server "'+name+'" — it is neither configured nor registered')
            await self._remount(name)
        await asyncio.shield(self._enqueue(operation))

    @Remote('probe')
    async def probeFromClient(self, name, signal):
        return await self.probe(name,dict(signal=signal))

    async def probe(self, name, options=None):
        if self._stopped:raise RuntimeError('mcp-manager: the manager is disposed')
        entry = self._entries().get(name)
        if entry is None:raise RuntimeError('mcp-manager: unknown server "'+name+'"')
        record = self._instances.get(name)
        if record is None:
            record = self._record(entry);self._instances[name] = record
        if record.retired or not _same_json(entry,record.entry):raise RuntimeError('mcp-manager: configuration for "'+name+'" is changing')
        if record.failure is not None:raise RuntimeError('mcp-manager: cleanup for "'+name+'" is incomplete; restart the Host')
        lifetime = AbortController();options = options or {}
        async def run():
            try:
                async with combined_signals(lifetime.signal,options.get('signal')) as signal:
                    result = await probe_server(self._owner_context,to_client_config(name,entry),dict(options,signal=signal))
                closure = {key:result[key] for key in ('closeConfirmed','cleanupError') if key in result}
                if not closure['closeConfirmed'] or 'cleanupError' in closure:
                    self._set_status(name,dict(state='failed',reason='cleanup',result=self._retain_failure(record,closure)))
                return result
            finally:record.probes.pop(lifetime,None)
        task = self._task(run());record.probes[lifetime] = task
        try:return await asyncio.shield(task)
        except asyncio.CancelledError:
            lifetime.abort()
            raise

    def _record(self, entry):
        return SimpleNamespace(entry=entry,probes={},handle=None,failure=None,retired=False,detach=None)

    def _retire(self, record):
        record.retired = True
        if record.detach is not None:record.detach()
        for lifetime in list(record.probes):lifetime.abort()

    def _stop(self):
        self._stopped = True
        self._lifetime.abort()
        for record in self._instances.values():self._retire(record)

    async def _dispose(self):
        self._stop()
        if self._tail is not None:await asyncio.shield(self._tail)
        for name,record in list(self._instances.items()):await self._unmount(name,record)

    def _entries_changed(self, what):
        entries = self._entries()
        for name,record in self._instances.items():
            if not _same_json(record.entry,entries.get(name)):self._retire(record)
        self._changed()
        return self._schedule(self._reconcile,what)

    def _changed(self):
        for notify in list(self._watchers):notify()

    def _enqueue(self, operation):
        previous = self._tail
        async def run():
            if previous is not None:await asyncio.shield(previous)
            if self._stopped:raise RuntimeError('mcp-manager: the manager is disposed')
            return await operation()
        task = self._task(run())
        async def settled():await asyncio.gather(asyncio.shield(task),return_exceptions=True)
        self._tail = self._task(settled())
        return task

    def _schedule(self, operation, what):
        task = self._enqueue(operation)
        async def contain():
            try:await asyncio.shield(task)
            except Exception as error:
                self.ctx.logger.error('mcp-manager: '+what+' failed');self.ctx.logger.error(error)
        return self._task(contain())

    async def _reconcile(self):
        entries = self._entries()
        for name,record in list(self._instances.items()):
            if not record.retired and name in entries and _same_json(entries[name],record.entry):continue
            await self._unmount(name,record)
        for name in list(self._statuses):
            if name not in entries and name not in self._instances:self._statuses.pop(name)
        self._changed()
        for name in _js_own_enumerable_keys(entries):
            entry,record = entries[name],self._instances.get(name)
            if record is not None and (record.retired or record.failure is not None):continue
            if not entry['enabled']:self._set_status(name,dict(state='disabled'));continue
            if record is not None and record.handle is not None:continue
            self._mount(name,entry,record)

    async def _remount(self, name):
        record = self._instances.get(name)
        if record is not None and not await self._unmount(name,record):raise RuntimeError('mcp-manager: cleanup for "'+name+'" is incomplete; restart the Host')
        entry = self._entries().get(name)
        if entry is None or self._stopped:return
        if not entry['enabled']:self._set_status(name,dict(state='disabled'));return
        self._mount(name,entry)

    def _mount(self, name, entry, existing=None):
        if self._stopped or not _same_json(self._entries().get(name),entry):return
        record = existing if existing is not None else self._record(entry)
        self._instances[name] = record
        self._set_status(name,dict(state='connecting',attempt=0))
        handle = record.handle = self._owner_context.plugin(CurrentMcpClient,to_client_config(name,entry))
        async def activated():
            try:
                await handle.await_settled()
                if record.retired:return
                cell = connection_status_in(handle)
                if cell is None:raise RuntimeError('mcp-manager: "'+name+'" activated without connection status')
                def publish(*_):
                    if record.retired:return
                    status = cell.current()
                    if status.get('reason')=='unclosed-generation' and status['state']=='failed':
                        had_failure = record.failure is not None
                        result = self._retain_failure(record,cell.closure())
                        self._set_status(name,dict(state='failed',reason='cleanup',result=result) if had_failure else status)
                    elif record.failure is None:self._set_status(name,status)
                record.detach = cell.onChange(publish)
                publish()
            except Exception as error:
                if record.retired or self._stopped:return
                async def failed(error=error):
                    if record.retired:return
                    if await self._unmount(name,record):self._set_status(name,dict(state='failed',reason='load',lastError=error_string(error)))
                self._schedule(failed,'failed startup of "'+name+'"')
        record.activation = self._task(activated())

    async def _unmount(self, name, record):
        self._retire(record)
        await asyncio.gather(*[asyncio.shield(task) for task in list(record.probes.values())],return_exceptions=True)
        if record.handle is not None:
            await record.handle.dispose()
            cell = connection_status_in(record.handle)
            if cell is not None and (not cell.closure()['closeConfirmed'] or 'cleanupError' in cell.closure()):self._retain_failure(record,cell.closure())
        if record.failure is not None:
            self._set_status(name,dict(state='failed',reason='cleanup',result=record.failure))
            return False
        self._instances.pop(name,None)
        return True

    def _retain_failure(self, record, result):
        previous = record.failure or {}
        record.failure = dict(result,**previous)
        record.failure['closeConfirmed'] = result['closeConfirmed'] and previous.get('closeConfirmed') is not False
        return record.failure

    def _set_status(self, name, status):
        if name not in self._entries() and name not in self._instances:return
        if name in self._statuses and _same_json(self._statuses[name],status):return
        self._statuses[name] = status
        if self._stopped:return
        self._changed()
        async def notify():
            try:await self.ctx.parallel('mcp-manager/status',name,status)
            except Exception as error:
                self.ctx.logger.error('mcp-manager: a mcp-manager/status listener failed for "'+name+'"');self.ctx.logger.error(error)
        self._task(notify())
