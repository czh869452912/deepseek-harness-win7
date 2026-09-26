"""
DeepSeek LLM API extension registry (`ctx.deepseekLlmApiExtensions`).

1:1 with reference/packages/llm/deepseek-llm-api-extensions/src/index.ts and
`src/types.ts`: plugins own independent top-level request fields while the
official adapter performs one preparation and acceptance transaction.

The reference `DeepSeekLlmApiExtensionRegistry` is a Cordis `Service` that
default-exports itself, so it mounts as the installation-owned row
`@deepseek-ai/dsh-deepseek-llm-api-extensions`.

LEGAL_ADAPTATION (Python 3.8.10): the platform `AggregateError` raised when more
than one acceptance callback fails has no Python 3.8 equivalent
(`ExceptionGroup` is 3.11+), so `ExtensionAcceptanceError` carries the same
`errors` attribute, message, and rejection contract.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import copy
from typing import Any, Callable, Dict, List, Optional, Tuple

from dsh.core.session.json import deep_freeze
from dsh.cordis.service import Service

__all__ = [
    "ExtensionAcceptanceError",
    "PreparedDeepSeekLlmApiExtensions",
    "DeepSeekLlmApiExtensionRegistry",
    "accept_all",
    "abortable",
    "freeze_json",
]

#: Diagnostic prefix every failure in this package carries.
_PREFIX = "deepseek-llm-api-extensions"

#: Message the platform's `AggregateError` is constructed with.
AGGREGATE_MESSAGE = "DeepSeek LLM API extension acceptance failed"


class ExtensionAcceptanceError(Exception):
    """
    Several acceptance callbacks failed.

    The platform raises `AggregateError` (an `Error` whose `errors` array holds
    every rejection reason); this carries the same `errors` sequence and
    message.
    """

    def __init__(self, errors: List[BaseException]) -> None:
        super().__init__(AGGREGATE_MESSAGE)
        self.name = "ExtensionAcceptanceError"
        self.errors = list(errors)


def freeze_json(value: Any) -> Any:
    """
    Recursively freeze a fresh structured clone.

    The reference `freezeJson` walks the value in place; `deep_freeze` is this
    port's established `Object.freeze` equivalent for JSON trees, so cloning
    first and freezing second mirrors `freezeJson(structuredClone(value))`.

    @param value: a cloned lossless-JSON value.
    @returns: the frozen value; containers become their frozen equivalents.
    """
    return deep_freeze(value)


def _detached(value: Any) -> Any:
    """`structuredClone(value)`: a detached copy with no caller-visible alias."""
    return copy.deepcopy(value)


def _abort_error(signal: Any) -> BaseException:
    """
    The failure an aborted prepare raises.

    `AbortSignal.throwIfAborted()` throws `signal.reason` whatever it is. Python
    can raise only `BaseException` instances, so a non-exception reason becomes a
    `RuntimeError` carrying that reason (LEGAL_ADAPTATION).
    """
    reason = getattr(signal, "reason", None)
    if isinstance(reason, BaseException):
        return reason
    return RuntimeError("operation aborted" if reason is None else str(reason))


def _throw_if_aborted(signal: Any) -> None:
    """`signal.throwIfAborted()`."""
    if getattr(signal, "aborted", False):
        raise _abort_error(signal)


async def _maybe_awaited(value: Any) -> Any:
    """Await `value` when it is awaitable; pass a plain value through."""
    if hasattr(value, "__await__") or asyncio.isfuture(value):
        return await value
    return value


async def abortable(work: Any, signal: Any) -> Any:
    """
    Stop awaiting provider work when the containing model request is cancelled.

    The provider keeps running (the reference only races the promise), so the
    abandoned awaitable is left to settle on its own and its outcome is
    consumed rather than reported as an unretrieved exception.

    @param work: an awaitable resolving to the providers' prepared results.
    @param signal: the request's cancellation signal.
    @returns: the awaited result.
    """
    _throw_if_aborted(signal)
    work_future = asyncio.ensure_future(work)
    aborted_future = asyncio.get_event_loop().create_future()

    def on_abort(*_args: Any) -> None:
        if not aborted_future.done():
            aborted_future.set_result(None)

    dispose = signal.add_listener("abort", on_abort)
    try:
        done, _pending = await asyncio.wait(
            {work_future, aborted_future}, return_when=asyncio.FIRST_COMPLETED
        )
        if work_future in done:
            result = await work_future
            # The platform re-checks after the race: an abort that landed while
            # the work was settling still cancels the request.
            _throw_if_aborted(signal)
            return result
        work_future.add_done_callback(_consume_outcome)
        raise _abort_error(signal)
    finally:
        dispose()


def _consume_outcome(future: Any) -> None:
    """Discard an abandoned provider awaitable's failure (never a silent swallow)."""
    if future.cancelled():
        return
    try:
        future.exception()
    except Exception:
        # `exception()` raises only for a cancelled future, which the branch
        # above already returned from.
        pass


async def _settle_callback(callback: Callable[[], Any]) -> Any:
    """`Promise.resolve().then(callback)`: run one callback and await its result."""
    return await _maybe_awaited(callback())


async def accept_all(callbacks: List[Callable[[], Any]]) -> None:
    """
    Settle every acceptance callback before reporting failures.

    Every callback is entered before any of them is awaited, so a failing
    callback never prevents a later one from committing - the same contract as
    `Promise.allSettled(callbacks.map(callback => Promise.resolve().then(callback)))`.

    @param callbacks: one callback per provider that returned an acceptance
        behavior, in field registration order.
    """
    outcomes = await asyncio.gather(
        *(_settle_callback(callback) for callback in callbacks), return_exceptions=True
    )
    failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    if not failures:
        return
    if len(failures) == 1:
        raise failures[0]
    raise ExtensionAcceptanceError(failures)


class PreparedDeepSeekLlmApiExtensions:
    """
    All fields prepared for one request plus their joint acceptance transaction.

    `accept()` joins one shared settlement: repeated calls observe the same
    outcome and every captured provider commits at most once.
    """

    def __init__(
        self,
        fields: Dict[str, Any],
        callbacks: List[Callable[[], Any]],
    ) -> None:
        self.fields = fields
        self._callbacks = callbacks
        self._acceptance: Optional[Any] = None

    def accept(self) -> Any:
        """
        Commit every captured provider after HTTP 2xx.

        @returns: an awaitable fulfilling after every commit succeeds.
        """
        if self._acceptance is None:
            self._acceptance = asyncio.ensure_future(accept_all(self._callbacks))
        return self._acceptance


def _resolve_prepare(provider: Any) -> Callable[[Any], Any]:
    """The provider's `prepare` under either a mapping or an object shape."""
    if isinstance(provider, dict):
        prepare = provider.get("prepare")
        if prepare is None:
            raise TypeError(f"{_PREFIX}: provider declares no prepare")
        return prepare
    prepare = getattr(provider, "prepare", None)
    if prepare is None:
        raise TypeError(f"{_PREFIX}: provider declares no prepare")
    return prepare


def _resolve_result(result: Any) -> Tuple[Any, Optional[Callable[[], Any]]]:
    """The prepared field value and its acceptance callback, or `None`."""
    if isinstance(result, dict):
        return result.get("value"), result.get("accept")
    return getattr(result, "value", None), getattr(result, "accept", None)


class DeepSeekLlmApiExtensionRegistry(Service):
    """
    Registry of independently owned top-level fields for official DeepSeek
    requests, mounted at `ctx.deepseekLlmApiExtensions`.
    """

    id = "deepseek-llm-api-extensions"
    name = "@deepseek-ai/dsh-deepseek-llm-api-extensions"

    def __init__(self, ctx: Any = None) -> None:
        super().__init__(ctx, "deepseekLlmApiExtensions")
        self._providers: Dict[str, Any] = {}

    def register(self, field: Any, provider: Any) -> Callable[[], Any]:
        """
        Register the sole provider of one top-level request field.
        Registration is effect-scoped.

        @param field: declaration-merged field owned by the provider.
        @param provider: request-time field preparation and optional acceptance
            behavior.
        @returns: the disposer that releases the field.
        """
        field_name = field if isinstance(field, str) else ""
        if len(field_name) == 0 or field_name.strip() != field_name:
            raise ValueError(f"{_PREFIX}: field must be a non-blank trimmed string")

        providers = self._providers

        def setup() -> Callable[[], None]:
            # The duplicate check runs inside the effect setup, so a rejected
            # registration never becomes a committed fiber effect.
            if field_name in providers:
                raise ValueError(
                    f"{_PREFIX}: field {_json_string(field_name)} is already registered"
                )
            providers[field_name] = provider

            def release() -> None:
                providers.pop(field_name, None)

            return release

        return self.ctx.effect(setup, label=f"deepseekLlmApiExtensions.register({_json_string(field_name)})")

    async def prepare(self, request: Any) -> PreparedDeepSeekLlmApiExtensions:
        """
        Prepare every currently registered field from one immutable base request.

        Preparation failures reject before HTTP dispatch. Field values are
        cloned and frozen; providers retain no mutable alias to the outgoing
        request.

        @param request: exact serialized request facts before extension fields.
        @returns: detached fields and their idempotent joint acceptance
            transaction.
        """
        signal = request["signal"] if isinstance(request, dict) else request.signal
        _throw_if_aborted(signal)

        entries = list(self._providers.items())
        # `Promise.all(entries.map(...))` enters every provider before any await
        # settles, so a provider's own synchronous failure rejects the whole
        # preparation.
        results: List[Tuple[str, Any]] = []
        for field, provider in entries:
            results.append((field, _resolve_prepare(provider)(request)))

        awaited = await abortable(
            asyncio.gather(*(_maybe_awaited(result) for _field, result in results)), signal
        )

        fields: Dict[str, Any] = {}
        callbacks: List[Callable[[], Any]] = []
        for (field, _result), outcome in zip(results, awaited):
            if outcome is None:
                continue
            value, accept = _resolve_result(outcome)
            fields[field] = freeze_json(_detached(value))
            if accept is not None:
                callbacks.append(accept)
        return PreparedDeepSeekLlmApiExtensions(deep_freeze(fields), callbacks)


def _json_string(value: str) -> str:
    """`JSON.stringify(value)` for the diagnostic strings this module emits."""
    import json

    return json.dumps(value)


#: `export default DeepSeekLlmApiExtensionRegistry`.
default = DeepSeekLlmApiExtensionRegistry
