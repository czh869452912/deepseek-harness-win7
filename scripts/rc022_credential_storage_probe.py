"""Actual mounted current credential provider lifecycle and durable operations."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_credential_editor_probe import cases as editor_cases

WORKSPACE = None


def cases():
    texts = list(dict.fromkeys(row['text'] for row in editor_cases()))
    return texts + ['version: 2\nrefs: {KEY: secret}\n', 'version: 1\nrefs: {KEY: 1}\n',
                    'version: 1\nrecords: null\n', 'version: 1\nrefs: {}\nrecords: {}\n']


def prepare(output):
    global WORKSPACE
    WORKSPACE = output/'files/native'
    path = output/'inputs.json'
    path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


async def observe(workspace=None):
    import asyncio
    from dsh.cordis.awaiting import await_callback_result
    from dsh.cordis.context import Context
    from dsh.credentials.local_current import CurrentCredentialsLocalPlugin
    directory = workspace or WORKSPACE
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, text in enumerate(cases()):
        filename = directory/(str(index)+'.yaml')
        if text is not None: filename.write_bytes(text.encode('utf-8')); filename.chmod(0o600)
        ctx = Context(); events = []; states = []
        ctx.on('credentials/reference-updated', lambda key: events.append('ref:'+key))
        ctx.on('credentials/record-updated', lambda key: events.append('record:'+key))
        def error_text(error): return str(error).replace(str(filename), '<file>')
        def snapshot(error=None):
            service = ctx.credentials
            return dict(error=error, exists=filename.exists(), events=list(events),
                ref=service.resolve('KEY'), info=service.describe('KEY'),
                record=service.readRecord('owner/a'), records=service.listRecords())
        try:
            try: await ctx.plugin(CurrentCredentialsLocalPlugin, dict(path=str(filename), watch=False))
            except Exception as error:
                rows.append(dict(activation=error_text(error), exists=filename.exists())); continue
            service = ctx.credentials
            states.append(snapshot())
            record = dict(kind='grant', payload=dict(count=1))
            operations = [lambda: service.set('KEY', 'new'), lambda: service.set('KEY', 'new'),
                lambda: service.unset('ABSENT'), lambda: service.modifyRecord('owner/a', lambda _: record),
                lambda: service.modifyRecord('owner/a', lambda _: None),
                lambda: service.set('KEY', ''), lambda: service.deleteRecord('owner/missing'),
                lambda: service.unset('KEY'), lambda: service.deleteRecord('owner/a')]
            for operation in operations:
                error = None
                try: await await_callback_result(operation())
                except Exception as failure: error = error_text(failure)
                # Snapshot must capture current values rather than references later mutated.
                states.append(json.loads(json.dumps(snapshot(error))))
            external = 'version: 1\nrefs: {KEY: external}\nrecords: {owner/a: {kind: grant, payload: {n: 2, x: true}}}\n'
            filename.write_bytes(external.encode('utf-8')); await service.queue_refresh(); states.append(snapshot())
            filename.write_bytes(b'version: 2\nrefs: {KEY: secret}\n'); await service.queue_refresh(); states.append(snapshot())
            filename.write_bytes(external.encode('utf-8')); await service.set('OTHER', 'other'); states.append(snapshot())
            filename.unlink(); await service.queue_refresh(); states.append(snapshot())
            rows.append(dict(activation=None, states=states))
        finally: await ctx.fiber.dispose()
    # Hold the actual writer inside a mutator while a later operation queues.
    ctx = Context(); entered = asyncio.Event(); release = asyncio.Event()
    filename = directory/'drain.yaml'
    await ctx.plugin(CurrentCredentialsLocalPlugin, dict(path=str(filename), watch=False))
    service = ctx.credentials
    record = dict(kind='grant', payload=dict(durable=True))
    async def mutate(current):
        entered.set(); await release.wait(); return record
    first = service.modifyRecord('owner/a', mutate)
    await entered.wait()
    queued = service.set('KEY', 'queued')
    disposing = asyncio.ensure_future(ctx.fiber.dispose())
    while not service.closed: await asyncio.sleep(0)
    pending = not disposing.done()
    release.set()
    result = await first
    try: await queued; error = None
    except Exception as failure: error = str(failure)
    await disposing
    try: await service.unset('KEY'); closed_error = None
    except Exception as failure: closed_error = str(failure)
    rows.append(dict(drainPending=pending, sameObject=result is record and service.readRecord('owner/a') is record,
        queuedError=error, closedError=closed_error, exists=filename.exists(), refs=dict(service._credentials)))
    ctx = Context(); events = asyncio.Queue(); filename = directory/'watch.yaml'
    ctx.on('credentials/reference-updated', lambda key: events.put_nowait(key))
    await ctx.plugin(CurrentCredentialsLocalPlugin, dict(path=str(filename), watch=True, debounceMs=5))
    service = ctx.credentials
    observed = []
    try:
        for value in ['created', 'changed', None]:
            if value is None: filename.unlink()
            else:
                filename.write_bytes(('version: 1\nrefs: {KEY: '+value+'}\n').encode('utf-8'))
                filename.chmod(0o600)
            event = await asyncio.wait_for(events.get(), 5)
            observed.append(dict(event=event, value=service.resolve('KEY')))
    finally: await ctx.fiber.dispose()
    rows.append(dict(watch=observed))
    return json.loads(json.dumps(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_credential_storage.mts',
        'Mounted provider activation, durable mutations, record identity/no-ops, prewrite reconciliation, reload failure recovery and removal.',
        [Path(__file__).resolve(), ROOT/'dsh/credentials/local_current.py'], prepare=prepare)
