import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
sys.path.insert(0, str(arguments.root.resolve()))
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionPlugin
from dsh.interaction.permission_presets import PermissionPresetsPlugin, fold_knobs


async def observe(name):
    ctx = Context()
    trace, raw_events = [], []
    session = None
    shell_default = 'danger-full-access' if name == 'inferred-danger' else None if name == 'unconfined' else 'workspace-write'
    approval_default = 'never' if name in ('inferred-danger', 'unmatched-default') else 'ask'
    config = {}
    if name == 'explicit-danger-default':
        config['defaultPreset'] = 'danger-full-access'
    if name == 'unknown-default':
        config['defaultPreset'] = 'foreign'
    if name in ('set-alias', 'stale-alias', 'empty-description'):
        config['presets'] = {'workspace-write': dict(sandbox='workspace-write', approval='ask'),
            'alias': dict(sandbox='workspace-write', approval='ask', name='Alias', description=''),
            'danger-full-access': dict(sandbox='danger-full-access', approval='never')}
    if name == 'reserved-table':
        config['presets'] = dict(custom=dict(sandbox='workspace-write', approval='ask'))
    if name == 'empty-key':
        config['presets'] = {'': dict(sandbox='workspace-write', approval='ask', name=''),
            'alias': dict(sandbox='workspace-write', approval='ask', name='Alias')}
    if name in ('numeric-first', 'numeric-selected'):
        config['presets'] = {'10': dict(sandbox='workspace-write', approval='ask', name='Ten'),
            '2': dict(sandbox='workspace-write', approval='ask', name='Two'),
            'plain': dict(sandbox='workspace-write', approval='ask', name='Plain')}
    if name == 'numeric-boundary':
        config['presets'] = {name: dict(sandbox='workspace-write', approval='ask')
            for name in ('4294967295', '4294967294', '01', '0')}
    observation = dict(name=name, config=copy.deepcopy(config), shellDefault=shell_default,
        approvalDefault=approval_default, trace=trace, rawEvents=raw_events)
    try:
        await ctx.plugin(SessionPlugin)
        ctx.provide('shell', SimpleNamespace(sandboxMode=shell_default))
        ctx.provide('approval', SimpleNamespace(config=dict(policy=approval_default)))
        ctx.on('session/event', lambda selected, event: raw_events.append(copy.deepcopy(event)))
        sessions = ctx.get('sessions')
        if name == 'mount-existing':
            session = sessions.create('permission-fixture')
        await ctx.plugin(PermissionPresetsPlugin, config)
        if name == 'seed-empty':
            session = sessions.create('permission-fixture', dict(seed=[]))
        elif name in ('seed-historical', 'seed-custom'):
            prior = Session.create('seed-fixture')
            if name == 'seed-custom':
                prior.append('sandbox/mode', dict(mode='read-only'))
            else:
                prior.append('turn/start', dict(turn=1))
                prior.append('turn/end', dict(turn=1, reason=dict(kind='completed')))
            session = sessions.create('permission-fixture', dict(seed=prior.events))
        elif name in ('selected-only', 'sandbox-only', 'approval-only', 'numeric-selected'):
            session = Session.create('permission-fixture')
            if name == 'selected-only':
                session.append('permission/preset', dict(preset='danger-full-access'))
            if name == 'numeric-selected':
                session.append('permission/preset', dict(preset='10'))
            if name == 'sandbox-only':
                session.append('sandbox/mode', dict(mode='read-only'))
            if name == 'approval-only':
                session.append('approval/policy', dict(policy='never'))
            sessions.enter(session)
            sessions.announce(session)
        elif session is None:
            session = sessions.create('permission-fixture')
        service = ctx.get('permissionPresets')
        if name == 'set-danger':
            service.set(session, 'danger-full-access')
        if name == 'set-noop':
            service.set(session, 'workspace-write')
        if name in ('set-alias', 'stale-alias'):
            service.set(session, 'alias')
        if name == 'stale-alias':
            session.append('sandbox/mode', dict(mode='danger-full-access'))
            session.append('approval/policy', dict(policy='never'))
        if name == 'custom-view':
            session.append('sandbox/mode', dict(mode='read-only'))
        if name == 'unknown-set':
            service.set(session, 'foreign')
        observation['result'] = dict(names=service.names, defaultPreset=service.defaultPreset,
            current=service.current(session.events), select=service.selectFor(fold_knobs(session.events)),
            approvalConfig=copy.deepcopy(ctx.get('approval').config),
            events=[dict(type=event['type'], data=copy.deepcopy(event['data'])) for event in session.events])
    except Exception as error:
        observation['error'] = dict(name=getattr(error, 'name', type(error).__name__), message=str(error))
    finally:
        await ctx.fiber.dispose()
    return observation


async def main():
    time.time = lambda: 1791283200
    names = ['fresh','mount-existing','inferred-danger','explicit-danger-default','selected-only','sandbox-only','approval-only',
        'seed-empty','seed-historical','seed-custom','set-danger','set-noop','set-alias','stale-alias','custom-view','unknown-set',
        'reserved-table','unconfined','unmatched-default','unknown-default','empty-description','empty-key','numeric-first','numeric-selected','numeric-boundary']
    rows = [await observe(name) for name in names]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            relative = path.relative_to(arguments.root.resolve()).as_posix()
            modules[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(arguments.root.resolve()), python=sys.version, executable=sys.executable, rows=rows, modules=modules, observedClock=1791283200000), stream, indent=2, ensure_ascii=False)
        stream.write('\n')


asyncio.run(main())
