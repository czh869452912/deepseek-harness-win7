import asyncio
import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
arguments = None
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('workspace', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    arguments = parser.parse_args()
    ROOT = arguments.root.resolve()
sys.path.insert(0, str(ROOT))
import dsh
from dsh.cordis import Context
from dsh.core.session import SessionHeader
from dsh.core.session.session import Session, SessionPlugin
from dsh.session.projections import SessionProjectionsPlugin
from dsh.session.projection_cache import SessionProjectionCachePlugin
from dsh.storage.hub import StoragePlugin
from dsh.storage.plugins import StorageJsonPlugin, StorageDomainPlugin


async def observe(workspace):
    rows = []
    for name in ('cold-malformed', 'prepared-malformed', 'cold-matching', 'cold-foreign-identity',
                 'cold-foreign-cwd', 'cold-version-mismatch', 'cold-beyond-log', 'cold-empty'):
        root = workspace / name
        document = root / 'session_projcache/sessions/owned.json'
        document.parent.mkdir(parents=True, exist_ok=True)
        header = SessionHeader('owned', created_at=9, cwd='/controlled/cwd')
        record = {'identity': {'createdAt': 8 if name == 'cold-foreign-identity' else 9,
            'cwd': '/foreign/cwd' if name == 'cold-foreign-cwd' else header.cwd},
            'rows': {} if name == 'cold-empty' else {'controlled/count': {
                'ver': 0 if name == 'cold-version-mismatch' else 1,
                'seq': 2 if name == 'cold-beyond-log' else 0, 'val': 'bad' if name.endswith('malformed') else 7}}}
        document.write_text(json.dumps({'version': 4, 'record': record}), encoding='utf-8')
        context, applied = Context(), []
        parser_failure = TypeError('controlled invalid cache value')
        def parse(value):
            if type(value) not in (int, float):
                raise parser_failure
            return value
        def apply(state, event):
            applied.append(event['seq'])
            return state + 1
        try:
            await context.plugin(StoragePlugin)
            await context.plugin(StorageJsonPlugin, config={'root': str(root)})
            await context.plugin(StorageDomainPlugin, config={'backend': 'json'})
            await context.plugin(SessionPlugin)
            await context.plugin(SessionProjectionsPlugin)
            context.get('sessionProjections').register({'key': 'controlled/count', 'stateVersion': 1,
                'stateSchema': parse, 'init': lambda meta: 0, 'apply': apply,
                'wire': {'viewSchema': parse, 'view': lambda state: state}})
            fiber = await context.plugin(SessionProjectionCachePlugin, config={'writeEveryEvents': 100, 'writeIntervalMs': 60000})
            cache = context.get('sessionProjectionCache')
            events = [{'type': 'controlled/event', 'seq': seq, 'time': seq, 'data': {}} for seq in (0, 1)]
            observed = {}
            try:
                if name == 'prepared-malformed':
                    session = Session.create('owned', events, header)
                    observed['snapshot'] = cache.hydrate_prepared(session, header, events)
                else:
                    observed['snapshot'] = cache.cold_snapshot(header, events)
            except Exception as error:
                observed['error'] = {'name': type(error).__name__, 'message': str(error), 'sameParserFailure': error is parser_failure}
            await fiber.dispose()
            observed.update(applied=applied, document=json.loads(document.read_text(encoding='utf-8')))
            rows.append({'name': name, 'observed': observed})
        finally:
            await context.fiber.dispose()
    return rows


if __name__ == '__main__':
    arguments.output.write_text(json.dumps({'observations': asyncio.run(observe(arguments.workspace)),
        'root': str(ROOT), 'module': str(Path(dsh.__file__).resolve()), 'python': list(sys.version_info[:3])},
        ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
