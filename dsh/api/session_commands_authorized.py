"""Current prompt admission: durable first receipts, caller source and retries."""
import asyncio
import weakref
import uuid
from dsh.api.session_commands_current import CurrentSessionCommands, error_text
from dsh.api.session_continuation import CONTINUATION
from dsh.attachment.error import AttachmentError
from dsh.core.session.json import UNDEFINED
from dsh.core.session.fork import build_fork_seed
from dsh.core.session.types import SessionSeq
from dsh.cordis.utils import js_to_string
from dsh.session.session_query import SessionQueryError
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


def latest_completed_prefix_boundary(events):
    ending = next((event for event in reversed(events) if event['type'] == 'turn/end'), None)
    if ending is None:
        return None
    boundary = ending['seq']
    for event in events[int(boundary) + 1:]:
        if (event['type'] in ('turn/start', 'agent/inbox/spliced')
                or event['type'] == 'user/message' and event.get('surfaceOp') == 'append'):
            break
        boundary = event['seq']
    return boundary


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

    async def fork(self, request):
        try:
            at_seq = SessionSeq(request['atSeq']) if 'atSeq' in request else None
        except (ValueError, TypeError):
            raise RemoteError('gateway/bad-request', 'atSeq must be a non-negative safe integer', {}) from None
        sid = request['sessionId']
        try:
            source = await self.ctx.get('sessionQuery').observeSession(sid)
        except Exception as error:
            if isinstance(error, SessionQueryError) and error.code == 'SESSION_QUERY_SESSION_NOT_FOUND':
                raise RemoteError('session/not-found', 'session "{}" not found'.format(sid), dict(sessionId=sid)) from None
            raise RemoteError('gateway/internal', 'fork source unavailable for session "{}": {}'.format(sid, error_text(error)), {}) from None
        try:
            boundary = latest_completed_prefix_boundary(source.events) if at_seq is None else at_seq
            if boundary is None or boundary >= len(source.events) or source.events[int(boundary)]['seq'] != boundary:
                message = ('session "{}" has no completed turn to fork from'.format(sid) if at_seq is None else
                    'event {} does not exist in session "{}" (last seq: {})'.format(js_to_string(at_seq), sid,
                        js_to_string(source.events[-1]['seq']) if source.events else 'none'))
                raise RemoteError('session/fork-unavailable', message, dict(sessionId=sid))
            seed = build_fork_seed(source.events, boundary)
            try:
                workspace = await self.fork_workspace(source.header)
            except Exception as error:
                raise RemoteError('gateway/internal', 'failed to resolve fork workspace for session "{}": {}'.format(sid, error_text(error)), {}) from None
            child_id = 'session-' + str(uuid.uuid4())
            composition = await self.agents.composeAgent(self.agents.presetForObservation(source))
            try:
                model = self.ctx.get('agentDefaultModel').currentSelection()
                meta = dict(isSeeded=True)
                if source.header.cwd is not None:
                    meta['cwd'] = source.header.cwd
                if composition.get('agentPreset') is not None:
                    meta['agentPreset'] = composition['agentPreset']
                await self.ctx.get('agents').create(dict(sessionId=child_id, seed=seed, inheritedEventCount=boundary + 1,
                    meta=meta, agentOptions=dict(provider=model['provider'], model=model['model']), setup=composition['setup']))
            except Exception as error:
                raise RemoteError('gateway/internal', 'failed to fork session "{}": {}'.format(sid, error_text(error)), {}) from None
            if workspace is not None:
                try:
                    await workspace.attachSession(child_id)
                except Exception as error:
                    raise RemoteError('session/workspace-attach-failed', 'session "{}" was forked but could not attach to workspace "{}": {}'.format(child_id, workspace.id, error_text(error)), dict(sessionId=child_id, workspaceId=workspace.id)) from None
            return dict(sessionId=child_id)
        finally:
            source.dispose()

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
