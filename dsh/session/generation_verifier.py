"""Bounded fresh-process verification of a staged JSONL generation (Python 3.8)."""
import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from dsh.session.preparations import throw_aborted

_permits = threading.BoundedSemaphore(2)


async def verifyCurrentGenerationInWorker(path, compression, expectedId,
        expectedEventCount, expectedPrefix=None, signal=None, format_version=3):
    # The bound covers every event loop in this Python process. Waiting owns no child.
    while True:
        throw_aborted(signal)
        if _permits.acquire(False):
            break
        await asyncio.sleep(0.01)
    process = None
    remove = None
    communication = None
    try:
        throw_aborted(signal)
        request = dict(path=path, compression=compression, expectedId=expectedId,
                       expectedEventCount=expectedEventCount, formatVersion=format_version)
        if expectedPrefix is not None:
            request['expectedPrefix'] = dict(bytes=expectedPrefix['bytes'], digest=expectedPrefix['digest'])
        arguments = dict(stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                         stderr=asyncio.subprocess.PIPE, cwd=str(Path(__file__).resolve().parents[2]))
        if os.name == 'nt':
            arguments['creationflags'] = subprocess.CREATE_NO_WINDOW
        spawning = asyncio.ensure_future(asyncio.create_subprocess_exec(sys.executable, '-m',
            'dsh.session.generation_verifier', '--worker', **arguments))
        try:
            process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            process = await spawning
            raise
        communication = asyncio.create_task(process.communicate(json.dumps(request).encode('utf-8')))
        aborted = asyncio.get_running_loop().create_future()
        if signal is not None:
            def on_abort(*args):
                if not aborted.done():
                    aborted.set_result(None)
            remove = signal.add_listener('abort', on_abort)
            throw_aborted(signal)
        done, _ = await asyncio.wait([communication, aborted], return_when=asyncio.FIRST_COMPLETED)
        if aborted in done:
            throw_aborted(signal)
        stdout, stderr = await asyncio.shield(communication)
        if process.returncode:
            raise ValueError('migration verifier exited before reporting a result (code %s): %s' %
                (process.returncode, stderr.decode('utf-8', 'replace')))
        try:
            response = json.loads(stdout.decode('utf-8'))
            if type(response.get('ok')) is not bool:
                raise ValueError()
        except (ValueError, AttributeError, UnicodeError) as error:
            raise ValueError('migration verifier returned an invalid response') from error
        if not response['ok']:
            raise ValueError(response['message'])
        return response['result']
    finally:
        if remove is not None:
            remove()
        if process is not None:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            # A cancelled caller still reaps its verifier and pipe transports.
            if communication is not None:
                await asyncio.shield(asyncio.gather(communication, return_exceptions=True))
            await asyncio.shield(process.wait())
        _permits.release()


def parse_request(value):
    from dsh.core.session.current import safe
    if not isinstance(value, dict):
        raise ValueError('migration verifier request must be an object')
    prefix = value.get('expectedPrefix')
    import re
    if (not isinstance(value.get('path'), str) or value.get('compression') not in ('none', 'zstd')
            or type(value.get('formatVersion', 3)) is not int or value.get('formatVersion', 3) not in (3, 4)
            or not isinstance(value.get('expectedId'), str)
            or not safe(value.get('expectedEventCount'), True, True)
            or prefix is not None and (not isinstance(prefix, dict)
                or not safe(prefix.get('bytes'), True, True)
                or not isinstance(prefix.get('digest'), str)
                or re.fullmatch('[0-9a-f]{64}', prefix['digest']) is None)):
        raise ValueError('migration verifier request is malformed')
    return value


async def worker():
    from dsh.session.generation import JsonlGenerationRuntime
    try:
        request = parse_request(json.loads(sys.stdin.buffer.read().decode('utf-8')))
        runtime = JsonlGenerationRuntime(dict(formatVersion=request.get('formatVersion', 3)))
        result = await runtime.verify(request['path'], request['compression'],
            request['expectedId'], request['expectedEventCount'], request.get('expectedPrefix'))
        response = dict(ok=True, result=result)
    except Exception as error:
        response = dict(ok=False, message=str(error))
    sys.stdout.buffer.write(json.dumps(response, ensure_ascii=True).encode('utf-8'))
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('migration verifier requires an explicit worker invocation')
    asyncio.run(worker())
