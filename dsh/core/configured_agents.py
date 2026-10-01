"""Configured Agent identities and owned asynchronous startup/reload."""
import asyncio
import inspect
import uuid
from dsh.core.agent import AgentOptions
from dsh.session.preparations import observe_queued_abort
from dsh.llm.error import error_chain

CONFIGURED_AGENT_IDENTITIES_KEY = 'configuredAgentIdentities'


def configured_agents(config, identities=None):
    rows = config.get('agents', [])
    if not isinstance(rows, list):
        raise ValueError('agents must be an array')
    result, exact = [], {}
    for source in rows:
        if not isinstance(source, dict) or not isinstance(source.get('id'), str):
            raise ValueError('configured agent id must be a string')
        row = dict(source)
        for key in ('sessionId', 'resumeSessionId', 'cwd', 'provider', 'model', 'reasoningEffort'):
            if key in row and (not isinstance(row[key], str) or (key in ('sessionId', 'reasoningEffort') and not row[key])):
                raise ValueError(key + ': expected string length >= 1' if key in ('sessionId', 'reasoningEffort') else key + ': expected string')
        maximum = row.get('maxTokens')
        if 'maxTokens' in row and (type(maximum) is not int or not 1 <= maximum <= 9007199254740991):
            raise ValueError('maxTokens must be a positive safe integer')
        identity = identities.get(row['id']) if identities is not None else None
        if identity is not None:
            row.pop('sessionId', None); row.pop('resumeSessionId', None)
            row['resumeSessionId' if identity['resume'] else 'sessionId'] = identity['id']
        resume = row.get('resumeSessionId')
        if 'sessionId' in row and resume:
            raise ValueError('sessionId and resumeSessionId are mutually exclusive')
        sid = resume or row.get('sessionId')
        if sid is not None:
            if sid in exact:
                raise ValueError('agents "{}" and "{}" use duplicate exact session identity "{}"'.format(exact[sid], row['id'], sid))
            exact[sid] = row['id']
        result.append(row)
    return result


def error_text(error):
    return error_chain(error)


class ConfiguredStartup:
    def __init__(self, factory):
        self.factory = factory
        self.ctx = factory.ctx
        self.jobs = set()

    def active(self):
        if not self.factory._accepting:
            return False
        try:
            self.ctx.fiber.assert_active()
            return True
        except RuntimeError:
            return False

    def start(self, operation):
        task = asyncio.ensure_future(operation)
        self.jobs.add(task)
        def done(job):
            self.jobs.discard(job)
            if not job.cancelled(): job.exception()
        task.add_done_callback(done)

    async def drain(self):
        if self.jobs:
            await asyncio.gather(*list(self.jobs), return_exceptions=True)

    def report(self, label, action, sid, error):
        if not self.active(): return
        self.ctx.logger.warn('agent "{}": config-driven {} of "{}" failed: {}'.format(label, action, sid, error_text(error)))
        args = ['agent-loop/config-start-failed', {'sessionId': sid, 'error': error}]
        for callback in list(self.ctx.events.dispatch('emit', args)):
            try:
                result = callback(*args[1:])
                if inspect.isawaitable(result):
                    async def observe(value):
                        try:
                            await observe_queued_abort(value, self.factory._factory_abort.signal)
                        except Exception as failure:
                            if not self.factory._factory_abort.signal.aborted:
                                self.ctx.logger.warn('agent "{}": config-start-failed listener rejected: {}'.format(label, error_text(failure)))
                    self.start(observe(result))
            except Exception as failure:
                self.ctx.logger.warn('agent "{}": config-start-failed listener threw: {}'.format(label, error_text(failure)))

    async def wait_released(self, sid):
        def vacant():
            return self.ctx.get('agents').get(sid) is None and self.ctx.get('sessions').get(sid) is None
        if vacant(): return
        released = asyncio.get_running_loop().create_future()
        def check(*args):
            if vacant() and not released.done(): released.set_result(None)
        remove_agent = self.ctx.on('agent/disposed', check)
        remove_session = self.ctx.on('session/disposed', check)
        try:
            check()
            await observe_queued_abort(released, self.factory._factory_abort.signal)
        finally:
            remove_agent(); remove_session()
            if not released.done(): released.cancel()

    async def restore(self, row, options, meta, persistence, explicit=False):
        sid = row['resumeSessionId'] if explicit else row['sessionId']
        try:
            if not explicit: await self.wait_released(sid)
            if not self.active(): return
            try:
                await self.factory.resume(sid, options, owner_ctx=self.ctx, persistence=persistence)
                return
            except Exception:
                if not self.active(): return
                if explicit: raise
                # Only an absent artifact falls back to create. An index failure
                # or a corrupt existing artifact remains a contained failure.
                headers = await observe_queued_abort(persistence.list(), self.factory._factory_abort.signal)
                if any(header.id == sid for header in headers): raise
            if self.active(): await self.factory.create_agent(sid, options, meta, owner_ctx=self.ctx)
        except Exception as error:
            self.report(row['id'], 'resume' if explicit else 'restore', sid, error)

    def mount(self, rows):
        fresh = []
        for row in rows:
            options = AgentOptions(**{key: row[key] for key in ('provider','model','reasoningEffort','maxTokens') if key in row})
            meta = {'cwd': row['cwd']} if 'cwd' in row else {}
            if row.get('resumeSessionId'):
                def setup(row=row, options=options, meta=meta):
                    def available(child):
                        self.start(self.restore(row, options, meta, child.get('sessionPersistence'), True))
                    fiber = self.ctx.inject(['sessionPersistence'], available)
                    return fiber.dispose
                self.ctx.effect(setup, 'agentLoop.resume({})'.format(row['id']))
            else:
                sid = row.get('sessionId', '{}-session-{}'.format(row['id'], uuid.uuid4()))
                persistence = self.ctx.get('sessionPersistence') if 'sessionId' in row else None
                if persistence is None:
                    fresh.append((sid, options, meta))
                else:
                    self.start(self.restore(row, options, meta, persistence))
        if fresh:
            async def initialize():
                for sid, options, meta in fresh:
                    await self.factory.create_agent(sid, options, meta, owner_ctx=self.ctx)
            return initialize()
        return None
