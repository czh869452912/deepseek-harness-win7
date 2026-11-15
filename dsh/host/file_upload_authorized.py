"""Session-owned typed file/image receipts for the rc.2.2 upload protocol."""
import inspect
import uuid
import weakref

from dsh.host.file_upload_current import CurrentFileUploads, FILE_UPLOAD_PATH, handle_file_upload_http
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService, remote_error_of


class AuthorizedFileUploads(CurrentFileUploads):
    def __init__(self, ctx, config=None):
        TypertRemoteService.__init__(self, ctx, 'fileUploads')
        self._staged = weakref.WeakKeyDictionary()
        self._resolver = {'value': None}

        def command_receipt(agent, receipt_id):
            staged = self.resolve(agent, receipt_id)
            return staged['attachment'] if staged is not None and staged['type'] == 'file' else None

        ctx.effect(lambda: ctx.get('commands').registerFileReceiptResolver(command_receipt), 'file-upload: command file receipt resolver')
        ctx.effect(lambda: ctx.get('connection').fetch.register(dict(path=FILE_UPLOAD_PATH, methods=['POST'],
            requestBody='streaming', fetch=lambda request: handle_file_upload_http(self, request))), 'file-upload: streaming route')
        ctx.on('session/event', self._observe)
        ctx.on('session/disposed', lambda session: self._staged.pop(session, None))

    @staticmethod
    def _assert_scope(agent):
        # Identity is the receiving Agent's exact Session, independent of calling Context.
        pass

    def resolve(self, agent, receipt_id):
        return self._staged.get(agent.session, {}).get(receipt_id, {}).get('attachment')

    async def resolve_agent(self, session_id):
        agent = self.ctx.get('agents').get(session_id)
        if agent is not None:
            return agent
        resolver = self._resolver['value']
        if resolver is None:
            raise RemoteError('session/not-found', 'session "{}" is not attached'.format(session_id), dict(sessionId=session_id))
        result = resolver(session_id)
        return await result if inspect.isawaitable(result) else result

    async def store(self, agent, save):
        if getattr(agent.session.header, 'origin', None) == 'subagent':
            raise RemoteError('subagent/attachment-invalid', 'subagent conversations do not accept file uploads',
                dict(reason='SUBAGENT_FILE_UNSUPPORTED'))
        try:
            return await save()
        except Exception as error:
            if remote_error_of(error) is not None:
                raise
            if self.ctx.get('attachments').isAttachmentError(error):
                raise RemoteError('session/attachment-invalid', error.message, dict(reason=error.code)) from None
            text = getattr(error, 'name', 'Error') + ': ' + str(error)
            raise RemoteError('gateway/internal', 'failed to store file upload: ' + text, {}, cause=error) from None

    def stage(self, agent, attachment):
        if self.ctx.get('agents').get(agent.id) is not agent:
            raise RemoteError('session/not-found', 'session "{}" was disposed before its file upload completed'.format(agent.id), dict(sessionId=agent.id))
        receipt = str(uuid.uuid4())
        self._staged.setdefault(agent.session, {})[receipt] = dict(attachment=attachment)
        return receipt

    @Remote('upload')
    async def upload(self, agent, request, signal):
        signal.throwIfAborted()
        file = await self.store(agent, lambda: self.ctx.get('attachments').admitEncodedFile(
            {key: request[key] for key in ('data', 'name') if key in request}))
        return dict(receiptId=self.stage(agent, dict(type='file', attachment=file)), file=file)

    async def uploadStream(self, request):
        agent = await self.resolve_agent(request['sessionId'])
        file = await self.store(agent, lambda: self.ctx.get('attachments').saveFileStream(
            {key: request[key] for key in ('data', 'signal', 'name') if key in request}))
        return dict(receiptId=self.stage(agent, dict(type='file', attachment=file)), file=file)

    async def uploadImageStream(self, request):
        agent = await self.resolve_agent(request['sessionId'])
        limits = self.ctx.get('attachments').imageLimits
        media_type = request['mediaType']
        if media_type not in limits['mediaTypes']:
            raise RemoteError('session/attachment-invalid', 'Image type {} is not accepted by this deployment.'.format(media_type),
                dict(reason='UNSUPPORTED_IMAGE_TYPE'))

        async def save():
            data = await read_at_most(request['data'], min(limits['maxImageBytes'], limits['maxMessageImageBytes']), request.get('signal'))
            signal = request.get('signal')
            if signal is not None:
                signal.throwIfAborted()
            refs = await self.ctx.get('attachments').saveImages([dict(data=data, mediaType=media_type,
                **({'name': request['name']} if 'name' in request else {}))])
            if signal is not None:
                signal.throwIfAborted()
            return dict(type='image', attachment=refs[0], encodedBytes=len(data))

        staged = await self.store(agent, save)
        return dict(receiptId=self.stage(agent, staged), image=staged['attachment'])


async def read_at_most(chunks, limit, signal=None):
    parts, length = [], 0
    async for chunk in chunks:
        if signal is not None:
            signal.throwIfAborted()
        length += len(chunk)
        if length > limit:
            raise RemoteError('session/attachment-invalid', 'Image exceeds the configured byte limit.', dict(reason='IMAGE_TOO_LARGE'))
        parts.append(chunk)
    return b''.join(parts)
