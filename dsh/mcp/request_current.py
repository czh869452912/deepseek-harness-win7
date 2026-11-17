"""SDK 2 per-wire request ownership, separate from the legacy protocol client."""
import asyncio
import math
import time

from dsh.core.cancellation import aborted, subscribe_abort
from dsh.cordis.utils import _js_truthy, js_to_string
from dsh.mcp.negotiation_current import SdkError
from dsh.mcp.diagnostic_current import CurrentProtocolError
from dsh.mcp.protocol import McpError


def now_ms():
    return int(time.time() * 1000)


def reason_error(reason):
    if isinstance(reason, SdkError):
        return reason
    message = (getattr(reason, 'name', 'Error')+': '+str(reason)) if isinstance(reason, BaseException) else js_to_string(reason)
    return SdkError('REQUEST_TIMEOUT', message)


def delay_seconds(timeout):
    try:
        value = float(timeout)
    except (ValueError, TypeError):
        value = 1
    if not math.isfinite(value) or value < 1 or value > 2147483647:
        value = 1
    return int(value) / 1000


def progress(owner, packet):
    params = packet.get('params') or {}
    try:
        token = float(params.get('progressToken', float('nan')))
        state = getattr(owner, '_sdk_requests', {}).get(owner._identity(token))
    except (ValueError, TypeError):
        state = None
    if state is None or state['onprogress'] is None:
        from dsh.cordis.json_text import stringify_json
        owner._callback(owner.on_error, RuntimeError('Received a progress notification for an unknown token: '+stringify_json(packet)))
        return
    if state['reset'] and not state['future'].done():
        elapsed = now_ms() - state['started']
        if _js_truthy(state['max_total']) and elapsed >= state['max_total']:
            state['fail'](SdkError('REQUEST_TIMEOUT','Maximum total timeout exceeded',
                dict(maxTotalTimeout=state['max_total'],totalElapsed=elapsed)),False)
            return
        state['timer'].cancel()
        state['timer'] = asyncio.get_running_loop().call_later(state['delay'],state['expire'])
    owner._callback(state['onprogress'], {key:value for key,value in params.items() if key!='progressToken'})


async def request(owner, packet, signal, timeout, options):
    if not owner._connected():
        raise RuntimeError('Not connected')
    if aborted(signal):
        raise reason_error(getattr(signal,'reason',None))
    timeout = 60000 if timeout is None else timeout
    identity = owner._next_id
    owner._next_id += 1
    key = owner._identity(identity)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    owner._pending[key] = future
    states = getattr(owner,'_sdk_requests',None)
    if states is None:
        states = owner._sdk_requests = {}
    state = dict(future=future,started=now_ms(),max_total=options.get('maxTotalTimeout'),
        reset=options.get('resetTimeoutOnProgress',False),onprogress=options.get('onprogress'),
        delay=delay_seconds(timeout),cancel=None,server_error=False,headers=options.get('headers'))
    states[key] = state
    missing = object()
    def fail(error, cancel, raw_reason=missing):
        if not future.done():
            if cancel:
                state['cancel'] = error
                state['cancel_reason'] = error if raw_reason is missing else raw_reason
            future.set_exception(error)
    state['fail'] = fail
    state['expire'] = lambda: fail(SdkError('REQUEST_TIMEOUT','Request timed out',dict(timeout=timeout)),True)
    state['timer'] = loop.call_later(state['delay'],state['expire'])
    detach = subscribe_abort(signal,lambda *_:fail(reason_error(getattr(signal,'reason',None)),True,getattr(signal,'reason',None)))
    if aborted(signal):
        fail(reason_error(getattr(signal,'reason',None)),True,getattr(signal,'reason',None))
    envelope = dict(packet,jsonrpc='2.0',id=identity)
    if state['onprogress'] is not None:
        params = dict(envelope.get('params') or {})
        params['_meta'] = dict(params.get('_meta') or {},progressToken=identity)
        envelope['params'] = params
    sender = asyncio.create_task(owner._write(envelope))
    if getattr(owner,'has_per_request_stream',False):
        sends = getattr(owner,'_request_sends',None)
        if sends is None:sends = owner._request_sends = set()
        sends.add(sender)
        sender.add_done_callback(sends.discard)
    def sent(done):
        if not done.cancelled():
            error = done.exception()
            if error is not None and not future.done():future.set_exception(error)
    sender.add_done_callback(sent)
    cancel_task = False
    try:
        try:
            result = await asyncio.shield(future)
            return owner._validate_result(packet['method'],result)
        except McpError as error:
            if state['server_error']:
                args = (error.code,error.message.split(': ',1)[1])
                raise CurrentProtocolError(*args, **(dict(data=error.data) if error.has_data else {})) from None
            if owner._closed:
                raise SdkError('CONNECTION_CLOSED','Connection closed') from None
            raise
    except asyncio.CancelledError:
        cancel_task = True
        raise
    finally:
        state['timer'].cancel()
        detach()
        states.pop(key,None)
        owner._pending.pop(key,None)
        if not future.done():future.cancel()
        elif not future.cancelled():future.exception()
        abandoned_legacy_http = False
        if cancel_task or state['cancel'] is not None:
            modern_http = getattr(owner,'has_per_request_stream',False) and (getattr(owner,'negotiated',None) or {}).get('era')=='modern'
            if not modern_http and packet['method']!='initialize':
                reason = state.get('cancel_reason',missing)
                text = (getattr(reason,'name','Error')+': '+str(reason) if isinstance(reason,BaseException)
                    else js_to_string(reason)) if reason is not missing else ''
                owner._callback(owner._cancel_request,dict(requestId=identity,reason=text))
            if modern_http or not getattr(owner,'has_per_request_stream',False):sender.cancel()
            else:abandoned_legacy_http=True
        async def finish():
            if not abandoned_legacy_http:await asyncio.gather(sender,return_exceptions=True)
        closing = asyncio.create_task(finish())
        interrupted = False
        while not closing.done():
            try:await asyncio.shield(closing)
            except asyncio.CancelledError:interrupted=True
        closing.result()
        if interrupted:raise asyncio.CancelledError()
