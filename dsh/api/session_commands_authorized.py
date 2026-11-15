"""Current prompt admission: durable first receipts, caller source and retries."""
import asyncio
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
        self.default_saves = set()

    async def initialize(self):
        self.continuation = await self.ctx.get('sessionProjections').register(CONTINUATION)
        self.ctx.effect(lambda: self.drain_default_saves, 'session-controller.default-model-saves')

    async def drain_default_saves(self):
        await asyncio.gather(*list(self.default_saves), return_exceptions=True)

    async def create(self, request):
        from dsh.api.session_agents_current import ApiSessionPresetConflict, ApiSessionCwdConflict, ApiSessionSubagentOwnership
        from dsh.api.session_commands_current import ownership_error
        if 'workspaceId' in request and 'cwd' in request:
            raise RemoteError('gateway/bad-request', 'session.create accepts workspaceId or cwd, not both', {})
        registry = self.ctx.get('workspaceRegistry')
        workspace = registry.get(request['workspaceId']) if 'workspaceId' in request else None
        if 'workspaceId' in request and workspace is None:
            raise RemoteError('workspace/not-found', 'workspace "{}" not found'.format(request['workspaceId']), dict(workspaceId=request['workspaceId']))
        cwd = workspace.path if workspace is not None else request.get('cwd', self.default_cwd)
        try:
            created = await self.agents.createSession(dict(
                {key: request[key] for key in ('sessionId', 'agentPreset') if key in request}, cwd=cwd,
                reusable=lambda sid: sid not in registry.archivedSessionIds and (workspace is None or sid in workspace.sessionIds)))
        except Exception as error:
            if remote_error_of(error) is not None:
                raise
            if isinstance(error, ApiSessionPresetConflict):
                raise RemoteError('agent-preset/conflict', str(error), dict(sessionId=error.sessionId, requestedPreset=error.requestedPreset)) from None
            if isinstance(error, ApiSessionCwdConflict):
                details = dict(sessionId=error.sessionId, requestedCwd=error.requestedCwd)
                if error.existingCwd is not None:
                    details['existingCwd'] = error.existingCwd
                raise RemoteError('session/conflict', str(error), details) from None
            if isinstance(error, ApiSessionSubagentOwnership):
                raise ownership_error(error.sessionId) from None
            raise RemoteError('gateway/internal', 'failed to create session: ' + error_text(error), {}) from None
        sid = created['agent'].id
        if workspace is not None:
            try:
                await workspace.attachSession(sid)
            except Exception as error:
                raise RemoteError('session/workspace-attach-failed', 'session "{}" was created but could not attach to workspace "{}": {}'.format(sid, workspace.id, error_text(error)), dict(sessionId=sid, workspaceId=workspace.id)) from None
        return dict(sessionId=sid, **(dict(agentPreset=created['agentPreset']) if created['agentPreset'] is not None else {}))

    async def selectModel(self, request):
        agent = await self.resolve_agent(request['sessionId'])
        async def select():
            try:
                llm = self.ctx.get('llm')
                available = any(provider['id'] == request['provider'] for provider in llm.listProviders())
                if available:
                    available = any(model['id'] == request['model'] for model in await llm.listModels(request['provider']))
                if not available:
                    raise RemoteError('session/model-unavailable', 'Select an available model before sending a message.', dict(provider=request['provider'], model=request['model']))
                selected = {key: request[key] for key in ('provider', 'model', 'reasoningEffort') if key in request}
                await llm.resolveCallConfig(selected)
                agent.model.select(selected)
                async def save():
                    try:
                        await self.ctx.get('agentDefaultModel').saveSelection(selected)
                    except Exception as error:
                        self.ctx.logger.warn('session-controller: model selection changed for the Session but the default was not saved: ' + error_text(error))
                task = asyncio.ensure_future(save())
                self.default_saves.add(task)
                task.add_done_callback(self.default_saves.discard)
                return dict(selected=dict(selected))
            except Exception as error:
                if remote_error_of(error) is not None:
                    raise
                raise RemoteError('session/model-unavailable', getattr(error, 'message', str(error)), dict(provider=request['provider'], model=request['model'])) from None
        return await self.agents.serializeImageAdmission(agent, select)

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
