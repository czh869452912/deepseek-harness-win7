import argparse
import asyncio
import copy
import hashlib
import inspect
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
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.core.scope import create_scope
from dsh.core.session import SessionPlugin
from dsh.interaction.commands import CommandsPlugin
from dsh.interaction.permission_presets import PermissionPresetsPlugin
from dsh.interaction.user_approval import UserApprovalPlugin
from dsh.session.projections import SessionProjectionsPlugin
from dsh.settings.provider import SettingsProvider


class MemorySettings(SettingsProvider):
    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self.doc = {}

    def load(self):
        return copy.deepcopy(self.doc)

    async def _persist_section(self, namespace, section):
        self.doc[namespace] = copy.deepcopy(section)


class AgentScope(Plugin):
    inject = ['commands']

    def apply(self, ctx):
        create_scope(ctx, self.config['agent'])


async def main():
    ctx = Context()
    rows, raw_errors = [], []
    try:
        await ctx.plugin(SessionPlugin)
        ctx.provide('shell', SimpleNamespace(sandboxMode='workspace-write'))
        await ctx.plugin(UserApprovalPlugin)
        await ctx.plugin(CommandsPlugin)
        await ctx.plugin(SessionProjectionsPlugin)
        settings_fiber = await ctx.plugin(MemorySettings)
        permission_fiber = await ctx.plugin(PermissionPresetsPlugin, dict(presets={
            'workspace-write': dict(sandbox='workspace-write', approval='ask', name='Workspace'),
            'danger-full-access': dict(sandbox='danger-full-access', approval='never', name='Full', description=''),
        }))
        rows.append(dict(name='settings-labels', value=ctx.get('settings').describe()))
        session = ctx.get('sessions').create('permission-lifecycle')
        rows.append(dict(name='initial-projection', value=ctx.get('sessionProjections').snapshot(session)))
        definition = ctx.get('sessionProjections').get_unit('permissions')
        states = [dict(preset=None, sandbox=None, approval=None), dict(preset='', sandbox='read-only', approval='never'),
            dict(preset=None, sandbox='foreign', approval=None), dict(preset=None, sandbox=None, approval='foreign'),
            dict(preset=None, sandbox=None, approval=None, extra=True), dict(preset=None, sandbox=None),
            dict(preset=5, sandbox=None, approval=None), None, [], dict(preset='custom', sandbox='workspace-write', approval='ask')]
        views = [dict(options=[], currentValue='custom'), dict(options=[dict(value='v', name='n', description='', extra=1)], currentValue='v', extra=1),
            dict(options=[dict(value='v', name='n')], currentValue='v'), dict(options=[dict(value='', name='n')], currentValue='v'),
            dict(options=[dict(value='v', name='')], currentValue='v'), dict(options=[dict(value='v', name='n', description=None)], currentValue='v'),
            dict(options=[], currentValue=''), dict(options={}, currentValue='v'), None]
        for kind, values, schema in [('state', states, definition['stateSchema']), ('view', views, definition['wire']['viewSchema'])]:
            for index, value in enumerate(values):
                name = '%s-%s' % (kind, index)
                try:
                    rows.append(dict(name=name, value=schema(value)))
                except Exception as error:
                    rows.append(dict(name=name, refused=True))
                    raw_errors.append(dict(name=name, error=dict(name=type(error).__name__, message=str(error))))
        injected = []
        agent = SimpleNamespace(id=session.id, session=session, inject=lambda value: injected.append(copy.deepcopy(value)))
        await ctx.plugin(AgentScope, dict(agent=agent))
        for index, line in enumerate(['/permission', '/permission foreign', '/permission danger-full-access',
                                     '/permission danger-full-access', '/permission workspace-write']):
            execution = await ctx.get('commands').execute(agent, line, [], AbortController().signal)
            rows.append(dict(name='command-%s' % index, line=line, value=execution.result if execution else None,
                current=ctx.get('permissionPresets').current(session.events),
                knobs=[dict(type=event['type'], data=copy.deepcopy(event['data'])) for event in session.events
                       if event['type'] in ('permission/preset', 'sandbox/mode', 'approval/policy')],
                approvalConfig=copy.deepcopy(ctx.get('approval').config), injected=copy.deepcopy(injected)))
        pending = ctx.get('settings').replace('permission', dict(defaultPreset='danger-full-access'))
        if inspect.isawaitable(pending):
            await pending
        rows.append(dict(name='live-default', value=ctx.get('permissionPresets').defaultPreset, descriptors=ctx.get('settings').describe()))
        future = ctx.get('sessions').create('permission-future')
        rows.append(dict(name='future-default', value=ctx.get('sessionProjections').snapshot(future)))
        await settings_fiber.dispose()
        rows.append(dict(name='settings-detach', value=ctx.get('permissionPresets').defaultPreset))
        await permission_fiber.dispose()
        rows.append(dict(name='permission-unload', value=ctx.get('sessionProjections').snapshot(session),
                         command=await ctx.get('commands').execute(agent, '/permission', [], AbortController().signal)))
    finally:
        await ctx.fiber.dispose()
    modules = {}
    for name, module in sorted(sys.modules.items()):
        if name == 'dsh' or name.startswith('dsh.'):
            filename = getattr(module, '__file__', None)
            if filename:
                path = Path(filename).resolve()
                relative = path.relative_to(selected_root).as_posix()
                modules[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(selected_root), executable=sys.executable, python=sys.version,
                       modules=modules, rows=rows, rawErrors=raw_errors), stream, ensure_ascii=False, indent=2)
        stream.write('\n')


asyncio.run(main())
