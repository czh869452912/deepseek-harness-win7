import argparse
import asyncio
import json
from pathlib import Path
import sys


PRODUCT_ROOT = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=PRODUCT_ROOT)
    arguments = parser.parse_args()
    PRODUCT_ROOT = arguments.root.resolve()
sys.path.insert(0, str(PRODUCT_ROOT))
import dsh
from dsh.cordis.context import Context
from dsh.subprocess.local import LocalSubprocessRuntime


async def observations():
    rows = []
    for name in ('host-exit-contained', 'pending-host-exit', 'mixed-failure', 'single-failure'):
        ctx = Context()
        await ctx.plugin(LocalSubprocessRuntime)
        service = ctx.get('subprocess')
        trace = []
        entered, release = asyncio.Event(), asyncio.Event()
        wait_failure, terminal_failure = RuntimeError('controlled wait failure'), RuntimeError('controlled terminal failure')
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)
        def terminate_ordinary():
            trace.append(['terminate', 'ordinary'])
        def force():
            trace.append(['force', 'ordinary'])
            if name == 'host-exit-contained':
                raise RuntimeError('controlled force failure')
        async def wait():
            trace.append(['wait', 'ordinary'])
            entered.set()
            if name == 'pending-host-exit':
                await release.wait()
            if name.endswith('failure'):
                raise wait_failure
            return True
        class Ordinary:
            def __init__(self):
                self.done = done
            terminate = staticmethod(terminate_ordinary)
            terminate_for_host_exit = staticmethod(force)
            wait_for_exit = staticmethod(wait)
        async def terminate_terminal():
            trace.append(['terminate', 'terminal'])
            raise terminal_failure
        class Terminal:
            pid = -1
            terminate = staticmethod(terminate_terminal)
            def terminate_for_host_exit(self):
                trace.append(['force', 'terminal'])
        service.live.add(Ordinary())
        if name in ('host-exit-contained', 'mixed-failure'):
            service.terminals.add(Terminal())
        retained, error = None, None
        try:
            if name == 'host-exit-contained':
                service._terminate_all()
                retained = {'ordinary': len(service.live), 'terminals': len(service.terminals)}
            else:
                disposing = asyncio.create_task(service._dispose_managed_processes())
                await entered.wait()
                if name == 'pending-host-exit':
                    service._terminate_all()
                    retained = {'ordinary': len(service.live), 'terminals': len(service.terminals)}
                    release.set()
                try:
                    await disposing
                except Exception as failure:
                    error = failure
            observed = {'trace': trace, 'after': {'ordinary': len(service.live), 'terminals': len(service.terminals)}}
            if retained is not None:
                observed['retained'] = retained
            if error is not None:
                observed['error'] = {'name': getattr(error, 'name', 'Error'), 'message': str(error), 'sameWaitFailure': error is wait_failure}
                if hasattr(error, 'errors'):
                    observed['error'].update(members=[{'name': getattr(member, 'name', 'Error'), 'message': str(member)} for member in error.errors],
                        memberIdentity=error.errors[0] is wait_failure and error.errors[1] is terminal_failure)
            rows.append({'name': name, 'observed': observed})
        finally:
            service.live.clear()
            service.terminals.clear()
            await ctx.fiber.dispose()
    return rows


if __name__ == '__main__':
    report = {'observations': asyncio.run(observations()), 'root': str(PRODUCT_ROOT),
        'module': str(Path(dsh.__file__).resolve()), 'python': list(sys.version_info[:3])}
    arguments.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
