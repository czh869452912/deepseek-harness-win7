"""Live permission catalog, current-only projection and Auto contribution lifecycle."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.awaiting import await_callback_result
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSession
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.interaction.permission_current import CurrentPermissionPresets
    class Projections(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    ctx=Context();await ctx.plugin(Projections)
    ctx.set_service('shell',NS(sandboxMode='workspace-write'));ctx.set_service('approval',NS(config=dict(policy='ask')))
    ctx.set_service('sessions',NS(list=lambda:[]));ctx.set_service('agents',NS(list=lambda:[]))
    commands=[];ctx.set_service('commands',NS(register=lambda definition:commands.append(definition)))
    table={'workspace-write':dict(sandbox='workspace-write',approval='ask',name='Workspace'), 'same':dict(sandbox='workspace-write',approval='ask'), 'danger-full-access':dict(sandbox='danger-full-access',approval='never')}
    owner=await ctx.plugin(CurrentPermissionPresets,dict(presets=table));service=ctx.permissionPresets;rows=[];catalog_events=[];admissions=[]
    def session(identity,seed=None):return CurrentSession.create(identity,seed,format_version=4)
    def events(subject):return [dict(type=event['type'],data=event['data']) for event in subject.snapshotEvents()]
    def snapshot(subject):return dict(current=service.current(subject),wire=ctx.sessionProjections.snapshot(subject,['permissions'])['values'],events=events(subject))
    def row(name,**value):rows.append(dict(name=name,**value))
    def failed():raise RuntimeError('listener defect')
    async def async_failed():raise RuntimeError('async listener defect')
    ctx.on('permission-presets/catalog-changed',failed);ctx.on('permission-presets/catalog-changed',async_failed)
    ctx.on('permission-presets/catalog-changed',lambda:catalog_events.append(service.catalog()))
    try:
        fresh=session('fresh');row('initial',catalog=service.catalog(),selection=snapshot(fresh))
        ctx.emit('agent/created',dict(agent=NS(session=fresh)));row('created',selection=snapshot(fresh))
        service.set(fresh,'same');service.set(fresh,'same');row('shared-bundle',selection=snapshot(fresh))
        command=commands[0]['handler'];row('command-query',value=command(NS(agent=NS(session=fresh),rawInput=' \ufeff ')));row('command-unknown',value=command(NS(agent=NS(session=fresh),rawInput='unknown')))
        def admit():admissions.append('admitted')
        class Auto(Plugin):
            inject=['permissionPresets']
            def apply(self,scope):scope.permissionPresets.registerAuto(admit)
        auto=await ctx.plugin(Auto);await asyncio.sleep(0);await asyncio.sleep(0)
        row('registered',catalog=service.catalog(),selection=snapshot(fresh),notifications=len(catalog_events))
        try:service.registerAuto(lambda:None)
        except Exception as error:row('duplicate',message=str(error))
        service.set(fresh,'auto');service.set(fresh,'auto');row('auto-selected',selection=snapshot(fresh),admissions=list(admissions))
        fresh.append('approval/policy',dict(policy='never'));row('delegated-never',selection=snapshot(fresh))
        restored=session('restored',fresh.snapshotEvents());ctx.emit('agent/created',dict(agent=NS(session=restored)));row('restored-live',selection=snapshot(restored),admissions=list(admissions))
        await auto.dispose();await asyncio.sleep(0);await asyncio.sleep(0);row('unregistered',catalog=service.catalog(),selection=snapshot(fresh),notifications=len(catalog_events))
        no_integration=session('no-integration',fresh.snapshotEvents());before=events(no_integration)
        try:ctx.emit('agent/created',dict(agent=NS(session=no_integration)))
        except Exception as error:row('restore-refused',message=str(error),unchanged=events(no_integration)==before)
        try:service.set(fresh,'auto')
        except Exception as error:row('unavailable',message=str(error))
        def refuse():raise RuntimeError('admission refused')
        release=service.registerAuto(refuse);before=events(fresh)
        try:service.set(fresh,'auto')
        except Exception as error:row('admission-refused',message=str(error),unchanged=events(fresh)==before)
        await await_callback_result(release());await asyncio.sleep(0);await asyncio.sleep(0)
        fresh.append('sandbox/mode',dict(mode='read-only'));row('custom',selection=snapshot(fresh),option=service.optionOf('custom'))
        seeded=session('seeded',[]);ctx.emit('agent/created',dict(agent=NS(session=seeded)));row('seeded',selection=snapshot(seeded))
        await owner.dispose();row('unload',service=ctx.get('permissionPresets') is not None,wire=ctx.sessionProjections.snapshot(fresh,['permissions'])['values'])
        return json.loads(json.dumps(rows))
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_permission_catalog.mts','Actual current permission Service and v4 projection: process catalog/default choices separate from current-only Session selection, creation pinning, shared-bundle identity/no-op, command query/unknown, child-owned live Auto contribution, duplicate/admission fences, non-vetoing sync/async catalog observers, delegated never, restore with/without integration, custom derivation, seeded sessions and unload.',[Path(__file__).resolve(),ROOT/'dsh/interaction/permission_current.py'])
