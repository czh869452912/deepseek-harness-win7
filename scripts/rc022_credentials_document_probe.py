"""Credential document admission against the unchanged fixed Source parser."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

DIAGNOSTICS = None


def cases():
    rows = ['', '# note\n', '{}', 'null', '[]', 'false', '1', 'secret', 'KEY: secret',
            'version: 1', 'version: 1\nforeign: secret\n', 'version: 1\nforeign: 9007199254740993123456\n',
            'version: 1\nforeign: &x [*x]\n', 'version: 1\nrefs: {YES: yes, ON: on, DATE: 2026-11-17}',
            'version: 1\nrefs: &x {KEY: secret}\nforeign: *x',
            'version: 1\nrecords: {owner/a: {kind: grant, payload: &x [*x]}}',
            'version: 1\nrecords: {owner/a: {kind: grant, payload: {when: 2026-11-17, number: 9007199254740993}}}']
    dump = lambda value: json.dumps(value, ensure_ascii=True)
    for value in [None, False, True, 0, 1.0, 2, '1', [], {}]: rows.append('version: '+dump(value))
    for section in ('refs', 'records'):
        for value in [None, False, True, 0, '', 'secret', [], [1], {}]: rows.append('version: 1\n'+section+': '+dump(value))
    for name in ['KEY', 'bad-name', '1', 'true', '', '\u00e9', '__proto__']:
        for value in ['secret', '', None, False, 1, [], {}]:
            rows.append('version: 1\nrefs: {'+dump(name)+': '+dump(value)+'}')
    for scalar in ['yes','on','off','012','0o12','0x12','0b12','1_000','1:20','1e3','1.0','.inf','.nan','null','~','true','FALSE']:
        rows.append('version: 1\nrefs: {KEY: '+scalar+'}')
    for key in ['owner/a', 'bad-key', 'owner/bad/id']:
        for record in [None, [], 'secret', {}, dict(kind=None), dict(kind='unknown'), dict(kind='api-key'),
                       dict(kind='api-key',key=None), dict(kind='api-key',key=''),dict(kind='api-key',key='secret'),
                       dict(kind='api-key',env=None),dict(kind='api-key',env={}),dict(kind='api-key',env={'KEY':'secret'}),
                       dict(kind='api-key',env={'KEY':''}),dict(kind='api-key',env={'bad-name':'secret'}),
                       dict(kind='api-key',env={'KEY':12}),dict(kind='api-key',foreign='secret'),
                       dict(kind='grant'),dict(kind='grant',payload=None),dict(kind='grant',payload=[1,True,'secret']),
                       dict(kind='grant',payload={},foreign='secret')]:
            rows.append('version: 1\nrecords: {'+dump(key)+': '+dump(record)+'}')
    for raw in ['.inf','.nan','-.inf']:
        rows.append('version: 1\nrecords: {owner/a: {kind: grant, payload: '+raw+'}}')
    rows += ['version: true\nrefs: {}', 'version: 1\nversion: 1', 'version: 1\nrefs: {KEY: secret, KEY: second}',
             'version: 1\nrefs: [secret', 'version: 1\nrefs:\n  KEY: "unterminated-secret',
             'version: 1\nrefs:\n  KEY: secret\n broken', 'version: 1\n---\nrefs: {}']
    rows += ['version: 1\nrefs: {KEY: secret', 'version: 1\nrefs: {KEY: "\\qsecret"}',
             'version: 1\nrefs:\n\tKEY: secret', 'version: 1\nrefs:\n  KEY secret',
             'version: 1\nrefs:\n  KEY: secret\n  KEY: second',
             'version: 1\nrefs: {KEY: !custom secret}',
             'version: 1\nforeign: {[one, two]: secret}',
             'version: 1\nrefs: {1: secret, "1": second}',
             'version: 1\nrefs: {true: secret}',
             'version: 1\nrefs: {KEY: !!str 123}',
             'version: 1\nforeign: {<<: {KEY: secret}}',
             '%YAML 1.1\n---\nversion: 1\nrefs: {KEY: yes}',
             'version: 1\nrecords: {owner/a: {kind: grant, payload: 012}}',
             'version: 1\nrecords: {owner/a: {kind: grant, payload: 1e3}}',
             'version: 1\nrecords: {owner/a: {kind: grant, payload: 0b11}}']
    for count in (98, 99, 100, 101):
        rows.append('version: 1\nforeign: {base: &x secret, aliases: ['+', '.join(['*x']*count)+']}')
    rows += ['version: 1\nforeign: {one: &x secret, two: &x replacement, alias: *x}',
             'version: 1\nforeign: *missing',
             'version: 1\nforeign: {one: &a [secret], two: &b [*a, *a, *a, *a, *a], three: &c [*b, *b, *b, *b, *b], four: [*c, *c, *c, *c, *c]}']
    for tag in ['!!int', '!!float', '!!bool', '!!null', '!!timestamp', '!!binary', '!custom']:
        for value in ['secret-text', '123', '2026-11-17']:
            rows.append('version: 1\nrecords: {owner/a: {kind: grant, payload: '+tag+' '+value+'}}')
    return rows


def prepare(output):
    global DIAGNOSTICS
    DIAGNOSTICS = output/'native-parser-diagnostics.json'
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe(diagnostics=None):
    from dsh.credentials.document_current import parse_credentials_document
    rows = []; raw = []
    for index, text in enumerate(cases()):
        try: rows.append(dict(value=parse_credentials_document(text, '<document>')))
        except Exception as error:
            message = str(error)
            if message.startswith('credentials-local: invalid document at <document>: '):
                raw.append(dict(index=index, error=message))
                message = 'credentials-local: invalid document at <document>: <runtime YAML diagnostic>'
            rows.append(dict(error=message))
    path = diagnostics if diagnostics is not None else DIAGNOSTICS
    if path is not None: path.write_text(json.dumps(raw), encoding='utf-8')
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_credentials_document.mts', 'Pinned credential document admission: core YAML scalars, references/records, foreign keys, safe diagnostics and duplicate keys.',
               [Path(__file__).resolve(), ROOT/'dsh/credentials/document_current.py'], prepare=prepare)
