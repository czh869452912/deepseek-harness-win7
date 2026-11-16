"""Pinned Messages adapter over current image, Files, extension and SSE contracts."""
import asyncio
from types import SimpleNamespace

from dsh.core.abort import AbortController
from dsh.core.timeout import idle_watchdog, timeout_of
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.errors import ThrownValueError
from dsh.cordis.utils import js_to_string
from dsh.llm.attribution import attribution_headers
from dsh.llm.deepseek_file_store_current import DeepSeekFileStore
from dsh.llm.deepseek_image_pricing_current import imagePricing, resolveRequestImageTarget
from dsh.llm.deepseek_messages_errors import providerError, providerErrorDetail
from dsh.llm.deepseek_messages_http import requestMessages
from dsh.llm.deepseek_messages_images import prepareImages, prepareFileIds, inlineImages
from dsh.llm.deepseek_messages_serialize import serialize
from dsh.llm.deepseek_messages_sse import parseSse
from dsh.llm.deepseek_messages_translate import translate
from dsh.llm.deepseek_model_info_current import modelInfo, messagesApiRoot, MESSAGES_FILES_BETA, MESSAGES_TOOL_CHANGES_BETA
from dsh.llm.deepseek_request_extensions import prepareRequestExtensions
from dsh.llm.deepseek_request_files import RequestFiles, FileResolutionFailure
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_json import loads


class DeepSeekMessagesAdapter:
    def __init__(self, dependencies):
        self.dependencies = dependencies
        self.files = self._dependency('resolveFiles', lambda: None)()
        self._owns_files = self.files is None
        if self.files is None: self.files = DeepSeekFileStore()

    def _dependency(self, name, default=None):
        return self.dependencies.get(name, default) if isinstance(self.dependencies, dict) else getattr(self.dependencies, name, default)

    def options(self): return self._dependency('options')()

    def _image_access(self, ref):
        attachments = self._dependency('resolveAttachments', lambda: None)()
        if attachments is None: return None
        return self._dependency('resolveImageAccess', lambda *_: None)(attachments, ref)

    def providerInfo(self, provider):
        name = self._dependency('providerName')
        return dict(id=provider, name='DeepSeek' if name is None else name)
    def providerRetryPolicy(self, provider): return self.options()['retryPolicy']

    async def listModels(self, provider):
        return await await_callback_result(self._dependency('discoverModels', lambda _: [])(provider))

    async def _connection(self, signal):
        connect = self._dependency('connect')
        return await await_callback_result(connect(signal) if connect is not None else self.options())

    async def resolveModel(self, provider, model, signal=None):
        return modelInfo(await self._connection(signal), provider, model)

    def imageRequestPricing(self, provider, model): return imagePricing(self.options(), model, self._image_access)

    def imageRequestTarget(self, provider, model, image):
        entry = next((entry for entry in self.options()['models'] if entry['id'] == model), None)
        if entry is None: raise LlmError('DeepSeek model "'+model+'" has no declared image projection', 'UNKNOWN_MODEL')
        return resolveRequestImageTarget(entry, image)

    async def prepareCall(self, provider, model, signal=None):
        connection = await self._connection(signal)
        self._dependency('admit', lambda *_: None)(connection, model)
        return dict(model=modelInfo(connection, provider, model), stream=lambda options: self._generate(options, connection))

    def stream(self, options):
        connection = self.options()
        self._dependency('admit', lambda *_: None)(connection, options['model'])
        return self._generate(options, connection)

    async def _generate(self, options, connection):
        consumer = AbortController(); caller = options.get('signal')
        detach = caller.add_listener('abort', lambda *_: consumer.abort(caller.reason)) if caller is not None else lambda: None
        demand = None
        with idle_watchdog(consumer.signal, connection['streamIdleTimeoutMs'], 'MESSAGES_IDLE') as watchdog:
            iterator = self._request(options, connection, watchdog.signal, watchdog.pulse)
            try:
                while True:
                    demand = asyncio.ensure_future(iterator.__anext__())
                    try: value = await watchdog.next(SimpleNamespace(next=lambda: demand))
                    except StopAsyncIteration: return
                    demand = None
                    yield value
            except Exception as error:
                if timeout_of(watchdog.signal, 'MESSAGES_IDLE') is not None:
                    raise LlmError('DeepSeek Messages stream idle timeout', 'TIMEOUT') from error
                if caller is not None and caller.aborted:
                    raise LlmError('DeepSeek Messages request aborted', 'ABORTED') from error
                if isinstance(error, LlmError): raise
                raise LlmError('DeepSeek Messages transport failed', 'TRANSPORT') from error
            finally:
                consumer.abort(); detach()
                if demand is not None:
                    if not demand.done(): demand.cancel()
                    await asyncio.gather(demand, return_exceptions=True)
                await iterator.aclose()

    def _notify(self, name, value):
        callback = self._dependency(name)
        if callback is not None: callback(value)

    async def _request(self, options, connection, signal, activity):
        signal.throw_if_aborted()
        prepared = await prepareImages(options['messages'], connection, options['model'],
            self._dependency('resolveAttachments', lambda: None)(), self._image_access, signal)
        messages, versions = prepared['messages'], prepared['versions']
        auth = await await_callback_result(self._dependency('resolveAuth')(connection))
        try:
            files = RequestFiles(self.files, dict(baseURL=connection['baseURL'], headers=auth['headers']),
                connection['filePolicy'], connection['filesApiTimeoutMs'], signal, activity)
            inline = False
            while True:
                signal.throw_if_aborted(); files.beginAttempt(); fileIds = None
                if not inline:
                    try: fileIds = await prepareFileIds(messages, versions, files)
                    except FileResolutionFailure:
                        inline = True; continue
                history = inlineImages(messages, versions, connection) if inline else messages
                identity = dict(provider=options['provider'], model=options['model'])
                body = serialize(options, connection, history, versions, self._image_access,
                    lambda reason: self._notify('onReplayDegrade', dict(identity, reason=reason)), fileIds)
                requestIdentity = dict(signal=signal)
                if 'sessionId' in options: requestIdentity['sessionId'] = js_to_string(options['sessionId'])
                if 'purpose' in options: requestIdentity['purpose'] = options['purpose']
                extensions = await prepareRequestExtensions(body, requestIdentity, self._dependency('prepareExtensions'),
                    lambda fields, error: self._notify('onExtensionsOmitted', dict(identity, fields=fields, error=error)),
                    lambda error: self._notify('onExtensionsUnaccepted', dict(identity, error=error)))
                signal.throw_if_aborted(); betas = []
                if fileIds: betas.append(MESSAGES_FILES_BETA)
                if any(block['type'] in ('tool_addition', 'tool_removal') for message in body['messages'] for block in message['content']):
                    betas.append(MESSAGES_TOOL_CHANGES_BETA)
                headers = dict(attribution_headers(), **{'content-type': 'application/json', 'accept': 'text/event-stream'})
                headers.update(auth['headers']); headers['anthropic-version'] = '2023-06-01'
                if betas: headers['anthropic-beta'] = ','.join(betas)
                headers['x-deepseek-harness-user-id'] = self._dependency('resolveUserId')()
                if 'sessionId' in options: headers['x-deepseek-harness-session-id'] = js_to_string(options['sessionId'])
                if requestIdentity.get('purpose') == 'compaction': headers['x-deepseek-harness-compact'] = '1'
                async with requestMessages(messagesApiRoot(connection['baseURL'])+'/messages', headers, extensions.payload, signal) as (response, chunks):
                    if not 200 <= response['status'] < 300:
                        payload = b''.join([chunk async for chunk in chunks])
                        text = payload.decode('utf-8-sig', errors='replace')
                        try: raw = loads(text)
                        except ValueError: raw = None
                        detail = providerErrorDetail(raw)
                        if await files.retry(detail): continue
                        failure = providerError(raw, response['status'], response['headers'])
                        data = dict(failure.failure, message=files.errorMessage(response['status'], failure.message, detail))
                        error = LlmError.fromFailure(data); error.cause = RuntimeError(text)
                        raise error from error.cause
                    await extensions.accept()
                    if not response['hasBody']: raise LlmError('DeepSeek Messages returned no response body', 'EMPTY_RESPONSE')
                    stream = translate(parseSse(chunks, activity), options['model'])
                    try:
                        async for chunk in stream: yield chunk
                    finally: await stream.aclose()
                    return
        except Exception as error:
            mapper = auth.get('onRequestError')
            if mapper is None: raise
            try: mapped = await await_callback_result(mapper(error))
            except Exception: raise error
            if isinstance(mapped, BaseException): raise mapped
            raise ThrownValueError(mapped)

    async def close(self):
        if self._owns_files: await self.files.close()
