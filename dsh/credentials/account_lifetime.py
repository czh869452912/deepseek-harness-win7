"""Owned request deadline fused with one account credential lifetime."""
import asyncio

from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort


class AccountTimeoutError(Exception):
    name = 'TimeoutError'

    def __init__(self):
        super().__init__('The operation was aborted due to timeout')


class AccountRequestLifetime:
    def __init__(self, upstream, timeout_ms):
        self.controller = AbortController()
        self.dispose = subscribe_abort(upstream, lambda *_: self.controller.abort(upstream.reason))
        self.timer = asyncio.get_running_loop().call_later(timeout_ms/1000, self.controller.abort, AccountTimeoutError())
        self.signal = self.controller.signal

    def __enter__(self):
        return self.signal

    def __exit__(self, *_):
        self.timer.cancel(); self.dispose()
