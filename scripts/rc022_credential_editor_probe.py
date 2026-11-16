"""Actual Source provider writes compared at the durable YAML boundary."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

WORKSPACE = None


def cases():
    documents = [None, '', '# c-header\n', 'version: 1\n', 'version: 1\nrefs: {}\n',
        'version: 1\nrefs: null\n',
        'version: 1\nrefs: {KEY: old, SECOND: second}\nforeign: 9007199254740993123456\n',
        '# c-header\nversion: 1\nrefs:\n  # c-first\n  KEY: old # c-inline\n  # c-second\n  SECOND: second\n# c-foreign\nforeign: 9007199254740993123456\n',
        'version: 1\nforeign: &keys {KEY: old}\nrefs: *keys\n',
        'version: 1\nrecords:\n  # c-record\n  owner/a:\n    # c-kind\n    kind: grant\n    payload: old # c-payload\n  owner/b: {kind: grant, payload: second}\nforeign: {nested: [keep, 9007199254740993123456]}\n',
        '{version: 1, refs: {KEY: old}, foreign: 9007199254740993123456}\n',
        'version: 1.0\nrefs:\n  KEY: old\n', 'KEY: old # c-flat\nSECOND: on\n',
        'null\n', '!!timestamp 2026-11-17\n',
        'version: 1\nrefs: # c-section\n  # c-first\n  KEY: old # c-inline\n  # c-second\n  SECOND: second\n# c-tail\n',
        'version: 1\nrefs:\n  # c-first\n  KEY: old # c-inline\n# c-tail\nforeign: keep\n',
        'version: 1\nrefs:\n  # c-first\n  KEY: old # c-inline\n# c-tail\n',
        'version: 1\nrefs: {KEY: old, # c-flow-first\n  SECOND: second # c-flow-second\n}\n# c-tail\n',
        'version: 1\nrefs:\n  KEY: | # c-block\n    old\n    continued\n  # c-second\n  SECOND: second\n',
        'version: 1\nrecords:\n  owner/a: {kind: grant, payload: old} # c-record-inline\n  owner/b: {kind: grant, payload: second}\n',
        'version: 1\nrecords:\n  owner/a: # c-record-value\n    # c-kind\n    kind: grant\n    payload: old\n  owner/b: {kind: grant, payload: second}\n',
        'version: 1\nrefs: {KEY: old}\nforeign: {decimal: 9007199254740993123456, hex: 0xabcdef, octal: 0o123}\n']
    operations = [dict(section='refs', key='KEY', value='new'), dict(section='refs', key='THIRD', value='yes'),
        dict(section='refs', key='KEY'), dict(section='refs', key='SECOND'),
        dict(section='records', key='owner/a', value=dict(kind='grant',payload=dict(value='new',lines='first\nsecond'))),
        dict(section='records', key='owner/c', value=dict(kind='api-key',key='stored-key',env=dict(OWN_KEY='owned'))),
        dict(section='records', key='owner/a'), dict(section='records', key='owner/b')]
    return [dict(text=text, **operation) for text in documents for operation in operations]


def prepare(output):
    global WORKSPACE
    WORKSPACE = output/'files/native'
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe(workspace=None):
    import datetime
    import re
    from dsh.credentials.document_current import load_document, parse_credentials_document, render_flat_layout_migration, _Collection
    from dsh.credentials.editor_current import render_edit
    directory = workspace if workspace is not None else WORKSPACE
    assert directory is not None
    directory.mkdir(parents=True, exist_ok=True)
    def normalized(value):
        if isinstance(value, bool): return value
        if isinstance(value, int): return {'$integer': str(value)}
        if isinstance(value, datetime.date):
            stamp = value if isinstance(value, datetime.datetime) else datetime.datetime.combine(value, datetime.time())
            if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=datetime.timezone.utc)
            return {'$date':stamp.astimezone(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')}
        if isinstance(value, _Collection):
            return {'$set':[normalized(item) for item in value.items]} if value.kind == 'set' else {'$map':[[normalized(key),normalized(item)] for key,item in value.items]}
        if isinstance(value, bytes): return {'$bytes':list(value)}
        if isinstance(value, list): return [normalized(item) for item in value]
        if isinstance(value, dict): return {key:normalized(item) for key,item in value.items()}
        return value
    rows = []
    for index, entry in enumerate(cases()):
        filename = directory/(str(index)+'.yaml'); text = entry['text']; error = None
        if text is not None: filename.write_bytes(text.encode('utf-8'))
        try:
            migrated = render_flat_layout_migration(text or '')
            if migrated is not None:
                text = migrated; filename.write_bytes(text.encode('utf-8'))
            parsed = parse_credentials_document(text or '', '<document>')
            if 'value' in entry or entry['key'] in parsed[entry['section']]:
                result = render_edit(text, entry['section'], entry['key'], **({'value':entry['value']} if 'value' in entry else {}))
                filename.write_bytes(result.encode('utf-8'))
        except Exception as failure: error = str(failure)
        text = filename.read_bytes().decode('utf-8') if filename.exists() else None
        document = normalized(load_document(text, '<document>', keep_int=True)) if text is not None else None
        rows.append(dict(error=error, present=text is not None, document=document, comments=[] if text is None else re.findall(r'# (c-[a-z-]+)', text)))
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_credential_editor.mts', 'Durable credential editor: admitted documents, Source error boundaries, retained annotations and exact foreign integer values.',
               [Path(__file__).resolve(), ROOT/'dsh/credentials/editor_current.py', ROOT/'dsh/credentials/document_current.py'], prepare=prepare)
