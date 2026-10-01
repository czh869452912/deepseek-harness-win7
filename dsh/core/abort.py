"""
The Python 3.8.10 / Windows 7 SP1 equivalent of the platform `AbortController`
primitive the reference host code takes its cancellation signals from.

The reference sources pass an `AbortSignal` through every cancellable host
entry point (`commands.execute`, `compaction.compactNow`, host RPC handlers).
Python 3.8 has no platform cancellation primitive, so the surface the ported
call sites observe is reproduced here:

* `signal.aborted` -- whether the signal settled as aborted;
* `signal.reason` -- the abort reason the caller supplied;
* `signal.add_listener("abort", callback)` / `remove_listener` -- notification,
  including the reference's immediate-notification contract for a listener added
  after the abort;
* `signal.wait_aborted()` -- an awaitable that settles when the signal aborts.

`AbortSignal.abort(reason)` mirrors `AbortController.abort(reason)`; the
no-reason form leaves `reason` unset so a consumer's `abortError()` normalization
produces its own default failure text, exactly like the reference
`CommandRuntime.abortError`.

LEGAL_ADAPTATION: the exception type raised by an aborted operation is defined by
its own consumer (Python has no single platform `Error`); this module only
carries the signal state.
"""

import asyncio
from typing import Any, Callable, List, Optional

__all__ = ["AbortSignal", "AbortController", "NEVER_ABORTED"]


class AbortSignal:
    """The observable half of the platform abort primitive."""

    __slots__ = ("aborted", "reason", "_listeners", "_waiters")

    def __init__(self) -> None:
        self.aborted = False
        self.reason: Any = None
        self._listeners: List[Callable[..., Any]] = []
        self._waiters: List["asyncio.Future[None]"] = []

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
            # The platform fires `abort` synchronously for a listener added
            # after the signal aborted.
            self._fire(callback)

        def dispose() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return dispose

    #: Reference `AbortSignal` spelling.
    addEventListener = add_listener

    def remove_listener(self, event: str, callback: Callable[..., Any]) -> None:
        if event == "abort" and callback in self._listeners:
            self._listeners.remove(callback)

    removeEventListener = remove_listener

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

        # A listener added after the abort fires synchronously, so the check
        # above and this registration cannot together miss an abort.
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
        """Raise `KeyboardInterrupt`-free cancellation: a plain `RuntimeError`."""
        if self.aborted:
            raise RuntimeError("operation aborted")

    throwIfAborted = throw_if_aborted

    def _fire(self, callback: Callable[..., Any]) -> None:
        try:
            callback(self.reason)
        except Exception:
            # A registered listener's failure never interrupts the aborting
            # caller, matching the platform's event dispatch.
            pass

    def _abort(self, reason: Any = None) -> None:
        if self.aborted:
            return
        self.aborted = True
        self.reason = reason
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

    def abort(self, reason: Any = None) -> None:
        """Abort the owned signal once; later calls are no-ops."""
        self.signal._abort(reason)


#: Shared never-aborting signal for call sites the host invokes without a
#: caller-owned cancellation source.
NEVER_ABORTED = AbortSignal()
