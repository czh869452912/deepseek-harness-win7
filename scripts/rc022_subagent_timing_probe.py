"""Pair completion markers, descriptor resets and the real fork seed provider."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    descriptor = dict(version=3, mode='continuable', provider='fork', label='Child')
    def event(kind, time, data=None):
        return dict(type=kind, time=time, data=data or {})
    start = lambda time: event('turn/start', time)
    end = lambda time, reason='completed': event('turn/end', time, dict(reason=dict(kind=reason)))
    desc = lambda time, data=descriptor: event('subagent/descriptor', time, data)
    return dict(timelines=[[], [end(1)], [start(1),end(2)], [start(1),desc(3),event('x',5),end(8)],
        [desc(1),start(2),end(5),start(8),end(10,'cancelled')],
        [desc(1),start(5),end(3,'failed'),end(9)],
        [desc(1),start(2),end(7),start(9),desc(10),end(15)],
        [desc(1),start(2),end(7),desc(9,dict(version=99)),start(10),end(12)],
        [desc(1),desc(2,dict(version=3,mode='continuable'))]],
        schemas=[{},dict(settledMs=0),dict(settledMs=0,lastTurnCompleted=True),
            dict(settledMs=0,lastTurnCompleted=None),dict(settledMs=0,lastTurnCompleted=1),
            dict(settledMs=9007199254740991),dict(settledMs=9007199254740992),
            dict(settledMs=True),dict(settledMs=1.5),dict(settledMs=-1),
            dict(settledMs=0,active=dict(since=2,through=1)),dict(settledMs=0,extra=0)])


async def observe():
    from dsh.subagent.projections import TIMING4, IDENTITY
    from dsh.subagent.in_process import InProcessProvider
    data, rows = cases(), []
    for index, events in enumerate(data['timelines']):
        states = [definition['init'](None,0) for definition in (TIMING4,IDENTITY)]
        steps = []
        for seq, raw in enumerate(events):
            event = dict(raw,seq=seq)
            values, same = [], []
            for position, definition in enumerate((TIMING4,IDENTITY)):
                previous = states[position]
                states[position] = definition['apply'](previous,event)
                definition['stateSchema'](states[position])
                values.append(definition['wire']['viewSchema'](definition['wire']['view'](states[position])))
                same.append(states[position] is previous)
            steps.append(dict(values=values,same=same))
        rows.append(dict(kind='timeline',index=index,steps=steps))
    for value in data['schemas']:
        try: TIMING4['wire']['viewSchema'](value); valid=True
        except ValueError: valid=False
        rows.append(dict(kind='schema',value=value,valid=valid))
    for cut in (0,1,3,4,5):
        events = [dict(type=kind,seq=seq,time=seq,data={}) for seq,kind in enumerate(
            ['turn/start','assistant/message','turn/end','turn/start','assistant/chunk'][:cut])]
        parent = SimpleNamespace(session=SimpleNamespace(events=events))
        provider = InProcessProvider('fork', True)
        spec = await provider.prepareContinuable(dict(parent=parent))
        captured = copy.deepcopy(spec)
        events.append(dict(type='turn/end',seq=len(events),time=10,data={}))
        rows.append(dict(kind='fork',cut=cut,spec=spec,unchanged=spec==captured))
    return rows


def prepare(output):
    path = output/'cases.json'
    path.write_text(json.dumps(cases()),encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_subagent_timing.mts', 'Completion markers, no-op identity, inherited descriptor resets, safe integer schemas and actual fork provider one-time completed prefix capture.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/projections.py',ROOT/'dsh/subagent/descriptor.py',ROOT/'dsh/subagent/in_process.py'],prepare=prepare)
