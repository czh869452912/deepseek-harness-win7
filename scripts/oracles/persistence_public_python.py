import argparse
import asyncio
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
    for backend in ('jsonl-none', 'jsonl-zstd', 'sqlite'):
        for operation, label, value in (
            ('create', 'whole', 1.0), ('create', 'negative-zero', -0.0), ('create', 'fraction', 1.5), ('create', 'boolean', True),
            ('append', 'whole', 0.0), ('append', 'negative-zero', -0.0), ('append', 'fraction', 0.5), ('append', 'boolean', False),
            ('read', 'whole', 0.0), ('read', 'negative-zero', -0.0), ('read', 'fraction', 0.5), ('read', 'boolean', False),
            ('read', 'unsafe', 9007199254740992), ('abort', 'before', 0), ('abort', 'after-read', 0),
        ):
            with tempfile.TemporaryDirectory(prefix='dsh-public-read-') as directory:
                ctx = Context()
                row = dict(name=backend + '/' + operation + '/' + label)
                try:
                    await ctx.plugin(SessionPlugin)
                    if backend == 'sqlite':
                        await ctx.plugin(SqliteSessionPersistencePlugin, dict(path=str(Path(directory) / 'store.db')))
                    else:
                        await ctx.plugin(JsonlSessionPersistencePlugin, dict(root=directory, compression='zstd' if backend == 'jsonl-zstd' else 'none'))
                    provider = ctx.get('sessionPersistence')
                    meta = SessionHeader('s', created_at=1)
                    event = dict(type='session/end-seed', seq=0, time=1, data={})
                    if operation == 'create':
                        await provider.create(SessionHeader('s', created_at=value))
                    else:
                        await provider.create(meta)
                        if operation != 'append':
                            await provider.append('s', [event])
                        if operation == 'append':
                            await provider.append('s', [dict(event, seq=value)])
                        elif operation == 'read':
                            result = await provider.read_from('s', value)
                            row['value'] = dict(meta=result.meta.to_dict(), events=result.events)
                        else:
                            owner = provider.store
                            key = 'load_stored_from' if backend == 'sqlite' else 'load_stored'
                            original = getattr(owner, key)
                            controller = AbortController()
                            entered, released = asyncio.Event(), asyncio.Event()
                            calls = []
                            async def held(*arguments, **keywords):
                                calls.append(dict(signalForwarded=any(argument is controller.signal for argument in arguments) or keywords.get('signal') is controller.signal))
                                result = await original(*arguments, **keywords)
                                if label == 'after-read':
                                    entered.set()
                                    await released.wait()
                                return result
                            setattr(owner, key, held)
                            reason = RuntimeError('controlled read retired')
                            if label == 'before':
                                controller.abort(reason)
                            reading = asyncio.create_task(provider.read_from('s', 0, controller.signal))
                            if label == 'after-read':
                                await asyncio.wait_for(entered.wait(), 5)
                                controller.abort(reason)
                                released.set()
                            try:
                                result = await asyncio.wait_for(reading, 5)
                                row['value'] = dict(meta=result.meta.to_dict(), events=result.events)
                            except Exception as error:
                                row.update(error=dict(name='TypeError' if isinstance(error, TypeError) else 'Error', message=str(error)), reasonIdentity=error is reason)
                            row.update(calls=calls, aborted=controller.signal.aborted)
                            setattr(owner, key, original)
                    if 'error' not in row:
                        row['accepted'] = True
                except Exception as error:
                    row.update(error=dict(name='TypeError' if isinstance(error, TypeError) else 'Error', message=str(error)), accepted=False)
                finally:
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
