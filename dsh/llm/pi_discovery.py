"""Catalog-first model discovery; draft HTTP listings have a bounded body."""
import inspect
import math
import urllib.request

from dsh.core.cancellation import aborted
from dsh.llm.attribution import attribution_headers
from dsh.llm.http_stream import open_stream
from dsh.llm.llm_service import LlmError, assert_usable_api_key
from dsh.llm.pi_catalog import catalog_models
from dsh.llm.pi_json import loads
from dsh.llm.stream_bridge import OwnedStream, iter_chunks

MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def read_listing(body):
    data = body.get('data') if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise LlmError('the endpoint model listing has no data array', 'DISCOVERY_FAILED')
    result = []
    for raw in data:
        if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not raw['id']:
            continue
        model = dict(id=raw['id'])
        label = next((raw[key] for key in ('name', 'display_name') if isinstance(raw.get(key), str) and raw[key]), None)
        if label is not None:
            model['name'] = label
        for target, keys in [('contextWindow', ('context_window', 'context_length')),
                             ('maxTokens', ('max_output_tokens', 'max_tokens'))]:
            for key in keys:
                value = raw.get(key)
                if type(value) in (int, float) and value > 0 and math.isfinite(value) and float(value).is_integer():
                    model[target] = value
                    break
        result.append(model)
    return result


async def discover_models(request, stored_api_key=None):
    installed = catalog_models(request.get('provider'))
    if installed:
        return [{key: model[key] for key in ('id', 'name', 'contextWindow', 'maxTokens')} for model in installed.values()]
    endpoint = request.get('baseURL')
    if not endpoint:
        raise LlmError('pi-ai has no catalog for this route; set baseURL or enter models by hand', 'DISCOVERY_FAILED')
    if request.get('api', 'openai-completions') not in ('openai-completions', 'openai-responses'):
        raise LlmError('this protocol has no supported model listing', 'DISCOVERY_UNSUPPORTED')
    key = request.get('apiKey')
    if key is None and stored_api_key:
        key = stored_api_key()
        if inspect.isawaitable(key):
            key = await key
    headers = dict(attribution_headers(), Accept='application/json')
    if key is not None:
        headers['Authorization'] = 'Bearer ' + assert_usable_api_key(key, 'llm-pi-ai discovery', 'apiKey')

    def read(signal):
        try:
            req = urllib.request.Request(endpoint.rstrip('/') + '/models', headers=headers, method='GET')
            with open_stream(req, signal, read_error_body=False) as (response, chunks):
                try:
                    declared = float(response.headers.get('Content-Length', 'nan'))
                except ValueError:
                    declared = float('nan')
                if math.isfinite(declared) and declared > MAX_RESPONSE_BYTES:
                    raise LlmError('model listing exceeds the 4 MiB response limit', 'DISCOVERY_FAILED')
                data = bytearray()
                for chunk in chunks:
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise LlmError('model listing exceeds the 4 MiB response limit', 'DISCOVERY_FAILED')
                    data.extend(chunk)
                body = loads(bytes(data).decode('utf-8', errors='replace'))
                yield read_listing(body)
        except Exception as error:
            if aborted(signal):
                raise LlmError('model discovery aborted by caller', 'ABORTED') from error
            if isinstance(error, LlmError) and error.code == 'DISCOVERY_FAILED':
                raise
            raise LlmError('could not read the endpoint model listing', 'DISCOVERY_FAILED') from error

    stream = iter_chunks(OwnedStream(read, request.get('signal')))
    try:
        async for models in stream:
            return models
    finally:
        await stream.aclose()
