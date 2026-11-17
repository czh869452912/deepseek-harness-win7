"""Pinned market format-1 validator/search in the shipped Win7 JavaScript worker.

This private carrier accepts JSON values, not untrusted executable source. It
does not fetch indexes, validate Gateway queries, or claim Node JSON diagnostics.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dsh.javascript.runtime import (JavaScriptRuntimeError, encode,
                                    verify_resources, worker_environment)

RESOURCE_ROOT = Path(__file__).with_name('market-index')
MANIFEST_SHA256 = '63082bf58db95e7cf41f694a409543c30ceb64364632d510614b2ba1ae37cc01'


class MarketIndexError(ValueError):
    def __init__(self, path, reason):
        self.path, self.reason = path, reason
        super().__init__(path + ' ' + reason)


def market_bootstrap():
    path = RESOURCE_ROOT / 'manifest.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise JavaScriptRuntimeError('Market index manifest bytes differ')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('format') != 'dsh-market-index@1' or manifest.get('target_upstream') != '38a6a5c965aa99ab525161efb7cc5cf1fe62fced':
        raise JavaScriptRuntimeError('Market index Source pin differs')
    for name, expected in manifest['resources'].items():
        if Path(name).name != name or ':' in name:
            raise JavaScriptRuntimeError('Market index resource path differs')
        if hashlib.sha256((RESOURCE_ROOT / name).read_bytes()).hexdigest() != expected:
            raise JavaScriptRuntimeError('Market index resource bytes differ: ' + name)
    # The shared core-js artifact replaces an incompatible existing constructor.
    # This worker has no native URL; the sentinel selects that same full parser.
    return 'globalThis.URL=function(){this.hostname="";};\n' + '\n'.join(
        (RESOURCE_ROOT / name).read_text(encoding='utf-8') for name in ('url.js', 'market.js', 'driver.js'))


def observe_market_operations(operations):
    if type(operations) is not list:
        raise TypeError('Market operations must be a list')
    request = dict(body='return null', name='market-index', timeoutMs=10000,
                   operations=operations, bootstrap=market_bootstrap())
    completed = subprocess.run([str(verify_resources())], input=encode(request) + encode(dict(type='go')),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=worker_environment(), timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    return _result(completed.stdout, completed.stderr, completed.returncode, len(operations))


def _result(stdout, stderr, code, count):
    try:
        frames = [json.loads(line.decode('utf-8')) for line in stdout.splitlines()]
    except (UnicodeError, ValueError) as error:
        raise JavaScriptRuntimeError('Market worker returned invalid protocol data') from error
    if (code != 0 or len(frames) != 2 or frames[0] != dict(type='ready')
            or frames[1].get('type') != 'terminal' or type(frames[1].get('result')) is not list
            or len(frames[1]['result']) != count):
        # Worker errors may contain the entire bootstrap. Keep diagnostics bounded.
        raise JavaScriptRuntimeError('Market worker failed (exit ' + str(code) + '): '
            + stderr.decode('utf-8', errors='replace')[-2000:])
    return frames[1]['result']


async def observe_market_operations_async(operations, signal=None):
    """Own the child from spawn through exit, including abort during spawn."""
    if type(operations) is not list:
        raise TypeError('Market operations must be a list')
    if signal is not None:
        signal.throwIfAborted()
    payload = encode(dict(body='return null', name='market-index', timeoutMs=10000,
                         operations=operations, bootstrap=market_bootstrap())) + encode(dict(type='go'))
    binary = verify_resources()

    async def execute():
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(str(binary), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=worker_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        process = None
        try:
            process = await asyncio.shield(spawn)
            stdout, stderr = await asyncio.wait_for(process.communicate(payload), 30)
            return _result(stdout, stderr, process.returncode, len(operations))
        finally:
            async def close():
                owned = process
                if owned is None:
                    try: owned = await spawn
                    except Exception: return
                if owned.returncode is None:
                    owned.kill()
                await owned.communicate()
            closing = asyncio.create_task(close())
            cancelled = False
            while not closing.done():
                try: await asyncio.shield(closing)
                except asyncio.CancelledError: cancelled = True
            closing.result()
            if cancelled:
                raise asyncio.CancelledError()
    task = asyncio.create_task(execute())
    remove = signal.add_listener('abort', lambda _: task.cancel()) if signal is not None else lambda: None
    try:
        return await task
    except asyncio.CancelledError:
        if signal is not None:
            signal.throwIfAborted()
        raise
    finally:
        remove()


async def parse_index_body(body, url, signal=None):
    """Platform strict UTF-8/BOM decode, then JS JSON and pinned validation.

    JSON syntax failures preserve the '$' path and 'must be JSON: ' prefix.
    Their shipped-engine wording differs from V8; exact prose alignment remains
    explicitly outside this platform-decoding and worker-lifetime batch.
    """
    if signal is not None:
        signal.throwIfAborted()
    if type(body) is not bytes:
        raise TypeError('Market index body must be bytes')
    try:
        text = body.decode('utf-8-sig', errors='strict')
    except UnicodeDecodeError:
        return dict(ok=False, path='$', reason='must be UTF-8', message='must be UTF-8')
    row = (await observe_market_operations_async([dict(kind='body', text=text, url=url)], signal))[0]
    if 'error' in row:
        raise ValueError(row['error']['message'])
    return row


def parse_market_index(value, url):
    row = observe_market_operations([dict(kind='parse', value=value, url=url)])[0]
    if row['ok']:
        return row['index']
    error = row['error']
    if error['name'] == 'MarketIndexError':
        raise MarketIndexError(error['path'], error['reason'])
    raise ValueError(error['message'])
