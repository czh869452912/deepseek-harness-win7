"""Executor-less agent composition used by the official minimal SDK profile.

Each child owns its services and effects. Optional providers must actually be
installed; an unavailable optional tool raises rather than silently disappearing.
"""
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.cordis.environment import resolve_dsh_home
from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.diagnostics.invariants import InvariantRegistry
from dsh.diagnostics.spine_invariants import AgentInvariant, ScopeInvariant, AgentLoopInvariant
from dsh.core.session.invariant import SessionInvariantPlugin


class AgentSpine(Plugin):
    id = 'agent-spine-demo'
    Config = z.object(dict(
        agents=z.array(z.any()), maxParallelToolCalls=z.number().step(1).min(1),
        includeHarnessIdentity=z.boolean().default(True), includeRuntimeContext=z.boolean().default(True),
        persona=z.string().default(''), toolOrder=z.any(), tools=z.object({}), dshHome=z.string(),
        sessionTitle=z.object({}).default(dict(fallbackMaxWords=5, fallbackMaxBytes=40, maxTitleBytes=80)), workspaceContext=z.union([z.const_(False), z.object({})]).required(),
        skills=z.object(dict(enabled=z.boolean().default(True), registry=z.object({}), filesystem=z.object({}), tool=z.object({}))),
        toolBash=z.union([z.const_(False), z.object({})]), jobs=z.object({}),
        toolJobs=z.union([z.const_(False), z.object({})]), invariants=z.object({}),
        goals=z.union([z.const_(False), z.object(dict(domain=z.object({}), tool=z.object({})))]),
    ))

    async def apply(self, ctx):
        config = self.config
        skills = config.get('skills') or {}
        nested = (skills.get('filesystem') or {}).get('dshHome')
        if config.get('dshHome') is not None and nested is not None and resolve_dsh_home(config['dshHome']) != resolve_dsh_home(nested):
            raise ValueError('agent-spine-demo: dshHome and skills.filesystem.dshHome must resolve to the same directory')
        home = resolve_dsh_home(config.get('dshHome', nested))
        rows = [('@deepseek-ai/cordis-plugin-timer', {}), ('llm', {}), ('session', {}),
            ('session-title', config.get('sessionTitle', dict(fallbackMaxWords=5, fallbackMaxBytes=40, maxTitleBytes=80))),
            ('system-prompt', {key: config[key] for key in ('includeHarnessIdentity', 'includeRuntimeContext', 'persona', 'toolOrder') if key in config}),
            ('tools', config.get('tools', {}))]
        if skills.get('enabled', True):
            rows.extend([('skill', skills.get('registry', {})), ('skill-filesystem', dict(skills.get('filesystem', {}), dshHome=home))])
        rows.extend([('agent', {}), ('llm-retry', {})])
        goals = config.get('goals')
        if goals is not None and goals is not False:
            rows.extend([('goal', goals.get('domain', {})), ('tool-goal', goals.get('tool', {})), ('goal-round-driver', {})])
        rows.append(('jobs-local', config.get('jobs', {})))
        if config.get('toolBash') is not False:
            rows.extend([('shell-env', dict(dshHome=home)), ('tool-bash', config.get('toolBash', {}))])
        if config['workspaceContext'] is not False:
            rows.append(('agent-instructions', config['workspaceContext']))
        if skills.get('enabled', True):
            rows.append(('tool-skill', skills.get('tool', {})))
        if config.get('toolJobs') is not False:
            rows.append(('tool-jobs', config.get('toolJobs', {})))
        rows.append(('agent-loop', {key: config[key] for key in ('agents', 'maxParallelToolCalls') if key in config}))
        # Resolve the whole composition first, so an unavailable optional row
        # does not leave a partly installed graph behind.
        resolved = []
        for name, child_config in rows:
            package = name if name.startswith('@') else '@deepseek-ai/dsh-' + name
            plugin = resolve_harness_plugin(package)
            if plugin is None:
                raise RuntimeError('agent-spine-demo requires unavailable provider ' + package)
            resolved.append((plugin, child_config))
        fibers = [ctx.plugin(plugin, child_config) for plugin, child_config in resolved]
        fibers.append(ctx.plugin(InvariantRegistry, config.get('invariants', {})))
        fibers.extend(ctx.plugin(plugin) for plugin in (SessionInvariantPlugin, AgentInvariant, ScopeInvariant, AgentLoopInvariant))
        for fiber in fibers:
            await fiber
