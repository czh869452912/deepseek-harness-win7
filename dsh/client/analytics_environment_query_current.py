"""Owned, shell-free environment queries; only fixed outcome reasons escape."""
import asyncio
import os
import subprocess
import threading
import time

from dsh.core.cancellation import aborted, subscribe_abort


def _execute(command, args, options, cancelled):
    limit = options['maxOutputBytes']
    deadline = time.monotonic() + options['timeoutMillis'] / 1000
    process = None
    readers = []
    streams = [bytearray(), bytearray()]
    overflow = threading.Event()
    read_failed = threading.Event()
    reason = None
    try:
        if cancelled.is_set():
            return dict(kind='missing', reason='query-failed')
        process = subprocess.Popen([command] + list(args), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=0x08000000 if os.name == 'nt' else 0)

        def read(pipe, output):
            try:
                while True:
                    chunk = os.read(pipe.fileno(), 8192)
                    if not chunk:
                        break
                    # Each pipe has its own byte budget. Continue draining after
                    # overflow so completion also owns stdio closure.
                    remaining = max(0, limit - len(output))
                    output.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()
            except (OSError, ValueError):
                read_failed.set()
            finally:
                pipe.close()

        for pipe, output in zip((process.stdout, process.stderr), streams):
            thread = threading.Thread(target=read, args=(pipe, output),
                name='analytics-environment-query-reader')
            readers.append(thread)
            thread.start()
        while True:
            # Like execFile's callback, settle the first terminal condition;
            # subsequent aborts cannot replace an already completed result.
            if overflow.is_set():
                reason = 'output-limit'
            elif cancelled.is_set():
                reason = 'query-failed'
            elif process.poll() is not None and not any(t.is_alive() for t in readers):
                break
            elif time.monotonic() >= deadline:
                reason = 'timeout'
            if reason is not None:
                if process.poll() is None:
                    process.kill()
                break
            cancelled.wait(0.005)
        process.wait()
    except Exception:
        reason = 'query-failed'
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            for thread in readers:
                thread.join()
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
    if overflow.is_set():
        reason = 'output-limit'
    if reason is None and (read_failed.is_set() or process.returncode != 0):
        reason = 'query-failed'
    if reason is not None:
        return dict(kind='missing', reason=reason)
    return dict(kind='value', stdout=bytes(streams[0]).decode('utf-8', errors='replace'))


async def queryEnvironment(command, args, options):
    """Wait for process and both pipes, including on caller cancellation.

    The command is a trusted internal metadata query, never a shell program
    supplied by an analytics event. Limits are validated by its owning Host.
    """
    signal = options.get('signal')
    cancelled = threading.Event()
    if aborted(signal):
        cancelled.set()
    unsubscribe = subscribe_abort(signal, lambda *_: cancelled.set())
    worker = asyncio.get_running_loop().run_in_executor(
        None, _execute, command, args, options, cancelled)
    try:
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled.set()
            # Shield the worker even if this awaiter is cancelled repeatedly.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    pass
            worker.result()
            raise
    finally:
        unsubscribe()
