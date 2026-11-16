"""Messages Files API: header authentication, owned HTTP, and wire validation."""
import asyncio
import math
import re
import urllib.parse
import urllib.request
import uuid
import zlib

from dsh.core.abort import AbortController, NEVER_ABORTED, abort_reason_error
from dsh.llm.attribution import attribution_headers
from dsh.llm.deepseek_messages_errors import _date_ms, providerErrorDetail
from dsh.llm.deepseek_model_info_current import messagesApiRoot, MESSAGES_FILES_BETA
from dsh.llm.http_stream import open_stream
from dsh.llm.llm_service import LlmError
from dsh.llm.model_listing import _decompress
from dsh.llm.pi_json import loads

MAX_FILE_UPLOAD_BYTES = 128 * 1024 * 1024


class DeepSeekFilesError(LlmError):
    def __init__(self, message, status, detail):
        code = ('AUTH' if status in (401, 403) else 'RATE_LIMIT' if status == 429
                else 'SERVER' if status >= 500 else 'FILES_API')
        super().__init__(message, code, status=status)
        self.name = 'DeepSeekFilesError'
        self.detail = detail


def isFilesQuotaError(error):
    return isinstance(error, DeepSeekFilesError) and bool(re.search(
        r'quota|storage|stored files|file count|too many files',
        error.detail.replace('\u017f', 's').replace('\u212a', 'k'), re.I | re.ASCII))


def invalidResponse(operation):
    return LlmError('DeepSeek Files API returned an invalid '+operation+' response.', 'INVALID_RESPONSE')


def safeInteger(value):
    return (type(value) in (int, float) and 0 <= value <= 9007199254740991
            and math.isfinite(value) and value == math.floor(value))


def parseFileObject(value, operation):
    if not isinstance(value, dict):
        raise invalidResponse(operation)
    created = _date_ms(value['created_at']) if isinstance(value.get('created_at'), str) else float('nan')
    created = math.floor(created / 1000) if math.isfinite(created) else created
    if (not isinstance(value.get('id'), str) or not value['id'] or value.get('type') != 'file'
            or not isinstance(value.get('mime_type'), str) or not safeInteger(value.get('size_bytes'))
            or not safeInteger(created) or not isinstance(value.get('filename'), str) or not value['filename']):
        raise invalidResponse(operation)
    return dict(id=value['id'], bytes=value['size_bytes'], createdAt=created, filename=value['filename'])


class DeepSeekFilesClient:
    def __init__(self, baseURL, headers):
        self.baseURL = messagesApiRoot(baseURL)
        self.authHeaders = headers

    async def _request(self, path, operation, method='GET', data=None, content_type=None, signal=None):
        signal = NEVER_ABORTED if signal is None else signal
        controller = AbortController()
        detach = signal.add_listener('abort', lambda *_: controller.abort(signal.reason))

        def read():
            response = None
            try:
                signal.throw_if_aborted()
                headers = {key.lower(): value.strip(' \t\r\n') for key, value in attribution_headers().items()}
                for key, value in self.authHeaders.items():
                    headers[key.lower()] = value.strip(' \t\r\n')
                headers.update({'anthropic-version': '2023-06-01', 'anthropic-beta': MESSAGES_FILES_BETA})
                headers.setdefault('accept', '*/*')
                headers.setdefault('accept-encoding', 'gzip, deflate')
                if content_type is not None:
                    headers.setdefault('content-type', content_type)
                # Fetch's URL serializer drops an empty trailing search on the wire.
                request = urllib.request.Request((self.baseURL+path).rstrip('?'), data=data, headers=headers, method=method)
                with open_stream(request, controller.signal, idle_timeout_ms=2147483647,
                                 redirect_policy='error', raise_http_errors=False) as (received, chunks):
                    response = received
                    try:
                        payload = b''.join(chunks)
                        for encoding in reversed(response.headers.get('content-encoding', '').split(',')):
                            encoding = encoding.strip().lower()
                            if encoding == 'gzip': payload = _decompress(payload, 16+zlib.MAX_WBITS)
                            elif encoding == 'deflate':
                                payload = _decompress(payload, zlib.MAX_WBITS if payload and payload[0]&15 == 8 else -zlib.MAX_WBITS)
                        text = payload.decode('utf-8-sig', errors='replace')
                        try:
                            value = loads(text)
                        except ValueError as error:
                            raise LlmError('DeepSeek Files API returned invalid JSON for '+operation+
                                           ' (HTTP '+str(response.status)+').', 'INVALID_RESPONSE',
                                           status=response.status) from error
                    except Exception:
                        if 200 <= response.status < 300: raise
                        value = None
                    if not 200 <= response.status < 300:
                        error = value.get('error') if isinstance(value, dict) else None
                        message = error.get('message') if isinstance(error, dict) else None
                        if not isinstance(message, str):
                            message = 'DeepSeek Files API error (HTTP '+str(response.status)+')'
                        raise DeepSeekFilesError(message, response.status, providerErrorDetail(value))
                    return value
            except Exception as error:
                if response is not None:
                    raise
                if signal.aborted:
                    raise abort_reason_error(signal)
                raise LlmError('DeepSeek Files API request to '+self.baseURL+' failed', 'TRANSPORT') from error

        worker = asyncio.get_running_loop().run_in_executor(None, read)
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            controller.abort()
            try: await asyncio.shield(worker)
            except Exception: pass
            raise
        finally:
            detach()

    async def upload(self, data, mediaType, filename, expiresAfterSeconds, signal=None):
        if len(data) > MAX_FILE_UPLOAD_BYTES:
            raise LlmError('DeepSeek Files API upload exceeds 128 MiB.', 'INVALID_REQUEST')
        if not safeInteger(expiresAfterSeconds) or not 3600 <= expiresAfterSeconds <= 2592000:
            raise LlmError('DeepSeek file expiry must be between 3600 and 2592000 seconds.', 'INVALID_REQUEST')
        boundary = 'dsh-'+uuid.uuid4().hex
        parts = []
        for name, value in (('expires_after[anchor]', 'created_at'),
                            ('expires_after[seconds]', str(int(expiresAfterSeconds)))):
            parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+name+'"\r\n\r\n'+value+'\r\n').encode('utf-8'))
        escaped = filename.replace('\r', '%0D').replace('\n', '%0A').replace('"', '%22')
        # Blob normalizes non-ASCII media types to the empty type.
        mediaType = mediaType.lower() if all(32 <= ord(char) <= 126 for char in mediaType) else ''
        parts.extend([('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+escaped+
                       '"\r\nContent-Type: '+(mediaType or 'application/octet-stream')+'\r\n\r\n').encode('utf-8'),
                      bytes(data), ('\r\n--'+boundary+'--\r\n').encode('ascii')])
        value = await self._request('/files', 'upload', 'POST', b''.join(parts),
                                    'multipart/form-data; boundary='+boundary, signal)
        result = parseFileObject(value, 'upload')
        result['expiresAt'] = result['createdAt']+expiresAfterSeconds
        return result

    async def list(self, after=None, limit=None, signal=None):
        from dsh.cordis.utils import js_to_string
        query = []
        if after is not None: query.append(('after_id', after))
        if limit is not None: query.append(('limit', js_to_string(limit)))
        value = await self._request('/files?'+urllib.parse.urlencode(query), 'list', signal=signal)
        if (not isinstance(value, dict) or not isinstance(value.get('data'), list)
                or type(value.get('has_more')) is not bool
                or any(value.get(key) is not None and not isinstance(value[key], str) for key in ('first_id', 'last_id'))):
            raise invalidResponse('list')
        result = dict(data=[parseFileObject(row, 'list') for row in value['data']], hasMore=value['has_more'])
        for key, target in (('first_id', 'firstId'), ('last_id', 'lastId')):
            if value.get(key) is not None: result[target] = value[key]
        return result

    async def retrieve(self, fileId, signal=None):
        path = '/files/'+urllib.parse.quote(fileId, safe="-_.!~*'()")
        return parseFileObject(await self._request(path, 'retrieve', signal=signal), 'retrieve')

    async def delete(self, fileId, signal=None):
        path = '/files/'+urllib.parse.quote(fileId, safe="-_.!~*'()")
        value = await self._request(path, 'delete', 'DELETE', signal=signal)
        if not isinstance(value, dict) or value.get('id') != fileId or value.get('type') != 'file_deleted':
            raise invalidResponse('delete')
