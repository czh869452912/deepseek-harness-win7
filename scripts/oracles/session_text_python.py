import argparse
import hashlib
import platform
import asyncio
import json
from pathlib import Path
import sys


parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
parser.add_argument('--inputs', type=Path, required=True)
parser.add_argument('--current-format', action='store_true')
arguments = parser.parse_args()
ROOT = arguments.root.resolve()
sys.path.insert(0, str(ROOT))
from dsh.session import text as text_module
from dsh.session.icu_collation import IcuCollator
from dsh.session.session_query import compile_session_text_filter, extract_session_event_text
from dsh.cordis.context import Context
from dsh.core.session import SessionHeader
from dsh.core.session.current_session import CurrentSession as Session, CurrentSessionPlugin as SessionPlugin
from dsh.session.query_current import CurrentSqliteSessionQueryEngine as SqliteSessionQueryEngine
if arguments.current_format:
    from dsh.core.runtime_v4 import SessionV4Plugin as SessionPlugin
    from dsh.session import text_current as text_module
    from dsh.session.text_current import extract_session_event_text, compile_session_text_filter


inputs = json.loads(arguments.inputs.read_text(encoding='utf-8'))
if arguments.current_format:
    for row in inputs['orders']:
        for header in row['headers']:
            header['version'] = 4
cases = []
for row in inputs['cases']:
    try:
        cases.append(dict(name=row['name'], matched=bool(compile_session_text_filter(row['text']).search(row['document']))))
    except Exception as error:
        cases.append(dict(name=row['name'], error=dict(code=error.code, message=error.message)))
events = [extract_session_event_text(event) for event in inputs['events']]


async def observe_orders():
    orders = []
    for row in inputs['orders']:
        context = Context()
        await context.plugin(SessionPlugin)
        live = [header for index, header in enumerate(row['headers']) if row['provider'] == 'live' or row['provider'] == 'mixed' and index % 2 == 0]
        persisted = [header for index, header in enumerate(row['headers']) if row['provider'] == 'persisted' or row['provider'] == 'mixed' and index % 2 == 1]
        for value in live:
            header = value
            context.get('sessions').enter(Session.create(header['id'], [], header,
                format_version=4 if arguments.current_format else 3))
        class Persistence:
            async def list(self, options=None):
                return [dict(header=header, revision='controlled') for header in persisted]
        context.set_service('sessionPersistence', Persistence())
        query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='never'))
        try:
            records = await query.listSessions()
            trace = await query.traceSession('root')
            orders.append(dict(name=row['name'], listed=[record['header']['id'] for record in records],
                               children=[child['session']['header']['id'] for child in trace['descendants']]))
        finally:
            await query.close()
            await context.fiber.dispose()
    return orders


orders = asyncio.run(observe_orders())
collator = IcuCollator()
try:
    runtime = collator.runtime_identity()
finally:
    collator.close()
data_path = ROOT / 'dsh/session/bin/unicode' / ('CaseFolding-16.0.0.txt' if arguments.current_format else 'CaseFolding.txt')
report = dict(root=str(ROOT), moduleFile=str(Path(text_module.__file__).resolve()), python=platform.python_version(),
              unicodeDataSha256=hashlib.sha256(data_path.read_bytes()).hexdigest(),
              runtime=runtime, observations=dict(cases=cases, events=events, orders=orders))
arguments.output.write_text(json.dumps(report, ensure_ascii=True, indent=2)+'\n', encoding='utf-8')
