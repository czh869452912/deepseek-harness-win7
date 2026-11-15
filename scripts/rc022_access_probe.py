"""Pair wire resource resolution and reversible registry ownership."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows = []
    def add(name, **extra):
        rows.append(dict(name=name, declarations=[], parameters=[], args={}, **extra))
    add('global')
    for value in ['book', '', None, [], ['book'], 1, False, {}]:
        rows.append(dict(name='field-'+str(len(rows)), declarations=[dict(kind='shelf', field='item')], parameters=['item'], args=dict(item=value)))
    rows.extend([
        dict(name='omitted',declarations=[dict(kind='shelf',field='item')],parameters=['item'],args={}),
        dict(name='nested',declarations=[dict(kind='shelf',field='item')],parameters=['options'],args=dict(options=dict(item='nested'))),
        dict(name='first-object-only',declarations=[dict(kind='shelf',field='item')],parameters=['options','other'],args=dict(options={},other=dict(item='ignored'))),
        dict(name='top-level-wins',declarations=[dict(kind='shelf',field='item')],parameters=['options','item'],args=dict(options=dict(item='nested'),item='top')),
        dict(name='resolve',declarations=[dict(kind='shelf',resolve=['named','target'])],parameters=['target'],args=dict(target='resolved')),
        dict(name='resolver-throw',declarations=[dict(kind='shelf',resolve=['throw'])],parameters=[],args={}),
        dict(name='resolver-array',declarations=[dict(kind='shelf',resolve=['constant',['x']])],parameters=[],args={}),
        dict(name='resolver-undefined',declarations=[dict(kind='shelf',resolve=['undefined'])],parameters=[],args={}),
    ])
    for value in [['constant','reader'], ['constant',['a','a','b']], ['constant',[]], ['constant',None], ['undefined'], ['throw']]:
        rows.append(dict(name='reader-'+str(len(rows)),declarations=[dict(kind='shelf',field='item')],parameters=['item'],args=dict(item='default'),readers=dict(shelf=value)))
    rows.extend([
        dict(name='lookup-replaces-default',declarations=[dict(kind='shelf',field='item')],parameters=['agent','item'],args=dict(agent='lookup',item='ignored'),lookups=dict(agent='shelf')),
        dict(name='optional-lookup',declarations=[],parameters=['agent'],args={},lookups=dict(agent='shelf')),
        dict(name='lookup-malformed',declarations=[],parameters=['agent'],args=dict(agent=None),lookups=dict(agent='shelf')),
        dict(name='context-before-lookups',declarations=[dict(kind='shelf',field='options')],parameters=['agent','other'],args=dict(scopeId='context',agent='a',other='b'),context='shelf',lookups=dict(agent='shelf',other='shelf')),
        dict(name='context-missing',declarations=[],parameters=[],args={},context='shelf'),
        dict(name='kind-order-reader-wins',declarations=[dict(kind='shelf',field='item'),dict(kind='desk',field='deskId')],parameters=['agent','item','deskId'],args=dict(agent='lookup',item='ignored',deskId='d'),lookups=dict(agent='shelf'),readers=dict(shelf=['constant','read'],frame=['constant','f'])),
        dict(name='positional-wire-order',declarations=[],parameters=['second','first'],args=dict(second='B',first='A'),readers=dict(shelf=['arg',1])),
        dict(name='cancellation-slot',declarations=[],parameters=['item'],args=dict(item='A'),cancellation=True,readers=dict(shelf=['signal',1])),
    ])
    for value in [None, {}, dict(shelf=['undefined']),dict(shelf=['constant','x']),dict(shelf=['constant',['a','b']]),dict(shelf=['constant',[]]),dict(shelf=['constant',None]),dict(shelf=['throw'])]:
        rows.append(dict(name='event-'+str(len(rows)),event=True,readers=value,args=['event']))
    return rows


def reader(spec, signal):
    from dsh.core.session.json import UNDEFINED
    def read(*values):
        if spec[0] == 'throw':raise RuntimeError('fixture private failure')
        if spec[0] == 'undefined':return UNDEFINED
        if spec[0] == 'constant':return spec[1]
        if spec[0] == 'arg':return values[spec[1]]
        if spec[0] == 'signal':return 'signal' if values[spec[1]] is signal else 'wrong'
        if spec[0] == 'named':return values[0]['args'].get(spec[1],UNDEFINED)
        raise AssertionError(spec)
    return read


async def observe():
    from types import SimpleNamespace as NS
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.access import call_resources, event_resources
    rows=[]; signal=AbortController().signal
    for case in cases():
        ctx=Context();await ctx.plugin(CurrentTypertRegistry)
        try:
            typert=ctx.typert
            readers={kind:reader(spec,signal) for kind,spec in (case.get('readers') or {}).items()}
            if case.get('event'):
                value=event_resources(readers,case['args'])
            else:
                for declaration in case['declarations']:
                    provider=dict(declaration);kind=provider.pop('kind')
                    if 'resolve' in provider:provider['resolve']=reader(provider['resolve'],signal)
                    typert.resources.register(kind,provider)
                parameters=[]
                for name in case['parameters']:
                    parameter=dict(name=name,wire=name)
                    if name in case.get('lookups',{}):
                        parameter['lookup']=name
                        typert.lookups.register(name,NS(parameter=name,wire=name,hostTypeSymbol='host',wireTypeSymbol='wire',resource=case['lookups'][name],resolve=lambda _:None))
                        typert.lookups.configure(name,lambda _:None)
                    parameters.append(parameter)
                invocation=dict(kind='direct')
                if 'context' in case:
                    typert.contexts.registerHost('scope',NS(wire='scopeId',wireTypeSymbol='wire',resource=case['context'],resolve=lambda _:None,identity=lambda _:None))
                    typert.contexts.configureHost('scope',lambda _:None)
                    invocation=dict(kind='context',context='scope',wire='scopeId')
                descriptor=dict(parameters=parameters,invocation=invocation)
                if case.get('cancellation'):descriptor['cancellation']=dict(parameter='signal')
                value=call_resources(typert,readers,descriptor,case['args'],signal)
            rows.append(dict(name=case['name'],value=value))
        finally:await ctx.fiber.dispose()
    ctx=Context();await ctx.plugin(CurrentTypertRegistry);changes=[]
    try:
        ctx.typert.resources.subscribe(changes.append)
        # Prototype methods survive registration; caller mutation cannot erase the branch.
        class Resolver:
            def resolve(self, value):return 'prototype'
        undo=ctx.typert.resources.register('shelf',Resolver())
        errors=[]
        for kind,declaration in [('shelf',dict(field='id')),('global',dict(field='id')),('empty',{})]:
            try:ctx.typert.resources.register(kind,declaration)
            except Exception as error:errors.append(str(error))
        frozen=False
        try:ctx.typert.resources.entries()[0]['kind']='changed'
        except TypeError:frozen=True
        undo();undo()
        rows.append(dict(name='ownership',value=dict(changes=changes,errors=errors,frozen=frozen,empty=ctx.typert.resources.entries()==[])))
    finally:await ctx.fiber.dispose()
    return rows


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_access.mts','Pre-lookup wire resource precedence, positional readers, default fields/resolvers, missing versus malformed identities, events, resource ownership and configured lookup/Context metadata.',
        [Path(__file__).resolve(),ROOT/'dsh/typert/access.py',ROOT/'dsh/typert/resource_registry.py',ROOT/'dsh/typert/current.py'],prepare=prepare)
