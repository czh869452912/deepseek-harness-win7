import argparse
import asyncio
import builtins
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--run-dir', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--preset', choices=('minimal', 'standard', 'cordis'), required=True)
parser.add_argument('--phase', choices=('fresh', 'cold'), required=True)
parser.add_argument('--workspace', type=Path, required=True)
parser.add_argument('--clock', type=int, required=True)
parser.add_argument('--port', default='0')
parser.add_argument('--history-turns', type=int, default=0)
parser.add_argument('--approval-artifact', type=Path, required=True)
options = parser.parse_args()
ROOT = options.root.resolve()
RUN = options.run_dir.resolve()
OUTPUT = options.output.resolve()
FIXTURE = Path(__file__).resolve().with_name('web_journey_fixture.py')
sys.path.insert(0, str(ROOT))
import yaml
from dsh.boot.profile_boot import run_profile


def answer(value):
    print('DSH_JOURNEY ' + json.dumps(value, ensure_ascii=True), flush=True)


def task_trace(task):
    chain = []
    current = task.get_coro()
    while current is not None:
        frame = getattr(current, 'cr_frame', None) or getattr(current, 'gi_frame', None) or getattr(current, 'ag_frame', None)
        if frame is not None:
            row = dict(path=frame.f_code.co_filename, function=frame.f_code.co_name, line=frame.f_lineno)
            for key in ('error', 'entry_id', 'eid'):
                if key in frame.f_locals:
                    row[key] = str(frame.f_locals[key])
            owner = frame.f_locals.get('self')
            if owner is not None:
                row['owner'] = type(owner).__name__
                row['ownerName'] = str(getattr(owner, 'name', ''))
            entry = frame.f_locals.get('entry')
            if entry is not None:
                row['entry'] = str(getattr(entry, 'id', ''))
            session = frame.f_locals.get('session')
            if type(session).__name__ == 'LocalTerminalSession':
                row['unpublishedTerminal'] = session.read(dict(count=1000))
                row['terminalConfig'] = session.config
            chain.append(row)
        next_frame = getattr(current, 'cr_await', None) or getattr(current, 'gi_yieldfrom', None) or getattr(current, 'ag_await', None)
        if frame is not None and frame.f_code.co_name == '_run_async_init':
            next_frame = frame.f_locals.get('gen', next_frame)
        current = next_frame
    return dict(name=task.get_name(), chain=chain)


def durable_files():
    paths = {}
    directory = RUN / 'home/sessions'
    if not directory.exists():
        return paths
    for base, folders, files in os.walk(str(directory), followlinks=False):
        for name in folders + files:
            path = Path(base) / name
            if getattr(path.lstat(), 'st_file_attributes', 0) & 0x400 or path.is_symlink():
                raise ValueError('Durable journey artifact link refused')
        for name in files:
            path = Path(base) / name
            if not path.is_file() or path.resolve().relative_to(directory.resolve()).as_posix() != path.relative_to(directory).as_posix():
                raise ValueError('Durable journey artifact path refused')
            paths[path.relative_to(RUN).as_posix()] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size)
    return paths


async def main():
    if OUTPUT.exists():
        raise ValueError('Fresh browser host receipt required')
    RUN.mkdir(parents=True, exist_ok=True)
    workspace = options.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    home = RUN / 'home'
    before = durable_files()
    if options.phase == 'fresh' and before or options.phase == 'cold' and not before:
        raise ValueError('Browser journey durable phase precondition differs')
    profile = home / 'profiles/web'
    profile.mkdir(parents=True, exist_ok=True)
    manifest = dict(name='controlled-browser-journey', private=True, type='module',
        dsh=dict(profile=dict(bundles=['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'])))
    (profile / 'package.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    patch = [dict(insert=[dict(id='web-journey-fixture', name=str(FIXTURE) + ':FixturePlugin')]),
        dict(id='agent-default-model', config=dict(provider='web-journey-fixture', model='fixture')),
        dict(id='session-persistence-jsonl', config=dict(root=str(home / 'sessions'), packChunks=False))]
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump(patch), encoding='utf-8')
    os.environ['DSH_HOME'] = str(home)
    os.environ['DSH_TELEMETRY_DISABLED'] = '1'
    os.chdir(str(workspace))
    record = dict(root=str(ROOT), executable=sys.executable, python=sys.version, phase=options.phase,
        preset=options.preset, observedClock=options.clock, lookups=[], requests=[], events=[], cancellation=[], snapshots=[], diagnostics=[],
        approvalArtifact=str(options.approval_artifact.resolve()), durableBefore=before,
        fixtureSha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
    builtins.__web_journey_probe = record
    time.time = lambda: options.clock / 1000
    runtime = None
    async def observe_boot():
        await asyncio.sleep(25)
        if runtime is None:
            OUTPUT.with_suffix('.boot-tasks.json').write_text(json.dumps(
                [task_trace(task) for task in asyncio.all_tasks()], indent=2), encoding='utf-8')
    boot_observer = asyncio.create_task(observe_boot())
    try:
        runtime = await run_profile(dict(profile='web', dshHome=str(home), args=['--no-open', '--port', options.port], waitForExit=False))
        boot_observer.cancel()
        ctx = runtime['ctx']
        record['loaderEntries'] = [dict(name=entry.options.get('name'), id=entry.options.get('id'),
            disabled=bool(entry.disabled), state=entry.fiber.state if entry.fiber else None)
            for entry in ctx.get('loader').entries()]
        record['clientGraph'] = copy.deepcopy(ctx.get('clientModules').graph())
        session_id = json.loads((RUN / 'selected-session.json').read_text(encoding='utf-8'))['sessionId'] if options.phase == 'cold' else None
        if options.phase == 'fresh':
            record['preparedWorkspace'] = await ctx.get('workspaceController').create(dict(path=str(workspace)))
            session_id = 'session-11111111-1111-4111-8111-111111111111'
            await ctx.get('sessionController').create(dict(sessionId=session_id,
                workspaceId=record['preparedWorkspace']['workspace']['workspaceId'], agentPreset=options.preset))
        if options.phase == 'fresh' and options.history_turns:
            session = ctx.get('sessions').get(session_id)
            for turn in range(1, options.history_turns + 1):
                session.append('turn/start', dict(turn=turn))
                session.append_user_message('HISTORY_PROMPT_%03d' % turn, message_id='history-user-%d' % turn)
                session.append('step/start', dict(turn=turn, step=1))
                session.append('request/context', dict(turn=turn, step=1, provider='web-journey-fixture', model='fixture'))
                session.append_assistant_message(dict(id='history-assistant-%d' % turn, role='assistant',
                    source=dict(kind='model', provider='web-journey-fixture', model='fixture'),
                    content=[dict(type='text', text='HISTORY_RESPONSE_%03d' % turn)]), turn=turn, step=1,
                    stream=[dict(type='chunk', time=options.clock, chunk=chunk) for chunk in [
                        dict(type='block-start', index=0, blockType='text'),
                        dict(type='text-delta', index=0, text='HISTORY_RESPONSE_%03d' % turn),
                        dict(type='block-end', index=0, block=dict(type='text', text='HISTORY_RESPONSE_%03d' % turn)),
                        dict(type='finish', reason=dict(kind='stop'))]])
                session.append('step/end', dict(turn=turn, step=1))
                session.append('turn/end', dict(turn=turn, reason=dict(kind='completed')))
            ctx.get('sessionTitle').rename(session, 'HISTORY_PROMPT_001')
            await ctx.get('sessions').flush(session)
            await ctx.get('sessionProjectionCache').write(session)
            record['historyTurns'] = options.history_turns
            runtime['shutdown'].shutdown(0)
            await runtime['shutdown'].wait()
            runtime = await run_profile(dict(profile='web', dshHome=str(home), args=['--no-open', '--port', options.port], waitForExit=False))
            ctx = runtime['ctx']
        record['attachedBeforeBrowser'] = session_id is not None and ctx.get('sessions').get(session_id) is not None
        if options.phase == 'cold' and record['attachedBeforeBrowser']:
            raise ValueError('Cold browser fixture eagerly attached its session')
        answer(dict(ready=True, sessionId=session_id, phase=options.phase, preset=options.preset,
            workspace=str(workspace), url=ctx.get('connection').authenticated_url(
                'http://127.0.0.1:{}'.format(ctx.get('webServer').port))))
        while True:
            line = await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                raise RuntimeError('Browser fixture controller closed before owned shutdown')
            request = json.loads(line)
            command = request['command']
            if command == 'snapshot':
                if session_id is None:
                    session_id = next((row['sessionId'] for row in record['events']), None)
                agent = ctx.get('agents').get(session_id) if session_id is not None else None
                session = ctx.get('sessions').get(session_id) if session_id is not None else None
                record['diagnostics'].append(dict(commandId=request['id'],
                    taskStacks=[task_trace(task) for task in asyncio.all_tasks()]
                        if os.environ.get('DSH_WEB_JOURNEY_DIAGNOSTIC') == '1' else [],
                    terminals=[dict(row=row, text=ctx.get('terminals').read(agent, row['sessionId'], dict(offset=0, count=1000)))
                        for row in ctx.get('terminals').list(agent)] if agent and ctx.get('terminals') else []))
                value = dict(attached=session is not None, agentStatus=agent.status if agent else None,
                    header=session.header.to_dict() if session else None,
                    events=copy.deepcopy(list(session.snapshotEvents())) if session else [],
                    requests=copy.deepcopy(record['requests']), cancellation=copy.deepcopy(record['cancellation']),
                    tools=[tool['name'] for tool in ctx.get('tools').schemas(agent)] if agent else [],
                    deepseekModels=await ctx.get('llm').listModels('deepseek-official'))
                if not record['snapshots'] or record['snapshots'][-1] != value:
                    record['snapshots'].append(value)
                record.setdefault('snapshotReads', []).append(dict(commandId=request['id'], index=len(record['snapshots']) - 1))
                answer(dict(id=request['id'], ok=True, value=value))
            elif command == 'disconnect':
                # Inject a transport failure at the owned server socket, without
                # touching application state or replacing any Remote response.
                sockets = list(ctx.get('webServer')._upgraded_sockets)
                if not sockets:
                    raise RuntimeError('No live upgraded browser sockets to disconnect')
                for writer in sockets:
                    writer.transport.abort()
                fault = dict(commandId=request['id'], kind='abort-upgraded-sockets', count=len(sockets))
                record.setdefault('transportFaults', []).append(fault)
                answer(dict(id=request['id'], ok=True, value=fault))
            elif command == 'shutdown':
                session = ctx.get('sessions').get(session_id) if session_id is not None else None
                if session is not None:
                    await ctx.get('sessions').flush(session)
                if session_id is not None:
                    (RUN / 'selected-session.json').write_text(json.dumps(dict(sessionId=session_id)) + '\n', encoding='utf-8')
                answer(dict(id=request['id'], ok=True, value=None))
                break
            else:
                raise ValueError('Unknown controlled browser fixture command')
    except Exception as error:
        record['failure'] = dict(name=type(error).__name__, message=str(error))
        raise
    finally:
        boot_observer.cancel()
        await asyncio.gather(boot_observer, return_exceptions=True)
        if runtime is not None:
            runtime['shutdown'].shutdown(1 if 'failure' in record else 0)
            await runtime['shutdown'].wait()
            record['exitCode'] = runtime['shutdown'].exit_code
        record['durableAfter'] = durable_files()
        record['modules'] = {}
        for name, module in sorted(sys.modules.items()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_file() and ROOT in Path(filename).resolve().parents and Path(filename).resolve().relative_to(ROOT).parts[0] in ('dsh', 'apps', 'packages'):
                path = Path(filename).resolve()
                relative = path.relative_to(ROOT).as_posix()
                record['modules'][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT.open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write('\n')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
