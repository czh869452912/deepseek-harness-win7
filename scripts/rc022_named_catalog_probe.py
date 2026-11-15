"""Pair named child admission and every catalog generation with fixed Source."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    names = ['', 'lead', 'Lead', 'a', 'a-0', '-a', '0a', 'a_b', 'a/b', 'a b', 'é', '中', 'a\n', 'a\r', 'a\u2028',
             'a'*31, 'a'*32, 'a'*33, 'b1234567-1234-1234-1234-123456789012', 'constructor', '__proto__']
    facts = []
    for version, mode in ((0,'one-shot'), (0,'continuable'), (1,'one-shot'), (1,'continuable'), (1,'unknown'),
                          (2,'external'), (3,'continuable'), (3,'external')):
        row = dict(version=version, childId='child', childCreatedAt=0, mode=mode)
        if mode == 'continuable': row['label'] = ''
        if version == 3: row['name'] = 'worker'
        facts.append(row)
    invalid = [None, {}, dict(facts[0], extra=True), dict(facts[0], childCreatedAt=True), dict(facts[0], childCreatedAt=-1),
               dict(facts[0], childCreatedAt=.1), dict(facts[0], childCreatedAt=9007199254740992), dict(facts[0], version=True),
               dict(facts[0], version=4), dict(facts[0], mode='unknown'), dict(facts[0], mode='external'),
               dict(facts[0], name='worker'), dict(facts[1], label=None), dict(facts[6], name='lead'),
               dict(facts[6], mode='one-shot'), dict(facts[7], name='Bad'), dict(facts[7], label=1)]
    return dict(names=names, facts=facts+invalid)


async def observe():
    from dsh.subagent import catalog
    from dsh.subagent.names import (is_agent_name, join_agent_path, agent_address, parent_agent_path, SiblingNameReservations)
    from dsh.core.session.json import UNDEFINED
    data = cases()
    rows = [dict(kind='name', value=name, valid=is_agent_name(name)) for name in data['names']]
    for path in (UNDEFINED, '', 'a', 'a/b'):
        for name in (UNDEFINED, 'c'):
            joined = join_agent_path(path, name)
            rows.append(dict(kind='path', address=agent_address(path,'legacy-id'), joined=None if joined is UNDEFINED else joined,
                parent=None if joined is UNDEFINED or joined == '' else parent_agent_path(joined)))
    reservations = SiblingNameReservations()
    left, right = {}, {}
    committed = {'agent-1', 'saved'}
    first = reservations.reserve(left, committed)
    second = reservations.reserve(left, committed)
    other = reservations.reserve(right, committed)
    errors = []
    for name in ('saved', first.name, 'lead', 'Bad'):
        try: reservations.reserve(left, committed, name)
        except Exception as error: errors.append(dict(code=error.code, message=str(error)))
    first.release(); first.release()
    replacement = reservations.reserve(left, committed)
    first.release()
    after = reservations.reserve(left, committed)
    rows.append(dict(kind='reservations', names=[first.name,second.name,other.name,replacement.name,after.name], errors=errors))
    for entry in (second,other,replacement,after): entry.release()
    fresh = reservations.reserve(left, set())
    rows.append(dict(kind='released', name=fresh.name))
    fresh.release()
    replacement = reservations.reserve(left, set())
    fresh.release()
    concurrent = reservations.reserve(left, set())
    rows.append(dict(kind='stale-pool', names=[replacement.name, concurrent.name]))
    replacement.release(); concurrent.release()
    for item in data['facts']:
        initial = dict(inheritedEventCount=1)
        ignored = catalog.apply(initial, dict(type='subagent/catalog', seq=0, data=item))
        row = dict(kind='fact', fact=item, inheritedSame=ignored is initial)
        try:
            state = catalog.apply(initial, dict(type='subagent/catalog', seq=1, data=item))
            restored = catalog.parse_state(state)
            row.update(accepted=True, view=catalog.parse_view(catalog.view(restored)), detached=restored is not state,
                previousSame=catalog.apply(state, dict(type='session/title', seq=2)) is state)
        except ValueError: row['accepted'] = False
        rows.append(row)
    state = dict(inheritedEventCount=0)
    valid = data['facts'][6]
    retained = []
    for index in range(190):
        state = catalog.apply(state, dict(type='subagent/catalog', seq=index, data=dict(valid, childId=str(index))))
        if index in (63,127): retained.append(state['head'])
    restored = catalog.parse_state(state)
    rows.append(dict(kind='chunks', capacity=len(state['head']['values']), count=len(catalog.view(restored)),
                     shared=state['head']['previous'] is retained[1] and retained[1]['previous'] is retained[0],
                     names=sorted(catalog.catalog_names(catalog.view(state)))))
    for bad in (dict(inheritedEventCount=0, head=None), dict(inheritedEventCount=0, head=dict(values=[])),
                dict(inheritedEventCount=0, head=dict(values=[valid], previous=None)),
                dict(inheritedEventCount=0, head=dict(values=[valid]*65)), dict(inheritedEventCount=0, surprise=True)):
        try: catalog.parse_state(bad); accepted = True
        except ValueError: accepted = False
        rows.append(dict(kind='checkpoint', accepted=accepted))
    recorded = []
    parent = SimpleNamespace(append=lambda name,value: recorded.append(dict(type=name, data=value)))
    catalog.establish_catalog_child(parent, dict(id='local',createdAt=10), dict(mode='continuable',label='Local'), 'local')
    with patch.object(catalog.time, 'time', return_value=.1):
        catalog.establish_external_catalog_child(parent, 'remote', 'External', 'remote')
    rows.append(dict(kind='recorded', rows=recorded))
    return rows


def prepare(output):
    path = output/'cases.json'
    path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_named_catalog.mts', 'Names, synchronous exact-parent sibling reservations and stale release, complete paths/history fallback, all catalog v0-v3 modes, inherited admission, strict malformed facts/checkpoints, immutable 64-entry chunks and local/external recording.',
        [Path(__file__).resolve(), ROOT/'dsh/subagent/names.py', ROOT/'dsh/subagent/catalog.py'], prepare=prepare)
