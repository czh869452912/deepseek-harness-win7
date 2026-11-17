"""Python 3.8/Win7 SDK process ownership for the canonical JSON-RPC wire.

Like the upstream SDK client this lives outside Cordis and owns its process
directly. Pipe polling uses Win7 PeekNamedPipe through StdioInput; no modern
Windows asyncio pipe APIs or third-party runtime dependencies are required.
"""
import asyncio
import codecs
from collections import deque
import os
from pathlib import Path
import subprocess
import sys
import uuid
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.errors import AggregateError
from dsh.cordis.json_text import stringify_json
from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise, SharedPromise
from dsh.core.session.json import UNDEFINED
from .errors import TransportClosedError, RequestTimeoutError, SdkProtocolError, JsonRpcResponseError
from .stdio import StdioInput
from .transport import JsonRpcLineTransport


def resolve_dsh_launch(options, caller_cwd=None):
    """Native equivalent of same-package SDK CLI resolution and profile argv."""
    caller_cwd = caller_cwd or os.getcwd()
    resolve = lambda path: os.path.abspath(os.path.join(caller_cwd, path))
    entry = resolve(options['dshBin']) if 'dshBin' in options else str(Path(__file__).resolve().parents[2] / 'dsh.py')
    args = [entry, '--profile', options.get('profile', 'sdk')]
    for patch in options.get('patches', []):
        args.extend(['--patch', resolve(patch)])
    home = resolve(options['dshHome']) if 'dshHome' in options else None
    def environment():
        env = dict(options.get('env', os.environ))
        if home is not None:
            env['DSH_HOME'] = home
        return env
    runtime = dict(command=sys.executable, args=args, environment=environment,
        description='dsh profile ' + stringify_json(options.get('profile', 'sdk')), initializeTimeoutMs=options.get('initializeTimeoutMs', 10000))
    if 'processCwd' in options:
        runtime['cwd'] = resolve(options['processCwd'])
    for key in ('requestTimeoutMs', 'shutdownTimeoutMs', 'disposeEofGraceMs', 'disposeGraceMs'):
        if key in options:
            runtime[key] = options[key]
    return runtime


class NotificationSubscription:
    def __init__(self, client, predicate):
        self.client, self.predicate = client, predicate
        self.queue, self.waiters, self.failure = deque(), deque(), None

    async def next(self):
        if self.queue:
            return self.queue.popleft()
        if self.failure is not None:
            raise self.failure
        waiter = asyncio.get_running_loop().create_future()
        self.waiters.append(waiter)
        try:
            return await waiter
        finally:
            if waiter in self.waiters:
                self.waiters.remove(waiter)

    def tryNext(self):
        return self.queue.popleft() if self.queue else UNDEFINED

    def fail(self, error):
        if self.failure is None:
            self.failure = error
        while self.waiters:
            waiter = self.waiters.popleft()
            if not waiter.done():
                waiter.set_exception(self.failure)

    def close(self):
        self.client.subscriptions.discard(self)
        self.queue.clear()
        self.fail(TransportClosedError('notification subscription closed'))

    def push(self, notification):
        try:
            matches = self.predicate is None or self.predicate(notification)
        except Exception as error:
            self.client.subscriptions.discard(self)
            self.fail(error)
            return
        if not matches or self.failure is not None:
            return
        while self.waiters:
            waiter = self.waiters.popleft()
            if not waiter.done():
                waiter.set_result(notification)
                return
        self.queue.append(notification)

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.next()


class _Output:
    def __init__(self, stream):
        self.stream = stream

    def write(self, text):
        self.stream.write(text.encode('utf-8'))

    def flush(self):
        self.stream.flush()


class _ClientTransport(JsonRpcLineTransport):
    def drain_lines(self):
        # Start each frame eagerly, preserving same-pipe notification/response
        # ordering, including the final frame immediately before EOF.
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line.strip():
                task = start_coroutine(self.handle_line(line.strip()))
                self.tasks.add(task)
                task.add_done_callback(self.retire)


class HarnessClient:
    def __init__(self, options=None, runtime=None):
        self.options = options or {}
        self.runtime = runtime if runtime is not None else resolve_dsh_launch(self.options)
        self.child = self.transport = self.input = self.stderr_input = None
        self.stderr_tail = deque(maxlen=400)
        self.stderr_buffer = ''
        self.stderr_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.subscriptions, self.session_parents, self.user_questions = set(), {}, {}
        self.exit_code, self.spawn_error = UNDEFINED, None
        self.close_task = self.monitor = None
        self.streams_settled = asyncio.Event()
        self.request_handler = None

    def start(self):
        if self.close_task is not None:
            raise TransportClosedError('DeepSeek Harness runtime client is closed')
        if self.child is not None:
            return
        try:
            self.child = subprocess.Popen([self.runtime['command']] + list(self.runtime['args']), cwd=self.runtime.get('cwd'),
                env=self.runtime['environment'](), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)
        except OSError as error:
            self.spawn_error = error
            self._fail_subscriptions(self._closed_error('DeepSeek Harness runtime failed to start'))
            raise self._closed_error('DeepSeek Harness runtime failed to start')
        self.input, self.stderr_input = StdioInput(self.child.stdout), StdioInput(self.child.stderr)
        self.transport = _ClientTransport(self.input, _Output(self.child.stdin))
        self.transport.on_request(self._runtime_request)
        self.transport.on_notification(self._notification)
        self.transport.start()
        self.stderr_input.on('data', self._stderr_data)
        self.stderr_input.on('end', self._stderr_end)
        self.monitor = asyncio.create_task(self._watch_exit())

    def _stderr_data(self, chunk):
        self.stderr_buffer += self.stderr_decoder.decode(chunk)
        while '\n' in self.stderr_buffer:
            line, self.stderr_buffer = self.stderr_buffer.split('\n', 1)
            if line:
                self.stderr_tail.append(line)

    def _stderr_end(self):
        self.stderr_buffer += self.stderr_decoder.decode(b'', final=True)
        if self.stderr_buffer:
            self.stderr_tail.append(self.stderr_buffer)
        self.stderr_buffer = ''

    async def _watch_exit(self):
        while self.child.poll() is None:
            await asyncio.sleep(.01)
        self.exit_code = self.child.returncode
        self._fail_subscriptions(self._closed_error('DeepSeek Harness runtime exited'))
        # Let the readers consume final responses and the non-newline stderr
        # tail before closing the transport, just as Node's close edge does.
        for reader in (self.input, self.stderr_input):
            if reader.task is not None:
                await asyncio.gather(reader.task, return_exceptions=True)
        self.transport.close()
        self.streams_settled.set()

    async def _settle_streams(self):
        try:
            await asyncio.wait_for(self.streams_settled.wait(), .1)
        except asyncio.TimeoutError:
            pass

    def _closed_error(self, reason):
        parts = [self.runtime['description'] + ': ' + reason]
        if self.spawn_error is not None:
            parts.append('spawn error: ' + str(self.spawn_error))
        if self.exit_code is not UNDEFINED:
            parts.append('exit code: ' + str(self.exit_code))
        if self.stderr_tail:
            parts.append('stderr tail:\n' + '\n'.join(self.stderr_tail))
        return TransportClosedError('\n'.join(parts))

    def _fail_subscriptions(self, error):
        for controller in list(self.user_questions.values()):
            controller.abort(error)
        for subscription in list(self.subscriptions):
            subscription.fail(error)

    def _notification(self, method, params):
        if method == 'user-question.cancelled':
            controller = self.user_questions.get(params.get('requestId'))
            if controller is not None:
                controller.abort(RuntimeError('SDK runtime cancelled the user question'))
        if method == 'subagent.started':
            parent, child = params.get('parentSessionId'), params.get('childSessionId')
            if isinstance(parent, str) and parent and isinstance(child, str) and child and child != parent:
                self.session_parents[child] = parent
        for subscription in list(self.subscriptions):
            subscription.push(dict(method=method, params=params))

    async def _runtime_request(self, method, params):
        if method != 'user-question/ask':
            if self.request_handler is not None:
                return await self.request_handler(method, params)
            raise SdkProtocolError('unknown runtime request: ' + method)
        handler = self.options.get('onUserQuestion')
        if handler is None:
            raise SdkProtocolError('user-question/ask requires an onUserQuestion callback')
        questions = params.get('questions')
        if not isinstance(params.get('requestId'), str) or not params['requestId'] or not isinstance(params.get('sessionId'), str) or not isinstance(questions, list) or not questions or not all(isinstance(q, dict) and isinstance(q.get('id'), str) and isinstance(q.get('question'), str) for q in questions):
            raise SdkProtocolError('user-question/ask requires requestId, sessionId, and questions')
        identity = params['requestId']
        if identity in self.user_questions:
            raise SdkProtocolError('duplicate user-question requestId')
        controller = AbortController(); self.user_questions[identity] = controller
        async def invoke():
            controller.signal.throwIfAborted()
            value = handler(params, dict(signal=controller.signal))
            return await value if hasattr(value, '__await__') else value
        work = asyncio.create_task(invoke()); cancel = asyncio.create_task(controller.signal.wait_aborted())
        work.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        try:
            await asyncio.wait([work, cancel], return_when=asyncio.FIRST_COMPLETED)
            if work.done():
                return work.result()
            controller.signal.throwIfAborted()
        finally:
            cancel.cancel(); await asyncio.gather(cancel, return_exceptions=True)
            self.user_questions.pop(identity, None)

    def onRequest(self, handler):
        if self.close_task is not None:
            raise TransportClosedError('DeepSeek Harness runtime client is closed; create a new client to install a request handler')
        if self.transport is None:
            raise TransportClosedError('start the SDK client before installing a request handler')
        self.request_handler = handler

    async def request(self, method, params=None, timeoutMs=None):
        self.start()
        if self.exit_code is not UNDEFINED or self.spawn_error is not None:
            await self._settle_streams()
            raise self._closed_error('DeepSeek Harness runtime is not running')
        timeout = self.runtime.get('requestTimeoutMs') if timeoutMs is None else timeoutMs
        operation = self.transport.request(method, {} if params is None else params)
        try:
            if timeout is None:
                return await operation
            try:
                return await asyncio.wait_for(operation, timeout / 1000)
            except asyncio.TimeoutError:
                stderr = '; stderr tail:\n' + '\n'.join(self.stderr_tail) if self.stderr_tail else ''
                raise RequestTimeoutError('%s timed out after %sms waiting for %s%s' % (method, timeout, self.runtime['description'], stderr))
        except (JsonRpcResponseError, RequestTimeoutError):
            raise
        except Exception as error:
            await self._settle_streams()
            raise self._closed_error(str(error))

    async def initialize(self, params):
        self.start()
        params = dict(params)
        if self.options.get('onUserQuestion') is not None:
            params['capabilities'] = dict(params.get('capabilities', {}), userQuestions=True)
        result = await self.request('initialize', params, self.runtime['initializeTimeoutMs'])
        info = result.get('serverInfo') if isinstance(result, dict) else None
        if not isinstance(info, dict) or not isinstance(info.get('name'), str) or not isinstance(info.get('version'), str):
            raise SdkProtocolError('initialize returned no server identity: ' + stringify_json(result))
        return dict(serverInfo=dict(name=info['name'], version=info['version']))

    async def prompt(self, sessionId, contentBlocks):
        result = await self.request('session/prompt', dict(sessionId=sessionId, contentBlocks=contentBlocks))
        if not isinstance(result, dict) or not isinstance(result.get('messageId'), str):
            raise SdkProtocolError('session/prompt returned no message id: ' + stringify_json(result))
        return result['messageId']

    async def resumeSession(self, sessionId):
        await self.request('session/resume', dict(sessionId=sessionId))

    async def _working_directory(self, method, params):
        result = await self.request(method, params)
        if not isinstance(result, dict) or not isinstance(result.get('cwd'), str):
            raise SdkProtocolError(method + ' returned no working directory: ' + stringify_json(result))
        return result['cwd']

    async def getWorkingDirectory(self, sessionId):
        return await self._working_directory('session/working-directory/get', dict(sessionId=sessionId))

    async def setWorkingDirectory(self, sessionId, path):
        return await self._working_directory('session/working-directory/set', dict(sessionId=sessionId, path=path))

    def subscribe(self, predicate=None):
        subscription = NotificationSubscription(self, predicate)
        if self.close_task is not None or self.exit_code is not UNDEFINED or self.spawn_error is not None:
            subscription.fail(self._closed_error('DeepSeek Harness runtime closed'))
        else:
            self.subscriptions.add(subscription)
        return subscription

    def subscribeSessionTree(self, sessionId):
        def descendant(identity):
            seen = set()
            while identity not in seen:
                if identity == sessionId:
                    return True
                seen.add(identity)
                identity = self.session_parents.get(identity)
                if identity is None:
                    return False
            return False
        def predicate(note):
            params = note['params']
            if note['method'] in ('subagent.started', 'subagent.finished'):
                parent = params.get('parentSessionId')
                return isinstance(parent, str) and descendant(parent) or params.get('childSessionId') == sessionId
            identity = params.get('sessionId')
            return isinstance(identity, str) and descendant(identity)
        return self.subscribe(predicate)

    async def _exits_within(self, milliseconds):
        deadline = asyncio.get_running_loop().time() + milliseconds / 1000
        while self.child.poll() is None:
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(.01)
        return True

    async def _perform_close(self):
        self._fail_questions(TransportClosedError('SDK client is closing'))
        child = self.child
        if child is None:
            return
        try:
            await self.request('shutdown', timeoutMs=self.runtime.get('shutdownTimeoutMs', 1000))
        except Exception as error:
            self.stderr_tail.append('shutdown request failed: ' + str(error))
        if child.poll() is None:
            child.stdin.close()
            exited = await self._exits_within(self.runtime.get('disposeEofGraceMs', 6000))
            if not exited and os.name != 'nt':
                child.terminate()
                exited = await self._exits_within(self.runtime.get('disposeGraceMs', 3000))
            if not exited:
                try:
                    child.kill()
                except Exception as error:
                    raise RuntimeError('SIGKILL failed') from error
                if not await self._exits_within(self.runtime.get('disposeGraceMs', 3000)):
                    raise RuntimeError('runtime process did not exit within %sms after SIGKILL was accepted' % self.runtime.get('disposeGraceMs', 3000))
        await self._settle_streams()
        # Readers are task-owned; inherited descendant pipes must not keep a
        # reaped runtime's reader alive indefinitely.
        for reader in (self.input, self.stderr_input):
            await reader.close()
        if self.monitor is not None:
            await self.monitor
        self.transport.close()
        for stream in (child.stdin, child.stdout, child.stderr):
            if not stream.closed:
                stream.close()
        self._fail_subscriptions(self._closed_error('DeepSeek Harness runtime closed'))

    def _fail_questions(self, error):
        for controller in list(self.user_questions.values()):
            controller.abort(error)

    def close(self):
        if self.close_task is None:
            self.close_task = CleanupPromise(start_coroutine(self._perform_close()))
        return self.close_task


class DeepSeekHarness:
    def __init__(self, options=None, client_factory=None):
        self.options = options or {}
        self.create_client = client_factory or (lambda: HarnessClient(self.options))
        self.client = self.create_client()
        self.cwd = os.path.abspath(self.options.get('cwd', self.options.get('processCwd', os.getcwd())))
        self.initialized, self.closed = None, False

    async def _start(self):
        try:
            self.client.start()
            params = dict(cwd=self.cwd, provider=self.options.get('provider', 'deepseek-official'), model=self.options.get('model', 'deepseek-v4-flash'))
            for key in ('reasoningEffort', 'maxTokens', 'approvalRequests'):
                if key in self.options:
                    params[key] = self.options[key]
            await self.client.initialize(params)
        except Exception as error:
            self.initialized = None
            try:
                await self.client.close()
            except Exception as cleanup:
                raise AggregateError([error, cleanup], 'DeepSeek Harness initialization and cleanup failed')
            if not self.closed:
                self.client = self.create_client()
            raise

    def start(self):
        if self.initialized is None:
            self.initialized = SharedPromise(start_coroutine(self._start()))
        return self.initialized

    def session(self, sessionId=None):
        return HarnessSession(self, 'session-' + uuid.uuid4().hex if sessionId is None else sessionId)

    async def resumeSession(self, sessionId):
        await self.start()
        await self.client.resumeSession(sessionId)
        return HarnessSession(self, sessionId)

    async def run(self, input, options=None):
        return await self.session((options or {}).get('sessionId')).run(input, options)

    def close(self):
        self.closed = True
        return self.client.close()


class HarnessSession:
    def __init__(self, harness, identity):
        self.harness, self.id = harness, identity

    async def run(self, input, options=None):
        from .run import run_session
        return await run_session(self, input, options)

    async def setWorkingDirectory(self, path):
        await self.harness.start()
        return await self.harness.client.setWorkingDirectory(self.id, path)

    async def getWorkingDirectory(self):
        await self.harness.start()
        return await self.harness.client.getWorkingDirectory(self.id)


def create_process_harness_client(runtime, options=None):
    return HarnessClient(options, runtime=runtime)


def create_process_deepseek_harness(runtime, options=None):
    return DeepSeekHarness(options, lambda: create_process_harness_client(runtime, options))
