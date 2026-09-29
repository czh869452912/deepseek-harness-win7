"""SDK methods and service-owned lifecycle notifications."""
import asyncio
import os

from dsh.attachment.admission import admit_encoded_images
from dsh.core.scope import carrier_key_of
from dsh.cordis.events import AggregateError
from dsh.llm.message import create_user_message


class HarnessSdkJsonRpcServer:
    def __init__(self, ctx, transport, options=None):
        self.ctx, self.transport, self.options = ctx, transport, options or {}
        self.cwd = os.getcwd()
        self.provider = self.model = 'deepseek-official'
        self.call_options = {}
        self.llm_fiber = None
        self.sessions, self.creations = {}, {}
        self.shutdown_task = None
        self.shutting_down = self.initialized = False
        self.disposers = [
            ctx.on('session/event', self.session_event),
            ctx.on('agent/status', self.agent_status),
            ctx.on('session/created', self.session_created),
            ctx.on('subagent/end', self.subagent_end),
        ]

    def session_event(self, session, event):
        self.transport.notify('session.event', dict(sessionId=str(session.id), event=event))

    def agent_status(self, info):
        self.transport.notify('session.status', dict(sessionId=str(info['agent'].session.id), status=info['status']))

    def session_created(self, session):
        parent = getattr(session.header, 'parentSession', None)
        if parent is not None:
            self.transport.notify('subagent.started', dict(parentSessionId=str(parent), childSessionId=str(session.id)))

    def subagent_end(self, info, caller_ctx=None):
        if not info.get('local'):
            return
        key = carrier_key_of(caller_ctx)
        # The Python AgentLoop mints ScopeKey({sessionId}) rather than using
        # the Agent object as its key. Only the service-owned carrier supplies it.
        value = getattr(key, 'value', key)
        parent_id = value.get('sessionId') if isinstance(value, dict) else getattr(getattr(value, 'session', None), 'id', None)
        if parent_id is None:
            raise RuntimeError('subagent/end requires a scoped parent carrier')
        reason = info['stopReason']
        payload = dict(provider=info['provider'], agentId=str(info['id']), parentSessionId=str(parent_id),
                       childSessionId=str(info['id']), stopReason=reason,
                       status='ok' if reason == 'completed' or reason == 'max-tokens' and self.options.get('maxTokensAsSuccess') is True else 'error')
        if 'lastAssistantMessage' in info:
            payload['lastAssistantMessage'] = info['lastAssistantMessage']
        self.transport.notify('subagent.finished', payload)

    async def initialize(self, params):
        effort, cap = params.get('reasoningEffort'), params.get('maxTokens')
        if 'reasoningEffort' in params and (not isinstance(effort, str) or not effort):
            raise TypeError('initialize reasoningEffort must be a non-empty string')
        if 'maxTokens' in params and (type(cap) is not int or not 0 < cap <= 9007199254740991):
            raise TypeError('initialize maxTokens must be a positive safe integer')
        cwd, provider, model = os.path.abspath(params['cwd']), params['provider'], params['model']
        llm = self.ctx.get('llm')
        if llm is None or not any(row['id'] == provider for row in llm.list_providers()):
            if provider != 'deepseek-official':
                raise RuntimeError('no adapter registered for provider "{}"'.format(provider))
            from dsh.llm.llm_deepseek import LLMDeepSeekPlugin
            self.llm_fiber = await self.ctx.plugin(LLMDeepSeekPlugin)
        call = {key: params[key] for key in ('reasoningEffort', 'maxTokens') if key in params}
        llm = self.ctx.get('llm')
        if llm is None:
            raise RuntimeError('SDK initialize requires ctx.llm')
        await llm.resolveCallConfig(dict(provider=provider, model=model, **call))
        self.cwd, self.provider, self.model, self.call_options = cwd, provider, model, call
        self.initialized = True
        return dict(serverInfo=dict(name='deepseek-harness-sdk-runtime', version='0.0.1'))

    def assert_live(self, handle, session_id):
        if self.ctx.get('agents').get(handle.agent.id) is not handle.agent:
            raise RuntimeError('session agent was disposed outside the server: ' + session_id)

    async def prompt(self, params):
        if not self.initialized:
            raise RuntimeError('SDK server is not initialized')
        sid = params['sessionId']
        handle = await self.get_or_create(sid)
        self.assert_live(handle, sid)
        content = params['contentBlocks']
        encoded = [block for block in content if block.get('type') == 'image' and 'data' in block]
        if encoded:
            store = self.ctx.get('attachments')
            if store is None:
                raise RuntimeError('SDK image prompt requires an attachment store')
            refs = await asyncio.get_running_loop().run_in_executor(None, admit_encoded_images, store,
                [dict(data=block['data'], mediaType=block['mimeType']) for block in encoded])
            iterator = iter(refs)
            content = [dict(type='image', attachment=next(iterator)) if block.get('type') == 'image' and 'data' in block else block for block in content]
        self.assert_live(handle, sid)
        message = create_user_message(dict(content=content, source=dict(kind='user')))
        handle.agent.followup(message)
        return dict(messageId=message['id'])

    async def get_or_create(self, session_id):
        if self.shutting_down:
            raise RuntimeError('SDK server is shutting down')
        if session_id in self.sessions:
            return self.sessions[session_id]
        task = self.creations.get(session_id)
        if task is None:
            task = asyncio.create_task(self.create_session(session_id))
            self.creations[session_id] = task
            task.add_done_callback(lambda done: self.creations.pop(session_id, None))
        return await asyncio.shield(task)

    async def create_session(self, session_id):
        handle = await self.ctx.get('agents').create(dict(sessionId=session_id, meta=dict(cwd=self.cwd),
            agentOptions=dict(provider=self.provider, model=self.model, **self.call_options)))
        self.sessions[session_id] = handle
        return handle

    async def shutdown(self):
        if self.shutdown_task is None:
            self.shutdown_task = asyncio.create_task(self.perform_shutdown())
        return await asyncio.shield(self.shutdown_task)

    async def perform_shutdown(self):
        self.shutting_down = True
        await asyncio.gather(*list(self.creations.values()), return_exceptions=True)
        self.creations.clear()
        handles, self.sessions = list(self.sessions.values()), {}
        failures = []
        while self.disposers:
            try:
                self.disposers.pop()()
            except Exception as error:
                failures.append(error)
        if self.llm_fiber is not None:
            handles.append(self.llm_fiber)
            self.llm_fiber = None
        results = await asyncio.gather(*(handle.dispose() for handle in handles), return_exceptions=True)
        failures.extend(result for result in results if isinstance(result, Exception))
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise AggregateError(failures)
        return {}

    async def handle_request(self, method, params=None):
        if method == 'initialize':
            return await self.initialize(params or {})
        if method == 'session/prompt':
            return await self.prompt(params or {})
        if method == 'shutdown':
            return await self.shutdown()
        raise RuntimeError('unknown DeepSeek Harness SDK runtime method: ' + method)
