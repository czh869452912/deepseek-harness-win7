"""Current persistent PowerShell polling, retention and shell ownership protocol."""
import asyncio
import math
import re
import uuid
import weakref

from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.core.timeout import deadline, timeout_of
from dsh.core.tools import ToolArgsError, ToolContextUnavailableError
from dsh.terminal.persistent_pwsh import PersistentPwshPlugin, DESCRIPTION, RESET, LOST, wrap_command

CLIPPED = '<response clipped><NOTE>To save on context only part of this file has been shown to you. You should retry this tool after you have searched inside the file with Select-String in order to find the line numbers of what you are looking for.</NOTE>'
TIMEOUT_CODE = 'PERSISTENT_PWSH_TIMEOUT'


def capture(snapshot, start, end, wrapper):
    text = snapshot['text']; finish = text.rfind(end)
    status = re.match(r'^(\d+) *\r?\n', text[finish + len(end):])
    if status is None:
        return None
    begin = text.rfind(start, 0, finish)
    content = text[begin + len(start) if begin >= 0 else 0:finish].replace(wrapper, '')
    return dict(text=re.sub(r'\r?\n$', '', re.sub(r'^\r?\n', '', content)),
                incomplete=begin < 0, exitCode=int(status[1]))


def partial(snapshot, start, end, wrapper, fallback, truncated=False):
    begin = snapshot['text'].rfind(start)
    if begin >= 0:
        return dict(text=re.sub(r'\r?\n$', '', re.sub(r'^\r?\n', '', snapshot['text'][begin + len(start):])), incomplete=False)
    begin = fallback.rfind(start)
    content = fallback if begin < 0 else re.sub(r'^\r?\n', '', fallback[begin + len(start):])
    finish = content.rfind(end)
    if finish >= 0:
        content = content[:finish]
    return dict(text=re.sub(r'\r?\n$', '', content.replace(wrapper, '')), incomplete=truncated or begin < 0)


def append_marker(text, marker):
    return text if marker is None else text + ('\n' if text else '') + marker


def render(output, maximum):
    text = output['text']; raw = text.encode('utf-16-le', 'surrogatepass')
    if len(raw) > maximum * 2:
        cut = raw[:maximum * 2]
        if cut and 0xD800 <= int.from_bytes(cut[-2:], 'little') <= 0xDBFF:
            cut = cut[:-2]
        text = cut.decode('utf-16-le', 'surrogatepass') + CLIPPED
    elif output['incomplete']:
        text += CLIPPED
    if output['incomplete'] and output['text']:
        text = LOST + text
    code = output.get('exitCode')
    return append_marker(text, '[exit code: {}]'.format(code) if code is not None and code != 0 else None)


class AuthorizedPersistentPwsh(PersistentPwshPlugin):
    inject = PersistentPwshPlugin.inject + ['workingDirectory']

    def apply(self, ctx):
        self.ctx = ctx
        self.config = dict(dict(backendType='shell', timeoutMs=300000, maxOutputChars=16000,
                                description=DESCRIPTION), **self.config)
        for name in ('backendType', 'description'):
            if not self.config[name].strip():
                raise ValueError('tool-pwsh-persistent: {} must be non-empty'.format(name))
        for name in ('timeoutMs', 'maxOutputChars'):
            value = self.config[name]
            if type(value) not in (int, float) or not 0 < value <= 9007199254740991 or not math.isfinite(value) or int(value) != value:
                raise ValueError('tool-pwsh-persistent: {} must be a positive safe integer'.format(name))
            self.config[name] = int(value)
        self.pending, self.locks = weakref.WeakKeyDictionary(), weakref.WeakKeyDictionary()
        self.live, self.creating, self.running = {}, set(), set()
        self.owner_cleanup = weakref.WeakSet()
        self.lifecycle = AbortController()
        ctx.effect(lambda: self.dispose)
        disposer = ctx.get('tools').register_canonical(dict(name='pwsh', description=self.config['description'],
            parameters=dict(type='object', properties=dict(command=dict(type='string', description='The PowerShell command to run. Relative path is preferred in the command.')), required=['command']),
            execute=self.execute, output=dict(schema=dict(type='string'), render=lambda args, value:[dict(type='text', text=value)]),
            presentCall=lambda args:dict(card='terminal', title=args['command'])))
        ctx.effect(lambda: disposer)

    async def close(self, owner, identity, reason):
        terminals = self.ctx.get('terminals')
        if any(row['sessionId'] == identity for row in terminals.list(owner)):
            await terminals.kill(owner, identity, reason)

    async def dispose(self):
        self.lifecycle.abort(RuntimeError('tool-pwsh-persistent disposed during shell creation'))
        await asyncio.gather(*list(self.creating), return_exceptions=True)
        await asyncio.gather(*(self.close(owner, identity, 'tool-pwsh-persistent disposed') for owner, identity in list(self.live.items())))
        self.live.clear()

    async def reset(self, owner, reason):
        self.pending.pop(owner, None)
        identity = self.live.pop(owner, None)
        if identity is not None:
            await self.close(owner, identity, reason)

    async def get(self, owner, signal):
        existing = self.pending.get(owner)
        if existing is not None:
            return await asyncio.shield(existing)
        combined = AbortController()
        detaches = [subscribe_abort(source, lambda reason=None:combined.abort(reason)) for source in (signal, self.lifecycle.signal)]
        async def create():
            try:
                cwd = await self.ctx.get('workingDirectory').ensure(owner, combined.signal)
                spawned = await self.ctx.get('terminals').spawn(owner, dict(type=self.config['backendType'], cwd=cwd), combined.signal)
                identity = spawned['sessionId'];self.live[owner] = identity
                if owner not in self.owner_cleanup:
                    self.owner_cleanup.add(owner)
                    def forget():
                        self.pending.pop(owner, None);self.live.pop(owner, None)
                    owner.ctx.effect(lambda:forget)
                return identity
            except BaseException:
                await self.reset(owner, 'persistent pwsh initialization failed')
                raise
            finally:
                for detach in detaches:detach()
        task = asyncio.create_task(create());self.pending[owner] = task;self.creating.add(task)
        task.add_done_callback(self.creating.discard)
        return await asyncio.shield(task)

    async def execute(self, args, execution):
        if not args['command'].strip():
            raise ToolArgsError('pwsh', ['command must be a non-empty string'])
        owner = getattr(execution, 'agent', None)
        if owner is None:
            raise ToolContextUnavailableError('pwsh requires an owning agent session')
        lock = self.locks.setdefault(owner, asyncio.Lock())
        async with lock:
            if aborted(execution.signal):
                return ''
            return await self.command(owner, args['command'], execution.signal)

    def retained(self, owner, identity, latest=None):
        terminals = self.ctx.get('terminals')
        latest = terminals.read(owner, identity, dict(offset=0, count=1000)) if latest is None else latest
        pages = [latest['text']] if latest['text'] else [];offset = latest['lineEnd'];truncated = latest['truncated']
        while offset < latest['totalLines']:
            page = terminals.read(owner, identity, dict(offset=offset, count=1000));truncated = truncated or page['truncated']
            if page['text']:pages.insert(0, page['text'])
            if not page['text'] or page['lineEnd'] <= offset or page['lineEnd'] >= page['totalLines']:break
            offset = page['lineEnd']
        return dict(text='\n'.join(pages), truncated=truncated)

    async def exited(self, owner, identity, status, start, end, wrapper, fallback, truncated):
        snapshot = self.retained(owner, identity)
        await self.reset(owner, 'persistent pwsh shell exited')
        text = render(partial(snapshot, start, end, wrapper, fallback, truncated), self.config['maxOutputChars'])
        marker = ('[shell killed by signal: {}]'.format(status['signal']) if status.get('signal') is not None else
                  '[shell exited: code {}]'.format(status['exitCode']) if status.get('exitCode') is not None else '[shell exited]')
        return append_marker(text, marker) + '\n' + RESET

    async def command(self, owner, command, upstream):
        with deadline(upstream, self.config['timeoutMs'], TIMEOUT_CODE) as timer:
            try:
                identity = await self.get(owner, timer.signal)
            except BaseException as error:
                if aborted(upstream) and error is upstream.reason:return ''
                raise
            nonce = str(uuid.uuid4());start = '__DSH_PERSISTENT_PWSH_START_' + nonce + '__';end = '__DSH_PERSISTENT_PWSH_END_' + nonce + ':'
            wrapper = wrap_command(command, start, end)
            first, fallback, truncated = True, '', False
            terminals = self.ctx.get('terminals')
            while True:
                status = next((row['status'] for row in terminals.list(owner) if row['sessionId'] == identity), None)
                if status is not None and status['kind'] == 'exited':
                    return await self.exited(owner, identity, status, start, end, wrapper, fallback, truncated)
                try:
                    operation = terminals.startSend(owner, identity, dict(text=wrapper if first else '', submit=first, signal=timer.signal));first = False
                    result = await asyncio.shield(operation.done)
                except BaseException:
                    await self.reset(owner, 'persistent pwsh send failed')
                    raise
                incremental = operation.readOutput()
                fallback = fallback + incremental['delta'] if incremental['delta'] else result['viewport']
                truncated = truncated or incremental['truncated'] or result['truncated']
                latest = terminals.read(owner, identity, dict(offset=0, count=1000))
                expired = timeout_of(timer.signal, TIMEOUT_CODE)
                if expired is not None:
                    text = render(partial(self.retained(owner, identity, latest), start, end, wrapper, fallback, truncated), self.config['maxOutputChars'])
                    await self.reset(owner, 'persistent pwsh command timed out')
                    seconds = math.floor(expired.timeoutMs / 1000 + .5)
                    return 'Your command timed out after {} seconds or experienced an OOM error. Below is partial output:\n{}\n{}'.format(seconds, text, RESET)
                if timer.signal.aborted:
                    await self.reset(owner, 'persistent pwsh command aborted')
                    return ''
                if end in latest['text']:
                    output = capture(self.retained(owner, identity, latest), start, end, wrapper)
                    if output is not None:return render(output, self.config['maxOutputChars'])
                if result['sessionStatus']['kind'] == 'exited':
                    return await self.exited(owner, identity, result['sessionStatus'], start, end, wrapper, fallback, truncated)
                if result['waitReason'] == 'stdin_read':
                    return render(partial(self.retained(owner, identity, latest), start, end, wrapper, fallback, truncated), self.config['maxOutputChars'])
                await asyncio.sleep(.025)
