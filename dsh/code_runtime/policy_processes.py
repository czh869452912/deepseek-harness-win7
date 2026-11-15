"""Own admitted PTC processes across committed Session policy changes."""
import asyncio

from dsh.cordis.awaiting import await_callback_result, start_coroutine


class PolicyProcesses:
    def __init__(self, ctx):
        self.ctx = ctx
        self.processes = {}
        self.next_id = 0
        ctx.on('session/event', self._session_event, global_listener=True)
        ctx.effect(lambda: self._dispose, label='PTC policy cleanup')

    def _session_event(self, session, event):
        if event['type'] != 'sandbox/mode':
            return
        for process in list(self.processes.values()):
            if process['sessionId'] != session.id or process['mode'] == event['data']['mode']:
                continue
            process['invalidated'] = True
            self._release(process).add_done_callback(self._warn)

    def _warn(self, future):
        if future.cancelled():
            return
        error = future.exception()
        if error is not None:
            self.ctx.logger.warn(error)

    def register(self, policy, release):
        if 'sessionId' not in policy:
            return lambda: None
        sessions = self.ctx.get('sessions')
        session = sessions.get(policy['sessionId']) if sessions is not None else None
        mode = (policy['mode'] if session is None else
                self.ctx.get('sandboxPolicy').resolve(dict(session=session))['mode'])
        key = self.next_id
        self.next_id += 1
        process = dict(key=key, sessionId=policy['sessionId'], mode=mode,
                       release=release, invalidated=False, cleanup=None)
        self.processes[key] = process
        return lambda: self.processes.pop(key, None)

    async def wait(self, session_id=None):
        await self._settle([process for process in self.processes.values()
                            if process['sessionId'] == session_id and process['invalidated']])

    def _release(self, process):
        if process['cleanup'] is None:
            process['cleanup'] = start_coroutine(self._finish_release(process))
        return process['cleanup']

    async def _finish_release(self, process):
        try:
            await await_callback_result(process['release']())
        except BaseException:
            # Also make a synchronous callback failure retryable after assignment.
            await asyncio.sleep(0)
            process['cleanup'] = None
            raise
        self.processes.pop(process['key'], None)

    async def _settle(self, processes):
        results = await asyncio.gather(*[asyncio.shield(self._release(process))
                                        for process in processes], return_exceptions=True)
        failure = next((result for result in results if isinstance(result, BaseException)), None)
        if failure is not None:
            raise failure

    async def _dispose(self):
        await self._settle(list(self.processes.values()))
