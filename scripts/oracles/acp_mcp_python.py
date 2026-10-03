import asyncio
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def capture_runtime(workspace, peer_path):
    import yaml
    from dsh.boot.profile import init_profile
    from dsh.boot.profile_boot import run_profile
    from dsh.core.abort import AbortController
    from dsh.core.tools import ToolExecutionInput
    home = workspace / 'home'
    profile = home / 'profiles/acp-mcp-observer'
    init_profile(str(profile), [], 'startup')
    rows = [{'id': name, 'name': '@deepseek-ai/dsh-' + name} for name in
            ('session', 'tools', 'system-prompt', 'llm', 'agent', 'agent-loop', 'acp')]
    rows.append({'id': 'persistence', 'name': '@deepseek-ai/dsh-session-persistence-jsonl',
                 'config': {'root': str(workspace / 'sessions'), 'packChunks': False}})
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([{'insert': rows}]), encoding='utf-8')
    runtime = await run_profile({'profile': 'acp-mcp-observer', 'dshHome': str(home), 'args': [], 'waitForExit': False})
    ctx = runtime['ctx']
    bridge = next(entry.fiber.plugin for entry in ctx.get('loader').entries
                  if entry.options.get('name') == '@deepseek-ai/dsh-acp')
    observations = {}
    def names(agent=None):
        return [tool.name for tool in ctx.get('tools').list_tools(agent)]
    async def echo(created, text):
        agent = bridge.sessions[created['sessionId']].agent
        result = await ctx.get('tools').execute(ToolExecutionInput('owned-echo', 'mcp__fixture__echo',
            {'text': text}, agent=agent, signal=AbortController().signal))
        return {'value': result.value, 'content': result.content, 'isError': result.is_error}
    try:
        observations['mcpCapabilities'] = (await bridge.initialize(ctx, {}))['agentCapabilities']['mcpCapabilities']
        params = {'cwd': str(workspace), 'mcpServers': [{'name': 'fixture', 'command': sys.executable,
            'args': [str(peer_path)], 'env': [{'name': 'EXPLICIT_TOKEN', 'value': 'session-owned'}]}]}
        first = await bridge.new_session(ctx, params)
        observations['globalTools'] = names()
        observations['firstTools'] = names(bridge.sessions[first['sessionId']].agent)
        observations['firstResult'] = await echo(first, 'first owned')
        second = await bridge.new_session(ctx, params)
        await bridge.close_session(ctx, first)
        observations['siblingResult'] = await echo(second, 'sibling remains')
        await bridge.resume_session(ctx, dict(first, **params))
        observations['resumedResult'] = await echo(first, 'fresh resume')
        await bridge.close_session(ctx, first)
        await bridge.resume_session(ctx, dict(first, cwd=str(workspace), mcpServers=[]))
        observations['emptyResumeTools'] = names(bridge.sessions[first['sessionId']].agent)
        await bridge.close_session(ctx, first)
        await bridge.close_session(ctx, second)
        observations['finalTools'] = names()
        observations['finalAgents'] = len(ctx.get('agents').list())
        return observations
    finally:
        runtime['shutdown'].shutdown(0)
        await runtime['shutdown'].wait()


def main():
    from dsh.acp.mcp import resolve_mcp_configs
    cases, runtime_path, output = [Path(value) for value in sys.argv[1:4]]
    rows = []
    for row in json.loads(cases.read_text(encoding='utf-8')):
        try:
            result = {'data': resolve_mcp_configs(row['servers'], row['cwd'])}
        except Exception as error:
            result = {'name': getattr(error, 'name', type(error).__name__), 'message': str(error), 'mounted': []}
        rows.append({'servers': row['servers'], 'cwd': row['cwd'], 'result': result})
    workspace = output.parent / (output.stem + '-runtime')
    workspace.mkdir()
    runtime = asyncio.run(capture_runtime(workspace, runtime_path))
    output.write_text(json.dumps({'declarations': rows, 'runtime': runtime}, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
