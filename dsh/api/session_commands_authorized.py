"""Current prompt admission: durable first receipts, caller source and retries."""
import weakref
from dsh.api.session_commands_current import CurrentSessionCommands, error_text
from dsh.api.session_continuation import CONTINUATION
from dsh.attachment.error import AttachmentError
from dsh.core.session.json import UNDEFINED
from dsh.llm.message import create_user_message
from dsh.typert.remote import RemoteError, remote_error_of


def resolve_prompt_receipts(content, staged):
    resolved, receipts = [], []
    for part in content:
        if part['type'] != 'file':
            resolved.append(part)
            continue
        attachment = staged(part['receiptId'])
        if attachment is None or attachment is UNDEFINED:
            raise RemoteError('session/attachment-invalid', 'File was not uploaded for this session.', dict(reason='FILE_NOT_STAGED'))
        resolved.append(attachment)
        if part['receiptId'] not in receipts:
            receipts.append(part['receiptId'])
    return resolved, receipts


class AuthorizedSessionCommands(CurrentSessionCommands):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prompt_receipts = weakref.WeakKeyDictionary()

    async def initialize(self):
        self.continuation = await self.ctx.get('sessionProjections').register(CONTINUATION)

    def has_prompt_request(self, session, request_id):
        receipts = self.prompt_receipts.setdefault(session, dict(offset=0, messages=set(), requests=set()))
        if receipts['offset'] != session.seq:
            for event in session.snapshotEvents(receipts['offset']):
                if event['type'] not in ('agent/inbox/spliced', 'user/message'):
                    continue
                messages = event['data']['inserted'] if event['type'] == 'agent/inbox/spliced' else [event['data']]
                for message in messages:
                    if message['id'] in receipts['messages']:
                        continue
                    receipts['messages'].add(message['id'])
                    if event['seq'] < session.inheritedEventCount:
                        continue
                    source = message['source']
                    if source['kind'] in ('user', 'retry') and 'rpcId' in source:
                        receipts['requests'].add(source['rpcId'])
            receipts['offset'] = session.seq
        return request_id in receipts['requests']

    async def prompt(self, request, source):
        agent = await self.resolve_agent(request['sessionId'])
        if self.has_prompt_request(agent.session, request['requestId']):
            return dict(accepted=True)
        if not request['content']:
            try:
                def retry(*_):
                    inbox = agent.inbox
                    if (request['mode'] != 'queue' or self.continuation.stateOf(agent.session)['ending'] is None or
                        inbox.nextTurn or any(message['source']['kind'] == 'user' for message in inbox.nextStep)):
                        raise RemoteError('session/agent-busy', 'generation continuation is unavailable', dict(reason='NO_CONTINUABLE_FAILURE_OR_PENDING_INPUT'))
                    agent.followup(create_user_message(dict(content=[], source=source)))
                    return dict(accepted=True)
                return await agent.runMaintenance(retry)
            except Exception as error:
                if remote_error_of(error) is not None:
                    raise
                raise RemoteError('session/agent-busy', 'generation continuation was not accepted', dict(reason=error_text(error))) from None
        content, receipts = resolve_prompt_receipts(request['content'], lambda identity:self.ctx.get('fileUploads').resolve(agent, identity))
        has_image = any(part['type'] == 'image' for part in content)
        async def admit():
            try:
                if self.has_prompt_request(agent.session, request['requestId']):
                    return dict(accepted=True)
                if has_image:
                    current = agent.model.current()
                    if current is not UNDEFINED and current is not None:
                        model = await self.ctx.get('llm').resolveModelInfo(current['provider'], current['model'])
                        if 'inputModalities' in model and 'image' not in model['inputModalities']:
                            raise RemoteError('session/attachment-invalid', 'Model "{}" does not support image input.'.format(current['model']), dict(reason='MODEL_DOES_NOT_SUPPORT_IMAGES'))
                admitted = await self.ctx.get('attachments').admitPromptContent(content)
                if self.has_prompt_request(agent.session, request['requestId']):
                    return dict(accepted=True)
                message = create_user_message(dict(content=admitted, source=source))
                if self.ctx.get('agents').get(agent.id) is not agent:
                    raise RemoteError('session/not-found', 'session "{}" was disposed during prompt admission'.format(agent.id), dict(sessionId=agent.id))
                binding = self.ctx.get('fileUploads').bindPrompt(agent, receipts, request['requestId'])
                try:
                    (agent.steer if request['mode'] == 'steer' else agent.followup)(message)
                    binding.commit()
                finally:
                    binding.dispose()
            except Exception as error:
                if self.has_prompt_request(agent.session, request['requestId']):
                    return dict(accepted=True)
                if remote_error_of(error) is not None:
                    raise
                if isinstance(error, AttachmentError):
                    raise RemoteError('session/attachment-invalid', error.message, dict(reason=error.code)) from None
                raise RemoteError('session/agent-busy', 'prompt rejected', dict(reason=error_text(error))) from None
            return dict(accepted=True)
        return await self.agents.serializeImageAdmission(agent, admit) if has_image else await admit()
