"""Pinned actual OTLP HTTP payloads and channel-local transport metadata."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    event = dict(seq=1, time=1700000000123.5, type='fixture', data=dict(text='synthetic'))
    session = dict(sessionId='fixture-session', event=event, attributes=dict(flag=True, count=2, fraction=1.25))
    ordinary = dict(eventName='fixture', body='synthetic', timestamp=event['time'], attributes=dict(flag=True, count=2, fraction=1.25))
    rows = [dict(kind=kind, records=[record], scope=dict(name='fixture', version='1'),
        resourceAttributes={'service.name':'fixture','flag':True,'count':2})
        for kind, record in [('session',session),('event',ordinary)]]
    import copy
    values = [None, False, True, '', '\U0001f600\nline', 0, -1, 1.5, 9007199254740992,
              [], [None, 1, True, 'x', {'nested': ['a']}], {}, {'10':'ten','2':'two','nested':None},
              'long-'+('a\U0001f600'*2048), -0.0, 1e-8, 1e21]
    for base in rows[:2]:
        for value in values:
            entry=copy.deepcopy(base);entry['records'][0]['attributes']['typed']=value
            entry['resourceAttributes']['typed']=value;rows.append(entry)
        entry=copy.deepcopy(base);entry['records'][0]['attributes']={str(index): index for index in range(132)}
        rows.append(entry)
        for count in [0, 2, 5]:
            entry=copy.deepcopy(base);entry['records']*=count;entry['scope'].pop('version');rows.append(entry)
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.session.otel_records_current import session_log_record,event_log_record
    from dsh.session.otel_wire_current import serialize_records
    rows=[]
    for entry in cases():
        session=entry['kind']=='session'
        records=[session_log_record(record) if session else event_log_record(record,1700000000999) for record in entry['records']]
        payload=serialize_records(records,entry['scope'],entry['resourceAttributes'],session,1700000000999)
        captures=[] if not records else [dict(document=json.loads(payload),bytes=len(payload))]
        rows.append(dict(captures=captures,warnings=[],error=None))
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_otel_wire.mts', 'Actual pinned OTLP HTTP payloads versus staged Native pure wire serialization, including exact UTF-8 size; no Native queue/transport claim.',
        [Path(__file__).resolve(), ROOT/'dsh/session/otel_wire_current.py'], prepare=prepare)
