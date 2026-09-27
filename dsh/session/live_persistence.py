"""Shared live write ownership for JSONL and SQLite persistence.

Cold preparation reservations remain separate from this live write lifecycle.
"""
import asyncio
import copy
import inspect
from dsh.session.write_behind import SessionWriteBehind


class LivePersistence:
    def __init__(self, backend, ctx, max_delay_ms=200):
        if type(max_delay_ms) is not int or not 1 <= max_delay_ms <= 2147483647:
            raise TypeError("writeBatchMaxDelayMs must be an integer between 1 and 2147483647")
        self.backend = backend
        self.ctx = ctx
        self.max_delay_ms = max_delay_ms
        self.live = {}
        self.owners = {}
        self.retirements = {}
        self.locks = {}
        self.closed = False

    def _warn(self, session, error):
        self.ctx.logger.warn('session "{}": persistence failed (buffer retained): {}'.format(session.id, error))

    def _init(self, session):
        if session in self.live:
            return self.live[session]
        if self.closed:
            raise RuntimeError('persistence write path is closed')
        if self.backend._prepared is not None:
            self.backend._prepared.attach(session)
        seed = copy.deepcopy(list(session.events))
        lock = self.locks.setdefault(session.id, asyncio.Lock())
        prior = self.retirements.get(session.id)
        state = {'cursor': 0, 'materialized': False}
        async def initialize():
            if prior is not None:
                await asyncio.shield(prior)
            async with lock:
                owner = self.owners.get(session.id)
                if owner is not None and owner is not session:
                    raise ValueError('session id collision: ' + session.id)
                tracked = self.backend.storage().states.get(session.id)
                if tracked is not None and tracked['meta'].cwd != session.header.cwd:
                    raise ValueError('persisted session cwd collision: ' + session.id)
                try:
                    stored = await self.backend.read_stored(session.id)
                except FileNotFoundError:
                    stored = None
                if stored is not None:
                    if stored.meta.cwd != session.header.cwd or seed[:len(stored.events)] != stored.events:
                        raise ValueError('persisted session id collision: ' + session.id)
                    await self.backend.repair_tail(session.id)
                    state['cursor'] = len(stored.events)
                    state['materialized'] = True
                    self.backend.storage().adopted(stored)
                elif session.id not in self.backend.storage().states:
                    await self.backend.create(session.header)
                self.owners[session.id] = session
                if seed[state['cursor']:]:
                    await persist(seed[state['cursor']:])
        async def persist(events):
            if not events:
                return
            if [e['seq'] for e in events] != list(range(state['cursor'], state['cursor'] + len(events))):
                raise ValueError('non-contiguous live session write: ' + session.id)
            await self.backend.append(session.id, events)
            state['materialized'] = True
            state['cursor'] += len(events)
        async def write(batch):
            await asyncio.shield(state['init'])
            async with lock:
                await persist([e for e in batch if e['seq'] >= state['cursor']])
        state['writes'] = SessionWriteBehind(write, lambda e: self._warn(session, e), self.max_delay_ms)
        self.live[session] = state
        state['init'] = asyncio.ensure_future(initialize())
        # Initialization is observed again by explicit flush/disposal.
        state['init'].add_done_callback(lambda job: None if job.cancelled() else job.exception())
        return state

    def on_created(self, session):
        self._init(session)

    def on_event(self, session, event):
        self._init(session)['writes'].enqueue(event)

    async def flush(self, session=None):
        if session is None:
            # Capture exact state before scheduling coroutines: retirement may
            # remove the Session before Python starts a child coroutine.
            results = await asyncio.gather(*(self._flush_state(state) for state in list(self.live.values())), return_exceptions=True)
            errors = [r for r in results if isinstance(r, BaseException)]
            if errors:
                error = RuntimeError('persistence drain failed: ' + '; '.join(str(e) for e in errors))
                error.errors = errors
                raise error
            return
        await self._flush_state(self._init(session))

    async def _flush_state(self, state):
        writes = state['writes']
        writes.cancel_automatic_wait()
        try:
            await asyncio.shield(state['init'])
        except BaseException:
            writes.cancel_automatic_wait()
            raise
        await asyncio.shield(writes.flush())

    def retire(self, session):
        if session not in self.live:
            return
        async def drain():
            await self.flush(session)
            self.live.pop(session, None)
            if self.owners.get(session.id) is session:
                self.owners.pop(session.id, None)
                self.backend.storage().states.pop(session.id, None)
        job = asyncio.ensure_future(drain())
        self.retirements[session.id] = job
        def settled(task):
            if self.retirements.get(session.id) is task:
                self.retirements.pop(session.id, None)
            if not task.cancelled() and task.exception() is not None:
                self._warn(session, task.exception())
        job.add_done_callback(settled)

    async def dispose(self):
        self.closed = True
        failure = None
        try:
            await self.flush()
            if self.retirements:
                await asyncio.gather(*list(self.retirements.values()), return_exceptions=True)
        except BaseException as error:
            failure = error
            raise
        finally:
            for state in self.live.values():
                state['writes'].cancel_automatic_wait()
            if self.backend._prepared is not None:
                await self.backend._prepared.drain()
            close = getattr(self.backend, 'close', None)
            if close is not None:
                try:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
                except BaseException:
                    if failure is None:
                        raise

    def mount(self):
        # Cordis reverses effects: close event admission before final drain.
        self.ctx.disposable(self.dispose, label='session persistence write path')
        self.ctx.on('session/created', self.on_created)
        self.ctx.on('session/event', self.on_event)
        self.ctx.on('session/flush', self.flush)
        self.ctx.on('session/disposed', self.retire)
        sessions = self.ctx.get('sessions')
        if sessions is not None:
            for session in sessions.list():
                self._init(session)
