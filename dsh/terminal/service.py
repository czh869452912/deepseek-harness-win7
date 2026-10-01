"""Exact-Agent terminal ownership, unpublished setup, and cleanup fences."""
import asyncio
import weakref

from dsh.cordis.events import AggregateError
from dsh.cordis.service import Service
from dsh.core.abort import AbortController, abort_reason_error
from dsh.core.cancellation import aborted


class TerminalError(RuntimeError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class TerminalBackendCleanupError(AggregateError):
    def __init__(self, spawn_error, cleanup_error):
        self.spawnError, self.cleanupError = spawn_error, cleanup_error
        super().__init__([spawn_error, cleanup_error])


def check_signal(signal):
    if aborted(signal):
        raise abort_reason_error(signal)


class TerminalSessionService(Service):
    def __init__(self, ctx, config=None):
        self.backends, self.sessions, self.names, self.pending, self.cleanups = {}, {}, {}, {}, {}
        self.disposed_owners = weakref.WeakSet()
        self.next_id, self.disposing = 0, False
        super().__init__(ctx, 'terminals')
        ctx.effect(lambda: self.dispose_all)

    def apply(self, ctx=None, config=None):
        pass

    def registerBackend(self, backend):
        if not isinstance(backend.type, str) or not backend.type:
            raise ValueError('pty backend type must be non-empty')
        if backend.type in self.backends:
            raise TerminalError('PTY backend already registered: ' + backend.type, 'DUPLICATE_BACKEND')
        self.backends[backend.type] = backend
        def dispose():
            if self.backends.get(backend.type) is backend:
                del self.backends[backend.type]
        return self.ctx.effect(lambda: dispose)

    def listBackends(self):
        return list(self.backends)

    def is_live(self, owner):
        registry = self.ctx.get('agents')
        return owner not in self.disposed_owners and registry is not None and registry.get(owner.id) is owner

    def ensure_cleanup(self, owner):
        if not self.is_live(owner):
            raise TerminalError('agent is not the registered PTY owner', 'OWNER_NOT_LIVE')
        if owner in self.cleanups:
            return
        async def cleanup():
            self.disposed_owners.add(owner)
            self.cleanups.pop(owner, None)
            try:
                await self.abort_and_close(owner, TerminalError('PTY owner is no longer live', 'OWNER_NOT_LIVE'), 'PTY owner disposed')
            finally:
                self.names.pop(owner, None)
        self.cleanups[owner] = owner.ctx.effect(lambda: cleanup)

    async def spawn(self, owner, request, signal=None):
        if self.disposing:
            raise TerminalError('PTY service is disposing', 'SERVICE_DISPOSING')
        check_signal(signal)
        self.ensure_cleanup(owner)
        backend = self.backends.get(request['type'])
        if backend is None:
            raise TerminalError('no PTY backend registered: ' + request['type'], 'NO_BACKEND')
        name = request.get('name')
        if name is not None:
            if not isinstance(name, str) or not name:
                raise ValueError('PTY session name must be non-empty')
            reserved = self.names.setdefault(owner, set())
            if name in reserved or any(row['owner'] is owner and row.get('name') == name for row in self.sessions.values()):
                raise TerminalError('PTY session name already exists: ' + name, 'DUPLICATE_NAME')
            reserved.add(name)
        controller = AbortController()
        pending = dict(controller=controller, settled=asyncio.get_running_loop().create_future(), failure=None)
        self.pending.setdefault(owner, []).append(pending)
        detach = None
        monitor = None
        if signal is not None:
            if hasattr(signal, 'add_listener'):
                detach = signal.add_listener('abort', lambda *_: controller.abort(getattr(signal, 'reason', None)))
            else:
                async def watch():
                    while not controller.signal.aborted:
                        if aborted(signal):
                            controller.abort(getattr(signal, 'reason', None))
                            return
                        await asyncio.sleep(.01)
                monitor = asyncio.create_task(watch())
        self.next_id += 1
        identity = 'pty-{}'.format(self.next_id)
        session = None
        try:
            session = await backend.spawn(dict(request, sessionId=identity, owner=owner, signal=controller.signal))
            check_signal(signal)
            if self.disposing:
                raise TerminalError('PTY service is disposing', 'SERVICE_DISPOSING')
            if not self.is_live(owner):
                raise TerminalError('PTY owner is no longer live', 'OWNER_NOT_LIVE')
            row = dict(id=identity, owner=owner, type=request['type'], session=session, active=None, closing=None)
            if name is not None:
                row['name'] = name
            self.sessions[identity] = row
            return dict(self.snapshot(row), motd=session.motd)
        except BaseException as error:
            if isinstance(error, TerminalBackendCleanupError):
                pending['failure'] = error.cleanupError
            rollback = None
            if session is not None and identity not in self.sessions:
                try:
                    await session.close('PTY spawn rolled back')
                except Exception as cleanup_error:
                    rollback = pending['failure'] = cleanup_error
            failure = error
            try:
                check_signal(signal)
                check_signal(controller.signal)
            except Exception as cancellation:
                failure = cancellation
            if rollback is not None and not aborted(signal):
                raise AggregateError([failure, rollback])
            raise failure
        finally:
            if detach is not None:
                detach()
            if monitor is not None:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            if pending['failure'] is None:
                self.remove_pending(owner, pending)
            pending['settled'].set_result(None)
            if name is not None:
                reserved.discard(name)
                if not reserved:
                    self.names.pop(owner, None)

    def remove_pending(self, owner, pending):
        owned = self.pending.get(owner, [])
        if pending in owned:
            owned.remove(pending)
        if not owned:
            self.pending.pop(owner, None)

    def hasOwnerActivity(self, owner):
        return bool(self.pending.get(owner)) or any(row['owner'] is owner for row in self.sessions.values())

    def expect_owned(self, owner, identity):
        row = self.sessions.get(identity)
        if row is None:
            raise TerminalError('unknown PTY session ' + identity, 'NO_SESSION')
        if row['owner'] is not owner:
            raise TerminalError('PTY session belongs to another agent', 'FOREIGN_SESSION')
        return row

    def startSend(self, owner, identity, request):
        row = self.expect_owned(owner, identity)
        if row['closing'] is not None:
            raise RuntimeError('PTY session is closing')
        if row['active'] is not None:
            raise TerminalError('PTY session already has an active send', 'SEND_ACTIVE')
        operation = row['session'].startSend(request)
        row['active'] = operation
        def settled(done):
            if row['active'] is operation:
                row['active'] = None
            if not done.cancelled():
                done.exception()
        operation.done.add_done_callback(settled)
        return operation

    def read(self, owner, identity, request=None):
        return self.expect_owned(owner, identity)['session'].read(request or {})

    async def signal(self, owner, identity, signal):
        return await self.expect_owned(owner, identity)['session'].signal(signal)

    async def close_record(self, row, reason):
        existing = row['closing']
        if existing is not None:
            await asyncio.shield(existing)
            return False
        closing = asyncio.create_task(row['session'].close(reason))
        row['closing'] = closing
        try:
            await asyncio.shield(closing)
            self.sessions.pop(row['id'], None)
            return True
        except asyncio.CancelledError:
            # Keep the cleanup fence when a caller abandons its wait.
            await closing
            self.sessions.pop(row['id'], None)
            raise
        except Exception:
            if row['closing'] is closing:
                row['closing'] = None
            raise

    async def kill(self, owner, identity, reason='model request'):
        return await self.close_record(self.expect_owned(owner, identity), reason)

    def snapshot(self, row):
        result = dict(sessionId=row['id'], type=row['type'], status=row['session'].status())
        if 'name' in row:
            result['name'] = row['name']
        pid = getattr(row['session'], 'pid', None)
        if pid is not None:
            result['pid'] = pid
        return result

    def list(self, owner):
        return [self.snapshot(row) for row in self.sessions.values() if row['owner'] is owner]

    async def abort_and_close(self, owner, error, reason):
        pending = [(key, item) for key, owned in list(self.pending.items()) if owner is None or key is owner for item in list(owned)]
        for _, item in pending:
            item['controller'].abort(error)
        await asyncio.gather(*(item['settled'] for _, item in pending))
        failures = [item['failure'] for _, item in pending if item['failure'] is not None]
        for key, item in pending:
            self.remove_pending(key, item)
        rows = [row for row in self.sessions.values() if owner is None or row['owner'] is owner]
        results = await asyncio.gather(*(self.close_record(row, reason) for row in rows), return_exceptions=True)
        failures.extend(result for result in results if isinstance(result, Exception))
        if failures:
            raise AggregateError(failures)

    async def dispose_all(self):
        self.disposing = True
        try:
            await self.abort_and_close(None, TerminalError('PTY service is disposing', 'SERVICE_DISPOSING'), 'PTY service disposed')
        finally:
            self.backends.clear()
            self.names.clear()
            self.pending.clear()
            cleanups, self.cleanups = list(self.cleanups.values()), {}
            for cleanup in cleanups:
                result = cleanup()
                if result is not None:
                    await result
