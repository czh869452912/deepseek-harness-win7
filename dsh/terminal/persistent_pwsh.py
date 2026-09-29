"""Persistent PowerShell tool consuming the canonical exact-owner PTY seam."""
import asyncio
import re
import time
import uuid
import weakref

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted
from dsh.terminal.service import check_signal


DESCRIPTION = ('Run commands in a persistent PowerShell shell. State, including the current directory '
               'and exported environment variables, persists across calls for this agent.')
RESET = 'The persistent pwsh shell was reset; the next pwsh call starts from the workspace with a fresh current directory and environment.'
CLIPPED = '<response clipped><NOTE>Only part of the command output has been retained.</NOTE>'
LOST = '<response clipped><NOTE>The beginning of this command output was dropped by the terminal scrollback limit. The following text is the earliest retained output.</NOTE>\n'


def wrap_command(command, start, end):
    # PowerShell 2 has no `e escape; a subexpression produces ESC literally.
    body = command.replace('`', '``').replace('"', '`"').replace('$', '`$').replace('\r', '').replace('\n', '`n').replace('\x1b', '$([char]27)')
    return ("Write-Output '{start}'; $LASTEXITCODE = $null; $__s = 1; try {{ Invoke-Expression \"{body}\"; $__ok = $? }} "
            "catch {{ $__ok = $false }}; if ($null -ne $LASTEXITCODE) {{ $__s = [int]$LASTEXITCODE }} "
            "else {{ $__s = if ($__ok) {{ 0 }} else {{ 1 }} }}; Write-Output ('{end}' + $__s)").format(start=start, end=end, body=body)


def capture(text, start, end, wrapper, complete=True):
    position = text.rfind(end)
    status = re.match(r'^(\d+)\r?\n', text[position + len(end):]) if position >= 0 else None
    if complete and status is None:
        return None
    finish = position if status is not None else len(text)
    begin = text.rfind(start, 0, finish)
    output = text[begin + len(start) if begin >= 0 else 0:finish].replace(wrapper, '')
    output = re.sub(r'^\r?\n', '', output)
    output = re.sub(r'\r?\n$', '', output)
    return dict(text=output, incomplete=begin < 0, exitCode=int(status[1]) if status else None)


def render(output, limit):
    text = output['text'][:limit]
    if len(output['text']) > limit or output['incomplete']:
        text += CLIPPED
    if output['incomplete'] and output['text']:
        text = LOST + text
    if output.get('exitCode'):
        text += ('\n' if text else '') + '[exit code: {}]'.format(output['exitCode'])
    return text


class PersistentPwshPlugin(Plugin):
    id = 'tool-pwsh-persistent'
    inject = ['tools', 'terminals']
    Config = Schema.object(dict(backendType=Schema.string().default('shell'), timeoutMs=Schema.number().default(300000),
        maxOutputChars=Schema.number().default(16000), description=Schema.string().default(DESCRIPTION)))

    def apply(self, ctx):
        self.ctx = ctx
        self.config = dict(dict(backendType='shell', timeoutMs=300000, maxOutputChars=16000, description=DESCRIPTION), **self.config)
        for key in ('timeoutMs', 'maxOutputChars'):
            if type(self.config[key]) is not int or not 0 < self.config[key] <= 9007199254740991:
                raise ValueError(key + ' must be a positive safe integer')
        for key in ('backendType', 'description'):
            if not self.config[key].strip():
                raise ValueError(key + ' must be non-empty')
        self.live, self.locks = {}, weakref.WeakKeyDictionary()
        self.running = set()
        self.lifecycle = AbortController()
        ctx.effect(lambda: self.dispose)
        disposer = ctx.get('tools').register_canonical(dict(name='pwsh', description=self.config['description'],
            parameters=dict(type='object', properties=dict(command=dict(type='string', description='The PowerShell command to run. Relative path is preferred in the command.')), required=['command']),
            execute=self.execute, output=dict(schema=dict(type='string'), render=lambda args, value: [dict(type='text', text=value)]),
            presentCall=lambda args: dict(card='terminal', title=args['command'])))
        ctx.effect(lambda: disposer)

    async def dispose(self):
        self.lifecycle.abort(RuntimeError('persistent pwsh disposed'))
        await asyncio.gather(*list(self.running), return_exceptions=True)
        # Failed cleanup retains the live entry and surfaces the error.
        await asyncio.gather(*(self.reset(owner, 'persistent pwsh disposed') for owner in list(self.live)))

    async def reset(self, owner, reason):
        identity = self.live.get(owner)
        if identity is not None:
            terminals = self.ctx.get('terminals')
            if any(item['sessionId'] == identity for item in terminals.list(owner)):
                await terminals.kill(owner, identity, reason)
            self.live.pop(owner, None)

    async def get(self, owner, signal):
        identity = self.live.get(owner)
        if identity is not None:
            return identity
        request = dict(type=self.config['backendType'])
        if owner.session.header.cwd is not None:
            request['cwd'] = owner.session.header.cwd
        spawned = await self.ctx.get('terminals').spawn(owner, request, signal)
        identity = self.live[owner] = spawned['sessionId']
        def forget():
            self.live.pop(owner, None)
        owner.ctx.effect(lambda: forget)
        return identity

    def snapshot(self, owner, identity):
        terminals, pages, offset = self.ctx.get('terminals'), [], 0
        while True:
            page = terminals.read(owner, identity, dict(offset=offset, count=1000))
            if page['text']:
                pages.insert(0, page['text'])
            if page['lineEnd'] <= offset or page['lineEnd'] >= page['totalLines']:
                break
            offset = page['lineEnd']
        return '\n'.join(pages)

    async def execute(self, args, execution):
        command, owner = args['command'], getattr(execution, 'agent', None)
        if not isinstance(command, str) or not command.strip():
            raise ValueError('command must be a non-empty string')
        if owner is None:
            raise RuntimeError('pwsh requires an owning agent session')
        lock = self.locks.setdefault(owner, asyncio.Lock())
        async def serialized():
            async with lock:
                check_signal(self.lifecycle.signal)
                check_signal(getattr(execution, 'signal', None))
                return await self.command(owner, command, getattr(execution, 'signal', None))
        task = asyncio.create_task(serialized())
        self.running.add(task)
        try:
            return await task
        finally:
            self.running.discard(task)

    async def command(self, owner, command, upstream):
        controller = AbortController()
        timed_out = False
        async def watch():
            nonlocal timed_out
            expires = time.monotonic() + self.config['timeoutMs'] / 1000
            while True:
                for signal in (upstream, self.lifecycle.signal):
                    if aborted(signal):
                        controller.abort(getattr(signal, 'reason', None))
                        return
                if time.monotonic() >= expires:
                    timed_out = True
                    controller.abort(RuntimeError('persistent pwsh timeout'))
                    return
                await asyncio.sleep(.01)
        watcher = asyncio.create_task(watch())
        identity = None
        nonce = uuid.uuid4().hex
        start, end = '__DSH_START_' + nonce + '__', '__DSH_END_' + nonce + ':'
        wrapper = wrap_command(command, start, end)
        try:
            identity = await self.get(owner, controller.signal)
            first = True
            terminals = self.ctx.get('terminals')
            while True:
                check_signal(controller.signal)
                operation = terminals.startSend(owner, identity, dict(text=wrapper if first else '', submit=first, signal=controller.signal))
                first = False
                # Watch the deadline independently: a draining native write or
                # Ctrl-C-resistant command cannot prolong the wall-clock limit.
                await asyncio.wait([operation.done, watcher], return_when=asyncio.FIRST_COMPLETED)
                if controller.signal.aborted:
                    check_signal(controller.signal)
                result = await operation.done
                text = self.snapshot(owner, identity)
                captured = capture(text, start, end, wrapper)
                if captured is not None:
                    return render(captured, self.config['maxOutputChars'])
                status = result['sessionStatus']
                if status['kind'] == 'exited':
                    partial = render(capture(text, start, end, wrapper, False), self.config['maxOutputChars'])
                    await self.reset(owner, 'persistent pwsh shell exited')
                    return partial + '\n[shell exited: code {}]\n'.format(status.get('exitCode')) + RESET
                await asyncio.sleep(.025)
        except BaseException:
            partial = ''
            if identity is not None:
                partial = render(capture(self.snapshot(owner, identity), start, end, wrapper, False), self.config['maxOutputChars'])
            await self.reset(owner, 'persistent pwsh command interrupted')
            if timed_out:
                return 'Your command timed out after {} seconds. Below is partial output:\n{}\n{}'.format(self.config['timeoutMs'] / 1000, partial, RESET)
            raise
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
