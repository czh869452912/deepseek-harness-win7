"""PTC call ownership, reset barriers and complete nested-call settlement."""
import asyncio
from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.core.abort import AbortController
from dsh.core.tools import CodeRunFailedError, _error_message


class PtcCalls:
    def __init__(self, ctx):
        self.calls = {}
        self.resets = {}
        self.disposed = False
        ctx.on('session/event', self._session_event, global_listener=True)
        ctx.effect(lambda: self._dispose, label='PTC calls')

    def _session_event(self, session, event):
        if event['type'] != 'sandbox/mode':
            return
        for call in list(self.calls.get(session.id, [])):
            if call['mode'] is not None and call['mode'] != event['data']['mode']:
                call['controller'].abort(RuntimeError('sandbox mode changed'))

    async def _dispose(self):
        self.disposed = True
        calls = [call for group in self.calls.values() for call in group]
        for call in calls:
            call['controller'].abort(RuntimeError('PTC tool executor disposed'))
        await asyncio.gather(*[asyncio.shield(item['done']) for item in calls + list(self.resets.values())],
                             return_exceptions=True)

    def run(self, session_id, signal, mode, run):
        return start_coroutine(self._run(session_id, signal, mode, run))

    async def _run(self, session_id, signal, mode, run):
        while True:
            reset = self.resets.get(session_id)
            if reset is not None:
                try:
                    await asyncio.shield(reset['done'])
                except Exception as error:
                    raise CodeRunFailedError('Program environment unavailable: %s. Ask the host to reset it before running more code.' % _error_message(error))
                continue
            pending = [call for call in self.calls.get(session_id, []) if call['signal'].aborted]
            if not pending:
                break
            await asyncio.gather(*[asyncio.shield(call['done']) for call in pending])
        signal.throwIfAborted()
        if self.disposed:
            raise RuntimeError('PTC tool executor disposed')
        controller, combined = AbortController(), AbortController()
        relays = [signal.add_listener('abort', lambda reason: combined.abort(reason)),
                  controller.signal.add_listener('abort', lambda reason: combined.abort(reason))]
        try:
            current_mode = mode()
        except BaseException:
            for remove in relays:
                remove()
            raise
        call = dict(mode=current_mode, controller=controller, signal=combined.signal,
                    done=asyncio.get_running_loop().create_future())
        group = self.calls.setdefault(session_id, [])
        group.append(call)
        try:
            return await await_callback_result(run(combined.signal))
        finally:
            for remove in relays:
                remove()
            group.remove(call)
            if not group:
                self.calls.pop(session_id, None)
            call['done'].set_result(None)

    def reset(self, session_id, release, notify=None):
        if self.disposed:
            future = asyncio.get_running_loop().create_future()
            future.set_exception(RuntimeError('PTC tool executor disposed'))
            return future
        previous = self.resets.get(session_id)
        if previous is not None and not previous['settled']:
            return previous['done']
        reset = dict(done=asyncio.get_running_loop().create_future(), settled=False)
        self.resets[session_id] = reset
        calls = list(self.calls.get(session_id, []))
        for call in calls:
            call['controller'].abort(RuntimeError('PTC environment reset'))
        # Match the queued release callback; reset aborts active calls synchronously.
        reset['task'] = asyncio.create_task(self._finish_reset(session_id, reset, calls, release, notify))
        return reset['done']

    async def _finish_reset(self, session_id, reset, calls, release, notify):
        async def release_environment():
            return await await_callback_result(release())
        results = await asyncio.gather(release_environment(),
            *[asyncio.shield(call['done']) for call in calls], return_exceptions=True)
        failure = next((value for value in results if isinstance(value, BaseException)), None)
        if failure is None and notify is not None:
            try:
                notify()
            except BaseException as error:
                failure = error
        reset['settled'] = True
        if failure is None:
            self.resets.pop(session_id, None)
            reset['done'].set_result(None)
        else:
            reset['done'].set_exception(failure)
