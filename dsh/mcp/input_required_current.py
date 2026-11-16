"""Default SDK input-required driver for a client with no input handlers."""
import asyncio

from dsh.core.cancellation import subscribe_abort
from dsh.cordis.utils import js_to_string
from dsh.mcp.negotiation_current import SdkError


def manual_result(decoded):
    value = dict(resultType='input_required', inputRequests=decoded['inputRequests'])
    for key in ('requestState', '_meta'):
        if key in decoded:
            value[key] = decoded[key]
    return value


def reject_unhandled_input(key, entry):
    if not isinstance(entry, dict) or not isinstance(entry.get('method'), str):
        raise SdkError('INVALID_RESULT', "Invalid input request '"+key+"': each inputRequests entry must be an embedded request object with a method", dict(key=key))
    method = entry['method']
    if method not in ('elicitation/create', 'sampling/createMessage', 'roots/list'):
        raise SdkError('INVALID_RESULT', "Invalid input request '"+key+"': '"+method+"' is not an embedded request the 2026-07-28 revision defines (expected elicitation/create, sampling/createMessage, or roots/list)", dict(key=key, method=method))
    raise SdkError('CAPABILITY_NOT_SUPPORTED', "Cannot fulfil input request '"+key+"': no handler is registered for '"+method+"' on this client. Declare the corresponding capability and register a handler, or handle input_required results manually.", dict(key=key, method=method))


async def pace_state_only(signal):
    done = asyncio.get_running_loop().create_future()
    timer = asyncio.get_running_loop().call_later(.25, lambda: done.set_result(None) if not done.done() else None)
    def aborted(*_):
        if done.done():
            return
        reason = signal.reason
        done.set_exception(reason if isinstance(reason, SdkError) else SdkError('REQUEST_TIMEOUT', js_to_string(reason)))
    detach = subscribe_abort(signal, aborted) if signal is not None else lambda: None
    try:
        if signal is not None and signal.aborted:
            aborted()
        await done
    finally:
        timer.cancel()
        detach()
