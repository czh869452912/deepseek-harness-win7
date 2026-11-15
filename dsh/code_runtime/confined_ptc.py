"""Policy-owned, stateless Python PTC provider with fail-closed confinement."""
import asyncio
import os
import sys

from dsh.code_runtime.contract import OutputLedger
from dsh.code_runtime.policy_processes import PolicyProcesses
from dsh.code_runtime.process import PythonProcessRuntime
from dsh.code_runtime.ptc import PythonPtcRuntime
from dsh.cordis.awaiting import await_callback_result
from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.core.timeout import clamp_timeout
from dsh.sandbox.runner_failure import runner_failure, spawn_runner_failure
from dsh.sandbox.vocabulary import SANDBOX_MODES, SandboxUnavailableError


class ConfinedPythonPtcRuntime(PythonPtcRuntime):
    inject = ['sandbox', 'sandboxPolicy']
    executionInstructions = PythonPtcRuntime.executionInstructions.replace(
        'This provider does not confine direct filesystem access.',
        "Direct filesystem access follows this execution's sandbox policy.")

    def __init__(self, ctx, config=None):
        self.live = {}
        self.next_run = 0
        super().__init__(ctx, config)
        self.processes = PolicyProcesses(ctx)

    @property
    def sandboxMode(self):
        return self.ctx.get('sandboxPolicy').defaultMode

    def resolve(self, request):
        if self.closed:
            raise RuntimeError('ptc-runtime-python: resolve after disposal')
        policy = request.get('sandboxPolicy')
        if policy is None:
            policy = self.ctx.get('sandboxPolicy').resolve()
        cwd = request.get('cwd')
        if cwd is None:
            cwd = policy.get('workspaceRoot')
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            raise ValueError('ptc-runtime-python: cwd must be absolute')
        timeout = (None if 'timeoutMs' in request and request['timeoutMs'] is None
            else clamp_timeout(request.get('timeoutMs'), self.ptc_config['timeoutMs'],
                               self.ptc_config['maxTimeoutMs'], 'ptc-runtime-python: timeoutMs'))
        return dict(request, sandboxPolicy=policy, cwd=cwd, timeoutMs=timeout)

    async def run(self, spec):
        if self.closed:
            raise RuntimeError('ptc-runtime-python: run after disposal')
        policy = spec.get('sandboxPolicy')
        if not isinstance(policy, dict):
            raise ValueError('ptc-runtime-python: run requires a resolved sandbox policy')
        if (policy.get('mode') not in SANDBOX_MODES or
                not isinstance(policy.get('workspaceRoot'), str) or
                not os.path.isabs(policy['workspaceRoot'])):
            raise ValueError('ptc-runtime-python: invalid resolved sandbox policy')
        self._validate_spec(spec)
        policy = dict(policy)
        if 'additionalWritableRoots' in policy:
            policy['additionalWritableRoots'] = list(policy['additionalWritableRoots'])
        controller = AbortController()
        relay = subscribe_abort(spec.get('signal'), lambda reason: controller.abort(reason))
        finished = asyncio.get_running_loop().create_future()
        key = self.next_run
        self.next_run += 1
        async def release():
            controller.abort(RuntimeError('sandbox mode changed'))
            await asyncio.shield(finished)
        unregister = None
        self.live[key] = dict(controller=controller, finished=finished)
        try:
            unregister = self.processes.register(policy, release)
            await self.processes.wait(policy.get('sessionId'))
            if self.closed:
                raise RuntimeError('ptc-runtime-python: run after disposal')
            return await PythonProcessRuntime.run(self,
                dict(spec, sandboxPolicy=policy, signal=controller.signal))
        finally:
            relay()
            if unregister is not None:
                unregister()
            self.live.pop(key, None)
            finished.set_result(None)

    async def dispose(self):
        self.closed = True
        live = list(self.live.values())
        for run in live:
            run['controller'].abort(RuntimeError('runtime disposed'))
        results = await asyncio.gather(super().dispose(),
            *[asyncio.shield(run['finished']) for run in live], return_exceptions=True)
        failure = next((result for result in results if isinstance(result, BaseException)), None)
        if failure is not None:
            raise failure

    def _failure(self, kind, message, logs=()):
        ledger = OutputLedger(int(self.ptc_config['maxOutputBytes']))
        for text in logs:
            if not ledger.admit(text):
                return ledger.limit()
        return ledger.result(error=dict(kind=kind, message=message))

    async def _execute(self, request, bindings):
        task = asyncio.create_task(self._admit_execute(request, bindings))
        remove = subscribe_abort(request.get('signal'), lambda reason: task.cancel())
        try:
            timeout = request['timeoutMs']
            done, unused = await asyncio.wait({task}, timeout=None if timeout is None else timeout/1000)
            if not done:
                task.cancel()
                results = await asyncio.gather(task, return_exceptions=True)
                previous = results[0] if isinstance(results[0], dict) else {}
                result = self._failure('timeout', 'wall-time budget exceeded', previous.get('logs', []))
                result['sandbox'] = previous.get('sandbox', dict(mode=request['sandboxPolicy']['mode'], denied=False))
                return result
            return task.result()
        except asyncio.CancelledError:
            task.cancel()
            results = await asyncio.gather(task, return_exceptions=True)
            previous = results[0] if isinstance(results[0], dict) else {}
            result = self._failure('abort', 'code execution aborted', previous.get('logs', []))
            result['sandbox'] = previous.get('sandbox', dict(mode=request['sandboxPolicy']['mode'], denied=False))
            return result
        finally:
            remove()

    async def _admit_execute(self, request, bindings):
        policy = request['sandboxPolicy']
        sandbox = dict(mode=policy['mode'], denied=False)
        launch = {}
        facts = None
        try:
            if aborted(request.get('signal')):
                result = self._failure('abort', 'code execution aborted')
            else:
                if policy['mode'] != 'danger-full-access':
                    argv = [getattr(sys, '_base_executable', sys.executable), '-u', '-B',
                            os.path.join(os.path.dirname(__file__), 'worker.py')]
                    provider = self.ctx.get('sandbox')
                    confine = getattr(provider, 'confine_process', None)
                    memory = int(self.ptc_config['maxOldGenerationSizeMb']*1024*1024)
                    facts = await await_callback_result(confine(argv, policy, memory) if callable(confine)
                                                        else provider.confine(argv, policy))
                    if (not isinstance(facts, dict) or not isinstance(facts.get('argv'), list)
                            or not facts['argv'] or not all(isinstance(arg, str) for arg in facts['argv'])
                            or facts.get('enforcement') not in ('full', 'partial')):
                        raise SandboxUnavailableError(policy['mode'], 'invalid confinement provider result')
                    launch.update(facts)
                    sandbox['enforcement'] = facts['enforcement']
                result = self._cleanup_result(await self._execute_process(request, bindings, launch), launch)
                if facts is not None and result.get('error', {}).get('kind') == 'worker-exit':
                    detail = runner_failure(launch.get('exitCode'), launch.get('stderr', ''),
                                            facts.get('runnerFailureRules', []))
                    error = launch.get('spawnError')
                    if detail is not None or spawn_runner_failure(error, facts['argv'][0], request['cwd']):
                        result = self._failure('sandbox-unavailable', str(SandboxUnavailableError(
                            policy['mode'], detail or str(error))), result.get('logs', []))
        except SandboxUnavailableError as error:
            result = self._failure('sandbox-unavailable', str(error))
        except asyncio.CancelledError:
            result = self._failure('abort', 'code execution aborted')
        except Exception as error:
            result = self._failure('worker-exit', str(error))
        if facts is not None and result.get('error', {}).get('kind') != 'sandbox-unavailable':
            diagnostic = result.get('error', {}).get('message', '').lower()
            sandbox['denied'] = any(signature.lower() in diagnostic
                                    for signature in facts.get('denialSignatures', []))
        return dict(result, sandbox=sandbox)
