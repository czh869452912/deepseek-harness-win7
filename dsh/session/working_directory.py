"""Durable Session working directories and access coordination."""
import asyncio
import os
import weakref

from dsh.cordis.json_text import stringify_json
from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.llm.error import HarnessError
from dsh.llm.message import create_user_message


class WorkingDirectoryError(HarnessError):
    pass


def directory_schema(value):
    if value is not None and (not isinstance(value, str) or not value or not os.path.isabs(value)):
        raise ValueError('working directory must be an absolute path or null')
    return value


class WorkingDirectoryService(Service):
    inject = ['fs', 'sessionProjections', 'systemPrompt']
    Config = Schema.object(dict(defaultDirectory=Schema.string()))

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'workingDirectory')
        self.defaultDirectory = (config or {}).get('defaultDirectory', os.getcwd())
        if not os.path.isabs(self.defaultDirectory):
            raise ValueError('working-directory: defaultDirectory must be absolute')
        self.pending = weakref.WeakKeyDictionary()
        self.operations = set()
        self.lifecycle = AbortController()

    async def init(self):
        ctx = self.ctx
        self.projection = await ctx.get('sessionProjections').register(dict(key='workingDirectory', stateVersion=1,
            stateSchema=directory_schema, init=lambda header, *_: header.get('cwd'),
            apply=lambda state, event: event['data']['cwd'] if event['type'] == 'working-directory/change' else state,
            wire=dict(viewSchema=directory_schema, view=lambda state: state)))
        ctx.get('systemPrompt').context(dict(name='working-directory:current',
            order=ctx.get('systemPrompt').getContextOrder('WORKING_DIRECTORY'), required=True, interpolate=False,
            text=lambda context: '' if context.get('agent') is None else self.context_text(context['agent'].session)))

        async def assemble(_assembly, context, next_fn):
            agent = context.get('agent')
            if agent is None:
                return await next_fn()
            await self.ensure(agent, context.get('signal'))
            assembly = await next_fn()
            self.lifecycle.signal.throwIfAborted()
            text = self.context_text(agent.session)
            contribution = next((entry for entry in assembly['contexts'] if entry['name'] == 'working-directory:current'), None)
            if contribution is None:
                assembly['contexts'].insert(0, dict(name='working-directory:current', text=text, interpolate=False))
            else:
                contribution.update(text=text, interpolate=False)
            return assembly

        ctx.on('system-prompt/assemble', assemble, prepend=True)

        async def dispose():
            self.lifecycle.abort(WorkingDirectoryError('working-directory service disposed', 'WORKING_DIRECTORY_UNAVAILABLE'))
            await asyncio.gather(*tuple(self.operations), return_exceptions=True)
        ctx.effect(lambda: dispose)

    def get(self, session):
        value = self.projection.stateOf(session)
        return self.defaultDirectory if value is None else value

    def context_text(self, session):
        return 'Current working directory: {}.'.format(stringify_json(self.get(session)))

    async def ensure(self, agent, signal=None):
        async def action(control):
            async def validate():
                current = self.get(agent.session)
                fs = self.ctx.get('fs')
                target = await fs.resolve(current, dict(signal=control))
                info = await fs.stat(target, control)
                control.throwIfAborted()
                agent.ctx.fiber.assert_active()
                if info is not None and info.type == 'directory':
                    if self.projection.stateOf(agent.session) is None:
                        agent.session.append('working-directory/change', dict(cwd=current))
                    return current
                original = agent.session.header.cwd or self.defaultDirectory
                def missing():
                    return WorkingDirectoryError('working-directory: directory does not exist: {}; the current working directory {} is also unavailable'.format(
                        stringify_json(original), stringify_json(current)), 'WORKING_DIRECTORY_UNAVAILABLE')
                restored = await self.directory(original, original, control, missing)
                self.commit(agent, restored, True, control)
                return restored
            return await self.ctx.waterfall('working-directory/access', dict(agent=agent, path=None, signal=control), validate)
        return await self.serialize(agent, signal, action)

    async def set(self, agent, path, signal=None):
        async def action(control):
            async def validate():
                if not path:
                    raise WorkingDirectoryError('working-directory: cd must not be empty', 'WORKING_DIRECTORY_INVALID')
                directory = await self.directory(path, self.get(agent.session), control)
                self.commit(agent, directory, False, control)
                return directory
            return await self.ctx.waterfall('working-directory/access', dict(agent=agent, path=path, signal=control), validate)
        return await self.serialize(agent, signal, action)

    async def directory(self, path, cwd, signal, missing=None):
        fs = self.ctx.get('fs')
        target = await fs.resolve(path, dict(cwd=cwd, signal=signal))
        info = await fs.stat(target, signal)
        signal.throwIfAborted()
        if info is None or info.type != 'directory':
            raise missing() if missing else WorkingDirectoryError('working-directory: directory does not exist: {}'.format(
                stringify_json(path)), 'WORKING_DIRECTORY_NOT_FOUND')
        return fs.processPath(target)

    def commit(self, agent, directory, recovered, signal):
        signal.throwIfAborted()
        agent.ctx.fiber.assert_active()
        previous = self.get(agent.session)
        if previous == directory:
            return
        agent.session.append('working-directory/change', dict(cwd=directory))
        text = ('The working directory {} is unavailable. The working directory is now {}.' if recovered else
            'The working directory changed from {} to {}.').format(stringify_json(previous), stringify_json(directory))
        notice = create_user_message(dict(content=[dict(type='text', text=text)], source=dict(kind='working-directory')))
        try:
            agent.inject(notice)
        except Exception as error:
            self.ctx.logger.warn('working-directory: committed {}, but could not queue its notice: {}'.format(stringify_json(directory), str(error)))

    async def serialize(self, agent, signal, action):
        combined = AbortController()
        disposers = [subscribe_abort(source, combined.abort) for source in (self.lifecycle.signal, signal)]
        previous = self.pending.get(agent.session)

        async def run():
            try:
                if previous is not None:
                    await asyncio.gather(previous, return_exceptions=True)
                combined.signal.throwIfAborted()
                agent.ctx.fiber.assert_active()
                return await action(combined.signal)
            finally:
                for dispose in disposers:
                    dispose()

        operation = asyncio.create_task(run())
        self.pending[agent.session] = operation
        self.operations.add(operation)
        def settled(task):
            self.operations.discard(task)
            if self.pending.get(agent.session) is task:
                self.pending.pop(agent.session, None)
            if not task.cancelled():
                task.exception()
        operation.add_done_callback(settled)
        return await asyncio.shield(operation)
