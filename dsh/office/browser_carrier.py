"""Private, one-operation Chromium carrier; no Node, CDP or third-party client.

The browser executes a trusted worker against an exact route table. This is host
plumbing, not an Office implementation. Windows descendants belong to a Job
before the first instruction executes; cancellation joins the owned range.
"""
import asyncio
import base64
import json
import os
import secrets
import signal as posix_signal
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dsh.core.abort import abort_reason_error
from .errors import OfficeKitError
from .outputs import _remove_tree


_PAGE = b'''<!doctype html><meta charset="utf-8"><title>Office worker</title>
<script src="bootstrap.js"></script>'''
_BOOTSTRAP = b'''
(() => {
  let worker, settled = false;
  const encode = (_, value) => {
    if (ArrayBuffer.isView(value) || value instanceof ArrayBuffer) {
      const bytes = value instanceof ArrayBuffer ? new Uint8Array(value) :
        new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
      let text = '';
      for (let i = 0; i < bytes.length; i += 8192)
        text += String.fromCharCode(...bytes.subarray(i, i + 8192));
      return {__dsh_bytes__: btoa(text)};
    }
    return value;
  };
  const finish = async payload => {
    if (settled) return;
    settled = true;
    if (worker) worker.terminate();
    await fetch('result', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload, encode)});
  };
  window.onerror = (_, __, ___, ____, error) => finish({error: String(error || _)});
  try {
    worker = new Worker('operation.js');
    worker.onmessage = event => finish({value: event.data});
    worker.onerror = event => finish({error: event.message});
  } catch (error) { finish({error: String(error)}); }
})();
'''
_WORKER_PREFIX = '''self.addEventListener('unhandledrejection', event => {
  event.preventDefault();
  fetch('result', {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({error:String(event.reason)})});
});
'''


def _decode(value):
    if isinstance(value, dict):
        if set(value) == {'__dsh_bytes__'}:
            return base64.b64decode(value['__dsh_bytes__'], validate=True)
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


class _Server(HTTPServer):
    allow_reuse_address = False

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address


class BrowserCarrier:
    def __init__(self, executable, *, temporary_directory=None):
        self.executable = os.path.abspath(executable)
        self.temporary_directory = temporary_directory
        self.active = set()
        self.cancelling = set()
        self.closed = False

    def _cancel(self, task):
        if task not in self.cancelling and not task.done():
            self.cancelling.add(task)
            task.cancel()

    async def close(self):
        self.closed = True
        pending = tuple(self.active)
        for task in pending:
            self._cancel(task)
        await asyncio.gather(*pending, return_exceptions=True)

    async def run(self, worker_source, assets, *, timeout=60, max_result_bytes=140000000, signal=None, observe_request=None):
        """Execute trusted JS and return its first postMessage, including bytes.

        Assets are exact URL-name -> Path entries, never a directory mount.
        An HTTP result is bounded before reading or decoding its body.
        """
        operation = asyncio.ensure_future(self._run(worker_source, dict(assets), timeout,
                                                    max_result_bytes, signal, observe_request))
        self.active.add(operation)
        def finished(done):
            self.active.discard(done)
            self.cancelling.discard(done)
        operation.add_done_callback(finished)
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            self._cancel(operation)
            # Further caller cancellation cannot interrupt the private cleanup.
            while not operation.done():
                try:
                    await asyncio.shield(operation)
                except asyncio.CancelledError:
                    pass
            if not operation.cancelled():
                operation.result()
            raise

    async def _run(self, worker_source, assets, timeout, max_result_bytes, signal, observe_request):
        if self.closed:
            raise OfficeKitError('unavailable', 'The Office browser carrier is closed.')
        if signal is not None:
            signal.throwIfAborted()
        if timeout <= 0 or max_result_bytes < 1:
            raise ValueError('Carrier limits must be positive.')
        reserved = {'', 'bootstrap.js', 'operation.js', 'result'}
        for name in assets:
            if name in reserved or not name or '/' in name or '\\' in name or '?' in name or '#' in name:
                raise ValueError('Invalid Office asset route.')
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        prefix = '/' + secrets.token_urlsafe(32) + '/'
        process = server = thread = directory = None
        remove_abort = lambda: None
        payloads = {'': (_PAGE, 'text/html'), 'bootstrap.js': (_BOOTSTRAP, 'application/javascript'),
                    'operation.js': ((_WORKER_PREFIX + worker_source).encode('utf-8'), 'application/javascript')}

        def settle(value=None, error=None):
            if not future.done():
                if error is not None:
                    future.set_exception(error)
                else:
                    future.set_result(value)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, content=b'', mime='text/plain'):
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(content)))
                self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
                self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(content)

            def authorized(self):
                return self.headers.get('Host') == server.server_name_header and self.path.startswith(prefix)

            def do_GET(self):
                if not self.authorized():
                    self.reply(404)
                    return
                name = self.path[len(prefix):]
                if observe_request is not None:
                    observe_request('GET', name[:1000])
                if name in payloads:
                    self.reply(200, *payloads[name])
                elif name in assets:
                    try:
                        # Open before responding so missing inputs cannot become a success.
                        with Path(assets[name]).open('rb') as stream:
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/wasm' if name.endswith('.wasm') else
                                             'application/javascript' if name.endswith(('.cjs', '.js')) else 'application/octet-stream')
                            self.send_header('Content-Length', str(os.fstat(stream.fileno()).st_size))
                            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
                            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
                            self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
                            self.end_headers()
                            while True:
                                chunk = stream.read(65536)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                    except OSError:
                        # Browser/worker error or operation deadline owns failure settlement.
                        self.close_connection = True
                else:
                    self.reply(404)

            def do_POST(self):
                if not self.authorized() or self.path != prefix + 'result':
                    self.reply(404)
                    return
                if observe_request is not None:
                    observe_request('POST', 'result')
                try:
                    length = int(self.headers.get('Content-Length', '-1'))
                    if self.headers.get('Transfer-Encoding') or not 0 <= length <= max_result_bytes:
                        raise ValueError('The Office worker result exceeds its byte limit or has invalid framing.')
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        raise ValueError('The Office worker result was truncated.')
                    payload = json.loads(raw.decode('utf-8'))
                    if not isinstance(payload, dict) or set(payload) not in ({'value'}, {'error'}):
                        raise ValueError('Invalid Office worker result envelope.')
                    if 'error' in payload:
                        raise OfficeKitError('failed', str(payload['error']))
                    value = _decode(payload['value'])
                except Exception as error:
                    loop.call_soon_threadsafe(settle, None, error)
                    self.reply(400)
                    return
                self.reply(200)
                loop.call_soon_threadsafe(settle, value)

        try:
            directory = tempfile.mkdtemp(prefix='dsh-office-browser-', dir=self.temporary_directory)
            server = _Server(('127.0.0.1', 0), Handler)
            server.server_name_header = '127.0.0.1:' + str(server.server_port)
            thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05),
                                      name='dsh-office-browser-http')
            thread.start()
            argv = [self.executable, '--headless', '--disable-gpu', '--no-first-run',
                    '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
                    '--no-default-browser-check', '--disable-background-networking', '--disable-extensions',
                    '--disable-sync', '--user-data-dir=' + directory,
                    'http://' + server.server_name_header + prefix]
            options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.name == 'nt':
                from dsh.subprocess.windows_process import WindowsJobProcess
                process = WindowsJobProcess(argv, **options)
            else:
                process = subprocess.Popen(argv, start_new_session=True, **options)
            if signal is not None:
                remove_abort = signal.add_listener('abort', lambda reason: settle(error=abort_reason_error(signal)))
            deadline = loop.time() + timeout
            while not future.done():
                if process.poll() is not None:
                    raise OfficeKitError('failed', 'The Office browser exited before returning a result.')
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise OfficeKitError('timeout', 'The Office browser operation timed out.')
                await asyncio.wait((future,), timeout=min(remaining, 0.05))
            return future.result()
        finally:
            remove_abort()
            if not future.done():
                future.cancel()
            # Retrieve a raced exception even if the parent task was cancelled.
            elif not future.cancelled():
                future.exception()
            try:
                if process is not None:
                    if os.name == 'nt':
                        try:
                            process.kill_range()
                            deadline = time.monotonic() + 5
                            while process.range_alive():
                                if time.monotonic() >= deadline:
                                    raise OfficeKitError('failed', 'The Office browser process range did not stop.')
                                await asyncio.sleep(0.01)
                            process.wait()
                        finally:
                            process.close_handles()
                    else:
                        try:
                            os.killpg(process.pid, posix_signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        await loop.run_in_executor(None, process.wait)
            finally:
                try:
                    if server is not None:
                        if thread is not None:
                            await loop.run_in_executor(None, server.shutdown)
                            thread.join()
                        server.server_close()
                finally:
                    if directory is not None:
                        await loop.run_in_executor(None, _remove_tree, directory)
