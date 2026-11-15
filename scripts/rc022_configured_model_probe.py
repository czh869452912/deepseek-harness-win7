"""Cold configured resumes apply complete routes before Agent publication."""
import asyncio
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = None


async def observe(workspace):
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin
    from dsh.session.persistence import SessionPersistenceNotFoundError
    class Store(Plugin):
        def apply(self, ctx): CurrentSessionStore(ctx, 4)
    class Projections(Plugin):
        def apply(self, ctx): SessionProjectionRegistry(ctx, 4)
    rows = []
    for explicit in (False, True):
        for action in ('same', 'changed', 'explicit', 'partial', 'equal', 'fresh'):
            ctx = Context()
            for plugin in (CurrentLlmRuntime, Store, Projections, CurrentSystemPrompt, CurrentToolsPlugin,
                           NativeToolExecutorPlugin, CurrentAgentPlugin):
                await ctx.plugin(plugin)
            await ctx.plugin(CurrentJsonlSessionPersistencePlugin, dict(root=str(workspace/(str(explicit)+'-'+action)), compression='none'))
            backend = ctx.sessionPersistence
            previous = dict(provider='p', model='m', reasoningEffort='high')
            options = dict(provider='p', model='m')
            if action == 'changed': options['model'] = 'other'
            if action == 'explicit': options['reasoningEffort'] = 'low'
            if action == 'partial': options.pop('provider')
            if action == 'equal': options['reasoningEffort'] = 'high'
            if action != 'fresh':
                prepared = ctx.sessions.prepare('saved')
                handle = await backend.create(prepared.header)
                await handle.append([dict(type='model/selection', seq=0, time=1, data=previous)])
                await handle.close()
            row = dict(action=action, explicit=explicit)
            created = asyncio.get_running_loop().create_future()
            def published(payload):
                agent = ctx.agents.get('saved')
                row['published'] = dict(agent.model.current())
                if not created.done(): created.set_result(None)
            ctx.on('agent/created', published)
            ctx.on('agent-loop/config-start-failed', lambda failure: created.set_exception(failure['error']) if not created.done() else None)
            try:
                config = dict(options, id='config', **{'resumeSessionId' if explicit else 'sessionId':'saved'})
                await ctx.plugin(CurrentAgentLoopPlugin, dict(agents=[config]))
                if explicit and action == 'fresh':
                    try: await asyncio.wait_for(asyncio.shield(created), 5)
                    except SessionPersistenceNotFoundError: row['error'] = 'not-found'
                else:
                    await asyncio.wait_for(asyncio.shield(created), 5)
                    agent = ctx.agents.get('saved')
                    row['events'] = [dict(event['data']) for event in agent.session.snapshotEvents() if event['type'] == 'model/selection']
                rows.append(row)
            finally:
                await ctx.fiber.dispose()
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE = output/'files'
    WORKSPACE.mkdir()
    path = output/'workspace.json'
    path.write_text(json.dumps(str(WORKSPACE)), encoding='utf-8')
    return [path]


async def native():
    return await observe(WORKSPACE/'native')


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_configured_model.mts', 'Actual cold JSONL configured restore/resume records the complete route before publication, preserves same-route reasoning only, skips incomplete routes, deduplicates equal selections and never creates an absent explicit resume.',
        [Path(__file__).resolve(), ROOT/'dsh/core/agent_lifecycle_current.py'], prepare=prepare)
