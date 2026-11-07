"""Real inherited Job observation; emulate Win7's nested-assignment refusal."""
import asyncio
import ctypes
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path[:0] = json.loads(os.environ.get('DSH_CORDIS_JOB_TEST_PATH', '[]'))
from dsh.sandbox import windows_acl
from dsh.extensions.cordis_host_process import HostProcess


async def observe(mode):
    api = windows_acl.WinApi()
    job = api.check(api.CreateJobObjectW(None, None), 'CreateJobObjectW')
    api.check(api.AssignProcessToJobObject(job, api.GetCurrentProcess()), 'assign real inherited Job')
    class Win7JobApi:
        def __getattr__(self, name):
            return getattr(api, name)
        def AssignProcessToJobObject(self, *args):
            ctypes.set_last_error(5)
            return 0
    windows_acl.WinApi = Win7JobApi
    handlers = {}
    def handle(name, callback):
        handlers[name] = callback
        return lambda: handlers.pop(name, None)
    harness = SimpleNamespace(handle=handle)
    host = HostProcess()
    assert host.job is None and host.watchdog is not None
    if mode == 'parent-death':
        await host.ready()
        host.peer.request('evaluate', ('sum(range(10 ** 12))', '<job-parent-death>'))
        while getattr(host.peer, 'evaluation_started', None) is None:
            await host.peer.pump()
        print(json.dumps(dict(parent=os.getpid(), worker=host.process.pid, watchdog=host.watchdog.pid)), flush=True)
        sys.stdin.readline()
        os._exit(0)
    try:
        await host.evaluate("harness.handle('echo', lambda args: {'text': args})\ndef plugin(ctx): pass\n", harness, 1000)
        assert await handlers['echo'].json_call('中文 Win7', 'result') == {'text': '中文 Win7'}
        await host.close()
        assert host.process.poll() is not None and host.watchdog.poll() is not None
        host = HostProcess()
        try:
            await host.evaluate('sum(range(10 ** 12))', harness, 30)
        except TimeoutError:
            pass
        else:
            raise AssertionError('native computation was not terminated')
        assert host.process.poll() is not None and host.watchdog.poll() is not None
        print(json.dumps(dict(passed=True, actualInheritedJob=True, simulatedWin7AssignmentError=5,
                              rpc=True, nativeTimeout=True, workerAndWatcherExited=True)), flush=True)
    finally:
        await host.close()
        api.CloseHandle(job)


if __name__ == '__main__':
    asyncio.run(observe(sys.argv[1]))
