"""rc.3 Agent-scoped upload receipts and the authenticated raw-byte route."""
import inspect
import uuid
import weakref
from urllib.parse import parse_qs, urlsplit

from dsh.cordis.json_text import stringify_json
from dsh.cordis.text import trim_js
from dsh.core.scope import scope_of
from dsh.host.connection.rpc_host import response
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService, remote_error_of

FILE_UPLOAD_PATH = '/api/session/uploadFileBinary'


class PromptFileBinding:
    def __init__(self, rollback):
        self._rollback = rollback
        self._settled = False

    def commit(self):
        self._settled = True

    def dispose(self):
        if not self._settled:
            self._settled = True
            self._rollback()


class CurrentFileUploads(TypertRemoteService):
    inject = ['agents', 'attachments', 'commands', 'connection']

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'fileUploads')
        self._staged = weakref.WeakKeyDictionary()
        self._resolver = {'value': None}
        ctx.effect(lambda: ctx.get('commands').registerFileReceiptResolver(self.resolve), 'file-upload: command file receipt resolver')
        ctx.effect(lambda: ctx.get('connection').fetch.register(dict(path=FILE_UPLOAD_PATH, methods=['POST'],
            requestBody='streaming', fetch=lambda request: handle_file_upload_http(self, request))), 'file-upload: streaming route')
        ctx.on('session/event', self._observe)
        ctx.on('session/disposed', lambda session: self._staged.pop(session, None))

    def registerAgentResolver(self, resolve):
        if self._resolver['value'] is not None:
            raise RuntimeError('file-upload: Agent resolver is already registered')
        self._resolver['value'] = resolve
        def dispose():
            if self._resolver['value'] is resolve:
                self._resolver['value'] = None
        return dispose

    @Remote('upload')
    async def upload(self, agent, request, signal):
        signal.throwIfAborted()
        return await self._commit(agent, lambda: self.ctx.get('attachments').admitEncodedFile(request))

    async def uploadStream(self, request):
        session_id = request['sessionId']
        agent = self.ctx.get('agents').get(session_id)
        if agent is None:
            resolver = self._resolver['value']
            if resolver is None:
                raise RemoteError('session/not-found', 'session "{}" is not attached'.format(session_id), dict(sessionId=session_id))
            agent = resolver(session_id)
            if inspect.isawaitable(agent):
                agent = await agent
        return await self._commit(agent, lambda: self.ctx.get('attachments').saveFileStream(
            {key: request[key] for key in ('data', 'signal', 'name') if key in request}))

    @staticmethod
    def _assert_scope(agent):
        if scope_of(agent.ctx) is not agent:
            raise RuntimeError("file-upload: operation requires the Agent's own scope")

    def resolve(self, agent, receipt_id):
        self._assert_scope(agent)
        return self._staged.get(agent.session, {}).get(receipt_id, {}).get('file')

    def bindPrompt(self, agent, receipt_ids, request_id):
        self._assert_scope(agent)
        staged = self._staged.get(agent.session, {})
        bound = []
        for receipt_id in receipt_ids:
            upload = staged.get(receipt_id)
            if upload is None:
                raise RemoteError('session/attachment-invalid', 'File was not uploaded for this session.', dict(reason='FILE_NOT_STAGED'))
            bound.append((upload, upload.get('requestId')))
        for upload, previous in bound:
            upload['requestId'] = request_id
        def rollback():
            for upload, previous in bound:
                if previous is None:
                    upload.pop('requestId', None)
                else:
                    upload['requestId'] = previous
        return PromptFileBinding(rollback)

    def retirePrompt(self, agent, request_id):
        self._assert_scope(agent)
        self._retire(agent.session, request_id)

    async def _commit(self, agent, save):
        self._assert_scope(agent)
        if getattr(agent.session.header, 'origin', None) == 'subagent':
            raise RemoteError('subagent/attachment-invalid', 'subagent conversations do not accept file uploads',
                              dict(reason='SUBAGENT_FILE_UNSUPPORTED'))
        try:
            file = await save()
        except Exception as error:
            if self.ctx.get('attachments').isAttachmentError(error):
                raise RemoteError('session/attachment-invalid', error.message, dict(reason=error.code)) from None
            text = getattr(error, 'name', 'Error') + ': ' + str(error)
            raise RemoteError('gateway/internal', 'failed to store file upload: ' + text, {}, cause=error)
        if self.ctx.get('agents').get(agent.id) is not agent:
            raise RemoteError('session/not-found', 'session "{}" was disposed before its file upload completed'.format(agent.id), dict(sessionId=agent.id))
        staged = self._staged.setdefault(agent.session, {})
        receipt = str(uuid.uuid4())
        staged[receipt] = dict(file=file)
        return dict(receiptId=receipt, file=file)

    def _observe(self, session, event):
        if event['type'] == 'user/message':
            source = event['data']['source']
            if source.get('kind') == 'user' and isinstance(source.get('rpcId'), str):
                self._retire(session, source['rpcId'])

    def _retire(self, session, request_id):
        staged = self._staged.get(session)
        if staged is None:
            return
        for receipt_id, upload in list(staged.items()):
            if upload.get('requestId') == request_id:
                del staged[receipt_id]
        if not staged:
            self._staged.pop(session, None)


async def handle_file_upload_http(service, request):
    if request['method'] != 'POST':
        return response(405, '', {'allow': 'POST'})
    media_type = trim_js(request.get('headers', {}).get('content-type', '').split(';', 1)[0]).lower()
    if media_type != 'application/octet-stream':
        return response(415, 'content type must be application/octet-stream')
    query = parse_qs(urlsplit(request['url']).query, keep_blank_values=True)
    session_id = query.get('sessionId', [None])[0]
    if session_id in (None, ''):
        return response(400, 'sessionId is required')
    async def chunks():
        body = request.get('body')
        if body is None:
            return
        if hasattr(body, '__aiter__'):
            async for chunk in body:
                yield chunk
        elif body:
            yield body
    try:
        upload = dict(sessionId=session_id, data=chunks(),
            **({'signal': request['signal']} if 'signal' in request else {}),
            **({'name': query['name'][0]} if 'name' in query else {}))
        result = dict(ok=True, value=await service.uploadImageStream(dict(upload, mediaType=query['mediaType'][0]))
            if 'mediaType' in query else await service.uploadStream(upload))
    except Exception as error:
        failure = remote_error_of(error)
        result = dict(ok=False, error=failure if failure is not None else dict(code='gateway/internal', message=str(error), details={}))
    return response(200, stringify_json(result), {'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store'})
