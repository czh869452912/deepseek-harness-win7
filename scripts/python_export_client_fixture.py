"""Export actual creative-mode source through Tools for native/browser tests."""
from pathlib import Path
import json
from pytest import MonkeyPatch
import yaml

from dsh.boot.profile_boot import run_profile
from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput

NAME = '@author/python-export-web'
SESSION_PRESETS = {'python-session-a': 'exported-a', 'python-session-b': 'exported-b',
                   'python-session-shared': 'exported-a', 'python-session-plain': 'minimal'}
HOST_SOURCE = '''counter = [0]
def plugin(ctx):
    def echo(args):
        counter[0] += 1
        return {'text': 'Python Web echo: ' + args['text'], 'calls': counter[0], 'version': '1.0.0'}
    harness.handle('echo', echo)
    harness.handle('snapshot', lambda args: {'calls': counter[0], 'args': args})
'''
CLIENT_SOURCE = '''styles.insert('[data-python-web-echo] {position: fixed; top: 20px; left: 800px; z-index: 999; pointer-events: auto;}');
return {inject: ['slots'], apply(ctx) {
  function Panel() {
    const [result, setResult] = React.useState('ready');
    const [text, setText] = React.useState('中文 portable');
    const invalid = {
      nan: () => NaN, negativeZero: () => -0, undefined: () => undefined,
      function: () => () => true,
      cycle: () => {const value = {}; value.self = value; return value;},
      sparse: () => {const value = [, 1]; value.extra = 2; return value;},
    };
    return React.createElement('section', {'data-python-web-echo': true},
      React.createElement('input', {value: text, onChange: event => setText(event.target.value)}),
      React.createElement('button', {'data-python-web-echo-call': true, onClick: async () => {
        try {setResult(JSON.stringify({ok: true, value: await host.call('echo', {text})}));}
        catch (error) {setResult(JSON.stringify({ok: false, error: {message: error.message}}));}
      }}, 'Call exported Python plugin'),
      React.createElement('output', {'data-python-web-echo-result': true, style: {display: 'block'}}, result),
      ...Object.entries(invalid).map(([kind, make]) => React.createElement('button', {key: kind, 'data-python-web-invalid': kind,
        onClick: async () => {try {await host.call('echo', {text: make()}); setResult('unexpected');}
          catch (error) {setResult(JSON.stringify({ok: false, error: {message: kind + ': ' + error.message}}));}}
      }, kind)),
      React.createElement('button', {'data-python-web-snapshot': true, onClick: async () => {
        const value = {safe: true}; Object.defineProperty(value, 'toJSON', {value: () => {throw new Error('hidden toJSON executed');}});
        try {setResult(JSON.stringify({ok: true, value: await host.call('snapshot', value)}));}
        catch (error) {setResult(JSON.stringify({ok: false, error: {message: error.message}}));}
      }}, 'Snapshot'));
  }
  ctx.slots.inject('shell.overlay', () => ctx.slots.register({name: 'shell.overlay', id: 'python-export-echo'}, Panel));
}};
'''


def install_session_presets(home, project):
    root = Path(__file__).resolve().parents[1]
    text = (root / 'packages/preset/agent-presets/presets/minimal/agent.cordis.yml').read_text(encoding='utf-8')
    fragment = json.loads((Path(project) / 'preset.fragment.yml').read_text(encoding='utf-8'))
    for name in ('exported-a', 'exported-b'):
        directory = Path(home) / '.agent-presets' / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'agent.cordis.yml').write_text(text + '\n' + yaml.safe_dump(fragment, sort_keys=False), encoding='utf-8')


async def create_session_fixture(ctx, workspace):
    for sid, preset in SESSION_PRESETS.items():
        await ctx.sessionController.create(dict(sessionId=sid, cwd=str(workspace), agentPreset=preset))
        agent = ctx.agents.get(sid)
        if not any(event['type'] == 'user/message' for event in agent.session.events):
            agent.session.append_user_message('Private Session ownership fixture')
            # A valid prepared zero-step turn makes the original list metadata
            # nonblank. User text alone deliberately leaves a blank Session.
            agent.session.append('turn/start', dict(turn=1))
            agent.session.append('turn/end', dict(turn=1, reason=dict(kind='completed')))
        await ctx.sessionController.rename(dict(sessionId=sid, title=sid))
        await agent.session.flush()


async def export_project_at(workspace, host_source=HOST_SOURCE, client_source=CLIENT_SOURCE, placement='host'):
    workspace = Path(workspace)
    environment = MonkeyPatch()
    environment.setenv('DSH_HOME', str(workspace / 'author-home'))
    environment.setenv('DSH_TELEMETRY_MODE', 'DISABLED')
    author = None
    try:
        author = await run_profile(dict(profile='web', dshHome=str(workspace / 'author-home'),
            args=['--no-open', '--port', '0'], waitForExit=False))
        ctx = author['ctx']
        await ctx.sessionController.create(dict(sessionId='export-author', cwd=str(workspace), agentPreset='cordis'))
        agent = ctx.agents.get('export-author')
        code = dict(client=client_source)
        if host_source is not None:
            code['host'] = host_source
        receipt = ctx.dynamicCordisRunner.define(dict(sessionId=agent.id,
            plugin=dict(kind='new', idPrefix='export'), name='Exported Web',
            purpose='Persist a Python Host and original dynamic Client', code=code))
        result = await ctx.tools.execute(ToolExecutionInput('export-source', 'cordis_export',
            dict(pluginId=receipt['pluginId'], packageId=receipt['packageId'], directory='project',
                name=NAME, version='1.0.0', placement=placement, isolateServices=[],
                license='UNLICENSED', licenseText='Private test source; no redistribution grant.\n'),
            agent=agent, signal=NEVER_ABORTED))
        if result.is_error:
            raise RuntimeError(str(result.error))
        return workspace / 'project', receipt
    finally:
        try:
            if author is not None:
                author['shutdown'].shutdown(0)
                await author['shutdown'].wait()
        finally:
            environment.undo()
