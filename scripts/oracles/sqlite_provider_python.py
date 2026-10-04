import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import platform
import sys


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path)
parser.add_argument('--directory', type=Path, required=True)
parser.add_argument('--mode', choices=('produce', 'consume'), required=True)
parser.add_argument('--inputs', type=Path, required=True)
parser.add_argument('--config-source', type=Path)
parser.add_argument('--output', type=Path)
arguments = parser.parse_args()
ROOT = arguments.root.resolve() if arguments.root else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.append(str(Path(__file__).resolve().parent))

from dsh.session.sqlite_schema import decode_session_row, decode_event_row, decode_store_identity, row_to_meta
from dsh.session.persistence_sqlite_canonical import SqliteSessionPersistencePlugin
from dsh.cordis import Context
from dsh.core.session import SessionPlugin
from dsh.session.sqlite_logical import logical_numbers
from dsh.session import sqlite_store
from sqlite_store_python import observe as observe_store
from sqlite_provider_cold_python import observe as observe_cold
from sqlite_store_lock_python import observe as observe_lock


async def main():
    directory = arguments.directory.resolve()
    await observe_store(directory, arguments.mode)
    if arguments.mode == 'produce':
        return
    inputs = json.loads(arguments.inputs.read_text(encoding='utf-8'))
    rows = json.loads((directory / 'native-observations.json').read_text(encoding='utf-8'))['rows']
    for item in inputs['cases']:
        try:
            value = row_to_meta(decode_session_row(item['value'])) if item['category'] == 'metadata' else decode_event_row(item['value']) if item['category'] == 'event' else decode_store_identity(item['value'])
            rows.append(dict(name='schema-' + item['name'], value=value))
        except Exception as error:
            rows.append(dict(name='schema-' + item['name'], error=str(error)))
    configuration = json.loads(arguments.config_source.read_text(encoding='utf-8'))
    for item in configuration['rows']:
        row = dict(name='config-' + item['name'], input=item['input'])
        try:
            row['value'] = SqliteSessionPersistencePlugin.Config(item['input'])
        except Exception as error:
            row['error'] = str(error)
        rows.append(row)
    cold = await observe_cold(directory / 'native-cold.db')
    rows.extend(dict(name='cold-' + name, value=value) for name, value in cold.items())
    lock = await observe_lock(directory / 'native-lock.db')
    rows.extend(dict(name='lock-' + name, value=value) for name, value in lock.items())
    for item in inputs['logicalCases']:
        context = Context()
        await context.plugin(SessionPlugin)
        await context.plugin(SqliteSessionPersistencePlugin, dict(path=':memory:'))
        persistence = context.get('sessionPersistence')
        try:
            if not item.get('missing'):
                metadata = dict(id=item['name'], version=item['version'], createdAt=1)
                await persistence.store.materialize_header(metadata)
                if item['events']:
                    await persistence.store.append_batch(metadata, item['events'], True)
            try:
                loaded = await persistence.read_from(item['name'], item['sequence'])
                rows.append(dict(name='logical-' + item['name'], value=loaded.events))
            except Exception as error:
                name = 'TypeError' if isinstance(error, TypeError) else getattr(error, 'name', type(error).__name__ if type(error).__name__ == 'SessionFormatUnsupportedError' else 'Error')
                rows.append(dict(name='logical-' + item['name'], error=dict(name=name, message=str(error))))
        finally:
            await context.fiber.dispose()
    names = inputs['modules']
    assets = inputs['assets']
    report = dict(root=str(ROOT), python=platform.python_version(), moduleFile=sqlite_store.__file__,
                  modules={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names},
                  assets={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in assets},
                  generatedInputsSha256=hashlib.sha256(arguments.inputs.read_bytes()).hexdigest(), rows=logical_numbers(rows))
    arguments.output.write_text(json.dumps(report, ensure_ascii=True), encoding='utf-8')


asyncio.run(main())
