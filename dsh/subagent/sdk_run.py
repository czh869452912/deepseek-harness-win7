"""One fresh SDK runtime per external run, published only after its handshake."""
import asyncio
import uuid
from types import SimpleNamespace
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.errors import AggregateError
from dsh.core.session.json import UNDEFINED
from dsh.sdk.errors import TransportClosedError, SdkProtocolError, JsonRpcResponseError
from dsh.sdk.event_validation import validated_session_event
from dsh.subprocess.service import scrubbed_parent_env
from .assistant_output_current import AssistantOutputFold
from .out_of_process import settle_run_result, subprocess_run_handle

DEFAULT_SHUTDOWN_TIMEOUT_MS = 1000
DEFAULT_DISPOSE_EOF_GRACE_MS = 6000
DEFAULT_DISPOSE_GRACE_MS = 3000


def _create_harness(options):
    from dsh.sdk.client import DeepSeekHarness
    return DeepSeekHarness(options)


internals = SimpleNamespace(createHarness=_create_harness)


def failure_diagnostic(facts):
    return 'Subagent failure (provider: DSH SDK; stage: %s; category: %s)' % (facts['stage'], facts['category'])


class SdkRunFailure(RuntimeError):
    name = 'SdkRunFailure'

    def __init__(self, facts, cause):
        super().__init__('subagent-dsh-sdk: ' + failure_diagnostic(facts))
        self.facts, self.cause = facts, cause
        if isinstance(cause, BaseException):
            self.__cause__ = cause


def sdk_configuration_failure(cause):
    return SdkRunFailure(dict(stage='initialize', category='configuration'), cause)


def sdk_failure(error, stage):
    category = 'transport' if isinstance(error, TransportClosedError) else 'protocol' if isinstance(error, (SdkProtocolError, JsonRpcResponseError)) else 'unknown'
    return SdkRunFailure(dict(stage=stage, category=category), error)


def sdk_child_outcome(reason=UNDEFINED):
    kind = reason.get('kind') if reason is not UNDEFINED and reason is not None else None
    if kind in ('completed', 'max-tokens'):
        return dict(stopReason=kind)
    if kind == 'aborted':
        if reason['reason']['kind'] == 'disposed':
            return dict(stopReason='aborted', diagnostic=failure_diagnostic(dict(stage='session-run', category='child-disposed')))
        return dict(stopReason='aborted')
    if kind == 'blocked':
        return dict(stopReason='refusal')
    if kind == 'interrupted':
        return dict(stopReason='error')
    category = 'child-error' if kind == 'error' else 'missing-terminal' if kind is None else 'child-unknown'
    return dict(stopReason='error', diagnostic=failure_diagnostic(dict(stage='session-run', category=category)))


def _report(spec, error):
    try:
        if spec.get('onError') is not None:
            spec['onError'](error, 'error')
    except Exception:
        pass


def _startup_failure(spec, error):
    if not isinstance(error, AggregateError) or len(error.errors) < 2:
        _report(spec, error)
        return sdk_failure(error, 'initialize')
    initialize, cleanup = error.errors[:2]
    _report(spec, initialize); _report(spec, cleanup)
    first = sdk_failure(initialize, 'initialize')
    second = SdkRunFailure(dict(stage='shutdown', category='unknown'), cleanup)
    return AggregateError([first, second], str(first) + '; ' + str(second))


async def _race(operation, cancellation, cancelled_error=None):
    """Promise.race semantics: losing I/O stays owned until harness.close()."""
    pending = asyncio.ensure_future(operation)
    # Consume losing failures without cancelling shared futures or child I/O.
    pending.add_done_callback(lambda task: None if task.cancelled() else task.exception())
    await asyncio.wait([pending, cancellation], return_when=asyncio.FIRST_COMPLETED)
    if pending.done():
        return pending.result()
    if cancelled_error is not None:
        raise cancelled_error


async def start_sdk_run(request, spec):
    signal = request['signal']
    aborted_message = 'subagent request was aborted before the SDK child started'
    if signal.aborted:
        raise RuntimeError(aborted_message)
    identity = str(uuid.uuid4())
    options = {key: spec[key] for key in ('profile', 'patches', 'dshHome', 'shutdownTimeoutMs', 'disposeEofGraceMs', 'disposeGraceMs', 'provider', 'model')}
    origin = spec.get('originCwd', UNDEFINED)
    options.update(processCwd=spec['cwd'], cwd=spec['cwd'] if origin is UNDEFINED or origin is None else origin,
        env=dict(scrubbed_parent_env(), **spec['env']))
    for key in ('dshBin', 'reasoningEffort', 'maxTokens'):
        if key in spec and spec[key] is not UNDEFINED:
            options[key] = spec[key]
    harness = internals.createHarness(options)
    cancelled = False
    cancel_settled = asyncio.get_running_loop().create_future()

    def request_cancel(*_):
        nonlocal cancelled
        if cancelled:
            return
        cancelled = True
        cancel_settled.set_result(None)

    signal.addEventListener('abort', request_cancel, dict(once=True))
    startup_cancelled = RuntimeError('subagent cancelled before the SDK child initialized')
    try:
        await _race(harness.start(), cancel_settled, startup_cancelled)
        if cancelled:
            raise startup_cancelled
    except Exception as error:
        signal.removeEventListener('abort', request_cancel)
        if error is not startup_cancelled:
            raise _startup_failure(spec, error)
        try:
            await harness.close()
        except Exception as cleanup:
            _report(spec, cleanup)
            failure = SdkRunFailure(dict(stage='shutdown', category='unknown'), cleanup)
            raise AggregateError([failure], str(failure))
        raise RuntimeError(aborted_message)

    child_session = 'session-' + uuid.uuid4().hex
    fold = AssistantOutputFold()
    subscription = harness.client.subscribe(lambda notification: notification['method'] == 'session.event' and notification['params']['sessionId'] == child_session)
    last_end, diagnostic, accepted = UNDEFINED, UNDEFINED, False

    def drain():
        nonlocal last_end
        while True:
            notification = subscription.tryNext()
            if notification is UNDEFINED:
                return
            event = validated_session_event(notification['params']['event'])
            fold.push(event)
            if event['type'] == 'turn/end':
                last_end = event['data']['reason']

    def collect():
        return fold.collect() or []

    async def teardown():
        try:
            await harness.close()
        except Exception as error:
            _report(spec, error)
            raise SdkRunFailure(dict(stage='shutdown', category='unknown'), error)

    async def work():
        nonlocal accepted
        await harness.session(child_session).setWorkingDirectory(spec['cwd'])
        if cancelled:
            return
        await harness.client.prompt(child_session, request['prompt'])
        accepted = True
        await harness.client.request('session/wait', dict(sessionId=child_session))

    async def attempt():
        nonlocal diagnostic
        try:
            try:
                await _race(start_coroutine(work()), cancel_settled)
            finally:
                if accepted:
                    drain()
            if cancelled:
                return dict(output=collect(), stopReason='aborted')
            outcome = sdk_child_outcome(last_end)
            diagnostic = outcome.get('diagnostic', UNDEFINED)
            return dict(output=collect(), **outcome)
        except Exception as error:
            diagnostic = failure_diagnostic(sdk_failure(error, 'session-run').facts)
            raise
        finally:
            subscription.close()

    result = settle_run_result(dict(attempt=attempt, collectOutput=collect, collectDiagnostic=lambda: diagnostic,
        cancelled=lambda: cancelled, onError=spec.get('onError'), signal=signal, onAbort=request_cancel))
    return subprocess_run_handle(dict(id=identity, result=result, signal=signal, onAbort=request_cancel,
        requestCancel=request_cancel, teardown=teardown))
