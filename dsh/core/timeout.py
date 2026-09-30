"""Signal-only timing and classification from the pinned dsh-timeout package."""

import asyncio
import math
import weakref
from decimal import Decimal

from dsh.core.abort import AbortSignal
from dsh.core.cancellation import subscribe_abort

MAX_TIMER_DELAY_MS = 2147483647


def _number_text(value):
    if not isinstance(value, float):
        return str(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if 1e-6 <= abs(value) < 1e21:
        fixed = format(Decimal(str(value)), "f")
        return fixed.rstrip("0").rstrip(".") if "." in fixed else fixed
    text = str(value)
    if "e" in text:
        mantissa, exponent = text.split("e")
        power = int(exponent)
        return "{}e{}{}".format(mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa,
                               "+" if power >= 0 else "", power)
    return str(int(value)) if value.is_integer() else text


class TimeoutReason(Exception):
    name = "TimeoutReason"

    def __init__(self, code, timeout_ms):
        self.code = code
        self.timeout_ms = timeout_ms
        self.timeoutMs = timeout_ms
        self.message = "{} after {}ms".format(code, _number_text(timeout_ms))
        super().__init__(self.message)


def _positive_finite(value):
    try:
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value > 0)
    except OverflowError:
        return False


def _assert_timer_delay(timeout_ms, name):
    if not _positive_finite(timeout_ms) or timeout_ms > MAX_TIMER_DELAY_MS:
        raise ValueError("{} must be a positive finite number no greater than {}".format(
            name, MAX_TIMER_DELAY_MS))


def clamp_timeout(requested, default, maximum, name="timeoutMs"):
    if requested is not None and not _positive_finite(requested):
        raise ValueError("{} must be a positive finite number".format(name))
    return min(default if requested is None else requested, maximum)


def timeout_of(carrier, code=None):
    reason = carrier.get("reason") if isinstance(carrier, dict) else getattr(carrier, "reason", None)
    if not isinstance(reason, TimeoutReason):
        return None
    return reason if code is None or reason.code == code else None


class _FusedTimeoutSignal(AbortSignal):
    __slots__ = ("__weakref__",)


def _fused_signal(upstream):
    signal = _FusedTimeoutSignal()
    if upstream is None:
        return signal
    target = weakref.ref(signal)
    detach_cell = []

    def relay(reason=None):
        current = target()
        if current is not None:
            current._abort(reason)
        if detach_cell:
            detach_cell[0]()

    detach = subscribe_abort(upstream, relay)
    detach_cell.append(detach)
    if signal.aborted:
        detach()
    # Disposing a timer still leaves a retained signal responsive to upstream.
    # The weak relay prevents that platform behavior from retaining its holder.
    weakref.finalize(signal, detach)
    return signal


class Deadline:
    def __init__(self, upstream, timeout_ms, code):
        self._timer = None
        if isinstance(timeout_ms, (int, float)) and not isinstance(timeout_ms, bool) and timeout_ms <= 0:
            self.signal = upstream if upstream is not None else AbortSignal()
            return
        _assert_timer_delay(timeout_ms, "deadline timeoutMs")
        self.signal = _fused_signal(upstream)
        self._timer = asyncio.get_running_loop().call_later(
            timeout_ms / 1000.0, self.signal._abort, TimeoutReason(code, timeout_ms))

    def dispose(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.dispose()


def deadline(upstream, timeout_ms, code):
    return Deadline(upstream, timeout_ms, code)


class IdleWatchdog:
    def __init__(self, upstream, timeout_ms, code):
        _assert_timer_delay(timeout_ms, "idleWatchdog timeoutMs")
        self.signal = _fused_signal(upstream)
        self._timeout_ms = timeout_ms
        self._code = code
        self._timer = None
        self._outstanding = False
        self._disposed = False

    def _clear(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _arm(self):
        self._clear()
        self._timer = asyncio.get_running_loop().call_later(
            self._timeout_ms / 1000.0, self.signal._abort,
            TimeoutReason(self._code, self._timeout_ms))

    async def next(self, iterator):
        if self._disposed:
            raise RuntimeError("idleWatchdog is disposed")
        if self._outstanding:
            raise RuntimeError("idleWatchdog next is already outstanding")
        self._outstanding = True
        self._arm()
        try:
            advance = getattr(iterator, "__anext__", None) or iterator.next
            return await advance()
        finally:
            self._clear()
            self._outstanding = False

    def pulse(self):
        if not self._disposed and self._outstanding:
            self._arm()

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._clear()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.dispose()


def idle_watchdog(upstream, timeout_ms, code):
    return IdleWatchdog(upstream, timeout_ms, code)
