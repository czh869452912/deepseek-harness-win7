"""Real Python counterparts of session-projection.spec.ts observations."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionPlugin
from dsh.session.projections import SessionProjectionRegistry


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('integer')
    return value


def unit(key='probe', wire=True):
    definition = dict(key=key, stateVersion=1, stateSchema=integer,
                      init=lambda header: 0, apply=lambda state, event: state + 1)
    if wire:
        definition['wire'] = dict(viewSchema=integer, view=lambda state: state)
    return definition


async def run():
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    reg = SessionProjectionRegistry(ctx)
    try:
        rows, changes = [], []
        session = ctx.get('sessions').create('probe')
        session.append('probe/event', {})
        release, shared = reg.register(unit()), reg.register(unit())
        reg.onChanged(lambda session, key, value, seq: changes.append(dict(key=key,value=value,seq=seq)))
        session.append('probe/event', {})
        rows.append(dict(mode='late',snapshot=reg.snapshot(session),changes=list(changes)))
        release(); release()
        rows.append(dict(mode='shared',snapshot=reg.snapshot(session)))
        rows.append(dict(mode='identity',snapshot=reg.snapshot(Session('probe'))))
        reg.register(unit('host',False))
        rows.append(dict(mode='selected',snapshot=reg.snapshot(session,[]),checkpoint=reg.checkpoint(session)))
        checkpoint = reg.checkpoint(session)
        checkpoint['probe']['val'] = 99
        rows.append(dict(mode='detached',snapshot=reg.snapshot(session),floor=reg.restoreFloor(checkpoint)))
        restored = reg.restore({},session.events,0,session.header)
        rows.append(dict(mode='restore',**restored,empty=reg.restore(restored['checkpoint'],[],session.seq,session.header)))
        truncated = invalid = False
        try: reg.restore(restored['checkpoint'],[],1,session.header)
        except ValueError: truncated = True
        try: reg.register(dict(unit(),stateVersion=2))
        except ValueError: invalid = True
        rows.append(dict(mode='guards',truncated=truncated,invalid=invalid,
                         hints=reg.viewCheckpoint(dict(probe=dict(ver=1,seq=1,val='bad')))))
        prepared = Session('prepared')
        prepared.append('probe/event',{}); prepared.append('probe/event',{})
        prefix = prepared.events[:1]
        hydrated = reg.hydrate(prepared,{},prefix,0)
        again = reg.hydrate(prepared,{},prefix,0)
        rows.append(dict(mode='hydrate',hydrated=hydrated,again=again,snapshot=reg.snapshot(prepared)))
        shared()
        rows.append(dict(mode='unregistered',snapshot=reg.snapshot(session)))
        Path(sys.argv[1]).write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
    finally:
        await ctx.fiber.dispose()


asyncio.run(run())
