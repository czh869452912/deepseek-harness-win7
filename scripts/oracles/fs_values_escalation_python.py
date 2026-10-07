import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
selected_root = arguments.root.resolve()
sys.path.insert(0, str(selected_root))
from dsh.core.abort import AbortController
from dsh.fs.fs_local import FsError
from dsh.fs.tool_fs_sandbox import FsSandboxController


async def observe(name):
    trace = []
    standing = dict(mode='read-only' if name == 'lower-standing' else 'danger-full-access' if name == 'highest-standing' else 'workspace-write',
                    workspaceRoot='C:/fixture', temporaryRoots=['C:/temp'])

    def resolve(options):
        trace.append(dict(kind='policy', sessionPresent='session' in options))
        return standing

    selected_policy = [None if name == 'missing-policy' else SimpleNamespace(resolve=resolve)]
    agent = None if name == 'missing-agent' else SimpleNamespace(session=SimpleNamespace(id='session-fixture'))
    signal = AbortController().signal

    async def ask(request):
        trace.append(dict(kind='ask', toolName=request['toolName'], callId=request['callId'], reason=request['reason'],
                          agentSame=request['agent'] is agent, signalSame=request.get('signal') is signal))
        if name == 'mutated-policy':
            standing['temporaryRoots'].append('C:/changed')
        return name if name in ('rejected', 'cancelled', 'unavailable') else 'allowed-once'

    approval = None if name == 'missing-approval' else SimpleNamespace(request=ask)
    services = dict(fs=SimpleNamespace(sandboxMode=None if name in ('unconfined', 'unconfined-request') else 'danger-full-access'))
    context = SimpleNamespace(get=lambda key: selected_policy[0] if key == 'sandboxPolicy' else approval if key == 'approval' else services.get(key))
    observation = dict(name=name, trace=trace)
    try:
        sandbox = FsSandboxController(context)
        observation['schema'] = sandbox.schema_fields() if sandbox.escalation_modes else {}
        if name == 'captured-policy':
            def replaced(options):
                raise RuntimeError('replacement must not resolve')
            selected_policy[0] = SimpleNamespace(resolve=replaced)
        args = {}
        if name not in ('unconfined', 'ordinary', 'provider-error', 'denied-error', 'other-error'):
            args.update(sandbox_permissions='danger-full-access', justification='Wider access for this exact operation.')
        if name == 'mode-only':
            del args['justification']
        if name == 'reason-only':
            del args['sandbox_permissions']
        if name == 'empty-reason':
            args['justification'] = ' '
        if name == 'same-mode':
            args['sandbox_permissions'] = 'workspace-write'
        if name == 'narrower-mode':
            args['sandbox_permissions'] = 'read-only'
        if name == 'lower-standing':
            args['sandbox_permissions'] = 'workspace-write'
        policy = await sandbox.resolve_policy('write', args, SimpleNamespace(agent=agent, callId='call-fixture', signal=signal))
        observation['policy'] = policy
        if name in ('provider-error', 'denied-error', 'other-error'):
            original = ValueError('ordinary provider failure') if name == 'other-error' else FsError('provider failure',
                'FS_SANDBOX_DENIED' if name == 'denied-error' else 'FS_STALE_WRITE')
            mapped = sandbox.map_error(original, policy)
            observation['mapping'] = dict(same=mapped is original, message=str(mapped), code=getattr(mapped, 'code', None),
                                           causeSame=getattr(mapped, 'cause', None) is original)
    except Exception as error:
        observation['error'] = dict(message=str(error))
    return observation


async def main():
    names = ['unconfined','missing-policy','ordinary','mode-only','reason-only','empty-reason','same-mode','narrower-mode',
        'missing-approval','missing-agent','granted','rejected','cancelled','unavailable','lower-standing','highest-standing',
        'unconfined-request','captured-policy','mutated-policy','provider-error','denied-error','other-error']
    rows = [await observe(name) for name in names]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            relative = path.relative_to(selected_root).as_posix()
            modules[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(selected_root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, ensure_ascii=False, indent=2)
        stream.write('\n')


asyncio.run(main())
