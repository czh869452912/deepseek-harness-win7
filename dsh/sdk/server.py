"""SDK methods and service-owned lifecycle notifications."""
import asyncio
import contextvars
import os

from dsh.attachment.admission import admit_encoded_images
from dsh.cordis.events import AggregateError
from dsh.cordis.awaiting import await_callback_result
from dsh.llm.message import create_user_message
from dsh.core.abort import AbortController
from dsh.session.storage_contract import field
from dsh.sdk.user_questions import SdkUserQuestionBridge, joined_signals
from dsh.sdk.query_input import query_command, query_content, query_command_images, js_trim
from dsh.sdk.query_activity import QueryActivity


class HarnessSdkJsonRpcServer:
    def __init__(self, ctx, transport, options=None):
        self.ctx, self.transport, self.options = ctx, transport, options or {}
        self.cwd = os.getcwd()
        self.provider = self.model = 'deepseek-official'
        self.call_options = {}
        self.llm_fiber = None
        self.sessions, self.creations = {}, {}
        self.failures, self.scheduled_sessions = {}, {}
        self.lifetime = AbortController()
        self.initialization = asyncio.get_event_loop().create_future()
        self.approval_requests = False
        self.command_tasks, self.query_activities = set(), set()
        self.query_invocation = contextvars.ContextVar('sdk.query.activity', default=None)
        self.query_disabled = False
        def goal_watch(scope):
            def unavailable():
                for activity in list(self.query_activities):
                    activity.goalUnavailable()
            scope.effect(lambda: unavailable)
        self.goal_lifetime = ctx.inject(['goals'], goal_watch)
        self.user_questions = SdkUserQuestionBridge(ctx, transport,
            lambda agent: self.sessions.get(agent.session.id) is not None and self.sessions[agent.session.id].agent is agent)
        self.shutdown_task = None
        self.shutting_down = self.initialized = False
        self.disposers = [
            ctx.on('session/event', self.session_event),
            ctx.on('agent/status', self.agent_status),
            ctx.on('session/created', self.session_created),
            ctx.on('subagent/end', self.subagent_end),
            ctx.on('agent/error', self.agent_error),
            ctx.on('schedule/resolve-agent', self.resolve_scheduled_agent),
            ctx.on('approval/request', self.approval_request),
        ]

    def owns_agent(self, agent):
        if self.ctx.get('agents').get(agent.id) is not agent:
            return False
        handle = self.sessions.get(agent.session.id)
        if handle is not None and handle.agent is agent:
            return True
        subagents = self.ctx.get('subagents')
        if subagents is None:
            return False
        try:
            root = subagents.rootOf(agent)
        except Exception as error:
            if getattr(error, 'name', None) == 'SubagentError' and getattr(error, 'code', None) == 'UNAUTHORIZED':
                return False
            raise
        handle = self.sessions.get(root.session.id)
        return handle is not None and handle.agent is root

    async def approval_request(self, request, next_fn):
        if not self.approval_requests or not self.owns_agent(request['agent']):
            return await next_fn()
        params = dict(sessionId=request['agent'].session.id, toolName=request['toolName'])
        params.update({key: request[key] for key in ('callId', 'reason') if key in request})
        signal, detach = joined_signals(request.get('signal'), self.lifetime.signal)
        try:
            result = await self.transport.request('approval/request', params, signal)
            if not isinstance(result, dict) or result.get('outcome') not in ('allowed-once', 'rejected', 'cancelled'):
                raise TypeError('approval/request response requires an allowed-once, rejected, or cancelled outcome')
            return result['outcome']
        finally:
            detach()

    def session_event(self, session, event):
        handle = self.sessions.get(session.id)
        failure = self.failures.get(session.id)
        if (event['type'] == 'turn/end' and handle is not None and handle.agent.session is session
                and failure is not None and event['seq'] >= failure['atOffset']):
            self.failures.pop(session.id, None)
        self.transport.notify('session.event', dict(sessionId=str(session.id), event=event))

    def agent_error(self, info):
        agent = info['agent']
        handle = self.sessions.get(agent.session.id)
        if handle is not None and handle.agent is agent:
            self.failures[agent.session.id] = dict(error=info['error'], atOffset=agent.session.seq)

    def agent_status(self, info):
        self.transport.notify('session.status', dict(sessionId=str(info['agent'].session.id), status=info['status']))

    def session_created(self, session):
        parent = getattr(session.header, 'parentSession', None)
        if getattr(session.header, 'origin', None) == 'subagent' and parent is not None:
            self.transport.notify('subagent.started', dict(parentSessionId=str(parent), childSessionId=str(session.id)))

    def subagent_end(self, info, caller_ctx=None):
        if not info.get('local'):
            return
        reason = info['stopReason']
        payload = dict(provider=info['provider'], agentId=str(info['id']), parentSessionId=str(info['parentSessionId']),
                       childSessionId=str(info['id']), stopReason=reason,
                       status='ok' if reason == 'completed' or reason == 'max-tokens' and self.options.get('maxTokensAsSuccess') is True else 'error')
        if 'lastAssistantMessage' in info:
            payload['lastAssistantMessage'] = list(info['lastAssistantMessage'])
        self.transport.notify('subagent.finished', payload)

    async def initialize(self, params):
        if 'approvalRequests' in params and type(params['approvalRequests']) is not bool:
            raise TypeError('initialize approvalRequests must be a boolean')
        effort, cap = params.get('reasoningEffort'), params.get('maxTokens')
        if 'reasoningEffort' in params and (not isinstance(effort, str) or not effort):
            raise TypeError('initialize reasoningEffort must be a non-empty string')
        if 'maxTokens' in params and (type(cap) not in (int, float) or not 0 < cap <= 9007199254740991 or int(cap) != cap):
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
        self.approval_requests = params.get('approvalRequests') is True
        capabilities = params.get('capabilities')
        self.user_questions.enabled = isinstance(capabilities, dict) and capabilities.get('userQuestions') is True
        if not self.initialization.done():
            self.initialization.set_result(None)
        return dict(serverInfo=dict(name='deepseek-harness-sdk-runtime', version='0.0.1'))

    def assert_live(self, handle, session_id):
        if self.ctx.get('agents').get(handle.agent.id) is not handle.agent:
            raise RuntimeError('session agent was disposed outside the server: ' + session_id)

    async def prompt(self, params):
        if not self.initialized:
            raise RuntimeError('SDK server is not initialized')
        sid = params['sessionId']
        handle = await self.get_or_create(sid)
        self.lifetime.signal.throwIfAborted()
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
        self.lifetime.signal.throwIfAborted()
        self.assert_live(handle, sid)
        message = create_user_message(dict(content=content, source=dict(kind='user')))
        handle.agent.followup(message)
        return dict(messageId=message['id'])

    async def get_or_create(self, session_id):
        if self.shutting_down:
            raise RuntimeError('SDK server is shutting down')
        self.scheduled_sessions.pop(session_id, None)
        if session_id in self.sessions:
            return self.sessions[session_id]
        task = self.creations.get(session_id) or self.open_session(session_id, False)
        return await asyncio.shield(task)

    async def query(self, params):
        if not self.initialized:
            raise RuntimeError('SDK server is not initialized')
        if self.shutting_down:
            raise RuntimeError('SDK server is shutting down')
        text = next((block for block in params['contentBlocks'] if block['type'] == 'text'), None)
        if text is not None and js_trim(text['text']).startswith('/'):
            commands = self.ctx.get('commands')
            if commands is not None:
                handle = await self.get_or_create(params['sessionId'])
                self.lifetime.signal.throwIfAborted()
                self.assert_live(handle, params['sessionId'])
                line = query_command(text['text'], commands.list(handle.agent))
                if line is not None:
                    images = query_command_images(params['contentBlocks'], text)
                    activity = QueryActivity(self.ctx, handle.agent, self.transport,
                        lambda: not self.query_disabled and self.query_invocation.get() is activity,
                        self.lifetime.signal, self.query_activities.discard)
                    self.query_activities.add(activity)
                    try:
                        token = self.query_invocation.set(activity)
                        try:
                            task = asyncio.create_task(commands.execute(handle.agent, line,
                                [dict(type='image', data=image['data'], mediaType=image['mimeType'],
                                      **({} if 'name' not in image else dict(name=image['name']))) for image in images], self.lifetime.signal))
                        finally:
                            self.query_invocation.reset(token)
                        self.command_tasks.add(task)
                        def settled(done):
                            self.command_tasks.discard(done)
                            if not done.cancelled():
                                done.exception()
                        task.add_done_callback(settled)
                        execution = await asyncio.shield(task)
                        if execution is None:
                            raise RuntimeError('The selected command is unavailable in this SDK profile')
                        dto = dict(commandId=field(execution, 'commandId'), result=field(execution, 'result'))
                        activity.accept(dto)
                        return dict(kind='command', execution=dto)
                    except BaseException:
                        activity.close()
                        raise
        receipt = await self.prompt(dict(sessionId=params['sessionId'], contentBlocks=params['contentBlocks']))
        return dict(kind='prompt', **receipt)

    def open_session(self, session_id, resume):
        task = asyncio.create_task(self.create_session(session_id, resume))
        self.creations[session_id] = task
        def settled(done):
            self.creations.pop(session_id, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(settled)
        return task

    async def create_session(self, session_id, resume=False):
        persistence = self.ctx.get('sessionPersistence')
        if resume and persistence is not None:
            stored = await persistence.stat(session_id)
            if stored is not None and field(field(stored, 'header'), 'origin') == 'subagent':
                raise RuntimeError('subagent session "%s" cannot be resumed directly; resume its root session instead' % session_id)
        options = dict(provider=self.provider, model=self.model, **self.call_options)
        if resume:
            def setup(_ctx, agent):
                previous = agent.model.current()
                selection = dict(options)
                if ('reasoningEffort' not in selection and previous is not None
                        and previous['provider'] == selection['provider'] and previous['model'] == selection['model']
                        and 'reasoningEffort' in previous):
                    selection['reasoningEffort'] = previous['reasoningEffort']
                agent.model.select(selection)
            handle = await self.ctx.get('agents').resume(dict(resumeSessionId=session_id, agentOptions=options, setup=setup))
        else:
            handle = await self.ctx.get('agents').create(dict(sessionId=session_id, meta=dict(cwd=self.cwd), agentOptions=options))
        self.sessions[session_id] = handle
        self.failures.pop(session_id, None)
        return handle

    async def resume(self, params):
        if not self.initialized:
            raise RuntimeError('SDK server is not initialized')
        if self.shutting_down:
            raise RuntimeError('SDK server is shutting down')
        session_id = params['sessionId']
        restoration = self.scheduled_sessions.pop(session_id, None)
        if restoration is not None:
            self.assert_live(await asyncio.shield(restoration), session_id)
            return {}
        if session_id in self.sessions or session_id in self.creations:
            raise RuntimeError('SDK session is already open or opening: ' + session_id)
        await asyncio.shield(self.open_session(session_id, True))
        return {}

    async def wait(self, params):
        if not self.initialized:
            raise RuntimeError('SDK server is not initialized')
        session_id = params['sessionId']
        handle = self.sessions.get(session_id)
        if handle is None:
            raise RuntimeError('unknown SDK session: ' + session_id)
        agent = handle.agent
        subagents = self.ctx.get('subagents')
        while True:
            self.assert_live(handle, session_id)
            await agent.whenIdle()
            sequence = agent.session.seq
            children = await subagents.waitForTreeWork(agent) if subagents is not None else None
            self.assert_live(handle, session_id)
            if not children and agent.status == 'idle' and agent.session.seq == sequence:
                failure = self.failures.get(session_id)
                if failure is not None:
                    raise failure['error']
                return {}

    async def resolve_scheduled_agent(self, session_id):
        await asyncio.shield(self.initialization)
        if self.shutting_down:
            raise RuntimeError('SDK server is shutting down')
        existing = self.sessions.get(session_id)
        if existing is not None:
            self.assert_live(existing, session_id)
            return existing.agent
        pending = self.creations.get(session_id)
        if pending is not None:
            return (await asyncio.shield(pending)).agent
        restoration = self.open_session(session_id, True)
        self.scheduled_sessions[session_id] = restoration
        try:
            return (await asyncio.shield(restoration)).agent
        except Exception:
            self.scheduled_sessions.pop(session_id, None)
            raise

    async def working_directory_agent(self, session_id):
        if not self.initialized:
            raise RuntimeError('SDK server is not initialized')
        handle = await self.get_or_create(session_id)
        self.assert_live(handle, session_id)
        return handle.agent

    async def getWorkingDirectory(self, params):
        agent = await self.working_directory_agent(params['sessionId'])
        return dict(cwd=await self.ctx.get('workingDirectory').ensure(agent))

    async def setWorkingDirectory(self, params):
        agent = await self.working_directory_agent(params['sessionId'])
        return dict(cwd=await self.ctx.get('workingDirectory').set(agent, params['path']))

    async def shutdown(self):
        if self.shutdown_task is None:
            self.shutdown_task = asyncio.create_task(self.perform_shutdown())
        return await asyncio.shield(self.shutdown_task)

    async def perform_shutdown(self):
        self.shutting_down = True
        self.lifetime.abort(RuntimeError('SDK server is shutting down'))
        self.user_questions.close()
        if not self.initialization.done():
            self.initialization.set_result(None)
        await await_callback_result(asyncio.gather(*list(self.creations.values()), return_exceptions=True))
        await asyncio.gather(*list(self.command_tasks), return_exceptions=True)
        self.query_disabled = True
        self.creations.clear()
        self.scheduled_sessions.clear()
        handles, self.sessions = list(self.sessions.values()), {}
        self.failures.clear()
        failures = []
        while self.disposers:
            try:
                self.disposers.pop()()
            except Exception as error:
                failures.append(error)
        if self.llm_fiber is not None:
            handles.append(self.llm_fiber)
            self.llm_fiber = None
        subagents = self.ctx.get('subagents')
        if subagents is not None:
            try:
                await subagents.drainDescendants([handle.agent for handle in handles if hasattr(handle, 'agent')])
            except Exception as error:
                failures.append(error)
        results = await asyncio.gather(self.goal_lifetime.dispose(), *(handle.dispose() for handle in handles), return_exceptions=True)
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
        if method == 'session/query':
            value = params or {}
            if (not isinstance(value, dict) or not isinstance(value.get('sessionId'), str)
                    or not value['sessionId'] or set(value) - {'sessionId', 'contentBlocks'}):
                raise TypeError('session/query requires only a non-empty sessionId and contentBlocks')
            return await self.query(dict(sessionId=value['sessionId'], contentBlocks=query_content(value.get('contentBlocks'))))
        if method == 'session/resume':
            value = params or {}
            if not isinstance(value, dict) or not isinstance(value.get('sessionId'), str) or not value['sessionId']:
                raise TypeError('session/resume requires a non-empty sessionId string')
            return await self.resume(dict(sessionId=value['sessionId']))
        if method == 'session/wait':
            value = params or {}
            if not isinstance(value, dict) or not isinstance(value.get('sessionId'), str):
                raise TypeError('session/wait requires a sessionId string')
            return await self.wait(dict(sessionId=value['sessionId']))
        if method in ('session/working-directory/get', 'session/working-directory/set'):
            value = params or {}
            if not isinstance(value, dict) or not isinstance(value.get('sessionId'), str) or not value['sessionId']:
                raise TypeError('working-directory requests require a non-empty sessionId')
            if method == 'session/working-directory/get':
                return await self.getWorkingDirectory(dict(sessionId=value['sessionId']))
            if not isinstance(value.get('path'), str):
                raise TypeError('working-directory set requires a path string')
            return await self.setWorkingDirectory(dict(sessionId=value['sessionId'], path=value['path']))
        if method == 'shutdown':
            return await self.shutdown()
        raise RuntimeError('unknown DeepSeek Harness SDK runtime method: ' + method)
