"""Workspace change service and reversible session/tool/filesystem hooks."""
import asyncio
import math
import tempfile
import weakref

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.core.abort import AbortController
from dsh.deliverables.change_git import GitRunner
from dsh.deliverables.change_recorder import TurnRecorder
from dsh.typert.stores import field


_DEFAULTS = dict(timeoutMs=30000, outputMaxBytes=8*1024*1024, maxFiles=500,
                 maxFileBytes=2*1024*1024, diffTimeoutMs=100)


class CurrentWorkspaceChanges(Plugin):
    id = 'workspace-changes'
    inject = ['subprocess', 'fs']
    Config = z.object({key: z.number().default(value) for key, value in _DEFAULTS.items()})

    def apply(self, ctx):
        config = dict(_DEFAULTS, **self.config)
        for key, value in config.items():
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or value < 1 or value > 9007199254740991 or int(value) != value):
                raise ValueError('workspace-changes requires a positive integer '+key)
        config = {key: int(value) for key, value in config.items()}
        lifetime = AbortController()
        recorders, by_id = {}, {}
        mutations = weakref.WeakKeyDictionary()
        retiring = set()
        runner = None

        def forget(session):
            recorder = recorders.pop(session, None)
            by_id.pop(session.id, None)
            if recorder is None:
                return None
            pending = asyncio.create_task(recorder.dispose())
            retiring.add(pending)
            # Keep failed retirement tasks until teardown can report them.
            pending.add_done_callback(lambda task: retiring.discard(task) if not task.cancelled() and task.exception() is None else None)
            return pending

        async def dispose():
            lifetime.abort()
            for session in list(recorders):
                forget(session)
            pending = list(retiring)
            if runner is not None:
                pending.append(runner)
            if pending:
                results = await asyncio.gather(*pending, return_exceptions=True)
                failures = [error for error in results if isinstance(error, BaseException)]
                if failures:
                    raise failures[0]
            mutations.clear()
        ctx.effect(lambda: dispose)

        class WorkspaceChanges:
            def summary(self, sessionId, seq):
                recorder = by_id.get(sessionId)
                return None if recorder is None else recorder.summary(seq)

            async def diff(self, sessionId, seq, index, signal):
                recorder = by_id.get(sessionId)
                return None if recorder is None else await recorder.diff(seq, index, signal)
        ctx.set_service('workspaceChanges', WorkspaceChanges())

        async def resolve_git():
            try:
                executable = await ctx.subprocess.resolveExecutable('git', None, lifetime.signal)
            except Exception:
                ctx.logger.info('workspace-changes: git is unavailable; only file-tool edits are summarized')
                return None
            return GitRunner(ctx.subprocess, executable, dict(timeoutMs=config['timeoutMs'], outputMaxBytes=config['outputMaxBytes']))

        def recorder_for(session, cwd):
            nonlocal runner
            recorder = recorders.get(session)
            if recorder is None:
                if runner is None:
                    runner = asyncio.create_task(resolve_git())
                recorder = TurnRecorder(session, cwd, dict(git=runner, tempRoot=tempfile.gettempdir(),
                    maxFiles=int(config['maxFiles']), maxFileBytes=int(config['maxFileBytes']),
                    diffTimeoutMs=config['diffTimeoutMs'], warn=ctx.logger.warn))
                recorders[session] = by_id[session.id] = recorder
            return recorder

        def on_event(session, event):
            kind, data = event['type'], event['data']
            if kind == 'turn/start':
                header = session.header
                cwd = header.get('cwd')
                if cwd is not None and header.get('origin') != 'subagent' and not (header.get('delegationDepth') or 0) > 0:
                    recorder_for(session, cwd).start(data['turn'])
                return
            recorder = recorders.get(session)
            if recorder is not None:
                if kind == 'tool/result': recorder.observe(event)
                elif kind == 'turn/end': recorder.end(data['turn'])

        async def stopping(payload):
            recorder = recorders.get(field(field(payload, 'agent'), 'session'))
            if recorder is not None:
                await recorder.stopping(field(payload, 'turn'))

        async def intent(target, actor, next_fn):
            decision = await next_fn()
            try:
                recorder = mutations.get(actor) if actor is not None else None
            except TypeError:
                # Foreign filesystem actors were never entered by the tool
                # registry (plain dictionaries cannot be weakly referenced).
                recorder = None
            if recorder is not None:
                recorder.capture(ctx.fs.processPath(target))
                await recorder.settled()
            return decision

        async def pre_execute(execution, next_fn):
            recorder = recorders.get(field(field(execution, 'agent'), 'session'))
            if recorder is not None:
                mutations[execution] = recorder
                await recorder.settled()
            return await next_fn()

        ctx.on('session/event', on_event)
        ctx.on('session/disposed', lambda session: forget(session))
        ctx.on('agent/turn-stopping', stopping)
        for event in ('fs/write-intent', 'fs/edit-intent', 'fs/delete-intent'):
            ctx.on(event, intent, prepend=True)
        ctx.on('tools/pre-execute', pre_execute)
