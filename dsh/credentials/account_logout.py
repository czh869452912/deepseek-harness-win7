"""Bounded memory-only revocation, owned by the account provider lifetime."""
import asyncio

from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.credentials.account_protocol import logoutAccount


class _TimeoutError(Exception):
    name = 'TimeoutError'

    def __init__(self):
        super().__init__('The operation was aborted due to timeout')


async def _delay(milliseconds, signal):
    future = asyncio.get_running_loop().create_future()
    def settle(error=None):
        if future.done():
            return
        if error is None:
            future.set_result(None)
        else:
            future.set_exception(RuntimeError('account logout cancelled'))
    dispose = subscribe_abort(signal, lambda *_: settle(True))
    timer = asyncio.get_running_loop().call_later(milliseconds/1000, settle)
    try:
        await future
    finally:
        timer.cancel(); dispose()


async def revokeAccount(origin, token, policy, signal, headers):
    for attempt in range(policy['maxRetries']+1):
        if aborted(signal):
            return
        if attempt:
            try:
                await _delay(policy['delayMs']*2**(attempt-1), signal)
            except Exception:
                return
        controller = AbortController()
        dispose = subscribe_abort(signal, lambda *_: controller.abort(signal.reason))
        timer = asyncio.get_running_loop().call_later(policy['requestTimeoutMs']/1000, controller.abort, _TimeoutError())
        try:
            await logoutAccount(origin, token, controller.signal, headers)
            return
        except Exception:
            pass
        finally:
            timer.cancel(); dispose()
