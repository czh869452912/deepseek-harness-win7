import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import sys
import tempfile


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root = options.root.resolve()
    sys.path.insert(0, str(root))
    from dsh.cordis.context import Context
    from dsh.core.session import SessionPlugin, SessionHeader
    from dsh.core.abort import AbortController
    from dsh.session.persistence_jsonl_canonical import JsonlSessionPersistencePlugin
    from dsh.session.persistence_sqlite_canonical import SqliteSessionPersistencePlugin
    rows = []
    for name in ('jsonl-none/queued', 'jsonl-zstd/queued', 'sqlite/queued', 'sqlite/legacy-forward', 'sqlite/legacy-after', 'sqlite/aborted-failure'):
        with tempfile.TemporaryDirectory(prefix='dsh-read-order-') as directory:
            ctx = Context()
            row = dict(name=name)
            controller = AbortController()
            reason = RuntimeError('controlled read retired')
            entered, released = asyncio.Event(), asyncio.Event()
            try:
                await ctx.plugin(SessionPlugin)
                if name.startswith('sqlite'):
                    await ctx.plugin(SqliteSessionPersistencePlugin, dict(path=str(Path(directory) / 'store.db')))
                else:
                    await ctx.plugin(JsonlSessionPersistencePlugin, dict(root=directory, compression='zstd' if name.startswith('jsonl-zstd') else 'none'))
                provider = ctx.get('sessionPersistence')
                legacy = 'legacy' in name
                await provider.create(SessionHeader('s', created_at=1))
                await provider.append('s', [dict(type='user/message' if legacy else 'session/end-seed', seq=0, time=1,
                    data=dict(content=[dict(type='text', text='legacy')], source=dict(kind='user')) if legacy else {})])
                owner = provider.store
                key = 'load_stored' if legacy or not name.startswith('sqlite') else 'load_stored_from'
                original = getattr(owner, key)
                calls = []
                async def held(*arguments, **keywords):
                    calls.append(dict(signalForwarded=any(argument is controller.signal for argument in arguments) or keywords.get('signal') is controller.signal))
                    result = await original(*arguments, **keywords)
                    if name.endswith('aborted-failure'):
                        controller.abort(reason)
                        raise RuntimeError('controlled read failure')
                    if name.endswith('queued') and len(calls) == 1 or name.endswith('legacy-after'):
                        entered.set()
                        await released.wait()
                    return result
                setattr(owner, key, held)
                async def settle(reading):
                    try:
                        value = await reading
                        return dict(value=dict(meta=value.meta.to_dict(), events=value.events))
                    except Exception as error:
                        return dict(error=dict(name='TypeError' if isinstance(error, TypeError) else 'Error', message=str(error)), reasonIdentity=error is reason)
                if name.endswith('queued'):
                    first = asyncio.create_task(settle(provider.read_from('s', 0)))
                    await asyncio.wait_for(entered.wait(), 5)
                    enqueued = asyncio.Event()
                    original_lock = provider.storage_lock
                    @asynccontextmanager
                    async def queued_lock(identity):
                        enqueued.set()
                        async with original_lock(identity):
                            yield
                    provider.storage_lock = queued_lock
                    second = asyncio.create_task(settle(provider.read_from('s', 0, controller.signal)))
                    await asyncio.wait_for(enqueued.wait(), 5)
                    controller.abort(reason)
                    try:
                        await asyncio.wait_for(asyncio.shield(second), 1)
                        row['settledBeforeRelease'] = True
                    except asyncio.TimeoutError:
                        row['settledBeforeRelease'] = False
                    row['callsBeforeRelease'] = len(calls)
                    released.set()
                    row['first'] = await first
                    row.update(await second)
                    provider.storage_lock = original_lock
                else:
                    reading = asyncio.create_task(settle(provider.read_from('s', 0, controller.signal)))
                    if name.endswith('legacy-after'):
                        await asyncio.wait_for(entered.wait(), 5)
                        controller.abort(reason)
                        released.set()
                    row.update(await reading)
                row.update(calls=calls, aborted=controller.signal.aborted)
                setattr(owner, key, original)
            finally:
                released.set()
                await ctx.fiber.dispose()
            rows.append(row)
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), python=sys.version, executable=sys.executable, modules=modules, rows=rows), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    asyncio.run(main())
