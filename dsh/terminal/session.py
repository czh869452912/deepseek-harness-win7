"""Bounded terminal session with exclusive sends and truthful readiness.

WinPTY has no verified foreground input-wait query. Its silence settlements
are explicitly inferred_idle; command completion belongs to the tool's nonce
protocol. This backend does not claim full xterm emulation.
"""
import asyncio
import codecs
import time

from dsh.core.cancellation import aborted
from dsh.sdk.stdio import StdioInput
from dsh.terminal.service import TerminalError, check_signal
from dsh.terminal.text import TerminalSanitizer, BoundedTextBuffer, utf8_tail


class SendOperation:
    def __init__(self, session):
        self.session = session
        self.done = asyncio.get_running_loop().create_future()
        self.output = BoundedTextBuffer(session.config['maxReadBytes'])
        self.cancel_requested = False

    def readOutput(self):
        return self.output.consume()

    def cancel(self):
        if self.done.done():
            return False
        self.cancel_requested = True
        return True

    def settle(self, reason):
        if not self.done.done():
            output = self.output.snapshot()
            self.done.set_result(dict(viewport=output['text'], waitReason=reason,
                sessionStatus=self.session.status(), truncated=output['truncated'] or self.session.scrollback.dropped))


class LocalTerminalSession:
    def __init__(self, terminal, config):
        self.terminal, self.config = terminal, config
        self.pid, self.motd = terminal.pid, ''
        self.scrollback = BoundedTextBuffer(config['scrollbackMaxBytes'], config['scrollbackLines'])
        self.sanitizer = TerminalSanitizer(config['maxReadBytes'])
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.reader = StdioInput(terminal.output)
        self.output_ended = asyncio.Event()
        self.last_output = time.monotonic()
        self.active = self.driver = self.close_task = None
        self.closing = False
        self.failure = None
        self.status_value = dict(kind='running')
        self.reader.on('data', self.data)
        self.reader.on('end', self.end)
        self.reader.on('error', self.error)
        self.completion = asyncio.create_task(self.complete())

    def data(self, chunk):
        self.append_decoded(self.decoder.decode(chunk))

    def append_decoded(self, decoded):
        result = self.sanitizer.push(decoded)
        text = result['text']
        self.last_output = time.monotonic()
        self.scrollback.append(text)
        if self.active is not None and not self.active.done.done():
            self.active.output.append(text)

    def end(self):
        self.append_decoded(self.decoder.decode(b'', final=True))
        tail = self.sanitizer.flush()
        self.scrollback.append(tail)
        if self.active is not None and not self.active.done.done():
            self.active.output.append(tail)
        self.output_ended.set()

    def error(self, error):
        if not self.closing:
            self.failure = error
            if self.active is not None and not self.active.done.done():
                self.active.done.set_exception(error)
        self.output_ended.set()

    async def complete(self):
        try:
            outcome = await self.terminal.done
            await self.output_ended.wait()
            self.status_value = dict(kind='exited', exitCode=outcome.exitCode, signal=outcome.signal)
            if self.active is not None:
                self.active.settle('session_exit')
        except Exception as error:
            self.error(error)

    def status(self):
        return dict(self.status_value)

    def startSend(self, request):
        if self.closing or self.status_value['kind'] == 'exited':
            raise RuntimeError('PTY session is closing or exited')
        if self.failure is not None:
            raise self.failure
        if self.active is not None:
            raise TerminalError('PTY session already has an active send or draining write', 'SEND_ACTIVE')
        check_signal(request.get('signal'))
        operation = SendOperation(self)
        self.active = operation
        self.last_output = time.monotonic()
        self.driver = asyncio.create_task(self.drive(operation, request))
        return operation

    async def drive(self, operation, request):
        deadline = asyncio.get_running_loop().call_later(self.config['timeoutMs'] / 1000, operation.settle, 'timeout')
        try:
            text = request['text'] + ('\r' if request['submit'] else '')
            if text and not operation.cancel_requested:
                await self.terminal.write(text)
            interrupted = False
            while not self.closing:
                if aborted(request.get('signal')):
                    operation.cancel()
                if operation.cancel_requested and not interrupted:
                    interrupted = True
                    interrupt = getattr(self.terminal, 'interrupt', None)
                    if interrupt is not None:
                        await interrupt()
                    else:
                        await self.terminal.signal_foreground('SIGINT')
                    self.last_output = time.monotonic()
                if operation.done.done():
                    return
                if self.status_value['kind'] == 'exited':
                    operation.settle('session_exit')
                    return
                if (time.monotonic() - self.last_output) * 1000 >= self.config['idleSilenceMs']:
                    operation.settle('inferred_idle')
                    return
                await asyncio.sleep(self.config['pollIntervalMs'] / 1000)
        except asyncio.CancelledError:
            operation.settle('session_exit')
            raise
        except Exception as error:
            if not operation.done.done():
                operation.done.set_exception(error)
        finally:
            deadline.cancel()
            if self.active is operation:
                self.active = None

    def read(self, request=None):
        request = request or {}
        offset, count = request.get('offset', 0), request.get('count', 500)
        if type(offset) is not int or not 0 <= offset <= 9007199254740991:
            raise ValueError('PTY read offset must be a non-negative safe integer')
        if type(count) is not int or not 0 < count <= 9007199254740991:
            raise ValueError('PTY read count must be a positive safe integer')
        snapshot = self.scrollback.snapshot()
        lines = snapshot['text'].split('\n') if snapshot['text'] else []
        if offset >= len(lines):
            return dict(text='', totalLines=len(lines), lineBegin=offset, lineEnd=offset, truncated=snapshot['truncated'])
        end = len(lines) - offset
        text, dropped = utf8_tail('\n'.join(lines[max(0, end - count):end]), self.config['maxReadBytes'])
        return dict(text=text, totalLines=len(lines), lineBegin=offset,
                    lineEnd=offset + (len(text.split('\n')) if text else 0), truncated=dropped or snapshot['truncated'])

    async def signal(self, signal):
        if self.closing:
            raise RuntimeError('PTY session is closing')
        pid = await self.terminal.signal_foreground(signal)
        return dict(delivered=True, targetPgid=pid)

    async def close(self, reason):
        self.closing = True
        if self.close_task is None:
            self.close_task = asyncio.create_task(self.close_once())
        try:
            await asyncio.shield(self.close_task)
        except Exception:
            self.close_task = None
            raise

    async def close_once(self):
        await self.terminal.terminate()
        await self.reader.close()
        self.output_ended.set()
        await self.completion
        if self.active is not None:
            self.active.settle('session_exit')
        if self.driver is not None:
            await self.driver
