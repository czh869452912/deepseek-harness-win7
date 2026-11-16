"""Ordered operation-bound credentials and owned Search/Fetch HTTP dispatch."""
import asyncio
import inspect
import json
from contextlib import asynccontextmanager

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.json_text import stringify_json
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.host.http_request import request as requestHttp
from dsh.host.url_current import _url
from dsh.web.deepseek_search_provider import error_text
from dsh.web.web_service import WebError


def searchAborted(signal=None, fallback=None):
    return WebError('DeepSeek web request aborted', 'WEB_ABORTED',
                    cause=getattr(signal, 'reason', None) if aborted(signal) else fallback)


def throwIfSearchAborted(signal):
    if aborted(signal):
        raise searchAborted(signal)


def invalidResponse():
    return WebError('DeepSeek returned an invalid response body', 'WEB_PROVIDER_ERROR')


def joinPath(base, path):
    return base.rstrip('/')+path


def hasDeepSeekWebCredential(auth):
    return any(source['kind'] != 'api-key' or not isinstance(source['key'], str) or bool(source['key'])
               for source in auth['sources'])


async def isDeepSeekWebAuthReady(auth, path):
    for source in auth['sources']:
        kind = source['kind']
        if kind == 'misconfigured':
            return False
        try:
            if kind == 'account':
                if await await_callback_result(source['resolveToken'](joinPath(source['baseURL'], path))):
                    return True
            elif kind == 'api-key':
                key = source['key']
                if isinstance(key, str):
                    if key: return True
                elif await await_callback_result(key['configured']()):
                    return True
            else:
                raise ValueError('web-deepseek-api: unexpected credential source '+stringify_json(source))
        except Exception:
            return False
    return False


async def abortable(operation, signal):
    if not inspect.isawaitable(operation):
        throwIfSearchAborted(signal)
        return operation
    task = asyncio.ensure_future(operation)
    if signal is None:
        return await task
    settled = asyncio.get_running_loop().create_future()

    def finish(future):
        try: value = future.result()
        except BaseException as error:
            if not settled.done(): settled.set_exception(error)
        else:
            if not settled.done(): settled.set_result(value)

    def cancel(_reason=None):
        if not settled.done(): settled.set_exception(searchAborted(signal))

    task.add_done_callback(finish)
    dispose = subscribe_abort(signal, cancel)
    try:
        throwIfSearchAborted(signal)
        return await settled
    finally:
        dispose()


async def resolveCredential(resolve, signal):
    throwIfSearchAborted(signal)
    try:
        return await abortable(resolve(), signal)
    except Exception as error:
        if aborted(signal) or getattr(error, 'name', None) == 'AbortError':
            raise searchAborted(signal, error)
        raise WebError('DeepSeek web credential resolution failed: '+error_text(error),
                       'WEB_PROVIDER_ERROR', cause=error)


async def authHeaders(auth, request, signal):
    throwIfSearchAborted(signal)
    for source in auth['sources']:
        throwIfSearchAborted(signal)
        kind = source['kind']
        if kind == 'misconfigured':
            raise WebError(source['message'], 'WEB_PROVIDER_MISCONFIGURED')
        endpoint = joinPath(source['baseURL'], request['path'])
        if kind == 'account':
            token = await resolveCredential(lambda: source['resolveToken'](endpoint), signal)
            if token:
                return dict(kind=kind, endpoint=endpoint, headers={'x-dsh-auth-token': token},
                            reject=lambda: source['rejectToken'](token))
        elif kind == 'api-key':
            key = source['key']
            value = key if isinstance(key, str) else await resolveCredential(key['resolve'], signal)
            if value:
                headers = dict(request['apiKeyHeaders'](value)) if request.get('apiKeyHeaders') else {}
                headers['authorization'] = 'Bearer '+value
                return dict(kind=kind, endpoint=endpoint, headers=headers)
        else:
            raise ValueError('web-deepseek-api: unexpected credential source '+stringify_json(source))
    raise WebError(auth.get('missingCredentialMessage', 'DeepSeek web access has no credential to send'),
                   'WEB_PROVIDER_CREDENTIAL_MISSING')


def searchEndpointError(options, endpoint, message, cause=None):
    subject, plugin = options['subject'], options['plugin']
    base = plugin+'.'+options['baseURLField']; key = plugin+'.'+options['apiKeyEnvField']
    if options['custom']:
        recovery = (subject+' sends the API key under '+key+' to '+base+'. If that endpoint is not intended, guide the'
                    +' user to correct '+base+' and '+key+', or to remove both so '+subject+' uses the DeepSeek'
                    +' credential of the conversation.')
    else:
        recovery = (subject+' derives this endpoint from the base URL of the DeepSeek model provider whose credential it uses. If that'
                    +' endpoint is not intended, guide the user to check that provider\'s base URL on the Models page, or to set'
                    +' '+base+' to a trusted DeepSeek endpoint and '+key+' to the credential reference of its API key.')
    return WebError(message+'\n\nThe web request used endpoint '+stringify_json(endpoint)+'. '+recovery
                    +' Only the user should choose or change the endpoint.', 'WEB_PROVIDER_ERROR', cause=cause)


def accountRejectedError(message):
    return WebError(message+'\n\nDeepSeek rejected the account sign-in used for this web request. '
                    +'Guide the user to sign in to DeepSeek again; the endpoint does not need changing.', 'WEB_PROVIDER_ERROR')


@asynccontextmanager
async def fetchResponse(endpoint, headers, body, signal):
    # The owned carrier yields metadata before reading the body, so a rejected
    # account token is still invalidated if its error body is interrupted.
    entered = False
    try:
        parsed = _url(endpoint)
        if parsed['credentials']:
            raise ValueError('URL contains credentials')
        async with requestHttp(endpoint, 'POST', headers, body, signal) as response:
            entered = True
            yield response
    except Exception as error:
        if entered or aborted(signal): raise
        failure = TypeError('fetch failed')
        raise failure from error


async def responseJson(chunks):
    data = bytearray()
    async for chunk in chunks: data.extend(chunk)
    # Fetch consumes UTF-8 with replacement and strips an initial BOM.
    text = bytes(data).decode('utf-8-sig', 'replace')
    return json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON constant')))


async def dispatchDeepSeekWeb(options, request, signal=None):
    auth = await authHeaders(options, request, signal)
    endpoint = auth['endpoint']; guidance = request['guidance']
    if request.get('waitToSend'):
        await await_callback_result(request['waitToSend'](signal))
    throwIfSearchAborted(signal)
    if request.get('recordRequest'): request['recordRequest'](endpoint)
    throwIfSearchAborted(signal)
    headers = dict(auth['headers']); headers.update(request.get('headers', {}))
    headers.update({'content-type': 'application/json', 'accept': 'application/json', 'user-agent': 'deepseek-harness/0.0.1'})
    manager = fetchResponse(endpoint, headers, stringify_json(request['body']), signal)
    try:
        metadata, chunks = await manager.__aenter__()
    except Exception as error:
        if aborted(signal) or getattr(error, 'name', None) == 'AbortError': raise searchAborted(signal, error)
        raise searchEndpointError(guidance, endpoint, 'DeepSeek web request failed: '+error_text(error), error)
    try:
        status = metadata['status']
        if not 200 <= status < 300:
            message = 'DeepSeek API error (HTTP '+str(status)+')'; interrupted = None
            try:
                parsed = await responseJson(chunks)
                if isinstance(parsed, dict):
                    detail = parsed.get('error')
                    if isinstance(detail, dict): detail = detail.get('message')
                    elif not isinstance(detail, str): detail = parsed.get('message')
                    if isinstance(detail, str) and detail: message += ': '+detail
            except Exception as error:
                if aborted(signal) or getattr(error, 'name', None) == 'AbortError': interrupted = searchAborted(signal, error)
            if status == 401 and auth['kind'] == 'account':
                try: await await_callback_result(auth['reject']())
                except Exception: pass
                raise interrupted or accountRejectedError(message)
            if interrupted: raise interrupted
            raise searchEndpointError(guidance, endpoint, message)
        try:
            payload = await responseJson(chunks)
            throwIfSearchAborted(signal)
            return request['decode'](payload)
        except Exception as error:
            if aborted(signal) or getattr(error, 'name', None) == 'AbortError': raise searchAborted(signal, error)
            message = error.message if isinstance(error, WebError) else 'DeepSeek returned an unprocessable response body: '+error_text(error)
            raise searchEndpointError(guidance, endpoint, message, error)
    finally:
        await manager.__aexit__(None, None, None)
