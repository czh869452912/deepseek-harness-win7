"""Paired Include journal and patch ownership observations."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.cordis import include_journal as journal
from dsh.cordis.include_patch import PatchIndex, route_journal
from dsh.cordis.utils import _UNDEFINED

UNDEF = {'$undefined': True}


def decode(value):
    if value == UNDEF: return _UNDEFINED
    if isinstance(value, dict): return {key: decode(item) for key, item in value.items()}
    if isinstance(value, list): return [decode(item) for item in value]
    return value


def encode(value):
    if value is _UNDEFINED: return UNDEF
    if isinstance(value, dict): return {key: encode(item) for key, item in value.items()}
    if isinstance(value, list): return [encode(item) for item in value]
    return value


def row(entry_id, value=1): return dict(id=entry_id, name='example', config={'value': value})


def upsert(created=False, parent=UNDEF, position=0, **changes):
    return dict(kind='upsert', created=created, parent=parent, position=position, changes=changes)


def cases():
    records = [None, {'kind': 'remove'}, upsert(), upsert(config=None),
               upsert(True, None, 2, config={'value': 2}), upsert(False, 'g', -1, config=UNDEF),
               upsert(False, None, 1, disabled=False)]
    result = [dict(op='merge', older=a, newer=b) for a in records for b in records[1:]]
    values = [{}, {'id': 'x'}, {'name': 'example'}, {'config': None}, {'config': {}},
              {'config': {'value': None}}, {'disabled': False}, {'disabled': 0}, {'config': [None]}]
    result += [dict(op='diff', older=a, newer=b) for a in values for b in values]
    states = [[], [row('a')], [row('a', 2), row('b')],
              [dict(id='g', name='group', group=True, config=[row('a')]), row('b')],
              [dict(id='g', group=True), row('a')], [dict(id='h', group=True, config=[row('a')]), dict(id='g',group=True,config=[])]]
    journals = [{}, {'a': {'kind': 'remove'}}, {'a': upsert(config={'value': 3})},
                {'a': upsert(config=UNDEF)}, {'a': upsert(True, None, 10, name='new')},
                {'a': upsert(False, 'g', 0, disabled=True)}, {'a': upsert(False, 'missing', 0, config={'value': 4})},
                {'g': {'kind': 'remove'}, 'b': upsert(True, 'g', 0, name='new')},
                {'c': upsert(True, 'g', -1, name='new')}, {'a': upsert(False, None, 0, disabled=False)}]
    patches = [[], [{'id': 'a', 'config': {'value': 7}}],
               [{'insert': [row('a'), dict(id='g',group=True,config=[row('c')])]}],
               [{'id':'a','disabled':True}, {'id':'a','disabled':False}],
               [{'id':'g','insert':[row('a')]}, {'id':'a','config':{'value':9}}]]
    for data in states:
        for delta in journals:
            for filtered in (False, True):
                result.append(dict(op='apply', data=data, journal=delta, filtered=filtered))
            for overlays in patches:
                result.append(dict(op='route', data=data, journal=delta, patches=overlays))
            for theirs in states:
                for overlays in patches[:3]:
                    result.append(dict(op='reconcile', base=data, theirs=theirs, journal=delta, patches=overlays))
    for overlays in patches:
        result.append(dict(op='index', patches=overlays, ids=['a','g','c','missing'], keys=['config','disabled','name']))
    for legacy in (None, row('a'), dict(id='a',disabled=True)):
        for moved in (False,True):
            result.append(dict(op='record', legacy=legacy, options=row('a',2), moved=moved))
    return result


def observe(raw):
    case=decode(copy.deepcopy(raw));op=case['op'];warnings=[]
    warn=lambda *args: warnings.append(list(args))
    if op=='merge': return encode(journal.merge_records(case['older'],case['newer']))
    if op=='diff': return encode(journal.diff_options(case['older'],case['newer']))
    if op=='apply':
        data=case['data'];predicate=lambda entry_id,key:not case['filtered'] or (entry_id!='b' and key!='config')
        journal.apply_journal(data,case['journal'],predicate,warn)
        return encode([data,warnings])
    if op=='route':
        changed=route_journal(case['journal'],case['data'],case['patches'],warn)
        return encode([case['data'],case['patches'],changed,warnings])
    if op=='reconcile':
        conflicts=journal.reconcile(case['journal'],journal.flatten(case['base']),journal.flatten(case['theirs']),PatchIndex(case['patches']).file_owned)
        return encode([case['journal'],conflicts])
    if op=='record':
        value=case['options'];change=dict(id='a',options=value,legacy=case['legacy'],group=SimpleNamespace(data=[{},value]))
        if case['moved']:change['from']=object()
        result={};journal.record(result,change,'g');return encode(result)
    index=PatchIndex(case['patches'])
    def owner(value):return {k:v for k,v in value.items() if k not in ('list','options')}
    return [[entry_id,owner(index.entry(entry_id)),[[key,owner(index.key(entry_id,key)),index.file_owned(entry_id,key)] for key in case['keys']]] for entry_id in case['ids']]


async def native(): return [observe(case) for case in cases()]


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_include_journal.mts',prepare=prepare,
        scope='Per-entry delta folding, file-wins conflict reconciliation, nested relocation and patch owner routing. Independent foundation; not production Include persistence acceptance.',
        extra_inputs=[ROOT/'scripts/rc022_include_journal_probe.py',ROOT/'dsh/cordis/include_journal.py',ROOT/'dsh/cordis/include_patch.py',
                      ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/include/src/journal.ts',ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/include/src/patch.ts'])
