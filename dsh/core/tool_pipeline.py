"""Executor-owned lookup over the shared registry invocation stages.

This is an invocation view, not another registry or service. It retains the
accepted registry while an executor supplies private transport capabilities.
"""
from dsh.core.tools import ToolsService


class ToolExecutionPipeline(ToolsService):
    def __init__(self, ctx, source=None):
        self.ctx = ctx
        self.registry = ctx.get('tools')
        self.source = source or {}
        self.contract_version = 4

    def __getattr__(self, name):
        return getattr(self.registry, name)

    def _source_callback(self, name):
        return self.source.get(name) if isinstance(self.source, dict) else getattr(self.source, name, None)

    def executable(self, name, scope=None, tool_set=None):
        lookup = self._source_callback('get')
        return self.registry.executable(name, scope, tool_set) if lookup is None else lookup(name, scope, tool_set)

    def _execution_rejection(self, name, nested, scope=None):
        reject = self._source_callback('reject')
        return None if reject is None else reject(name, nested)

    async def complete(self, execution, outcome):
        if outcome['kind'] == 'post-result':
            return await self.finalize(execution, outcome['result'])
        if outcome['kind'] == 'final-result':
            return self.finish(execution, outcome['result'])
        raise ValueError('unknown scheduled tool outcome ' + str(outcome['kind']))
