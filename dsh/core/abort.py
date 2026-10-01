"""
The Python 3.8.10 / Windows 7 SP1 equivalent of the platform `AbortController`
primitive the reference host code takes its cancellation signals from.

The reference sources pass an `AbortSignal` through every cancellable host
entry point (`commands.execute`, `compaction.compactNow`, host RPC handlers).
Python 3.8 has no platform cancellation primitive, so the surface the ported
call sites observe is reproduced here:

* `signal.aborted` -- whether the signal settled as aborted;
* `signal.reason` -- the abort reason the caller supplied;
* `addEventListener` follows platform event delivery; `add_listener` is the
  Python subscription adapter that also observes an already-aborted signal;
* `signal.wait_aborted()` -- an awaitable that settles when the signal aborts.

Omitting an abort reason creates an AbortError; explicit None represents JS null.
Throwing a non-exception reason uses ThrownValueError without losing its value.

LEGAL_ADAPTATION: Python carries non-exception thrown values in ThrownValueError;
consumers with their own cancellation normalization keep that business contract.
"""

import asyncio
from types import SimpleNamespace
from typing import Any, Callable, List, Optional

from dsh.cordis.errors import ThrownValueError

__all__ = ["AbortSignal", "AbortController", "AbortError", "abort_reason_error", "NEVER_ABORTED"]

_OMITTED = object()


class AbortError(RuntimeError):
    """Native representation of the default platform DOMException."""
    name, code = 'AbortError', 20

    def __init__(self):
        self.message = 'This operation was aborted'
        super().__init__(self.message)


def abort_reason_error(signal, message='operation aborted'):
    """Preserve exception identity and explicit null/false/zero abort reasons."""
    reason = getattr(signal, 'reason', _OMITTED)
    if reason is _OMITTED:
        return RuntimeError(message)  # Historical Event/external signal adapter.
    return reason if isinstance(reason, BaseException) else ThrownValueError(reason, message)


class AbortSignal:
    """The observable half of the platform abort primitive."""

    __slots__ = ("aborted", "reason", "_listeners", "_waiters", "_dom_listeners")

    def __init__(self) -> None:
        self.aborted = False
        self.reason: Any = None
        self._listeners: List[Callable[..., Any]] = []
        self._waiters: List["asyncio.Future[None]"] = []
        self._dom_listeners = {}

    def add_listener(self, event: str, callback: Callable[..., Any]) -> Callable[[], None]:
        """
        Register one `abort` callback.

        @param event: the event name; only `abort` is meaningful.
        @param callback: the callback invoked at most once.
        @returns: a disposer removing exactly this registration.
        """
        if event != "abort" or not callable(callback):
            return lambda: None
        self._listeners.append(callback)
        if self.aborted:
            # Python subscriptions intentionally include settled state. Raw
            # platform addEventListener below does not replay an old event.
            self._fire(callback)

        def dispose() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return dispose

    def addEventListener(self, event, callback, options=None):
        """Raw platform notification: no replay; duplicate/capture/once ownership."""
        if event != 'abort' or not callable(callback):
            return
        capture = options if type(options) is bool else bool((options or {}).get('capture', False))
        key = (event, id(callback), capture)
        if key in self._dom_listeners:
            return
        once = bool((options or {}).get('once', False)) if isinstance(options, dict) else False
        def wrapped(_reason):
            if self._dom_listeners.get(key) is not wrapped:
                return
            if once:
                self.removeEventListener(event, callback, capture)
            callback(SimpleNamespace(type='abort', target=self, currentTarget=self))
        self._dom_listeners[key] = wrapped
        self._listeners.append(wrapped)

    def remove_listener(self, event: str, callback: Callable[..., Any]) -> None:
        if event == "abort" and callback in self._listeners:
            self._listeners.remove(callback)

    def removeEventListener(self, event, callback, options=None):
        capture = options if type(options) is bool else bool((options or {}).get('capture', False))
        wrapped = self._dom_listeners.pop((event, id(callback), capture), None)
        if wrapped is not None:
            self.remove_listener(event, wrapped)

    async def wait_aborted(self) -> None:
        """Settle once this signal aborts (immediately when already aborted)."""
        if self.aborted:
            return
        loop = asyncio.get_event_loop()
        future: "asyncio.Future[None]" = loop.create_future()
        self._waiters.append(future)

        def _settle(*_args: Any) -> None:
            if not future.done():
                future.set_result(None)

        # The Python subscription adapter observes an already settled signal.
        dispose = self.add_listener("abort", _settle)
        try:
            await future
        finally:
            dispose()
            if future in self._waiters:
                self._waiters.remove(future)

    # Python Host plugins historically received asyncio.Event signals.
    # Preserve their read/wait API while retaining a synchronous abort reason.
    wait = wait_aborted

    def is_set(self) -> bool:
        return self.aborted

    def throw_if_aborted(self) -> None:
        """Throw the actual first reason, using a carrier for non-exceptions."""
        if self.aborted:
            raise abort_reason_error(self)

    throwIfAborted = throw_if_aborted

    def _fire(self, callback: Callable[..., Any]) -> None:
        try:
            callback(self.reason)
        except Exception:
            # A registered listener's failure never interrupts the aborting
            # caller, matching the platform's event dispatch.
            pass

    @classmethod
    def abort(cls, reason=_OMITTED):
        signal = cls()
        signal._abort(reason)
        return signal

    def _abort(self, reason: Any = _OMITTED) -> None:
        if self.aborted:
            return
        self.aborted = True
        from dsh.core.session.json import UNDEFINED
        self.reason = AbortError() if reason is _OMITTED or reason is UNDEFINED else reason
        listeners = list(self._listeners)
        self._listeners = []
        for callback in listeners:
            self._fire(callback)
        waiters = list(self._waiters)
        self._waiters = []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)


class AbortController:
    """The mutating half of the platform abort primitive."""

    __slots__ = ("signal",)

    def __init__(self) -> None:
        self.signal = AbortSignal()

    def abort(self, reason: Any = _OMITTED) -> None:
        """Abort the owned signal once; later calls are no-ops."""
        self.signal._abort(reason)


#: Shared never-aborting signal for call sites the host invokes without a
#: caller-owned cancellation source.
NEVER_ABORTED = AbortSignal()
