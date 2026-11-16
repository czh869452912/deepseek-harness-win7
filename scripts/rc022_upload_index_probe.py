"""Actual durable index transitions and byte-for-byte canonical rewrites."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = None


def record(**changes):
    row = dict(scope='a'*64, attachmentId='sha256:'+'b'*64, variantId='sha256:'+'c'*64,
               fileId='file-雪', bytes=4, createdAt=1000, expiresAt=100000)
    row.update(changes); return row


def cases():
    valid = record(); envelope = lambda rows: dict(formatVersion=3, records=rows)
    initial = [None, 'not-json', 'null', '[]', '{}', '{"formatVersion":2,"records":[]}',
               json.dumps(envelope([])), json.dumps(envelope([valid])), json.dumps(envelope([valid, valid]))]
    for field, values in dict(scope=['A'*64, None], variantId=['bad'], attachmentId=['bad'],
                               fileId=['', None], bytes=[-1, True, 1.0, 9007199254740992],
                               createdAt=[None, 0.0], expiresAt=[1001, 1002, 1003, 0.0]).items():
        for value in values:
            changed = dict(valid); changed[field] = value; initial.append(json.dumps(envelope([changed])))
    initial += [json.dumps(envelope([valid, record(scope='d'*64, variantId='sha256:'+'e'*64, expiresAt=0)])),
                '{"formatVersion":3,"records":[NaN]}',
                json.dumps(envelope([dict(valid, extra='ignored')]))]
    return [dict(text=text) for text in initial]


def prepare(output):
    global WORKSPACE
    WORKSPACE = output/'files'; WORKSPACE.mkdir()
    path = output/'inputs.json'; path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8')
    return [path]


async def observe(workspace=None):
    from dsh.llm.deepseek_upload_index_current import DeepSeekUploadIndex, deepSeekFileScope
    root = workspace or WORKSPACE
    rows = []
    for index, entry in enumerate(cases()):
        path = root/('native-'+str(index))/'index.json'; path.parent.mkdir(parents=True)
        if entry['text'] is not None: path.write_text(entry['text'], encoding='utf-8')
        store = DeepSeekUploadIndex(str(path)); events = []
        async def step(name, operation):
            value = await operation
            events.append(dict(name=name, value=value, text=path.read_text(encoding='utf-8') if path.exists() else None))
        await step('get', store.get('a'*64, 'sha256:'+'c'*64, 1000, 2))
        await step('commit', store.commit(record(fileId='new'), 1000, 2))
        await step('second', store.commit(record(variantId='sha256:'+'f'*64, fileId='second', bytes=1.0), 1000, 2))
        await step('remove', store.remove('a'*64, [dict(variantId='sha256:'+'c'*64, fileId='old'),
                    dict(variantId='sha256:'+'f'*64, fileId='second'), dict(variantId='sha256:'+'f'*64, fileId='second')]))
        await step('clear-other', store.clear('d'*64))
        await step('get-after', store.get('a'*64, 'sha256:'+'c'*64, 99998, 2))
        await step('expire', store.commit(record(fileId='successor', bytes=0), 99998, 2))
        await step('remove-stale', store.remove('a'*64, [dict(variantId='sha256:'+'c'*64, fileId='new')]))
        await step('clear', store.clear('a'*64))
        rows.append(dict(index=index, events=events, leftovers=sorted(p.name for p in path.parent.iterdir())))
    for base in ('https://a/v1', 'https://a/v1///', 'https://a/雪'):
        for credential in ('', 'secret', '雪', 'a\0b', '\ud800', '\ud800\udc00'):
            rows.append(dict(base=base, credential=credential, scope=deepSeekFileScope(base, credential)))
    return json.loads(json.dumps(rows, ensure_ascii=True))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_upload_index.mts', 'Actual upload-index disk transitions, canonical bytes, generation sets and namespace hashes.',
               [Path(__file__).resolve(), ROOT/'dsh/llm/deepseek_upload_index_current.py'], prepare=prepare)
