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
arguments = parser.parse_args()
ROOT = arguments.root.resolve()
sys.path.insert(0, str(ROOT))
from dsh.session import text as text_module
from dsh.session.icu_collation import IcuCollator
from dsh.session.session_query import compile_session_text_filter, extract_session_event_text
from dsh.cordis.context import Context
from dsh.core.session import SessionHeader, Session, SessionPlugin
from dsh.session.query_engine import SqliteSessionQueryEngine


inputs = json.loads(arguments.inputs.read_text(encoding='utf-8'))
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
        persisted = [SessionHeader.from_dict(header) for index, header in enumerate(row['headers']) if row['provider'] == 'persisted' or row['provider'] == 'mixed' and index % 2 == 1]
        for value in live:
            header = SessionHeader.from_dict(value)
            context.get('sessions').enter(Session.create(header.id, [], header))
        class Persistence:
            async def list(self, signal=None):
                return persisted
        context.set_service('sessionPersistence', Persistence())
        query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='never'))
        try:
            records = await query.listSessions()
            trace = await query.traceSession('root')
            orders.append(dict(name=row['name'], listed=[record['header'].id for record in records],
                               children=[child['session']['header'].id for child in trace['descendants']]))
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
report = dict(root=str(ROOT), moduleFile=str(Path(text_module.__file__).resolve()), python=platform.python_version(),
              unicodeDataSha256=hashlib.sha256((ROOT / 'dsh/session/bin/unicode/CaseFolding.txt').read_bytes()).hexdigest(),
              runtime=runtime, observations=dict(cases=cases, events=events, orders=orders))
arguments.output.write_text(json.dumps(report, ensure_ascii=True, indent=2)+'\n', encoding='utf-8')
