"""Credential-scoped model listings with shared loads and automatic refresh."""
import asyncio
import hashlib
import math

from dsh.cordis.awaiting import await_callback_result
from dsh.core.abort import AbortController, abort_reason_error
from dsh.core.cancellation import subscribe_abort
from dsh.core.timeout import MAX_TIMER_DELAY_MS, deadline
from dsh.typert.stores import field

LISTING_TIMEOUT = 'MODEL_LISTING_TIMEOUT'
DEFAULT_MODELS_TIMEOUT_MS = 5000
DEFAULT_MODELS_MAX_AGE_MS = 600000


def resolveListingTiming(options, owner):
    timeout = options.get('modelsTimeoutMs', DEFAULT_MODELS_TIMEOUT_MS)
    age = options.get('modelsMaxAgeMs', DEFAULT_MODELS_MAX_AGE_MS)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0 or timeout > MAX_TIMER_DELAY_MS:
        raise ValueError(owner+': modelsTimeoutMs must be a positive finite number no greater than '+str(MAX_TIMER_DELAY_MS))
    if type(age) not in (int, float) or not math.isfinite(age) or age < 0 or age > 9007199254740991 or int(age) != age:
        raise ValueError(owner+': modelsMaxAgeMs must be a non-negative safe integer')
    return dict(timeoutMs=timeout, maxAgeMs=age)


def _deep_equal(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_deep_equal(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_deep_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def _error_text(error):
    # JS Error String() differs from the tool-facing Error.message projection.
    name = getattr(error, 'name', 'Error')
    message = getattr(error, 'message', str(error))
    return name+': '+message if message else name


async def abandonable(task, signal):
    if signal is None:
        await asyncio.shield(task)
        return
    abandoned = asyncio.get_running_loop().create_future()
    def abort(*_):
        if not abandoned.done():
            abandoned.set_result(None)
    detach = subscribe_abort(signal, abort)
    try:
        done, _ = await asyncio.wait([task, abandoned], return_when=asyncio.FIRST_COMPLETED)
        if abandoned in done:
            raise abort_reason_error(signal)
        await asyncio.shield(task)
    finally:
        detach()
        abandoned.cancel()


class ModelListingCache:
    def __init__(self, dependencies):
        self.dependencies = dependencies
        self.scope = self.listing = self.settledAt = self.inflight = self.request = self.timer = None
        self.generation, self.failing, self.closed = 0, False, False
        self.pending = set()

    def current(self):
        # None represents an absent optional listing in this internal service;
        # wire catalog projection belongs to the provider, not this cache.
        return dict(authenticated=self.scope is not None, listing=self.listing)

    async def view(self, settings, signal=None):
        credential = await await_callback_result(field(self.dependencies, 'credential')(settings['url']))
        if signal is not None:
            signal.throwIfAborted()
        if self.closed:
            return self.current()
        scope = None if credential is None else settings['url']+'\n'+hashlib.sha256(credential.encode('utf-8')).hexdigest()
        if scope != self.scope:
            self.rescope(scope)
        if credential is not None:
            if self.settledAt is None:
                await abandonable(self.start(settings, credential), signal)
            elif field(self.dependencies, 'now')()-self.settledAt >= settings['maxAgeMs']:
                self.start(settings, credential)
        return self.current()

    def invalidate(self):
        self.rescope(self.scope)

    async def dispose(self):
        self.closed = True
        self.generation += 1
        self.clear_timer()
        if self.request is not None:
            self.request.abort()
        await asyncio.gather(*(asyncio.shield(task) for task in list(self.pending)), return_exceptions=True)

    def clear_timer(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None

    def rescope(self, scope):
        self.clear_timer()
        if self.request is not None:
            self.request.abort()
        self.scope = scope
        self.listing = self.settledAt = self.inflight = None
        self.failing = False
        self.generation += 1

    def start(self, settings, credential):
        if self.inflight is not None:
            return self.inflight
        self.clear_timer()
        self.generation += 1
        generation = self.generation
        request = self.request = AbortController()
        limit = deadline(request.signal, settings['timeoutMs'], LISTING_TIMEOUT)
        # Invoke load at admission, before returning a shared completion. A
        # transport may return a Future or an ordinary coroutine in Python.
        loading = field(self.dependencies, 'load')(settings['url'], credential, limit.signal)
        async def run():
            try:
                try:
                    listing = await await_callback_result(loading)
                except Exception as error:
                    if generation != self.generation:
                        return
                    if not self.failing:
                        fallback = 'using the bundled catalog' if self.listing is None else 'keeping the previous catalog'
                        field(self.dependencies, 'warn')('model listing from '+settings['url']+' failed ('+_error_text(error)+'); '+fallback)
                    self.settledAt = field(self.dependencies, 'now')()
                    self.failing = True
                else:
                    if generation != self.generation:
                        return
                    changed = not _deep_equal(self.listing, listing)
                    self.listing = listing
                    self.settledAt = field(self.dependencies, 'now')()
                    self.failing = False
                    field(self.dependencies, 'info')('model listing from '+settings['url']+' loaded '+str(len(listing['entries']))
                        +' model(s), skipped '+str(listing['skipped'])+' row(s)')
                    if changed:
                        self.notify()
            finally:
                limit.dispose()
                self.pending.discard(task)
                if self.inflight is task:
                    self.inflight = None
                if generation == self.generation:
                    self.schedule(settings)
        task = asyncio.create_task(run())
        self.inflight = task
        self.pending.add(task)
        return task

    def notify(self):
        try:
            field(self.dependencies, 'changed')()
        except Exception as error:
            field(self.dependencies, 'warn')('model listing change notification failed ('+_error_text(error)+'); reload the model catalog')

    def schedule(self, settings):
        self.clear_timer()
        if self.closed or settings['maxAgeMs'] == 0:
            return
        age = 0 if self.settledAt is None else field(self.dependencies, 'now')()-self.settledAt
        delay = min(MAX_TIMER_DELAY_MS, max(1, settings['maxAgeMs']-age))
        def refresh():
            task = asyncio.create_task(self.refresh(settings))
            self.pending.add(task)
            task.add_done_callback(self.pending.discard)
        self.timer = asyncio.get_running_loop().call_later(delay/1000, refresh)

    async def refresh(self, previous):
        settings = previous
        try:
            next_settings = field(self.dependencies, 'settings')()
            if next_settings is None:
                self.invalidate()
                self.notify()
                return
            settings = next_settings
            authenticated = self.current()['authenticated']
            await self.view(settings)
            if self.closed:
                return
            if authenticated and not self.current()['authenticated']:
                self.notify()
        except Exception as error:
            if self.closed:
                return
            if not self.failing:
                field(self.dependencies, 'warn')('model listing refresh failed ('+_error_text(error)
                    +'); keeping the previous catalog; check listing configuration and credentials')
            self.failing = True
            self.settledAt = field(self.dependencies, 'now')()
        if self.inflight is None:
            self.schedule(settings)
